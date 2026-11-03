from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import time
import tomllib


class CoreError(Exception):
    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


def executable():
    official = shutil.which("herdr-core")
    if official:
        return str(Path(official).resolve())
    alias = shutil.which("hc")
    if alias:
        try:
            probe = subprocess.run([alias, "--version"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CoreError(f"cannot identify installed hc: {exc}") from exc
        if probe.returncode == 0 and probe.stdout.startswith("hc "):
            return str(Path(alias).resolve())
    return None


def new_binding(binary):
    session = os.environ.get("HC_SESSION", "").strip() or "default"
    if session in (".", "..") or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in session):
        raise CoreError("invalid HC_SESSION; core was not started", "usage")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config").resolve()
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state").resolve()
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    run = Path(runtime).resolve() if runtime else Path(f"/run/user/{os.getuid()}")
    config_socket = None
    config_file = config_home / "herdr-core/config.toml"
    if config_file.exists():
        try:
            config_socket = tomllib.loads(config_file.read_text()).get("socket")
        except (OSError, ValueError) as exc:
            raise CoreError(f"cannot read core configuration: {exc}") from exc
    endpoint = os.environ.get("HC_SOCKET") or config_socket
    if not endpoint:
        folder = run / "herdr-core" if run.is_dir() else state_home / "herdr-core" / session
        endpoint = folder / (session + ".sock")
    binding = {"kind": "core", "executable": binary, "session": session,
               "endpoint": str(Path(endpoint).resolve()), "core_id": None, "terminal": None,
               "env": {"XDG_CONFIG_HOME": str(config_home), "XDG_STATE_HOME": str(state_home)}}
    if runtime:
        binding["env"]["XDG_RUNTIME_DIR"] = str(run)
    env = cli_env(binding)
    try:
        proc = subprocess.run([binary, "--json", "server", "start"], env=env,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CoreError(f"core startup failed: {exc}") from exc
    if proc.returncode:
        raise CoreError(f"installed core startup failed: {(proc.stderr or proc.stdout).strip()[:1000]}")
    with Connection(binding) as connection:
        binding["core_id"] = connection.core_id
    return binding


def validate(binding):
    required = ("executable", "session", "endpoint", "core_id", "terminal", "name", "nonce")
    if (any(not isinstance(binding.get(k), str) or not binding[k] for k in required)
            or not Path(binding["endpoint"]).is_absolute()
            or not Path(binding["executable"]).is_absolute()
            or not isinstance(binding.get("env"), dict)
            or any(k not in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")
                   or not isinstance(v, str) for k, v in binding["env"].items())):
        raise ValueError("invalid core backend binding")


def cli_env(binding):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "XDG_"))}
    env.update(binding["env"])
    env.update(HC_SESSION=binding["session"], HC_SOCKET=binding["endpoint"])
    return env


class Connection:
    def __init__(self, binding, timeout=30):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.stream = None
        try:
            self.socket.connect(binding["endpoint"])
            self.stream = self.socket.makefile("rb", buffering=0)
            hello = self.call("hello")
            self.core_id = hello["core"]["id"]
            if binding.get("core_id") and self.core_id != binding["core_id"]:
                raise CoreError("core identity differs at recorded endpoint; refusing operation", "identity_mismatch")
        except OSError as exc:
            self.close()
            raise CoreError(f"recorded core endpoint unavailable: {exc}") from exc
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.stream:
            self.stream.close()
        self.socket.close()

    def receive(self):
        try:
            line = self.stream.readline()
            if not line:
                raise CoreError("core connection closed; outcome may be unknown")
            return json.loads(line)
        except (OSError, ValueError) as exc:
            raise CoreError(f"core response unavailable: {exc}; outcome may be unknown") from exc

    def call(self, method, **params):
        try:
            self.socket.sendall((json.dumps({"jsonrpc": "2.0", "id": 1,
                                            "method": method, "params": params}) + "\n").encode())
        except OSError as exc:
            raise CoreError(f"core request failed: {exc}; outcome may be unknown") from exc
        reply = self.receive()
        error = reply.get("error")
        if error:
            kind = (error.get("data") or {}).get("kind")
            raise CoreError(f"{kind or 'core_error'}: {error.get('message')}", kind)
        if "result" not in reply:
            raise CoreError("invalid core response")
        return reply["result"]


def call(binding, method, **params):
    try:
        with Connection(binding) as connection:
            return connection.call(method, **params)
    except OSError as exc:
        raise CoreError(f"recorded core endpoint unavailable: {exc}") from exc


def get(binding):
    try:
        terminal = call(binding, "terminal.get", terminal=binding["terminal"])
    except CoreError as exc:
        if exc.kind == "not_found":
            return None
        raise
    if (not isinstance(terminal, dict) or terminal.get("state") not in ("live", "finished")
            or isinstance(terminal.get("turn"), bool) or not isinstance(terminal.get("turn"), int)
            or not isinstance(terminal.get("reported"), bool)
            or (terminal.get("status") is not None and not isinstance(terminal["status"], dict))):
        raise CoreError("core get returned invalid terminal facts")
    labels = terminal.get("labels", {})
    if terminal.get("name") != binding["name"] or labels.get("horch.nonce") != binding["nonce"]:
        raise CoreError("terminal identity does not match task; refusing operation", "identity_mismatch")
    return terminal


def launch(binding, harness, argv, cwd):
    program = shutil.which(harness)
    if not program:
        raise CoreError(f"configured harness {harness} is not installed")
    # The core can have inherited a different controller's environment.
    command = [sys.executable, str(Path(__file__).resolve()), "--exec", program, *argv]
    env = {k: os.environ[k] for k in ("PATH", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")
           if k in os.environ}
    return call(binding, "terminal.run", argv=command, cwd=str(cwd), name=binding["name"],
                labels={"horch.task": binding["name"], "horch.nonce": binding["nonce"]},
                no_parent=True, no_notify=True, env=env)


def status(terminal):
    return (terminal.get("status") or {}).get("state")


def fingerprint(terminal):
    if terminal is None:
        return None
    return terminal.get("state"), status(terminal), terminal.get("reported"), terminal.get("turn")


def wait_changes(observations, seconds):
    if seconds <= 0:
        return
    try:
        with ExitStack() as stack:
            connections = []
            for binding, terminal in observations:
                connection = stack.enter_context(Connection(binding))
                snapshot = connection.call("events.subscribe", terminal=binding["terminal"])
                current = next(iter(snapshot["terminals"]), None)
                if fingerprint(current) != fingerprint(terminal):
                    return
                connections.append(connection.socket)
            if connections:
                select.select(connections, [], [], seconds)
    except OSError as exc:
        raise CoreError(f"core event connection failed: {exc}") from exc


def ready(binding, seconds):
    deadline = time.monotonic() + seconds
    while True:
        terminal = get(binding)
        word = status(terminal) if terminal else None
        if terminal and terminal["state"] == "live" and terminal.get("reported") and word == "idle":
            return terminal
        if terminal is None or terminal["state"] != "live" or word in ("blocked", "error"):
            raise CoreError("worker did not reach native idle readiness; no task was sent")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CoreError("native idle readiness missing; inspect startup/trust dialog; no task was sent")
        wait_changes([(binding, terminal)], remaining)


def close(binding):
    terminal = get(binding)
    if terminal is None:
        return {"terminal": "already_gone"}
    if terminal["state"] == "live":
        call(binding, "terminal.kill", terminal=binding["terminal"])
        terminal = get(binding)
    if terminal is not None and terminal["state"] != "finished":
        raise CoreError("kill did not confirm a finished terminal; reservation retained")
    if terminal is not None:
        call(binding, "terminal.rm", terminal=binding["terminal"])
    if get(binding) is not None:
        raise CoreError("terminal removal not confirmed; reservation retained")
    return {"terminal": "removed"}


if __name__ == "__main__" and sys.argv[1:2] == ["--exec"]:
    for key in list(os.environ):
        if key.startswith("HERDR") or key in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "PI_SESSION_ID", "CLAUDECODE"):
            os.environ.pop(key, None)
    os.environ["HERDR_ENV"] = "0"
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
