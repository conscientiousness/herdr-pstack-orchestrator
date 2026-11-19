#!/usr/bin/env python3
"""Verify horch worker placement and delivery on an isolated, real Rex server."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


HORCH = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
LEDGERS = {"alpha": [37, -12, 60, -5], "beta": [41, 7, -70, 19]}
MUX_PREFIXES = ("REX_", "HERDR", "HC_")
AGENT_SESSION_KEYS = {"CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"}
FIXTURE = r'''import json, os, pathlib, re, select, sys, tty
root = pathlib.Path(__file__).resolve().parents[1]
if "--version" in sys.argv or "--list-models" in sys.argv:
    print("pi rex-e2e-fixture 1" if "--version" in sys.argv else "provider model")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())

tty.setraw(0)
os.write(1, b"\x1b[?2004hREX_E2E_READY\r\n")
report("idle")
buffer = b""
mode = None
finished = False
while True:
    if mode and not finished and (root / f"{mode}.release").is_file():
        report("done")
        finished = True
    if not select.select([0], [], [], 0.05)[0]:
        continue
    data = os.read(0, 4096)
    if not data:
        break
    lines = re.split(rb"[\r\n]", buffer + data)
    buffer = lines.pop()
    for line in lines:
        match = re.search(rb"Read (/[^\x1b]+?/brief\.md) in full", line)
        if not match:
            continue
        if mode:
            (root / f"{mode}.duplicate").touch()
            continue
        brief = pathlib.Path(os.fsdecode(match.group(1)))
        text = brief.read_text()
        mode = re.search(r"^REX_E2E_MODE=(\w+)$", text, re.MULTILINE).group(1)
        charges = json.loads(re.search(r"^REX_E2E_CHARGES=(.*)$", text, re.MULTILINE).group(1))
        task_id = re.search(r'"task_id"\s*:\s*"([^"]+)"', text).group(1)
        nonce = re.search(r'"nonce"\s*:\s*"([^"]+)"', text).group(1)
        result = brief.with_name("result.json")
        report("working")
        running_total = 0
        balances = []
        for charge in charges:
            running_total += charge
            balances.append(running_total)
        (result.parent / "balances.json").write_text(json.dumps(balances))
        temporary = result.with_suffix(".new")
        temporary.write_text(json.dumps({"task_id": task_id, "nonce": nonce, "status": "completed",
                                         "summary": f"Computed {mode} balances.",
                                         "files": ["balances.json"], "question": None}))
        temporary.replace(result)
'''


def write_json(path, data):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def rows(proc):
    if proc.returncode:
        raise RuntimeError((proc.stdout or proc.stderr).strip()[:1000])
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def horch(path, *args, env=None, timeout=100):
    return subprocess.run([sys.executable, str(path), *args], env=env, timeout=timeout,
                          capture_output=True, text=True)


def controller(root, program):
    """Run inside Rex so the public CLI sees the actual terminal's environment."""
    observation = {"session": os.environ.get("REX_SESSION"), "block": os.environ.get("REX_BLOCK")}
    try:
        observation["detected"] = rows(horch(program, "detect"))[0]["backend"]
        if observation["detected"] != "rex":
            raise RuntimeError(f"Rex controller reported backend {observation['detected']!r}")
        observation["runs"] = {}
        for mode, charges in LEDGERS.items():
            brief = root / f"{mode}.md"
            brief.write_text(f"REX_E2E_MODE={mode}\nREX_E2E_CHARGES={json.dumps(charges)}\n")
            observation["runs"][mode] = rows(horch(program, "run", "fixture", "--brief", str(brief)))[0]
        mixed = horch(program, "detect", env=dict(os.environ, HERDR_ENV="1"))
        observation["mixed_context_rejected"] = (mixed.returncode == 1
                                                  and json.loads(mixed.stdout)["error"] == "caller_context_conflict")
    except Exception as exc:
        observation["error"] = str(exc)
    write_json(root / "controller.json", observation)
    while not (root / "controller.release").exists():
        time.sleep(0.1)


class Scenario:
    def __init__(self, args, rex, root, listener):
        self.args, self.root = args, root
        self.endpoint = f"unix://{listener}"
        self.cli = [rex, "--autostart=false", "-S", self.endpoint]
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(MUX_PREFIXES) and key not in AGENT_SESSION_KEYS}
        bindir = root / "bin"
        bindir.mkdir()
        self.env.update(PATH=str(bindir) + os.pathsep + os.defpath,
                        XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"))
        (bindir / "rex").symlink_to(Path(rex).resolve())
        fixture = bindir / "pi"
        fixture.write_text(f"#!{sys.executable}\n" + FIXTURE)
        fixture.chmod(0o700)
        for name in ("herdr", "herdr-core", "hc"):
            guard = bindir / name
            guard.write_text('#!/bin/sh\ntouch "$(dirname "$0")/../herdr-invoked"\nexit 97\n')
            guard.chmod(0o700)
        config = root / "config/herdr-orchestrator/workers.toml"
        config.parent.mkdir(parents=True)
        config.write_text('max_active_workers = 2\n[workers.fixture]\nharness = "pi"\nmodel = "fixture"\n')
        self.init = root / "init.lua"
        self.init.touch()
        self.checks = {}
        self.evidence = {"schema": "horch/rex-backend-e2e/v1", "verdict": "fail", "checks": self.checks,
                         "scope": "real Rex; two deterministic interactive Pi workers; no model calls",
                         "deliveries": {},
                         "rerun": shlex.join([sys.executable, str(Path(__file__).resolve()),
                                               "--horch", str(args.horch), "--output", str(args.output)])}

    def rx(self, *args):
        proc = subprocess.run([*self.cli, *args], env=self.env, timeout=15, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError((proc.stdout or proc.stderr).strip()[:1000])
        return json.loads(proc.stdout)

    def check(self, name, fact):
        self.checks[name] = bool(fact)
        if not fact:
            raise AssertionError(name)

    def until_file(self, path, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text())
            time.sleep(0.1)
        raise TimeoutError(f"no {path.name} after {seconds} seconds")

    def session(self, label, *argv):
        result = self.rx("new", label, "--cwd", str(self.root), "--shell=none", "--keep-open", "--json", "--", *argv)
        first = result["initial_windows"][0]
        return result["session_id"], first["window_id"], first["block_ids"][0]

    def windows(self, session):
        return self.rx("session", "inspect", session, "--json")

    def blocks(self, session):
        return self.rx("block", "ls", "-s", session, "--json")["blocks"]

    def verify(self):
        self.evidence["rex_version"] = self.rx("whoami", "--json")["rex_version"]
        other, _, other_block = self.session("unrelated", "/bin/sleep", "300")
        baseline = self.windows(other)
        session, controller_window, controller_block = self.session(
            "project", "/usr/bin/env", f"REX_SERVER={self.endpoint}", f"PATH={self.env['PATH']}", sys.executable,
            str(Path(__file__).resolve()), "--horch", str(self.args.horch), "--controller", str(self.root))
        observed = self.until_file(self.root / "controller.json", 200)
        if observed.get("error"):
            raise RuntimeError(observed["error"])
        self.check("inherited Rex environment routes dispatch", observed["detected"] == "rex"
                   and observed["session"] == session and observed["block"] == controller_block)
        self.check("simultaneous Rex and Herdr context is rejected", observed["mixed_context_rejected"])
        runs = observed["runs"]
        tasks = {mode: json.loads((Path(row["task_dir"]) / "task.json").read_text())
                 for mode, row in runs.items()}
        bindings = [task["backend"] for task in tasks.values()]
        self.check("both tasks were submitted on the same Rex session", len(bindings) == 2 and all(
            binding["kind"] == "rex" and binding["session"] == session and binding["endpoint"] == self.endpoint
            for binding in bindings) and all(row["backend"] == "rex" and row["startup_ready"]
                                             and row["submission"] == "sent" for row in runs.values()))
        worker_window = bindings[0]["window"]
        worker_blocks = {binding["block"] for binding in bindings}
        live_layout = self.windows(session)
        self.check("both workers share a background rexOrch tab", worker_window != controller_window
                   and len(worker_blocks) == 2 and all(binding["window"] == worker_window for binding in bindings)
                   and live_layout["active_window_id"] == controller_window
                   and any(row["window_id"] == worker_window and row["label"] == "rexOrch"
                           for row in live_layout["windows"])
                   and {row["block_id"] for row in self.blocks(session) if row["window_id"] == worker_window}
                   == worker_blocks)
        self.evidence["layout"] = {"session": session, "controller": controller_window,
                                   "worker": worker_window, "worker_blocks": sorted(worker_blocks)}

        wait_env = dict(self.env, REX_SERVER=self.endpoint + ".absent", REX_SESSION=other, REX_BLOCK=other_block)
        for mode, run in runs.items():
            task = tasks[mode]
            result = self.until_file(Path(task["result_path"]), 15)
            early, = rows(horch(self.args.horch, "wait", run["task_id"], "--max-seconds", "0", env=wait_env))
            self.check(f"{mode} stays running with a result but without turn completion",
                       early["state"] == "running" and not early["closed"] and early["summary"] is None)
            (self.root / f"{mode}.release").touch()
            done, = rows(horch(self.args.horch, "wait", run["task_id"], "--max-seconds", "15", env=wait_env))
            balances = json.loads(Path(done["result_path"]).with_name("balances.json").read_text())
            charges = LEDGERS[mode]
            self.check(f"{mode} delivers exact output and closes by stored Rex binding", done["state"] == "done"
                       and done["closed"] and done["summary"] == f"Computed {mode} balances."
                       and done["files"] == ["balances.json"] and result["task_id"] == run["task_id"]
                       and result["nonce"] == task["nonce"] and result["status"] == "completed"
                       and balances == [sum(charges[:index + 1]) for index in range(len(charges))])
            self.evidence["deliveries"][mode] = {"state": done["state"], "closed": done["closed"],
                                                  "balances": balances}
            worker_blocks.remove(task["backend"]["block"])
            self.check(f"{mode} leaves only the remaining owned blocks and controller", {
                row["block_id"] for row in self.blocks(session)} == worker_blocks | {controller_block})
        self.check("last block closure removes only the worker tab", {
            row["window_id"] for row in self.windows(session)["windows"]} == {controller_window})
        after = self.windows(other)
        self.check("unrelated Rex session stayed intact", baseline["windows"] == after["windows"]
                   and baseline["active_window_id"] == after["active_window_id"])
        self.check("no Herdr command or duplicate prompt", not (self.root / "herdr-invoked").exists()
                   and not list(self.root.glob("*.duplicate")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--controller", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.horch = args.horch.resolve()
    if args.controller:
        controller(args.controller, args.horch)
        return 0
    rex = shutil.which("rex")
    if not rex or args.output is None:
        parser.error("an installed Rex CLI and --output outside the checkout are required")
    args.output = args.output.resolve()
    if args.output.is_relative_to(HORCH.parents[3]):
        parser.error("keep Rex evidence outside the checkout")
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="rex-backend-", dir=args.output))
    receipt = root / "evidence.json"
    with tempfile.TemporaryDirectory(prefix="rx-", dir="/tmp") as runtime:
        listener = Path(runtime) / "server.sock"
        scenario = Scenario(args, rex, root, listener)
        with (root / "server.log").open("w") as log:
            server = subprocess.Popen([rex, "server", "run", "--listen", scenario.endpoint,
                                       "--state-dir", str(Path(runtime) / "state"), "--restore=false",
                                       "--config", str(scenario.init)], env=scenario.env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while not listener.exists() and server.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                scenario.check("isolated Rex server ready", listener.exists())
                scenario.verify()
                scenario.evidence["verdict"] = "pass"
            except Exception as exc:
                scenario.evidence["problem"] = str(exc)
            finally:
                (root / "controller.release").touch()
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
                        scenario.evidence["verdict"] = "fail"
                        scenario.evidence["problem"] = "isolated Rex required forced shutdown"
                scenario.evidence["server_stopped"] = server.poll() is not None
                write_json(receipt, scenario.evidence)
    print(receipt)
    return 0 if scenario.evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
