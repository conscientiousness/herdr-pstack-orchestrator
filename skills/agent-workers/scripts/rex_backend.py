"""Rex CLI transport and worker placement for Agent Workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


WINDOW_LABEL = "Workers"
TERMINAL = "com.superlogical.terminal"
NATIVE_STATES = {"idle", "working", "done", "blocked", "error"}
NATIVE_APPS = {"pi": {"pi"}, "codex": {"codex"}, "claude": {"claude", "claude-code"}}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
REX_TARGET_ENV = ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT")


class RexError(Exception):
    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


def full_id(value, kind):
    return isinstance(value, str) and re.fullmatch(f"{kind}:{UUID_PATTERN}", value) is not None


def _local_endpoint(value):
    if not isinstance(value, str):
        return None
    path = value.removeprefix("unix://")
    if not Path(path).is_absolute() or "\0" in path:
        return None
    return f"unix://{path}"


def _cli(binding, *args, operation, expect_json=True, input_text=None):
    argv = [binding["executable"], "--autostart=false", "--timeout=5s"]
    if binding.get("endpoint"):
        argv += ["-S", binding["endpoint"]]
    env = {key: value for key, value in os.environ.items() if key not in REX_TARGET_ENV}
    try:
        proc = subprocess.run([*argv, *args], env=env, input=input_text, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=12)
    except OSError as exc:
        raise RexError(f"cannot run the Rex CLI for {operation}: {exc}", "unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RexError(f"Rex {operation} timed out", "unavailable") from exc
    if proc.returncode:
        if operation in ("session.new_window", "session.new_split"):
            # These server rejections are atomic. Timeouts and other responses
            # do not prove that the server failed to create the block.
            rejection = re.search(r"\(status=(400|404|409) code=([a-z_]+)\)$", proc.stderr.strip())
            if rejection or proc.returncode == 3:
                reason = rejection[2] if rejection else "target not found"
                raise RexError(f"Rex {operation} rejected: {reason}", "worker_absent")
        kind = {3: "target_not_found", 4: "unavailable"}.get(proc.returncode)
        # The CLI may include arguments, including pasted text, in its diagnostics.
        raise RexError(f"Rex {operation} failed with exit status {proc.returncode}", kind)
    if not expect_json:
        return proc.stdout
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RexError(f"Rex {operation} did not return JSON") from exc
    if not isinstance(response, dict):
        raise RexError(f"Rex {operation} did not return a JSON object")
    return response


def new_binding():
    binary = shutil.which("rex")
    if not binary:
        raise RexError("Rex CLI is required inside a Rex controller", "unavailable")
    binding = {"kind": "rex", "executable": str(Path(binary).absolute())}
    requested = os.environ.get("REX_SERVER")
    if requested:
        binding["endpoint"] = _local_endpoint(requested)
        if binding["endpoint"] is None:
            raise RexError("Rex workers require a local Unix socket for access to the task files", "unsupported_endpoint")
    identity = _cli(binding, "whoami", "--json", operation="whoami")
    endpoint = _local_endpoint(identity.get("endpoint"))
    if endpoint is None or (requested and endpoint != binding["endpoint"]):
        raise RexError("Rex whoami did not identify the selected local Unix endpoint", "identity_mismatch")
    if any(not isinstance(identity.get(key), str) or not identity[key] for key in ("host_id", "instance_id")):
        raise RexError("Rex whoami did not identify the server host and instance", "identity_mismatch")
    return dict(binding, endpoint=endpoint, host_id=identity["host_id"], instance_id=identity["instance_id"])


def validate(binding):
    required = ("executable", "endpoint", "host_id", "instance_id", "label", "harness")
    window, block = binding.get("window"), binding.get("block")
    if (any(not isinstance(binding.get(key), str) or not binding[key] for key in required)
            or not {"window", "block"} <= binding.keys()
            or not Path(binding["executable"]).is_absolute()
            or _local_endpoint(binding["endpoint"]) != binding["endpoint"]
            or binding["harness"] not in NATIVE_APPS
            or not full_id(binding.get("session"), "session")
            or ((window is not None or block is not None) and
                (not full_id(window, "window") or not full_id(block, "block")))):
        raise ValueError("invalid Rex backend binding")


def _check_server(binding):
    identity = _cli(binding, "whoami", "--json", operation="whoami")
    if (_local_endpoint(identity.get("endpoint")) != binding["endpoint"]
            or any(identity.get(key) != binding[key] for key in ("host_id", "instance_id"))):
        raise RexError("Rex server identity differs at the recorded endpoint", "identity_mismatch")


def _api(binding, method, **params):
    return _cli(binding, "api", "call", "-s", binding["session"], method, "-",
                operation=method, input_text=json.dumps(params))


def _records(response, key):
    records = response.get(key)
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise RexError(f"Rex returned invalid {key}")
    return records


def _sessions(binding):
    response = _cli(binding, "session", "ls", "--json", operation="session list")
    sessions = [record.get("session_id") for record in _records(response, "sessions")]
    if any(not full_id(session, "session") for session in sessions):
        raise RexError("Rex session list did not return full session IDs")
    return sessions


def _session_blocks(binding):
    response = _api(binding, "session.list_blocks")
    records = _records(response, "blocks")
    if any(not full_id(record.get("block_id"), "block") for record in records):
        raise RexError("Rex block list did not return full block IDs")
    return [dict(record, session_id=binding["session"]) for record in records]


def blocks(binding, all_sessions=False):
    _check_server(binding)
    if all_sessions:
        records = [record for session in _sessions(binding)
                   for record in _session_blocks(dict(binding, session=session))]
    else:
        try:
            records = _session_blocks(binding)
        except RexError as exc:
            if exc.kind != "target_not_found" or binding["session"] in _sessions(binding):
                raise
            records = []  # the pinned server independently confirms the session is gone
    _check_server(binding)
    return records


def windows(binding):
    _check_server(binding)
    return _records(_api(binding, "session.view"), "windows")


def _block_method(binding, block_id, method):
    if not full_id(block_id, "block"):
        raise RexError("Rex requires a full block ID", "invalid_target")
    return _cli(binding, "block", "call", "-s", binding["session"], "-b", block_id, method,
                operation=f"terminal {method}")


def block_process(binding, block_id):
    _check_server(binding)
    result = _block_method(binding, block_id, "process")
    if "last_exit" not in result:
        raise RexError("Rex process metadata lacks the terminal exit status")
    return result


def capture(binding, block_id, *, visible=False):
    _check_server(binding)
    if not full_id(block_id, "block"):
        raise RexError("Rex capture requires a full block ID", "invalid_target")
    if visible:
        rows = _block_method(binding, block_id, "size").get("rows")
        if type(rows) is not int or rows <= 0:
            raise RexError("Rex did not report the terminal's screen size")
    text = _cli(binding, "capture", "-s", binding["session"], "-b", block_id,
                operation="capture", expect_json=False)
    # Rex returns screen and scrollback together on the primary screen.
    return "\n".join(text.removesuffix("\n").split("\n")[-rows:]) if visible else text


def _tiled_blocks(layout):
    if not isinstance(layout, dict):
        return
    if full_id(layout.get("block_id"), "block"):
        _, _, width, height = layout["rect"]
        yield layout["block_id"], width * height
    elif isinstance(layout.get("split"), dict):
        for side in ("before", "after"):
            yield from _tiled_blocks(layout["split"].get(side))


def _placement(binding, caller_window, candidate_windows, panes_per_tab):
    for window in windows(binding):
        window_id = window.get("window_id")
        if (not full_id(window_id, "window") or window_id == caller_window
                or window_id not in candidate_windows or window.get("label") != WINDOW_LABEL):
            continue
        layers = _records(window, "layers")
        live_count = sum(len(_records(layer, "blocks")) for layer in layers)
        if live_count >= panes_per_tab:
            continue
        owned = candidate_windows[window_id]
        anchors = [item for layer in layers if layer.get("kind") == "tiled"
                   for item in _tiled_blocks(layer.get("layout")) if item[0] in owned]
        if anchors:
            anchor, _ = max(anchors, key=lambda item: item[1])
            return window_id, anchor, "horizontal" if live_count == 1 else "vertical"
    return None, None, None


def launch(binding, caller_window, candidate_windows, argv, cwd, panes_per_tab):
    try:
        window, anchor, direction = _placement(binding, caller_window, candidate_windows, panes_per_tab)
        _check_server(binding)
    except RexError as exc:
        raise RexError(f"Rex placement could not start: {exc}", "worker_absent") from exc
    layout = {"block": {"flavor": f"{TERMINAL}.shell", "label": binding["label"],
                        "options": {"shell": "none", "login": False, "command": argv, "cwd": str(cwd),
                                    "exit": {"on_completion": False}}}}
    if anchor is None:
        response = _api(binding, "session.new_window", window_label=WINDOW_LABEL, layout=layout, focus=False)
        window = response.get("window_id")
    else:
        response = _api(binding, "session.new_split", anchor_id=anchor, direction=direction, side="after",
                        layout=layout, focus=False)
    ids = response.get("block_ids")
    if (not full_id(window, "window") or not isinstance(ids, list) or len(ids) != 1
            or not full_id(ids[0], "block")):
        raise RexError("Rex creation did not return a full window and block ID")
    placement = reconcile(dict(binding, block=ids[0]))
    if placement is None:
        raise RexError("Rex did not confirm the new worker block")
    if placement["window"] != window:
        close(dict(binding, **placement))
        raise RexError("The Rex split anchor moved during creation; removed the misplaced worker", "worker_absent")
    return placement


def _check_block(binding, record):
    if (record.get("host_id") != binding["host_id"] or record.get("creator_name") != TERMINAL
            or record.get("placement") != "placed" or not full_id(record.get("window_id"), "window")
            or record.get("label") != binding["label"]
            or (binding.get("window") and record["window_id"] != binding["window"])):
        raise RexError("Rex block no longer matches its recorded host, window, or worker label", "identity_mismatch")


def reconcile(binding):
    matches = [record for record in blocks(binding) if record.get("label") == binding["label"]]
    if not matches:
        return None
    if len(matches) != 1:
        raise RexError("Rex worker label matched multiple blocks", "identity_mismatch")
    record = matches[0]
    _check_block(binding, record)
    if binding.get("block") and record["block_id"] != binding["block"]:
        raise RexError("Rex worker label does not match its recorded block ID", "identity_mismatch")
    return {"window": record["window_id"], "block": record["block_id"]}


def _owned_block(binding):
    for record in blocks(binding):
        if record["block_id"] == binding["block"]:
            _check_block(binding, record)
            return record
    return None


def get(binding):
    if binding.get("block") is None:
        raise RexError("Rex worker creation is unresolved", "creation_unresolved")
    if _owned_block(binding) is None:
        return None
    block = binding["block"]
    process = _block_method(binding, block, "process")
    if "last_exit" not in process:
        raise RexError("Rex process metadata lacks the terminal exit status")
    if process["last_exit"] is not None:
        return {"state": "finished", "status": None, "updated_at": None, "owner": None}
    processes = [process.get("child"), process.get("foreground"), *(process.get("ancestors") or [])]
    records = _records(_block_method(binding, block, "program_status"), "records")
    for record in records:
        owner, status, updated_at = record.get("owner"), record.get("state"), record.get("updated_at")
        if (not record.get("id") and isinstance(record.get("app"), str)
                and record["app"] in NATIVE_APPS[binding["harness"]]
                and isinstance(owner, dict) and type(owner.get("pid")) is int
                and any(isinstance(candidate, dict) and candidate.get("pid") == owner["pid"]
                        and candidate.get("name") == owner.get("name") for candidate in processes)
                and isinstance(status, str) and status in NATIVE_STATES
                and isinstance(updated_at, str) and updated_at):
            return {"state": "live", "status": status, "updated_at": updated_at, "owner": owner}
    return {"state": "live", "status": None, "updated_at": None, "owner": None}


def send(binding, text, baseline):
    try:
        if baseline.get("status") != "idle" or get(binding) != baseline:
            raise RexError("Rex worker changed before prompt paste")
    except RexError as exc:
        raise RexError(str(exc), "not_sent") from exc
    _api(binding, "block.event", block_id=binding["block"], event={"type": "paste", "payload": {"text": text}})
    if binding["harness"] == "codex":
        # Rex reports a completed paste when input is queued. Codex can still
        # buffer those bytes and absorb an immediately following Enter.
        time.sleep(0.3)
    if get(binding) != baseline:
        raise RexError("Rex worker changed after prompt paste; Enter was withheld", "worker_changed")
    _cli(binding, "send-key", "-s", binding["session"], "-b", binding["block"], "enter",
         operation="submit prompt", expect_json=False)


def close(binding):
    if binding.get("block") is None:
        found = reconcile(binding)
        if found is None:
            raise RexError("Rex creation outcome is unresolved; no owned block can be confirmed", "creation_unresolved")
        binding = dict(binding, **found)
    if _owned_block(binding) is None:
        return {"block": "already_gone"}
    _check_server(binding)
    try:
        _api(binding, "block.close", block_id=binding["block"])
    except RexError:
        if _owned_block(binding) is None:
            return {"block": "already_gone"}
        raise
    if _owned_block(binding) is not None:
        raise RexError("Rex did not confirm removal of the recorded worker block")
    return {"block": "closed"}
