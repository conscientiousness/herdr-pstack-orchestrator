#!/usr/bin/env python3
"""horch - start, watch, and close herdr worker agents.

Core of the herdr-orchestrator skill. Subcommands: run, wait, list, close.
Python 3.11+, standard library only. Every command prints JSON on stdout;
errors are one {"error": code, "message": text} object with exit status 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

HARNESSES = ("pi", "codex", "claude")
CONFIG_TOP_KEYS = {"max_active_workers", "notify_after_minutes", "workers", "roles"}
WORKER_KEYS = {"harness", "model", "provider", "effort", "args"}
WORKER_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,15}")
PANE_ID_RE = re.compile(r"w\d+:p\d+")
TAB_ID_RE = re.compile(r"w\d+:t\d+")

SETTLED_STATES = {
    "done",
    "blocked",
    "not_started",
    "start_failed",
    "exited",
    "result_missing",
    "result_invalid",
}

POLL_SECONDS = 2.0
ACK_TIMEOUT_MS = 15000
START_TIMEOUT_MS = 90000
PANE_LABEL = "horch"
PANES_PER_TAB = 4

WORKER_RULES = """\
## Worker rules

- Write your output files first. Write `result.json` last.
- Do not ask the user questions. If something is unclear, write `result.json` with status `blocked` and the question, then stop.
- Do not run `herdr` or `horch`.
- You may use your own subagents.

Write `result.json` at exactly this path:

    {result_path}

Use these exact values in `result.json`:

- task_id: {task_id}
- nonce: {nonce}
"""


# ---------------------------------------------------------------------------
# output and errors
# ---------------------------------------------------------------------------


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))


def fail(code, message, herdr_payload=None):
    obj = {"error": code, "message": message}
    if herdr_payload is not None:
        obj["herdr"] = herdr_payload
    emit(obj)
    sys.exit(1)


def require_herdr_env():
    if os.environ.get("HERDR_ENV") != "1":
        fail("not_in_herdr", "horch must run inside a herdr pane (HERDR_ENV is not 1)")


# ---------------------------------------------------------------------------
# herdr CLI
# ---------------------------------------------------------------------------


class HerdrError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload


def _read_json_text(text):
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _herdr_message(payload, returncode, stderr):
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message")
            if code and message:
                return f"{code}: {message}"
            return str(code or message or "herdr command failed")
        if isinstance(err, str):
            return err
    return (stderr or "").strip()[:500] or f"herdr exited with status {returncode}"


def herdr(*args, timeout=120.0):
    """Run one herdr command and return its parsed stdout JSON document."""
    argv = ["herdr", *[str(a) for a in args]]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise HerdrError("herdr CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {args[0]} {args[1]} timed out after {timeout:g}s") from exc
    if proc.returncode != 0:
        parsed = _read_json_text(proc.stderr) or _read_json_text(proc.stdout)
        payload = parsed if isinstance(parsed, dict) else {"raw": (proc.stderr or proc.stdout).strip()[:2000]}
        raise HerdrError(_herdr_message(payload, proc.returncode, proc.stderr), payload)
    parsed = _read_json_text(proc.stdout)
    if isinstance(parsed, list):
        return {"result": parsed}
    return parsed if isinstance(parsed, dict) else {}


def notify(title, body):
    try:
        herdr("notification", "show", title, "--body", body, "--sound", "request", timeout=30.0)
    except HerdrError:
        pass  # a lost notice must never break task handling


# ---------------------------------------------------------------------------
# JSON tree helpers (herdr response shapes are not documented, only observed)
# ---------------------------------------------------------------------------


def iter_nodes(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from iter_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_nodes(value)


def find_ids(node, regex):
    found = []
    for candidate in iter_nodes(node):
        if isinstance(candidate, str) and regex.fullmatch(candidate) and candidate not in found:
            found.append(candidate)
    return found


def entries_with_id(node, key, fallback_regex):
    found = []
    for candidate in iter_nodes(node):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get(key)
        if isinstance(value, str):
            found.append((value, candidate))
            continue
        value = candidate.get("id")
        if isinstance(value, str) and fallback_regex.fullmatch(value):
            found.append((value, candidate))
    return found


# ---------------------------------------------------------------------------
# paths and task store
# ---------------------------------------------------------------------------


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "herdr-orchestrator" / "workers.toml"


def tasks_root():
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "herdr-orchestrator" / "tasks"


def task_dir(task_id):
    return tasks_root() / task_id


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_state():
    return {
        "state": "running",
        "baseline_seq": None,
        "saw_working": False,
        "long_notified": False,
        "closed": False,
    }


def load_state(directory):
    stored = read_json(directory / "state.json")
    state = default_state()
    if isinstance(stored, dict):
        state.update({key: value for key, value in stored.items() if key in state})
    return state


def save_state(directory, state):
    write_json(directory / "state.json", state)


def all_task_ids():
    root = tasks_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / "task.json").is_file())


def active_task_count():
    # A task counts while its pane is not closed, whatever its recorded state.
    root = tasks_root()
    if not root.is_dir():
        return 0
    count = 0
    for directory in root.iterdir():
        if not directory.is_dir() or not (directory / "task.json").is_file():
            continue
        stored = read_json(directory / "state.json")
        if isinstance(stored, dict) and stored.get("closed") is True:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def load_config():
    path = config_path()
    if not path.is_file():
        fail("config_invalid", f"workers.toml not found at {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        fail("config_invalid", f"cannot parse {path}: {exc}")

    unknown = sorted(set(data) - CONFIG_TOP_KEYS)
    if unknown:
        fail("config_invalid", f"unknown top-level keys in workers.toml: {', '.join(unknown)}")

    def int_key(key, default, minimum):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            fail("config_invalid", f"{key} must be an integer >= {minimum}")
        return value

    max_active = int_key("max_active_workers", 4, 0)
    notify_minutes = int_key("notify_after_minutes", 180, 1)

    workers_table = data.get("workers", {})
    if not isinstance(workers_table, dict):
        fail("config_invalid", "[workers] must be a table")
    workers = {}
    for name, spec in workers_table.items():
        if not isinstance(spec, dict):
            fail("config_invalid", f"worker {name!r} must be a table")
        if not WORKER_NAME_RE.fullmatch(name):
            fail("config_invalid", f"worker name {name!r} must match [a-z][a-z0-9-]{{0,15}}")
        unknown = sorted(set(spec) - WORKER_KEYS)
        if unknown:
            fail("config_invalid", f"worker {name!r} has unknown keys: {', '.join(unknown)}")
        harness = spec.get("harness")
        if harness not in HARNESSES:
            fail("config_invalid", f"worker {name!r} needs harness set to one of: {', '.join(HARNESSES)}")
        model = spec.get("model")
        if not isinstance(model, str) or not model.strip():
            fail("config_invalid", f"worker {name!r} needs a non-empty model")
        provider = spec.get("provider")
        if provider is not None:
            if not isinstance(provider, str) or not provider.strip():
                fail("config_invalid", f"worker {name!r} provider must be a non-empty string")
            if harness != "pi":
                fail("config_invalid", f"worker {name!r} sets provider, which only the pi harness accepts")
        effort = spec.get("effort")
        if effort is not None and (not isinstance(effort, str) or not effort.strip()):
            fail("config_invalid", f"worker {name!r} effort must be a non-empty string")
        extra = spec.get("args", [])
        if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
            fail("config_invalid", f"worker {name!r} args must be a list of strings")
        workers[name] = {
            "harness": harness,
            "model": model,
            "provider": provider,
            "effort": effort,
            "args": extra,
        }
    return {"max_active_workers": max_active, "notify_after_minutes": notify_minutes, "workers": workers}


# ---------------------------------------------------------------------------
# agents, panes, placement
# ---------------------------------------------------------------------------


def agent_index():
    """Map live agent name to its herdr entry, or None when herdr cannot be polled."""
    try:
        doc = herdr("agent", "list", timeout=30.0)
    except HerdrError:
        return None
    index = {}
    for node in iter_nodes(doc.get("result", doc)):
        if isinstance(node, dict) and isinstance(node.get("name"), str) and "agent_status" in node:
            index[node["name"]] = node
    return index


def pane_exists(pane_id):
    args = ["pane", "list"]
    workspace = os.environ.get("HERDR_WORKSPACE_ID")
    if workspace:
        args += ["--workspace", workspace]
    try:
        doc = herdr(*args, timeout=30.0)
    except HerdrError:
        return False
    return pane_id in find_ids(doc, PANE_ID_RE)


def close_pane(pane_id):
    """Close a pane; True also when the pane turned out to be gone already."""
    try:
        herdr("pane", "close", pane_id, timeout=30.0)
        return True
    except HerdrError:
        return not pane_exists(pane_id)


def tab_label(entry):
    for key in ("label", "title", "name"):
        value = entry.get(key)
        if isinstance(value, str):
            return value
    return None


def panes_of_tab(tab_id, entry, panes_by_tab):
    ids = panes_by_tab.get(tab_id)
    if ids:
        return ids
    listed = entry.get("pane_ids")
    if isinstance(listed, list):
        ids = [p for p in listed if isinstance(p, str) and PANE_ID_RE.fullmatch(p)]
        if ids:
            return ids
    try:
        doc = herdr("tab", "get", tab_id, timeout=30.0)
    except HerdrError:
        return []
    return find_ids(doc, PANE_ID_RE)


def has_pane_below(pane_id):
    try:
        doc = herdr("pane", "neighbor", "--direction", "down", "--pane", pane_id, timeout=30.0)
    except HerdrError:
        return False  # cannot tell; splitting down anyway is safe
    return bool(find_ids(doc, PANE_ID_RE))


def split_pane(source, direction, cwd):
    doc = herdr("pane", "split", source, "--direction", direction, "--cwd", str(cwd), "--no-focus", timeout=60.0)
    result = doc.get("result", doc)
    pane = result.get("pane") if isinstance(result, dict) else None
    if isinstance(pane, dict) and isinstance(pane.get("pane_id"), str):
        return pane["pane_id"]
    others = [p for p in find_ids(result, PANE_ID_RE) if p != source]
    if others:
        return others[0]
    raise HerdrError("could not read the new pane id from herdr pane split")


def place_pane(workspace, cwd, caller_tab):
    """Return (pane_id, tab_id) for a fresh worker pane; never touches caller_tab."""
    tabs_doc = herdr("tab", "list", "--workspace", workspace, timeout=30.0)
    panes_doc = herdr("pane", "list", "--workspace", workspace, timeout=30.0)

    panes_by_tab = {}
    for pane_id, entry in entries_with_id(panes_doc, "pane_id", PANE_ID_RE):
        tab_id = entry.get("tab_id")
        if isinstance(tab_id, str):
            panes_by_tab.setdefault(tab_id, []).append(pane_id)

    for tab_id, entry in entries_with_id(tabs_doc, "tab_id", TAB_ID_RE):
        if tab_id == caller_tab or tab_label(entry) != PANE_LABEL:
            continue
        panes = panes_of_tab(tab_id, entry, panes_by_tab)
        if not panes or len(panes) >= PANES_PER_TAB:
            continue
        if len(panes) == 1:
            new_pane = split_pane(panes[0], "right", cwd)
        else:
            target = next((p for p in panes if not has_pane_below(p)), panes[0])
            new_pane = split_pane(target, "down", cwd)
        return new_pane, tab_id

    doc = herdr(
        "tab", "create",
        "--workspace", workspace,
        "--cwd", str(cwd),
        "--label", PANE_LABEL,
        "--no-focus",
        timeout=60.0,
    )
    result = doc.get("result", doc)
    root = result.get("root_pane") if isinstance(result, dict) else None
    if isinstance(root, dict) and isinstance(root.get("pane_id"), str):
        pane_id = root["pane_id"]
    else:
        pane_id = next(iter(find_ids(result, PANE_ID_RE)), None)
    tab_id = next(iter(find_ids(result, TAB_ID_RE)), None)
    if not pane_id:
        raise HerdrError("could not read the new pane id from herdr tab create")
    return pane_id, tab_id


# ---------------------------------------------------------------------------
# launch arguments and brief
# ---------------------------------------------------------------------------


def launch_args(worker, directory):
    harness, model, effort = worker["harness"], worker["model"], worker["effort"]
    args = []
    if harness == "pi":
        if worker["provider"]:
            args += ["--provider", worker["provider"]]
        args += ["--model", model]
        if effort:
            args += ["--thinking", effort]
    elif harness == "codex":
        args += ["-m", model]
        if effort:
            args += ["-c", f'model_reasoning_effort="{effort}"']
        args += ["--add-dir", str(directory)]
    else:  # claude
        args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        args += ["--add-dir", str(directory)]
    return args + list(worker["args"])


def write_brief(directory, controller_brief, task_id, nonce):
    text = controller_brief.rstrip("\n") + "\n\n" + WORKER_RULES.format(
        result_path=directory / "result.json", task_id=task_id, nonce=nonce
    )
    (directory / "brief.md").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def cmd_run(args):
    require_herdr_env()
    workspace = os.environ.get("HERDR_WORKSPACE_ID")
    if not workspace:
        fail("not_in_herdr", "HERDR_WORKSPACE_ID is not set; horch cannot place worker panes")
    config = load_config()
    worker = config["workers"].get(args.worker)
    if worker is None:
        fail("unknown_worker", f"no worker named {args.worker!r} in {config_path()}")

    brief_source = Path(args.brief).expanduser()
    try:
        brief_source = brief_source.resolve(strict=True)
    except OSError:
        brief_source = None
    if brief_source is None or not brief_source.is_file():
        fail("brief_not_found", f"brief file not found: {args.brief}")
    try:
        cwd = Path(args.cwd or os.getcwd()).resolve(strict=True)
    except OSError:
        cwd = None
    if cwd is None or not cwd.is_dir():
        fail("cwd_not_found", f"--cwd is not a directory: {args.cwd}")

    max_active = config["max_active_workers"]
    active = active_task_count()
    if active >= max_active:
        fail(
            "worker_limit",
            f"worker limit reached: {active} active tasks, max_active_workers = {max_active}",
        )

    root = tasks_root()
    taken = {d.name for d in root.iterdir()} if root.is_dir() else set()
    while True:
        task_id = "t-" + secrets.token_hex(3)
        if task_id not in taken:
            break
    agent = "horch-" + task_id[2:]
    nonce = secrets.token_hex(8)

    directory = root / task_id
    directory.mkdir(parents=True)
    write_brief(directory, brief_source.read_text(encoding="utf-8", errors="replace"), task_id, nonce)

    try:
        pane_id, tab_id = place_pane(workspace, cwd, os.environ.get("HERDR_TAB_ID"))
    except HerdrError as exc:
        # Nothing was started; do not leave a stale half-built task directory.
        shutil.rmtree(directory, ignore_errors=True)
        fail("herdr_error", f"pane placement failed: {exc}", exc.payload)

    task = {
        "task_id": task_id,
        "nonce": nonce,
        "worker": args.worker,
        "harness": worker["harness"],
        "model": worker["model"],
        "cwd": str(cwd),
        "task_dir": str(directory),
        "brief_path": str(directory / "brief.md"),
        "result_path": str(directory / "result.json"),
        "agent": agent,
        "pane_id": pane_id,
        "tab_id": tab_id,
        "argv": launch_args(worker, directory),
        "created_at": iso_now(),
    }
    write_json(directory / "task.json", task)
    state = default_state()
    save_state(directory, state)

    def run_object(state_name):
        return {
            "task_id": task_id,
            "worker": args.worker,
            "agent": agent,
            "pane_id": pane_id,
            "state": state_name,
            "brief_path": task["brief_path"],
            "task_dir": task["task_dir"],
        }

    start_problem = None
    try:
        doc = herdr(
            "agent", "start", agent,
            "--kind", worker["harness"],
            "--pane", pane_id,
            "--timeout", str(START_TIMEOUT_MS),
            "--", *task["argv"],
            timeout=150.0,
        )
        started_type = (doc.get("result") or {}).get("type")
        if started_type != "agent_started":
            start_problem = f"herdr agent start reported {started_type!r}"
    except HerdrError as exc:
        start_problem = str(exc)
    if start_problem:
        state["state"] = "start_failed"
        save_state(directory, state)
        notify(f"horch: {task_id} start_failed", f"worker {args.worker} failed to start in pane {pane_id}: {start_problem}")
        emit(run_object("start_failed"))
        return

    index = agent_index()
    entry = (index or {}).get(agent)
    if entry is not None and isinstance(entry.get("state_change_seq"), int):
        state["baseline_seq"] = entry["state_change_seq"]
        save_state(directory, state)

    pointer = f"New task {task_id}. Read {directory / 'brief.md'} in full and follow it exactly."
    try:
        doc = herdr(
            "agent", "prompt", agent, pointer,
            "--wait", "--until", "working", "--until", "blocked",
            "--timeout", str(ACK_TIMEOUT_MS),
            timeout=45.0,
        )
        status = ((doc.get("result") or {}).get("agent") or {}).get("agent_status")
        if status == "blocked":
            state["state"] = "blocked"
            notify(f"horch: {task_id} blocked", f"worker {args.worker} is waiting at a dialog in pane {pane_id}")
        else:
            state["state"] = "running"
            state["saw_working"] = status == "working"
    except HerdrError as exc:
        code = None
        if isinstance(exc.payload, dict) and isinstance(exc.payload.get("error"), dict):
            code = exc.payload["error"].get("code")
        if code == "agent_blocked":
            state["state"] = "blocked"
            notify(f"horch: {task_id} blocked", f"worker {args.worker} is waiting at a dialog in pane {pane_id}")
        else:
            state["state"] = "not_started"
            notify(
                f"horch: {task_id} not_started",
                f"worker {args.worker} never reported working within {ACK_TIMEOUT_MS // 1000}s: {exc}",
            )
    save_state(directory, state)
    emit(run_object(state["state"]))


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------


def turn_ended(agent, state):
    status = agent.get("agent_status")
    if status not in ("idle", "done"):
        return False
    completion = agent.get("completion_seq")
    baseline = state.get("baseline_seq")
    if isinstance(completion, (int, float)) and isinstance(baseline, (int, float)):
        return completion > baseline
    # completion_seq stays null after some turns (observed on Codex); fall back
    # to "working was seen after the prompt".
    return bool(state.get("saw_working"))


def result_verdict(directory, task):
    path = directory / "result.json"
    if not path.is_file():
        return "missing"
    parsed = read_json(path)
    if not isinstance(parsed, dict):
        return "invalid"
    if parsed.get("task_id") == task.get("task_id") and parsed.get("nonce") == task.get("nonce"):
        return "valid"
    return "invalid"


def ran_longer_than(task, minutes):
    try:
        started = datetime.fromisoformat(str(task.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() > minutes * 60


def evaluate_task(info, agent, config):
    state, task = info["state"], info["task"]
    task_id = info["task_id"]
    title = f"horch: {task_id}"
    if agent is None:
        state["state"] = "exited"
        notify(title, f"worker {task['worker']} ({task['agent']}) is gone from herdr")
        return "exited"
    status = agent.get("agent_status")
    if status == "working":
        state["saw_working"] = True
    if status == "blocked":
        state["state"] = "blocked"
        notify(title, f"worker {task['worker']} is waiting at a dialog in pane {task['pane_id']}")
        return "blocked"
    if turn_ended(agent, state):
        verdict = result_verdict(info["dir"], task)
        if verdict == "valid":
            state["state"] = "done"
            if close_pane(task["pane_id"]):
                state["closed"] = True
            return "done"
        if verdict == "missing":
            state["state"] = "result_missing"
            notify(title, f"turn ended without a valid result.json ({task['result_path']})")
            return "result_missing"
        state["state"] = "result_invalid"
        notify(title, f"result.json does not match task_id/nonce ({task['result_path']})")
        return "result_invalid"
    if not state["long_notified"] and ran_longer_than(task, config["notify_after_minutes"]):
        state["long_notified"] = True
        notify(
            title,
            f"worker {task['worker']} has run longer than {config['notify_after_minutes']} minutes; still waiting",
        )
        return "long_running"
    state["state"] = "running"
    return "running"


def poll_round(infos, previous, config):
    """One herdr agent list poll for all unsettled tasks; returns (changed, polled)."""
    index = agent_index()
    if index is None:
        return False, False
    changed = False
    for info in infos:
        state = info["state"]
        if state["state"] in SETTLED_STATES:
            continue
        reported = evaluate_task(info, index.get(info["task"]["agent"]), config)
        save_state(info["dir"], state)
        info["reported"] = reported
        if previous.get(info["task_id"]) != reported:
            previous[info["task_id"]] = reported
            changed = True
    return changed, True


def wait_line(info):
    parsed = read_json(info["dir"] / "result.json")
    parsed = parsed if isinstance(parsed, dict) else None
    return {
        "task_id": info["task_id"],
        "state": info["reported"],
        "summary": parsed.get("summary") if parsed else None,
        "result_path": str(info["dir"] / "result.json"),
        "files": parsed.get("files") if parsed and isinstance(parsed.get("files"), list) else [],
        "question": parsed.get("question") if parsed else None,
    }


def make_info(task_id):
    directory = task_dir(task_id)
    task = read_json(directory / "task.json")
    state = load_state(directory)
    return {"task_id": task_id, "dir": directory, "task": task, "state": state, "reported": state["state"]}


def cmd_wait(args):
    require_herdr_env()
    config = load_config()
    if args.task_ids:
        seen = []
        for task_id in args.task_ids:
            if task_id not in seen:
                seen.append(task_id)
        infos = []
        for task_id in seen:
            if not (task_dir(task_id) / "task.json").is_file():
                fail("unknown_task", f"no such task: {task_id}")
            infos.append(make_info(task_id))
    else:
        infos = []
        for task_id in all_task_ids():
            info = make_info(task_id)
            if info["state"]["state"] not in SETTLED_STATES:
                infos.append(info)
    if not infos:
        return

    if not all(info["state"]["state"] in SETTLED_STATES for info in infos):
        deadline = None if args.max_seconds is None else time.monotonic() + max(0.0, args.max_seconds)
        previous = {info["task_id"]: info["state"]["state"] for info in infos}
        failures = 0
        while True:
            changed, polled = poll_round(infos, previous, config)
            failures = 0 if polled else failures + 1
            if failures >= 3:
                fail("herdr_error", "could not poll herdr agent list")
            if changed:
                break
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            gap = POLL_SECONDS if deadline is None else min(POLL_SECONDS, deadline - now)
            if gap > 0:
                time.sleep(gap)

    for info in infos:
        if info["reported"] is None:
            info["reported"] = info["state"]["state"]
    for info in infos:
        emit(wait_line(info))


# ---------------------------------------------------------------------------
# list and close
# ---------------------------------------------------------------------------


def cmd_list(args):
    require_herdr_env()
    rows = []
    for task_id in all_task_ids():
        task = read_json(task_dir(task_id) / "task.json")
        state = load_state(task_dir(task_id))
        rows.append(
            (
                str(task.get("created_at") or ""),
                task_id,
                {
                    "task_id": task_id,
                    "worker": task.get("worker"),
                    "agent": task.get("agent"),
                    "pane_id": task.get("pane_id"),
                    "state": state["state"],
                    "closed": bool(state.get("closed")),
                    "created_at": task.get("created_at"),
                },
            )
        )
    rows.sort(key=lambda row: (row[0], row[1]))
    for _, _, row in rows:
        emit(row)


def cmd_close(args):
    require_herdr_env()
    directory = task_dir(args.task_id)
    task = read_json(directory / "task.json")
    if not isinstance(task, dict) or not isinstance(task.get("pane_id"), str):
        fail("unknown_task", f"no such task: {args.task_id}")
    state = load_state(directory)
    if state.get("closed"):
        emit({"task_id": args.task_id, "closed": True, "pane": "already_gone"})
        return
    if close_pane(task["pane_id"]):
        state["closed"] = True
        save_state(directory, state)
        emit({"task_id": args.task_id, "closed": True, "pane": "closed"})
    else:
        fail("herdr_error", f"pane {task['pane_id']} could not be closed")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="horch",
        description="Start herdr worker agents, give each one task, wait for the result.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p_run = sub.add_parser("run", help="start a worker and submit one task")
    p_run.add_argument("worker", help="worker name from workers.toml")
    p_run.add_argument("--brief", required=True, help="path of the brief file for the worker")
    p_run.add_argument("--cwd", help="working directory for the worker (default: the current directory)")
    p_run.set_defaults(func=cmd_run)

    p_wait = sub.add_parser("wait", help="wait until at least one waited task changes state")
    p_wait.add_argument("task_ids", nargs="*", help="tasks to wait on (default: every task that is not settled)")
    p_wait.add_argument("--max-seconds", type=int, default=None, help="return after at most this many seconds")
    p_wait.set_defaults(func=cmd_wait)

    p_list = sub.add_parser("list", help="print every task as one JSON line, oldest first")
    p_list.set_defaults(func=cmd_list)

    p_close = sub.add_parser("close", help="close the pane of a task horch started")
    p_close.add_argument("task_id", help="task to close")
    p_close.set_defaults(func=cmd_close)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except HerdrError as exc:
        fail("herdr_error", str(exc), exc.payload)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # never crash with a traceback at the controller
        fail("internal_error", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
