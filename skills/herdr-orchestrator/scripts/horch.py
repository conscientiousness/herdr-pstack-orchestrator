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

It must be one JSON object with exactly these keys:

    {{
      "task_id": "{task_id}",
      "nonce": "{nonce}",
      "status": "completed",
      "summary": "One or two sentences.",
      "files": [],
      "question": null
    }}

`status` is `completed`, `blocked`, or `failed`. `files` lists the output files you wrote, relative to the directory of `result.json`. `question` is required when `status` is `blocked`, else null.
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
    if not isinstance(parsed, dict):
        raise HerdrError(f"herdr {' '.join(str(a) for a in args)} did not return a JSON object")
    return parsed


def notify(title, body):
    try:
        herdr("notification", "show", title, "--body", body, "--sound", "request", timeout=30.0)
    except HerdrError:
        pass  # a lost notice must never break task handling


# ---------------------------------------------------------------------------
# herdr response accessors (fixed field paths; herdr ids are opaque strings)
# ---------------------------------------------------------------------------


def herdr_path(doc, *path):
    """Follow a known field path into a herdr response, e.g. result.layout.panes."""
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise HerdrError(f"herdr response has no {'.'.join(path)}")
        node = node[key]
    return node


def herdr_id(doc, *path, id_key):
    """Read an id herdr reports either as a plain string or as an object holding id_key."""
    node = herdr_path(doc, *path)
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and isinstance(node.get(id_key), str):
        return node[id_key]
    raise HerdrError(f"herdr response has no {'.'.join(path)} ({id_key})")


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
        agents = herdr_path(herdr("agent", "list", timeout=30.0), "result", "agents")
    except HerdrError:
        return None
    index = {}
    for agent in agents:
        name = agent.get("name") if isinstance(agent, dict) else None
        if isinstance(name, str):  # herdr also lists unnamed pane agents
            index[name] = agent
    return index


def workspace_panes(workspace):
    """(pane_id, tab_id) pairs for every pane of a workspace, read from result.panes."""
    panes = herdr_path(herdr("pane", "list", "--workspace", workspace, timeout=30.0), "result", "panes")
    pairs = []
    for pane in panes:
        pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
        tab_id = pane.get("tab_id") if isinstance(pane, dict) else None
        if not isinstance(pane_id, str) or not isinstance(tab_id, str):
            raise HerdrError("herdr pane list has a pane without pane_id or tab_id")
        pairs.append((pane_id, tab_id))
    return pairs


def pane_exists(pane_id, workspace):
    return any(pane == pane_id for pane, _ in workspace_panes(workspace))


def close_pane(pane_id):
    """Close a pane; returns "closed" or "already_gone", raises HerdrError when herdr cannot say."""
    workspace = os.environ.get("HERDR_WORKSPACE_ID")
    if not pane_exists(pane_id, workspace):
        return "already_gone"
    try:
        herdr("pane", "close", pane_id, timeout=30.0)
    except HerdrError:
        if pane_exists(pane_id, workspace):
            raise  # the pane is still there, so the close really failed
        return "already_gone"  # it vanished between the two calls
    return "closed"


def widest_pane_id(any_pane_id):
    """Pane with the largest rect area of that tab; first in list order on a tie."""
    panes = herdr_path(herdr("pane", "layout", "--pane", any_pane_id, timeout=30.0), "result", "layout", "panes")
    best_id, best_area = None, -1
    for pane in panes:
        pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
        rect = pane.get("rect") if isinstance(pane, dict) else None
        width = rect.get("width") if isinstance(rect, dict) else None
        height = rect.get("height") if isinstance(rect, dict) else None
        if not isinstance(pane_id, str) or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise HerdrError("herdr pane layout has a pane without pane_id or rect size")
        if width * height > best_area:
            best_id, best_area = pane_id, width * height
    if best_id is None:
        raise HerdrError("herdr pane layout lists no panes")
    return best_id


def split_pane(source, direction, cwd):
    doc = herdr("pane", "split", source, "--direction", direction, "--cwd", str(cwd), "--no-focus", timeout=60.0)
    return herdr_id(doc, "result", "pane", id_key="pane_id")


def place_pane(workspace, cwd, caller_tab):
    """Return (pane_id, tab_id) for a fresh worker pane; never touches caller_tab."""
    tabs = herdr_path(herdr("tab", "list", "--workspace", workspace, timeout=30.0), "result", "tabs")
    panes = workspace_panes(workspace)
    for tab in tabs:
        tab_id = tab.get("tab_id") if isinstance(tab, dict) else None
        if not isinstance(tab_id, str) or tab_id == caller_tab or tab.get("label") != PANE_LABEL:
            continue
        count = tab.get("pane_count")
        if not isinstance(count, int) or count < 1 or count >= PANES_PER_TAB:
            continue
        ids = [pane_id for pane_id, pane_tab in panes if pane_tab == tab_id]
        if not ids:
            raise HerdrError(f"herdr tab list says tab {tab_id} has {count} panes, but pane list shows none")
        if count == 1:
            return split_pane(ids[0], "right", cwd), tab_id
        return split_pane(widest_pane_id(ids[0]), "down", cwd), tab_id

    doc = herdr(
        "tab", "create",
        "--workspace", workspace,
        "--cwd", str(cwd),
        "--label", PANE_LABEL,
        "--no-focus",
        timeout=60.0,
    )
    return herdr_id(doc, "result", "root_pane", id_key="pane_id"), herdr_id(doc, "result", "tab", id_key="tab_id")


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
            try:
                close_pane(task["pane_id"])
                state["closed"] = True
            except HerdrError:
                pass  # herdr cannot say whether the pane is gone; horch close can retry
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
    outcome = close_pane(task["pane_id"])
    state["closed"] = True
    save_state(directory, state)
    emit({"task_id": args.task_id, "closed": True, "pane": outcome})


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
