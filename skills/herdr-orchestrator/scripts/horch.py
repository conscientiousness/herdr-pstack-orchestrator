#!/usr/bin/env python3
"""horch - start, watch, and close herdr worker agents.

Core of the herdr-orchestrator skill. Subcommands: run, wait, list, close, detect, check, stats.
Python 3.11+, standard library only. Every command prints JSON on stdout;
errors are one {"error": code, "message": text} object with exit status 1.
"""

from __future__ import annotations

import argparse
import core_backend as core
import fcntl
import json
import math
import os
import re
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

HARNESSES = ("pi", "codex", "claude")
CONFIG_TOP_KEYS = {"max_active_workers", "notify_after_minutes", "workers", "roles"}
WORKER_KEYS = {"harness", "model", "provider", "effort", "args", "description"}
WORKER_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,15}")
TASK_ID_RE = re.compile(r"t-[0-9a-f]{6}")
MISSING_PANE_CODES = {"pane_not_found", "tab_not_found", "workspace_not_found"}
# Session IDs a controller harness exports to its tool commands.
CONTROLLER_SESSION_ENV = {"codex": "CODEX_THREAD_ID", "claude": "CLAUDE_CODE_SESSION_ID"}

SETTLED_STATES = {
    "done",
    "blocked",
    "not_started",
    "start_failed",
    "exited",
    "result_missing",
    "result_invalid",
    "error",
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


def herdr(*args, timeout=120.0, env=None, expect_json=True):
    """Run a Herdr command, parsing JSON unless its output is requested as text."""
    argv = ["herdr", *[str(a) for a in args]]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise HerdrError("herdr CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {args[0]} {args[1]} timed out after {timeout:g}s") from exc
    if proc.returncode != 0:
        parsed = _read_json_text(proc.stderr) or _read_json_text(proc.stdout)
        payload = parsed if isinstance(parsed, dict) else {"raw": (proc.stderr or proc.stdout).strip()[:2000]}
        raise HerdrError(_herdr_message(payload, proc.returncode, proc.stderr), payload)
    if not expect_json:
        return proc.stdout
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


def validate_task_id(task_id):
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        fail("invalid_task_id", f"task ID must match t-[0-9a-f]{{6}}: {task_id!r}")


def task_dir(task_id):
    validate_task_id(task_id)
    return tasks_root() / task_id


@contextmanager
def task_store_lock():
    """Serialize allocation and startup across run/check processes on this store."""
    root = tasks_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".start.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_json(path, obj):
    path = Path(path)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_state():
    return {
        "state": "running",
        "baseline_seq": None,
        "saw_working": False,
        "long_notified": False,
        "closed": False,
        "problem": None,
        "settled_at": None,
        "first_done_at": None,
    }


def mark_settled(state):
    """Retain independent first settlement and delivery observations across recheck."""
    observed = iso_now()
    if state["state"] in SETTLED_STATES and not state.get("settled_at"):
        state["settled_at"] = observed
    if state["state"] == "done" and not state.get("first_done_at"):
        state["first_done_at"] = observed


def load_state(directory):
    stored = read_json(directory / "state.json")
    state = default_state()
    if isinstance(stored, dict):
        state.update({key: value for key, value in stored.items() if key in state})
    return state


@contextmanager
def task_state_lock(directory):
    """Serialize short state transactions; never hold across herdr calls."""
    with (directory / ".state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save_state(directory, state):
    with task_state_lock(directory):
        current = load_state(directory)
        merged = dict(current if current["closed"] or current["state"] == "done" else state)
        for key in ("closed", "saw_working", "long_notified"):
            merged[key] = bool(current[key] or state[key])
        for key in ("settled_at", "first_done_at"):
            merged[key] = current[key] or state.get(key)
        mark_settled(merged)
        write_json(directory / "state.json", merged)
        state.update(merged)


class TaskInvalidError(Exception):
    pass


class TaskMissingError(Exception):
    pass


def load_task(directory, task_id):
    path = directory / "task.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TaskMissingError(f"no such task: {task_id}") from exc
    except (OSError, UnicodeDecodeError):
        text = ""
    task = _read_json_text(text)
    required = ("nonce", "worker", "agent", "pane_id", "result_path", "created_at")
    if (not isinstance(task, dict) or task.get("task_id") != task_id
            or any(not isinstance(task.get(key), str) or not task[key] for key in required)
            or ("workspace_id" in task and (
                not isinstance(task["workspace_id"], str) or not task["workspace_id"].strip()))):
        raise TaskInvalidError(f"task {task_id} has an invalid task.json")
    try:
        created = datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise TaskInvalidError(f"task {task_id} has an invalid created_at in task.json") from exc
    binding = task.get("backend", {"kind": "legacy"})
    if not isinstance(binding, dict) or binding.get("kind") not in ("legacy", "core"):
        raise TaskInvalidError(f"task {task_id} has an unknown backend")
    if binding["kind"] == "core":
        try:
            core.validate(binding)
            viewer = task.get("viewer")
            if viewer is not None and (not isinstance(viewer, dict) or any(
                    not isinstance(viewer.get(k), str) or not viewer[k]
                    for k in ("pane_id", "tab_id", "socket_path"))):
                raise ValueError("invalid core viewer binding")
        except ValueError as exc:
            raise TaskInvalidError(f"task {task_id}: {exc}") from exc
    return task


def is_core(task):
    return task.get("backend", {}).get("kind") == "core"


def all_task_ids():
    root = tasks_root()
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if TASK_ID_RE.fullmatch(d.name) and d.is_dir() and (d / "task.json").is_file()
    )


def active_task_count(workspace_id):
    """Unclosed reservations owned by one workspace, including live legacy panes."""
    return task_capacity(workspace_id)[0]


def task_capacity(workspace_id, binding=None):
    """Return the reservation count and invalid IDs from the same bulk scan."""
    active = 0
    legacy_panes = []
    invalid = []
    for task_id in all_task_ids():
        directory = task_dir(task_id)
        if load_state(directory)["closed"]:
            continue
        try:
            task = load_task(directory, task_id)
        except TaskMissingError:
            continue  # manual recovery removed the record after enumeration
        except TaskInvalidError:
            active += 1  # unknown owner and pane; reserve a slot in every workspace
            invalid.append(task_id)
            continue
        if binding is not None and is_core(task):
            if task["backend"]["core_id"] == binding["core_id"]:
                active += 1
        elif binding is not None and workspace_id is None:
            continue
        elif is_core(task):
            if task.get("workspace_id") == workspace_id:
                active += 1
        elif "workspace_id" not in task:
            legacy_panes.append(task["pane_id"])
        elif task["workspace_id"] == workspace_id:
            active += 1
    if legacy_panes:
        panes = {pane_id for pane_id, _ in workspace_panes(workspace_id)}
        active += sum(pane_id in panes for pane_id in legacy_panes)
    return active, invalid


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
        if "description" in spec and not isinstance(spec["description"], str):
            fail("config_invalid", f"worker {name!r} description must be a string")
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
            "description": spec.get("description"),
        }
    return {"max_active_workers": max_active, "notify_after_minutes": notify_minutes,
            "workers": workers, "roles": data.get("roles", {})}


# ---------------------------------------------------------------------------
# agents, panes, placement
# ---------------------------------------------------------------------------


def agent_index():
    """Map live agent name to its herdr entry, or None when herdr cannot be polled."""
    try:
        agents = herdr_path(herdr("agent", "list", timeout=30.0), "result", "agents")
    except HerdrError:
        return None
    if not isinstance(agents, list):
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


def herdr_error_code(exc):
    error = exc.payload.get("error") if isinstance(exc.payload, dict) else None
    return error.get("code") if isinstance(error, dict) else None


def close_pane(pane_id, *, socket_path=None):
    """Close the authoritative pane, independent of the caller's workspace."""
    env = dict(os.environ, HERDR_SOCKET_PATH=socket_path) if socket_path else None
    try:
        pane = herdr_path(herdr("pane", "get", pane_id, timeout=30.0, env=env), "result", "pane")
    except HerdrError as exc:
        if herdr_error_code(exc) in MISSING_PANE_CODES:
            return "already_gone"
        raise
    target = pane.get("pane_id") if isinstance(pane, dict) else None
    if not isinstance(target, str) or not target:
        raise HerdrError("herdr pane get has a pane without pane_id")
    try:
        herdr("pane", "close", target, timeout=30.0, env=env)
    except HerdrError as exc:
        if herdr_error_code(exc) in MISSING_PANE_CODES:
            return "already_gone"  # it vanished after pane get
        raise
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


def place_pane(workspace, cwd, caller_tab, label=PANE_LABEL):
    """Return (pane_id, tab_id) for a fresh worker pane; never touches caller_tab."""
    tabs = herdr_path(herdr("tab", "list", "--workspace", workspace, timeout=30.0), "result", "tabs")
    panes = workspace_panes(workspace)
    for tab in tabs:
        tab_id = tab.get("tab_id") if isinstance(tab, dict) else None
        if not isinstance(tab_id, str) or tab_id == caller_tab or tab.get("label") != label:
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
        "--label", label,
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


def resolve_cwd(raw):
    try:
        cwd = Path(raw or os.getcwd()).resolve(strict=True)
    except OSError:
        cwd = None
    if cwd is None or not cwd.is_dir():
        fail("cwd_not_found", f"--cwd is not a directory: {raw}")
    return cwd


def process_ancestors():
    """Return the pids from this process up to init, or an empty set if ps is unusable."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                                 text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    parents = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
    chain, pid = set(), os.getpid()
    while pid > 1 and pid in parents and pid not in chain:
        chain.add(pid)
        pid = parents[pid]
    return chain


def pane_process_info(pane_id):
    return herdr_path(herdr("pane", "process-info", "--pane", pane_id, timeout=30.0),
                      "result", "process_info")


def pane_owning_process(ancestors):
    """Return the pane whose shell is an ancestor of this process, if any."""
    for pane in herdr_path(herdr("pane", "list", timeout=30.0), "result", "panes"):
        try:
            if pane_process_info(pane["pane_id"]).get("shell_pid") in ancestors:
                return pane["pane_id"]
        except HerdrError:
            continue  # a pane closed during the scan cannot own this process
    return None


def require_caller_context(claimed=None):
    """Return the controller's live pane after proving that it hosts this process.

    HERDR_PANE_ID alone is not proof: a shell snapshot or a shared agent daemon
    can carry another live pane's ID. The pane's shell must be an ancestor of
    horch. Without any pane ancestor, only an explicit --caller-pane is accepted,
    and its foreground must run the controller's harness.
    """
    source = "--caller-pane" if claimed is not None else "HERDR_PANE_ID"
    pane_id = claimed if claimed is not None else os.environ.get("HERDR_PANE_ID")
    guidance = ("Confirm the controller's pane from its own process or session, never from UI focus, "
                "and see caller context in references/setup.md.")
    # Herdr can fall back to UI focus when the caller pane ID is blank.
    if not pane_id or not pane_id.strip():
        fail("caller_context_invalid", f"Controller pane ID is missing. {guidance}")
    try:
        pane = herdr_path(herdr("pane", "current", "--pane", pane_id, timeout=30.0), "result", "pane")
    except HerdrError as exc:
        if herdr_error_code(exc) not in MISSING_PANE_CODES:
            raise
        fail("caller_context_invalid", f"Controller pane {pane_id!r} is no longer available. {guidance}")
    if not isinstance(pane, dict) or any(
        not isinstance(pane.get(key), str) or not pane[key].strip()
        for key in ("pane_id", "tab_id", "workspace_id")
    ):
        fail("caller_context_invalid", f"Controller context is missing live Herdr IDs. {guidance}")

    info = pane_process_info(pane["pane_id"])
    ancestors = process_ancestors()
    if info.get("shell_pid") in ancestors:
        return pane
    owner = pane_owning_process(ancestors)
    if owner is not None:
        fail("caller_context_invalid",
             f"{source} names pane {pane_id!r}, but horch runs inside pane {owner!r}. "
             f"Rerun with HERDR_PANE_ID={owner} if that pane is this controller. {guidance}")
    if claimed is None:
        fail("caller_context_invalid",
             f"horch is not running inside any Herdr pane's process tree, so HERDR_PANE_ID={pane_id!r} "
             "cannot be trusted; a shared agent daemon may have inherited another pane's ID. "
             f"Confirm the controller's pane and pass --caller-pane <pane-id>. {guidance}")

    controllers = [h for h in ("codex", "claude") if os.environ.get(CONTROLLER_SESSION_ENV[h])]
    expected = controllers or list(HARNESSES)
    names = {p.get("name") for p in info.get("foreground_processes") or [] if isinstance(p, dict)}
    if not names.intersection(expected):
        fail("caller_context_invalid",
             f"--caller-pane {pane_id!r} is not running {' or '.join(expected)} in its foreground "
             f"(found: {', '.join(sorted(n for n in names if n)) or 'nothing'}). {guidance}")
    session = pane.get("agent_session") if isinstance(pane.get("agent_session"), dict) else {}
    for harness in controllers:
        own = os.environ[CONTROLLER_SESSION_ENV[harness]]
        if session.get("agent") == harness and session.get("value") and session["value"] != own:
            fail("caller_context_invalid",
                 f"--caller-pane {pane_id!r} reports {harness} session {session['value']!r}, "
                 f"not this controller's {own!r}. {guidance}")
    return pane


def core_caller_context(claimed=None):
    """Require a viewer for Herdr callers, even when HERDR_ENV was dropped."""
    has_context = claimed is not None or os.environ.get("HERDR_ENV") == "1" or any(
        os.environ.get(key) for key in (
            "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID", "HERDR_SOCKET_PATH"))
    if not has_context:
        return None
    caller = require_caller_context(claimed)
    if not os.environ.get("HERDR_SOCKET_PATH", "").strip():
        fail("caller_context_invalid",
             "Herdr viewer requires HERDR_SOCKET_PATH before worker launch. "
             "Restore the controller's endpoint; do not bypass placement by clearing Herdr context.")
    return caller


def cmd_run(args):
    binary = core.executable()
    if binary is None:
        require_herdr_env()
        require_caller_context(args.caller_pane)
    else:
        core_caller_context(args.caller_pane)
    config = load_config()
    brief_source = Path(args.brief).expanduser()
    try:
        brief_source = brief_source.resolve(strict=True)
    except OSError:
        brief_source = None
    if brief_source is None or not brief_source.is_file():
        fail("brief_not_found", f"brief file not found: {args.brief}")
    brief_text = brief_source.read_text(encoding="utf-8", errors="replace")
    worker = config["workers"].get(args.worker)
    if binary is None and worker is not None and worker["harness"] == "pi":
        require_pi_integration()
    binding = core.new_binding(binary) if binary else None
    emit(start_task(config, args.worker, brief_text, resolve_cwd(args.cwd),
                    caller_pane=args.caller_pane, binding=binding))


def start_task(config, worker_name, brief_text, cwd, *, skip_if_full=False, caller_pane=None, binding=None):
    # Startup includes placement, publication, and acknowledgement, never completion.
    with task_store_lock():
        if binding is not None:
            return start_core_task(config, worker_name, brief_text, cwd, skip_if_full, caller_pane, binding)
        return _start_task_locked(config, worker_name, brief_text, cwd, skip_if_full, caller_pane)


def core_agent(terminal):
    if terminal is None or terminal.get("state") != "live":
        return None
    return {"agent_status": core.status(terminal), "completion_seq": terminal.get("turn")}


def close_task_resources(task):
    if not is_core(task):
        return {"pane": close_pane(task["pane_id"])}
    outcome = core.close(task["backend"])
    viewer = task.get("viewer")
    if task.get("viewer_unresolved"):
        raise HerdrError("viewer placement outcome is unknown; inspect the recorded viewer endpoint before releasing this reservation")
    outcome["viewer"] = (close_pane(viewer["pane_id"], socket_path=viewer["socket_path"])
                         if viewer else "not_created")
    return outcome


def start_core_task(config, worker_name, brief_text, cwd, skip_if_full, caller_pane, binding):
    worker = config["workers"].get(worker_name)
    if worker is None:
        fail("unknown_worker", f"no worker named {worker_name!r} in {config_path()}")
    caller = core_caller_context(caller_pane)
    active, invalid = task_capacity(caller["workspace_id"] if caller else None, binding)
    if active >= config["max_active_workers"]:
        if skip_if_full:
            return None
        fail("worker_limit", f"core session {binding['session']} has {active} reserved tasks; "
             f"max_active_workers = {config['max_active_workers']}; invalid tasks: {invalid}")
    task_id = "t-" + secrets.token_hex(3)
    directory = task_dir(task_id)
    while directory.exists():
        task_id = "t-" + secrets.token_hex(3)
        directory = task_dir(task_id)
    nonce = secrets.token_hex(8)
    argv = launch_args(worker, directory)
    if worker["harness"] == "codex":
        if any(arg == "--daemon" or arg.startswith(("--daemon=", "--no-daemon=")) for arg in argv):
            fail("config_invalid", "core Codex requires --no-daemon; conflicting daemon arguments were not changed")
        if "--no-daemon" not in argv:
            argv.append("--no-daemon")
    binding = dict(binding, terminal="horch-" + task_id[2:], name="horch-" + task_id[2:], nonce=nonce)
    task = {"task_id": task_id, "nonce": nonce, "worker": worker_name,
            "harness": worker["harness"], "model": worker["model"], "cwd": str(cwd),
            "task_dir": str(directory), "brief_path": str(directory / "brief.md"),
            "result_path": str(directory / "result.json"), "agent": binding["name"],
            "pane_id": binding["terminal"], "argv": argv, "created_at": iso_now(),
            "backend": binding, "viewer": None}
    if caller:
        task["workspace_id"] = caller["workspace_id"]
    directory.mkdir(parents=True)
    write_brief(directory, brief_text, task_id, nonce)
    write_json(directory / "task.json", task)
    state = default_state()
    save_state(directory, state)
    warning = None
    try:
        try:
            terminal = core.launch(binding, worker["harness"], argv, cwd)
        except core.CoreError as exc:
            terminal = core.get(binding)
            if terminal is None:
                raise core.CoreError(f"creation outcome unresolved: {exc}; reservation retained. "
                                     f"Inspect {binding['name']} at the stored endpoint; do not relaunch") from exc
        binding["terminal"] = terminal["address"]
        task["pane_id"] = terminal["address"]
        write_json(directory / "task.json", task)
        if caller:
            try:
                viewer_socket = os.environ.get("HERDR_SOCKET_PATH")
                if not viewer_socket:
                    raise HerdrError("cannot pin viewer endpoint without HERDR_SOCKET_PATH; no GUI writes attempted")
                task["viewer_socket"] = viewer_socket
                task["viewer_unresolved"] = True
                write_json(directory / "task.json", task)
                pane_id, tab_id = place_pane(caller["workspace_id"], cwd, caller["tab_id"], "hcOrch")
                task["viewer"] = {"pane_id": pane_id, "tab_id": tab_id, "socket_path": viewer_socket}
                task["viewer_unresolved"] = False
                write_json(directory / "task.json", task)
                env = core.cli_env(binding)
                assignments = [f"{k}={env[k]}" for k in (*binding["env"], "HC_SESSION", "HC_SOCKET")]
                command = shlex.join(["env", "-u", "HC_TERMINAL_ID", *assignments,
                                      binding["executable"], "attach", binding["terminal"]])
                herdr("pane", "run", pane_id, command, timeout=30, expect_json=False)
            except HerdrError as exc:
                warning = f"core worker retained; required hcOrch viewer failed: {exc}; "
                warning += "inspect for an empty viewer pane after ambiguous placement"
                task["viewer_warning"] = warning
                write_json(directory / "task.json", task)
        terminal = core.ready(binding, START_TIMEOUT_MS / 1000)
        baseline = terminal.get("turn")
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            raise core.CoreError("native turn baseline missing; no task was sent")
        state["baseline_seq"] = baseline
        save_state(directory, state)
    except core.CoreError as exc:
        state["state"] = "start_failed"
        state["problem"] = str(exc)
        save_state(directory, state)
    if state["state"] == "running" and not state["closed"]:
        pointer = f"New task {task_id}. Read {directory / 'brief.md'} in full and follow it exactly."
        try:
            sent = core.call(binding, "terminal.send", terminal=binding["terminal"], text=pointer, **{"if": "idle"})
            terminal = core.get(binding)
            observed = core_agent(terminal)
            acknowledged = sent.get("started") is True or (observed and (
                observed["agent_status"] in ("working", "blocked", "error") or
                observed.get("completion_seq", baseline) > baseline))
            if not acknowledged:
                raise core.CoreError("prompt acknowledgement not observed; never resend automatically")
            if observed and observed["agent_status"] in ("blocked", "error"):
                state["state"] = observed["agent_status"]
                state["problem"] = "worker reported " + observed["agent_status"]
            else:
                state["saw_working"] = True
        except core.CoreError as exc:
            state["state"] = "not_started"
            state["problem"] = f"send outcome unresolved: {exc}; inspect native state, then use wait --recheck; do not resend"
            try:
                observed = core_agent(core.get(binding))
                if observed and (observed["agent_status"] in ("working", "blocked", "error")
                                 or observed["completion_seq"] > baseline):
                    state["state"] = observed["agent_status"] if observed["agent_status"] in ("blocked", "error") else "running"
                    state["saw_working"] = True
                    state["problem"] = ("worker reported " + state["state"]
                                        if state["state"] in ("blocked", "error") else None)
            except core.CoreError as reconcile_error:
                state["problem"] += f"; endpoint reconciliation failed: {reconcile_error}"
        save_state(directory, state)
    return {"task_id": task_id, "worker": worker_name, "agent": task["agent"],
            "pane_id": task["pane_id"], "terminal_id": binding["terminal"], "backend": "core",
            "viewer": task["viewer"], "state": state["state"], "message": state["problem"],
            "warning": warning, "brief_path": task["brief_path"], "task_dir": str(directory)}


def wait_for_pi_session(agent, deadline):
    """Do not submit input to Pi's pre-session trust dialog.

    Herdr 0.9.3 can classify that dialog as idle/interactive_ready. The Pi
    integration reports its session only after project trust is resolved and
    the interactive input handler is installed. Fresh panes have no old session.
    """
    while time.monotonic() < deadline:
        entry = herdr_path(herdr("agent", "get", agent), "result", "agent")
        if entry.get("agent_status") == "blocked":
            raise HerdrError("Pi is blocked during startup; no task prompt was sent")
        session = entry.get("agent_session") or {}
        if (session.get("agent") == "pi" and session.get("source") == "herdr:pi"
                and session.get("value") and entry.get("agent_status") in ("idle", "done")):
            return
        time.sleep(POLL_SECONDS)
    raise HerdrError("Pi did not report a ready session; no task prompt was sent. "
                     "Inspect its pane for a startup dialog and verify that the Pi "
                     "integration is installed with herdr integration install pi")


def _start_task_locked(config, worker_name, brief_text, cwd, skip_if_full, caller_pane):
    """Start one worker on one task and return the run object; fail() on contract errors."""
    caller = require_caller_context(caller_pane)
    worker = config["workers"].get(worker_name)
    if worker is None:
        fail("unknown_worker", f"no worker named {worker_name!r} in {config_path()}")

    max_active = config["max_active_workers"]
    active, invalid = task_capacity(caller["workspace_id"])
    if active >= max_active:
        if skip_if_full:
            return None
        guidance = (f"; invalid tasks: {', '.join(invalid)}; inspect them with horch list"
                    if invalid else "")
        fail(
            "worker_limit",
            f"worker limit reached in workspace {caller['workspace_id']}: "
            f"{active} active tasks, max_active_workers = {max_active}{guidance}",
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
    try:
        write_brief(directory, brief_text, task_id, nonce)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    try:
        pane_id, tab_id = place_pane(caller["workspace_id"], cwd, caller["tab_id"])
    except BaseException as exc:
        shutil.rmtree(directory, ignore_errors=True)
        print(f"warning: pane placement failed: {exc}; an empty pane may exist "
              "after an ambiguous placement failure", file=sys.stderr)
        raise

    task = {
        "task_id": task_id,
        "nonce": nonce,
        "worker": worker_name,
        "harness": worker["harness"],
        "model": worker["model"],
        "cwd": str(cwd),
        "task_dir": str(directory),
        "brief_path": str(directory / "brief.md"),
        "result_path": str(directory / "result.json"),
        "agent": agent,
        "pane_id": pane_id,
        "tab_id": tab_id,
        "workspace_id": caller["workspace_id"],
        "argv": launch_args(worker, directory),
        "backend": {"kind": "legacy"},
        "created_at": iso_now(),
    }
    state = default_state()
    try:
        write_json(directory / "task.json", task)
        save_state(directory, state)
    except BaseException:
        # If publication fails, close the unused pane. If close is uncertain,
        # retain/publish its reservation so a later launch cannot reuse the slot.
        try:
            close_pane(pane_id)
        except HerdrError as exc:
            state["state"] = "start_failed"
            state["problem"] = f"task publication failed; unused pane cleanup failed: {exc}"
            try:
                write_json(directory / "task.json", task)
                save_state(directory, state)
            except OSError as recovery_error:
                print(f"warning: cannot preserve task {task_id} for pane {pane_id}: "
                      f"{recovery_error}", file=sys.stderr)
        else:
            shutil.rmtree(directory, ignore_errors=True)
        raise

    def run_object(state_name):
        return {
            "task_id": task_id,
            "worker": worker_name,
            "agent": agent,
            "pane_id": pane_id,
            "state": state_name,
            "brief_path": task["brief_path"],
            "task_dir": task["task_dir"],
        }

    start_problem = None
    startup_deadline = time.monotonic() + START_TIMEOUT_MS / 1000
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
        elif worker["harness"] == "pi":
            wait_for_pi_session(agent, startup_deadline)
    except HerdrError as exc:
        start_problem = str(exc)
    if start_problem:
        state["state"] = "start_failed"
        state["problem"] = start_problem
        save_state(directory, state)
        notify(f"horch: {task_id} start_failed", f"worker {worker_name} failed to start in pane {pane_id}: {start_problem}")
        return run_object("start_failed")

    index = agent_index()
    entry = (index or {}).get(agent)
    baseline = entry.get("state_change_seq") if isinstance(entry, dict) else None
    if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
        state["state"] = "start_failed"
        state["problem"] = "could not capture a usable agent baseline; prompt was not submitted"
        save_state(directory, state)
        notify(f"horch: {task_id} start_failed", state["problem"])
        return run_object(state["state"])
    state["baseline_seq"] = baseline
    save_state(directory, state)
    if state["closed"] or state["state"] == "done":
        return run_object(state["state"])

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
            state["problem"] = "the worker is waiting at a dialog"
            notify(f"horch: {task_id} blocked", f"worker {worker_name} is waiting at a dialog in pane {pane_id}")
        else:
            state["state"] = "running"
            state["saw_working"] = status == "working"
    except HerdrError as exc:
        code = None
        if isinstance(exc.payload, dict) and isinstance(exc.payload.get("error"), dict):
            code = exc.payload["error"].get("code")
        if code == "agent_blocked":
            state["state"] = "blocked"
            state["problem"] = "the worker is waiting at a dialog"
            notify(f"horch: {task_id} blocked", f"worker {worker_name} is waiting at a dialog in pane {pane_id}")
        else:
            state["state"] = "not_started"
            state["problem"] = f"prompt acknowledgement not observed: {exc}"
            notify(
                f"horch: {task_id} not_started",
                f"worker {worker_name} prompt acknowledgement not observed within {ACK_TIMEOUT_MS // 1000}s: {exc}",
            )
    save_state(directory, state)
    return run_object(state["state"])


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
    return validate_result(read_json(path), task)


def validate_result(parsed, task):
    if not isinstance(parsed, dict):
        return "invalid"
    keys = {"task_id", "nonce", "status", "summary", "files", "question"}
    if (set(parsed) != keys or parsed["task_id"] != task["task_id"]
            or parsed["nonce"] != task["nonce"]
            or parsed["status"] not in ("completed", "blocked", "failed")
            or not isinstance(parsed["summary"], str)
            or not isinstance(parsed["files"], list)
            or not all(isinstance(item, str) for item in parsed["files"])):
        return "invalid"
    question = parsed["question"]
    if parsed["status"] == "blocked":
        return "valid" if isinstance(question, str) and question.strip() else "invalid"
    return "valid" if question is None else "invalid"


def ran_longer_than(task, minutes):
    try:
        started = datetime.fromisoformat(str(task.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() > minutes * 60


def evaluate_task(info, agent, config):
    state, task = info["state"], info["task"]
    if agent is None:
        state["state"] = "exited"
        state["problem"] = f"worker {task['worker']} ({task['agent']}) has finished or is gone from its backend"
        return "exited"
    status = agent.get("agent_status")
    if status == "working":
        state["saw_working"] = True
    if status == "error":
        state["state"] = "error"
        state["problem"] = f"worker {task['worker']} reported a native error"
        return "error"
    if status == "blocked":
        state["state"] = "blocked"
        state["problem"] = f"worker {task['worker']} is waiting at a dialog in pane {task['pane_id']}"
        return "blocked"
    if turn_ended(agent, state):
        verdict = result_verdict(info["dir"], task)
        if verdict == "valid":
            state["state"] = "done"
            state["problem"] = None
            return "done"
        if verdict == "missing":
            state["state"] = "result_missing"
            state["problem"] = f"turn ended without a valid result.json ({task['result_path']})"
            return "result_missing"
        state["state"] = "result_invalid"
        state["problem"] = f"result.json does not match the result schema or task_id/nonce ({task['result_path']})"
        return "result_invalid"
    if not state["long_notified"] and ran_longer_than(task, config["notify_after_minutes"]):
        state["long_notified"] = True
        state["state"] = "running"
        state["problem"] = None
        return "long_running"
    state["state"] = "running"
    state["problem"] = None
    return "running"


def poll_round(infos, previous, config):
    observing = {info["task_id"]: info for info in infos
                 if not info["state"]["closed"] and info["state"]["state"] != "done"
                 and (info["state"]["state"] not in SETTLED_STATES or info.get("recheck"))}
    legacy = any(not is_core(info["task"]) for info in observing.values())
    index = agent_index() if legacy else {}
    if index is None:
        return False, False
    observations = {}
    for info in observing.values():
        if is_core(info["task"]):
            terminal = core.get(info["task"]["backend"])
            info["terminal_observation"] = terminal
            observations[info["task_id"]] = core_agent(terminal)
    changed = False
    for info in infos:
        directory = info["dir"]
        notice = None
        cleanup = False
        with task_state_lock(directory):
            state = load_state(directory)
            info["state"] = state
            old_state = state["state"]
            if info["task_id"] not in observing or state["closed"] or old_state == "done" or (
                    old_state in SETTLED_STATES and not info.pop("recheck", False)):
                reported = old_state
            else:
                agent = (observations.get(info["task_id"]) if is_core(info["task"])
                         else index.get(info["task"]["agent"]))
                reported = evaluate_task(info, agent, config)
                cleanup = reported == "done"
                if reported == "long_running":
                    notice = (f"worker {info['task']['worker']} has run longer than "
                              f"{config['notify_after_minutes']} minutes; still waiting")
                elif state["problem"] and old_state != state["state"]:
                    notice = state["problem"]
                mark_settled(state)
                write_json(directory / "state.json", state)
        if cleanup:
            cleanup_error = None
            try:
                close_task_resources(info["task"])
            except (HerdrError, core.CoreError) as exc:
                cleanup_error = f"task cleanup failed: {exc}; retry with horch close {info['task_id']}"
            with task_state_lock(directory):
                state = load_state(directory)
                if not state["closed"]:
                    state["closed"] = cleanup_error is None
                    if state["problem"] != cleanup_error:
                        notice = cleanup_error
                    state["problem"] = cleanup_error
                    write_json(directory / "state.json", state)
                info["state"] = state
        # Notices are claimed in the state transaction, sent outside the lock.
        # Suppress a notice if a concurrent close has already completed.
        if (notice and not load_state(directory)["closed"]
                and (not is_core(info["task"]) or info["task"].get("viewer"))):
            notify(f"horch: {info['task_id']}", notice)
        info["reported"] = reported
        if previous.get(info["task_id"]) != reported:
            previous[info["task_id"]] = reported
            changed = True
    return changed, True


def wait_line(info):
    state = load_state(info["dir"])
    reported = state["state"] if state["closed"] or state["state"] == "done" else info["reported"]
    # A worker may write its result before its turn ends. Do not deliver it yet.
    parsed = read_json(info["dir"] / "result.json") if reported == "done" else None
    parsed = parsed if validate_result(parsed, info["task"]) == "valid" else None
    return {
        "task_id": info["task_id"],
        "state": reported,
        "closed": bool(state["closed"]),
        "message": state["problem"],
        "summary": parsed.get("summary") if parsed else None,
        "result_path": str(info["dir"] / "result.json"),
        "files": parsed.get("files") if parsed and isinstance(parsed.get("files"), list) else [],
        "question": parsed.get("question") if parsed else None,
    }


def make_info(task_id):
    directory = task_dir(task_id)
    task = load_task(directory, task_id)
    state = load_state(directory)
    return {"task_id": task_id, "dir": directory, "task": task, "state": state, "reported": state["state"]}


def cmd_wait(args):
    config = load_config()
    if args.recheck and not args.task_ids:
        fail("invalid_arguments", "wait --recheck requires explicit task IDs")
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
            try:
                info = make_info(task_id)
            except (TaskInvalidError, TaskMissingError):
                continue
            if not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES:
                infos.append(info)
    if not infos:
        return

    if args.recheck:
        for info in infos:
            if (not info["state"]["closed"] and info["state"]["state"] in SETTLED_STATES
                    and info["state"]["state"] != "done"):
                info["recheck"] = True
    wait_until_change(infos, config, args.max_seconds)
    for info in infos:
        emit(wait_line(info))


def wait_until_change(infos, config, max_seconds):
    """Poll until a waited task changes state or max_seconds pass; no-op when all are settled."""
    if all((info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES)
           and not info.get("recheck") for info in infos):
        return
    deadline = None if max_seconds is None else time.monotonic() + max(0.0, max_seconds)
    previous = {info["task_id"]: info["state"]["state"] for info in infos}
    failures = 0
    while True:
        changed, polled = poll_round(infos, previous, config)
        failures = 0 if polled else failures + 1
        if failures >= 3:
            fail("herdr_error", "could not poll herdr agent list")
        if changed or (polled and all(info["state"]["closed"] or
                                     info["state"]["state"] in SETTLED_STATES for info in infos)):
            return
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return
        native_only = all(is_core(info["task"]) for info in infos)
        interval = 180.0 if native_only else POLL_SECONDS
        gap = interval if deadline is None else min(interval, deadline - now)
        if gap > 0:
            observations = [(info["task"]["backend"], info.get("terminal_observation"))
                            for info in infos if is_core(info["task"]) and not info["state"]["closed"]
                            and info["state"]["state"] not in SETTLED_STATES]
            if observations:
                core.wait_changes(observations, gap)
            else:
                time.sleep(gap)


# ---------------------------------------------------------------------------
# read-only worker statistics
# ---------------------------------------------------------------------------


def stats_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed.astimezone(timezone.utc)


def duration_summary(samples, sources):
    ordered = sorted(samples)
    return {
        "sample_size": len(ordered),
        "median": statistics.median(ordered) if ordered else None,
        "p90": ordered[math.ceil(len(ordered) * 0.9) - 1] if ordered else None,
        "max": ordered[-1] if ordered else None,
        "sources": dict(sorted(sources.items())),
    }


def cmd_stats(args):
    # No Herdr calls, state locks, or writes: a per-record view, not a snapshot.
    now = datetime.now(timezone.utc)
    if args.workspace is not None and not args.workspace.strip():
        fail("invalid_arguments", "--workspace must not be blank")
    try:
        if args.days is not None and args.days <= 0:
            raise ValueError("nonpositive days")
        cutoff = now - timedelta(days=args.days) if args.days is not None else None
    except (ValueError, OverflowError):
        fail("invalid_arguments", "--days must be a positive integer within datetime range")
    config = load_config()
    roles = config["roles"]
    if not isinstance(roles, dict):
        fail("config_invalid", "[roles] must be a table")
    missing_roles = {}
    for role, assigned in sorted(roles.items()):
        names = [assigned] if isinstance(assigned, str) else assigned
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            fail("config_invalid", "role assignments must be worker names or lists of names")
        missing = sorted(set(names) - config["workers"].keys())
        if missing:
            missing_roles[role] = missing
    workers = {}
    samples = {}
    invalid = []
    timings = []

    def worker_row(name):
        if name not in workers:
            spec = config["workers"].get(name)
            workers[name] = {
                "configured": spec is not None,
                **{key: spec.get(key) if spec else None for key in ("harness", "model", "effort", "provider")},
                "task_count": 0, "reminder_fired": 0, "states": {}, "result_statuses": {},
                "problem_count": 0, "problem_rate": None, "unclosed_running": 0, "last_use": None,
                "workspaces": {}, "unknown_workspace_count": 0,
                "duration_excluded_count": 0, "duration_samples": [],
            }
            samples[name] = ([], {})
        return workers[name]

    for name in config["workers"]:
        worker_row(name)
    for task_id in all_task_ids():
        directory = task_dir(task_id)
        # Missing files are normal during publication/removal; existing corrupt
        # files remain diagnostic. Raw metadata is used only to narrow scope.
        if not (directory / "task.json").exists():
            continue
        raw = read_json(directory / "task.json")
        if isinstance(raw, dict):
            workspace = raw.get("workspace_id")
            if (args.workspace is not None and isinstance(workspace, str)
                    and workspace != args.workspace):
                continue
            try:
                if cutoff is not None and stats_timestamp(raw.get("created_at")) < cutoff:
                    continue
            except (ValueError, OverflowError):
                pass
        try:
            task = load_task(directory, task_id)
            created = stats_timestamp(task["created_at"])
        except TaskMissingError:
            continue
        except (TaskInvalidError, ValueError, OverflowError):
            if directory.is_dir():
                invalid.append(task_id)
            continue
        if ((args.workspace is not None and task.get("workspace_id") != args.workspace)
                or (cutoff is not None and created < cutoff)):
            continue
        if not (directory / "state.json").exists():
            continue
        state = read_json(directory / "state.json")
        if (not isinstance(state, dict) or not isinstance(state.get("state"), str)
                or state["state"] not in SETTLED_STATES | {"running"}):
            if directory.is_dir():
                invalid.append(task_id)
            continue
        result = read_json(directory / "result.json")
        minutes, source = None, None
        valid_result = state["state"] == "done" and validate_result(result, task) == "valid"
        if valid_result:
            try:
                if state.get("first_done_at") is not None:
                    ended = stats_timestamp(state["first_done_at"])
                    source = "first_done_at"
                else:
                    ended = datetime.fromtimestamp((directory / "result.json").stat().st_mtime, timezone.utc)
                    source = "result_mtime"
                minutes = (ended - created).total_seconds() / 60
                if minutes < 0 or ended > now:
                    minutes = None
            except (OSError, ValueError, OverflowError):
                pass
        if not directory.is_dir():
            continue
        row = worker_row(task["worker"])
        row["task_count"] += 1
        row["reminder_fired"] += state.get("long_notified") is True
        name = ("closed_before_done" if state.get("closed") and state["state"] not in SETTLED_STATES
                else state["state"])
        row["states"][name] = row["states"].get(name, 0) + 1
        row["problem_count"] += name in SETTLED_STATES - {"done"}
        row["unclosed_running"] += name == "running"
        last = row["last_use"]
        if last is None or created > stats_timestamp(last):
            row["last_use"] = created.isoformat().replace("+00:00", "Z")
        workspace = task.get("workspace_id")
        if workspace is None:
            row["unknown_workspace_count"] += 1
        else:
            row["workspaces"][workspace] = row["workspaces"].get(workspace, 0) + 1
        if name == "done":
            if valid_result:
                status = result["status"]
                row["result_statuses"][status] = row["result_statuses"].get(status, 0) + 1
            if minutes is None:
                row["duration_excluded_count"] += 1
        if minutes is not None:
            values, sources = samples[task["worker"]]
            values.append(minutes)
            sources[source] = sources.get(source, 0) + 1
            timings.append(minutes)
            row["duration_samples"].append({"task_id": task_id, "minutes": minutes,
                                            "endpoint_source": source})
    for name, row in workers.items():
        settled_count = row["problem_count"] + row["states"].get("done", 0)
        row["problem_rate"] = row["problem_count"] / settled_count if settled_count else None
        row["duration_minutes"] = duration_summary(*samples[name])

    def above(threshold):
        count = sum(value > threshold for value in timings)
        return {"minutes": threshold, "count": count,
                "share": count / len(timings) if timings else None}

    emit({
        "scope": {"workspace_id": args.workspace, "days": args.days,
                  "created_since": cutoff.isoformat().replace("+00:00", "Z") if cutoff else None},
        "task_count": sum(row["task_count"] for row in workers.values()),
        "reminder_fired": sum(row["reminder_fired"] for row in workers.values()),
        "workers": dict(sorted(workers.items())),
        "configured_unused_workers": sorted(name for name, row in workers.items()
                                            if row["configured"] and not row["task_count"]),
        "roles_with_unconfigured_workers": missing_roles,
        "invalid_task_ids": invalid,
        "delivered_duration_estimate": {"timed_task_count": len(timings),
                                        "current": above(config["notify_after_minutes"]),
                                        "thresholds": [above(n) for n in (15, 30, 45, 60, 90)
                                                       if n != config["notify_after_minutes"]]},
    })


# ---------------------------------------------------------------------------
# list and close
# ---------------------------------------------------------------------------


def cmd_list(args):
    rows = []
    for task_id in all_task_ids():
        try:
            task = load_task(task_dir(task_id), task_id)
        except TaskMissingError:
            continue
        except TaskInvalidError as exc:
            rows.append(("", task_id, {"task_id": task_id, "state": "task_invalid",
                                      "error": "task_invalid", "message": str(exc)}))
            continue
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
                    "backend": task.get("backend", {"kind": "legacy"}),
                    "terminal_id": task["backend"]["terminal"] if is_core(task) else None,
                    "viewer": task.get("viewer"),
                    "warning": task.get("viewer_warning"),
                    "workspace_id": task.get("workspace_id"),
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
    directory = task_dir(args.task_id)
    try:
        task = load_task(directory, args.task_id)
    except TaskInvalidError as exc:
        fail("task_invalid", f"{exc}; pane is unknown. Check herdr pane list for a leftover "
             f"horch pane, then remove task directory {directory} by hand")
    outcome = close_task_resources(task)
    with task_state_lock(directory):
        current = load_state(directory)
        current["closed"] = True
        current["problem"] = None
        write_json(directory / "state.json", current)
    emit({"task_id": args.task_id, "closed": True, **outcome})


# ---------------------------------------------------------------------------
# detect and check
# ---------------------------------------------------------------------------


CHECK_BRIEF = """\
# horch setup check

This task only checks that horch can start you and read your result. Do not
read, create, or change any file except `result.json`. Write `result.json` now
with status `completed` and summary `check ok`.
"""


def tool_version(name):
    path = shutil.which(name)
    if path is None:
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
        version = (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr).strip() else None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    return {"path": path, "version": version}


def pi_providers():
    """Providers that `pi --list-models` shows, with how many models each lists.

    Sign-in status is left out: `pi auth check` does not know providers that come
    from extensions (measured: commandcode reports provider_not_found yet works).
    `horch check` is the real test.
    """
    try:
        proc = subprocess.run(["pi", "--list-models"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    counts = {}
    for line in proc.stdout.splitlines()[1:]:  # first line is the column header
        fields = line.split()
        if len(fields) >= 2:
            counts[fields[0]] = counts.get(fields[0], 0) + 1
    return [{"provider": provider, "models": count} for provider, count in counts.items()]


def pi_integration_status():
    """Read Herdr's local plaintext protocol without exposing paths or diagnostics."""
    try:
        proc = subprocess.run(["herdr", "integration", "status"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return {"status": "unavailable", "version": None}
    if proc.returncode != 0:
        return {"status": "unavailable", "version": None}
    lines = [line for line in proc.stdout.splitlines() if line.startswith("pi:")]
    if len(lines) == 1:
        match = re.fullmatch(
            r"pi: (?:not installed|(?:current|needs repair) \((?:v[0-9]+|legacy)\)"
            r"|outdated \((?:v[0-9]+|legacy) < v[0-9]+\)) \(.+\)", lines[0])
        if match:
            state = lines[0][4:].split(" (")[0].replace(" ", "_")
            version = re.match(r"pi: [a-z ]+ \(v([0-9]+)\b", lines[0])
            return {"status": state,
                    "version": int(version[1]) if state != "not_installed" and version else None}
    return {"status": "unknown", "version": None}


def require_pi_integration():
    if pi_integration_status()["status"] == "not_installed":
        fail("pi_integration_missing",
             "Pi requires the Herdr integration; install it with herdr integration install pi")


def herdr_server_version():
    """Read the running server version independently of the installed CLI."""
    try:
        proc = subprocess.run(["herdr", "status", "server", "--json"],
                              capture_output=True, text=True, timeout=10)
        status = _read_json_text(proc.stdout) if proc.returncode == 0 else None
        version = status.get("version") if isinstance(status, dict) else None
        return version if isinstance(version, str) else None
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def cmd_detect(args):
    binary = core.executable()
    harnesses = {name: tool_version(name) for name in HARNESSES}
    emit({
        "backend": "core" if binary else "legacy",
        "core": {"path": binary, "status_source": "native OSC 7501"} if binary else None,
        "herdr_env": os.environ.get("HERDR_ENV") == "1",
        "herdr": tool_version("herdr") if not binary else None,
        "herdr_server_version": herdr_server_version() if not binary else None,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "harnesses": harnesses,
        "pi_providers": pi_providers() if harnesses["pi"] else [],
        "pi_integration": ({"status": "native", "version": None} if binary else pi_integration_status()),
        "config": {"path": str(config_path()), "exists": config_path().is_file()},
    })


def cmd_check(args):
    binary = core.executable()
    if binary is None:
        require_herdr_env()
    caller = (require_caller_context(args.caller_pane) if binary is None
              else core_caller_context(args.caller_pane))
    binding = core.new_binding(binary) if binary else None
    config = load_config()
    names = list(dict.fromkeys(args.workers or list(config["workers"])))
    unknown = [name for name in names if name not in config["workers"]]
    if unknown:
        fail("unknown_worker", f"no worker named {', '.join(unknown)} in {config_path()}")
    if binary is None and any(config["workers"][name]["harness"] == "pi" for name in names):
        require_pi_integration()
    cwd = resolve_cwd(args.cwd)
    deadline = time.monotonic() + args.max_seconds
    pending = list(names)
    started = {}
    settled_times = {}
    capacity_invalid = set()
    while pending or any(not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES
                         for info, _ in started.values()):
        while pending and time.monotonic() < deadline:
            name = pending[0]
            began = time.monotonic()
            run = start_task(config, name, CHECK_BRIEF, cwd, skip_if_full=True,
                             caller_pane=args.caller_pane, binding=binding)
            if run is None:
                _, invalid = task_capacity(caller["workspace_id"] if caller else None, binding)
                capacity_invalid.update(invalid)
                break  # poll our started tasks before retrying pending workers
            pending.pop(0)
            info = make_info(run["task_id"])
            started[name] = (info, began)
            if info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES:
                settled_times[name] = time.monotonic()
        waiting = [info for info, _ in started.values()
                   if not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES]
        if time.monotonic() >= deadline or (not waiting and pending):
            break  # out of time, or problem panes hold every slot
        wait_until_change(waiting, config, deadline - time.monotonic())
        for name, (info, _) in started.items():
            if name not in settled_times and (info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES):
                settled_times[name] = time.monotonic()
    for name in names:
        if name not in started:
            message = ("check wait limit reached before this worker could start" if time.monotonic() >= deadline
                       else "no free worker slot; review max_active_workers or close problem panes with horch close")
            if capacity_invalid:
                message += (f"; invalid tasks held capacity: {', '.join(sorted(capacity_invalid))}; "
                            "inspect them with horch list")
            emit({"worker": name, "task_id": None, "state": "not_checked", "ok": False,
                  "pane_id": None, "seconds": None, "message": message})
            continue
        info, began = started[name]
        info["state"] = load_state(info["dir"])
        result = read_json(info["dir"] / "result.json")
        status = result.get("status") if isinstance(result, dict) else None
        state = info["state"]["state"]
        message = info["state"]["problem"]
        if state == "done" and status != "completed":
            result_message = f"worker result status is {status!r}; expected completed"
            message = f"{message}; {result_message}" if message else result_message
        elif state not in SETTLED_STATES and message is None:
            message = "check wait limit reached; task is still unsettled"
        emit({
            "worker": name,
            "task_id": info["task_id"],
            "state": state,
            "ok": state == "done" and status == "completed" and info["state"]["closed"]
                  and result_verdict(info["dir"], info["task"]) == "valid"
                  and not info["task"].get("viewer_warning"),
            "pane_id": None if info["state"]["closed"] else info["task"]["pane_id"],
            "viewer": info["task"].get("viewer"),
            "warning": info["task"].get("viewer_warning"),
            "seconds": round(settled_times.get(name, time.monotonic()) - began),
            "message": message,
        })


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
    p_run.add_argument("--caller-pane", help="controller pane confirmed by the caller when horch runs outside every pane process tree")
    p_run.set_defaults(func=cmd_run)

    p_wait = sub.add_parser("wait", help="wait until at least one waited task changes state")
    p_wait.add_argument("task_ids", nargs="*", help="tasks to wait on (default: every task that is not settled)")
    p_wait.add_argument("--recheck", action="store_true", help="re-poll named unclosed problem tasks")
    p_wait.add_argument("--max-seconds", type=int, default=None, help="return after at most this many seconds")
    p_wait.set_defaults(func=cmd_wait)

    p_list = sub.add_parser("list", help="print every task as one JSON line, oldest first")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="summarize stored worker performance without Herdr or writes")
    p_stats.add_argument("--workspace", help="only tasks created in this workspace")
    p_stats.add_argument("--days", type=int, help="only tasks created in the last n days")
    p_stats.set_defaults(func=cmd_stats)

    p_close = sub.add_parser("close", help="close the task's backend terminal and owned viewer")
    p_close.add_argument("task_id", help="task to close")
    p_close.set_defaults(func=cmd_close)

    p_detect = sub.add_parser("detect", help="print installed harnesses, versions, and pi providers")
    p_detect.set_defaults(func=cmd_detect)

    p_check = sub.add_parser("check", help="start each worker on a tiny task and report whether it works")
    p_check.add_argument("workers", nargs="*", help="workers to check (default: all in workers.toml)")
    p_check.add_argument("--cwd", help="working directory for the check workers (default: the current directory)")
    p_check.add_argument("--max-seconds", type=int, default=300, help="stop waiting after this many seconds (default: 300)")
    p_check.add_argument("--caller-pane", help="controller pane confirmed by the caller when horch runs outside every pane process tree")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for task_id in getattr(args, "task_ids", []):
            validate_task_id(task_id)
        if hasattr(args, "task_id"):
            validate_task_id(args.task_id)
        args.func(args)
    except TaskMissingError as exc:
        fail("unknown_task", str(exc))
    except TaskInvalidError as exc:
        fail("task_invalid", str(exc))
    except HerdrError as exc:
        fail("herdr_error", str(exc), exc.payload)
    except core.CoreError as exc:
        fail("core_error", str(exc))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # never crash with a traceback at the controller
        fail("internal_error", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
