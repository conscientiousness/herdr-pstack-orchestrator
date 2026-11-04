#!/usr/bin/env python3
"""Black-box core backend E2E with real herdr-core and a deterministic Pi fixture.

No models, real Pi integration, or legacy lifecycle are tested.
Optional --viewer checks real Herdr attachment with HERDR_ENV absent: explicit
and inherited caller identity must create same-workspace viewers, incomplete
context must stop both run/check before launch, and cleanup must close viewers.
Evidence survives cleanup. Product mode is expected to fail before core support.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid


HORCH = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
RESULT_KEYS = {"task_id", "nonce", "status", "summary", "files", "question"}
SCENARIOS = {"valid": "done", "missing": "result_missing", "invalid": "result_invalid",
             "blocked": "blocked", "cancel": None}
FIXTURE = r'''import json, os, pathlib, re, sys, termios, time, tty
root = pathlib.Path(os.environ["CORE_E2E_ROOT"])
if "--version" in sys.argv:
    print("pi core-e2e-fixture 1")
    sys.exit(0)
(root / ("fixture-start-" + str(os.getpid()))).write_text(json.dumps(sys.argv))
def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())
tty.setraw(0)
report("idle")
buf = ""
while True:
    chunk = os.read(0, 4096)
    if not chunk:
        sys.exit(0)
    buf += chunk.decode(errors="replace")
    match = re.search(r"(/[^\s\x1b]+/brief\.md)", buf)
    if not match:
        continue
    brief = pathlib.Path(match.group(1))
    if not brief.is_file():
        continue
    text = brief.read_text()
    mode = re.search(r"CORE_E2E_CASE=(\w+)", text).group(1)
    task_id = re.search(r'"task_id"\s*:\s*"([^"]+)"', text).group(1)
    nonce = re.search(r'"nonce"\s*:\s*"([^"]+)"', text).group(1)
    result = re.search(r"Write `result.json` at exactly this path:\s*([^\s]+)", text).group(1)
    report("working")
    os.write(1, ("CORE_E2E_CASE=" + mode + "\r\n").encode())
    row = {"brief": str(brief), "task_id": task_id, "nonce": nonce,
           "result_path": result, "pid": os.getpid(), "mode": mode}
    (root / (mode + ".prompt.json")).write_text(json.dumps(row))
    if mode in ("valid", "invalid"):
        payload = {"task_id": task_id, "nonce": nonce if mode == "valid" else "wrong-nonce",
                   "status": "completed", "summary": "Deterministic interactive fixture result.",
                   "files": [], "question": None}
        path = pathlib.Path(result)
        tmp = path.with_suffix(".fixture-tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)
    if mode == "blocked":
        report("blocked")
    while not (root / (mode + ".release")).exists():
        time.sleep(0.05)
    (root / (mode + ".ended")).write_text("released for done report\n")
    report("done")
    buf = ""
'''
GUARD = r'''import json, os, pathlib, sys
root = pathlib.Path(os.environ["CORE_E2E_ROOT"])
with (root / "forbidden-cli.jsonl").open("a") as f:
    f.write(json.dumps(sys.argv) + "\n")
print("core E2E refuses legacy Herdr and the potentially unrelated hc alias", file=sys.stderr)
sys.exit(97)
'''


def unwrap(value):
    return value.get("result", value) if isinstance(value, dict) else value


def rows(stdout):
    return [unwrap(json.loads(line)) for line in stdout.splitlines() if line.strip()]


class Run:
    def __init__(self, args, core):
        self.args, self.core = args, core
        self.root = Path(tempfile.mkdtemp(prefix="core-backend-", dir=args.output))
        self.runtime = Path(tempfile.mkdtemp(prefix="hce-", dir="/tmp"))
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("HERDR", "HC_"))}
        self.env.update(HC_SESSION="e2e-" + uuid.uuid4().hex[:10],
                        XDG_CONFIG_HOME=str(self.root / "config"),
                        XDG_STATE_HOME=str(self.root / "state"),
                        XDG_RUNTIME_DIR=str(self.runtime), CORE_E2E_ROOT=str(self.root))
        self.checks, self.commands, self.waiters = [], [], []
        self.evidence = {"schema": "horch/core-backend-e2e/v1", "verdict": "fail",
                         "mode": "baseline" if args.baseline else "product",
                         "scope": "headless real core; deterministic interactive pi fixture; no models",
                         "unverified": ["actual Pi hooks, auth, trust, and model execution",
                                        "visible hcOrch tabs and legacy horch tabs",
                                        "absence-only live legacy fallback", "mixed-backend task affinity"],
                         "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                           for p in (args.horch, Path(__file__), core)},
                         "session": self.env["HC_SESSION"], "runtime": str(self.runtime),
                         "checks": self.checks, "commands": self.commands}
        bindir = self.root / "bin"
        bindir.mkdir()
        for name, program in (("pi", FIXTURE), ("herdr", GUARD), ("hc", GUARD)):
            path = bindir / name
            path.write_text("#!" + sys.executable + "\n" + program)
            path.chmod(0o700)
        (bindir / "herdr-core").symlink_to(core)
        self.env["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
        self.evidence["executables"] = {name: shutil.which(name, path=self.env["PATH"])
                                         for name in ("pi", "herdr-core", "hc", "herdr")}
        config = self.root / "config/herdr-orchestrator/workers.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[workers.fixture]\nharness = "pi"\nmodel = "fixture-no-model"\n')

    def check(self, name, ok):
        self.checks.append({"name": name, "ok": bool(ok)})
        if not ok:
            raise AssertionError(name)

    def command(self, argv, env=None, timeout=120):
        label = f"command-{len(self.commands):03d}"
        row = {"argv": list(map(str, argv)), "stdout": label + ".stdout",
               "stderr": label + ".stderr"}
        self.commands.append(row)
        try:
            proc = subprocess.run(argv, env=env or self.env, capture_output=True,
                                  text=True, timeout=timeout)
            row["returncode"] = proc.returncode
            (self.root / row["stdout"]).write_text(proc.stdout)
            (self.root / row["stderr"]).write_text(proc.stderr)
            return proc
        except subprocess.TimeoutExpired as exc:
            row["timeout"] = timeout
            for key in ("stdout", "stderr"):
                value = getattr(exc, key) or b""
                (self.root / row[key]).write_text(value.decode(errors="replace")
                                                if isinstance(value, bytes) else value)
            raise

    def hc(self, *args, env=None):
        return self.command([str(self.core), "--json", *args], env=env, timeout=30)

    def cli(self, *args, env=None):
        return self.command([sys.executable, str(self.args.horch), *args], env=env)

    def terminals(self):
        proc = self.hc("ls", "--all")
        if proc.returncode:
            raise RuntimeError("independent core ls failed")
        return unwrap(json.loads(proc.stdout))["terminals"]

    def get(self, address):
        proc = self.hc("get", address)
        if proc.returncode == 3:
            return None
        if proc.returncode:
            raise RuntimeError("independent core get failed without authoritative absence")
        return unwrap(json.loads(proc.stdout))

    def until(self, label, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.1)
        raise TimeoutError(label)

    def no_guard(self):
        self.check("no legacy Herdr or unrelated hc invocation",
                   not (self.root / "forbidden-cli.jsonl").exists())

    def launch(self, mode, env=None):
        brief = self.root / (mode + "-input.md")
        brief.write_text("CORE_E2E_CASE=" + mode + "\nFollow the deterministic fixture protocol.\n")
        return self.cli("run", "fixture", "--brief", str(brief), "--cwd", str(self.root), env=env)

    def baseline(self):
        proc = self.launch("baseline")
        parsed = rows(proc.stdout)
        self.check("current headless backend support is explicitly absent",
                   proc.returncode == 1 and len(parsed) == 1
                   and parsed[0].get("error") == "not_in_herdr")
        self.check("baseline did not launch fixture", not list(self.root.glob("fixture-start-*")))
        self.check("baseline did not allocate core workers", not self.terminals())
        self.no_guard()
        self.evidence["verdict"] = "baseline-unsupported"

    def wait_start(self, task_id, mode):
        out = (self.root / (mode + "-wait.stdout")).open("w")
        err = (self.root / (mode + "-wait.stderr")).open("w")
        argv = [sys.executable, str(self.args.horch), "wait", task_id]
        proc = subprocess.Popen(argv, env=self.env, stdout=out, stderr=err, text=True)
        self.waiters.append((proc, out, err))
        self.commands.append({"argv": argv, "pid": proc.pid,
                              "stdout": out.name, "stderr": err.name})
        return proc

    def wait_finish(self, proc, mode, task_id, expected):
        proc.wait(timeout=45)
        actual = rows((self.root / (mode + "-wait.stdout")).read_text())
        self.check(mode + " public wait state", proc.returncode == 0 and any(
            r.get("task_id") == task_id and r.get("state") == expected for r in actual))
        return next(r for r in actual if r.get("task_id") == task_id)

    def scenario(self, mode, expected):
        before = {t["address"] for t in self.terminals()}
        launched = self.launch(mode)
        self.check(mode + " public run succeeds headless", launched.returncode == 0)
        task = rows(launched.stdout)[0]
        task_id = task["task_id"]
        prompt_path = self.root / (mode + ".prompt.json")
        self.until(mode + " fixture receives brief pointer", prompt_path.exists)
        prompt = json.loads(prompt_path.read_text())
        self.check(mode + " prompt identity matches run", prompt["task_id"] == task_id)
        new = [t for t in self.terminals() if t["address"] not in before]
        self.check(mode + " preference creates one actual core terminal", len(new) == 1)
        address = new[0]["address"]
        observed = self.until(mode + " core reports status", lambda: (
            t if (t := self.get(address)) and (t.get("status") or {}).get("state") ==
            ("blocked" if mode == "blocked" else "working") else None))
        (self.root / (mode + "-core.json")).write_text(json.dumps(observed, indent=2) + "\n")
        self.no_guard()
        if mode == "valid":
            result = Path(prompt["result_path"])
            self.until("fixture writes early result", result.exists)
            payload = json.loads(result.read_text())
            self.check("exact old nonce-bound result protocol", set(payload) == RESULT_KEYS
                       and payload["task_id"] == task_id and payload["nonce"] == prompt["nonce"]
                       and payload["status"] == "completed" and payload["question"] is None
                       and isinstance(payload["summary"], str) and payload["files"] == [])
            bounded = self.cli("wait", task_id, "--max-seconds", "1")
            current = rows(bounded.stdout)[0]
            self.check("valid early result cannot finish working turn",
                       bounded.returncode == 0 and current["state"] == "running"
                       and not current["closed"] and current.get("summary") is None)
        waiter = self.wait_start(task_id, mode)
        if mode in ("blocked", "cancel"):
            if mode == "blocked":
                self.wait_finish(waiter, mode, task_id, "blocked")
            else:
                time.sleep(1)
                self.check("original cancel wait stays alive", waiter.poll() is None)
            closed = self.cli("close", task_id)
            self.check(mode + " explicit close succeeds", closed.returncode == 0)
            if mode == "cancel":
                waiter.wait(timeout=30)
                cancelled = rows((self.root / (mode + "-wait.stdout")).read_text())
                self.check("cancellation does not deliver result", cancelled and all(
                    r.get("state") != "done" and r.get("summary") is None for r in cancelled))
        else:
            time.sleep(1)
            self.check(mode + " original wait stays alive before ended turn", waiter.poll() is None)
            (self.root / (mode + ".release")).write_text("release\n")
            ended = self.wait_finish(waiter, mode, task_id, expected)
            self.check(mode + " turn was actually released", (self.root / (mode + ".ended")).exists())
            if mode == "valid":
                self.check("ended turn delivers and auto-closes", ended["closed"]
                           and ended["summary"] == "Deterministic interactive fixture result.")
            else:
                self.check(mode + " result problem not delivered", ended.get("summary") is None)
                closed = self.cli("close", task_id)
                self.check(mode + " explicit cleanup succeeds", closed.returncode == 0)
        self.until(mode + " independent terminal is no longer live", lambda: (
            not (t := self.get(address)) or t.get("state") != "live"))
        self.no_guard()

    def settled_endpoint(self):
        first, second = Run(self.args, self.core), Run(self.args, self.core)
        second.env["XDG_STATE_HOME"] = first.env["XDG_STATE_HOME"]
        first_cleaned = False
        passed = False
        for child in (first, second):
            child.evidence.update(mode="settled-endpoint-child", verdict="scenario-fail",
                                  scope="two owned real cores sharing a scratch task store; settled endpoint isolation; no models")
        self.evidence["settled_endpoint"] = {"artifacts": [str(first.root), str(second.root)]}
        try:
            for child in (first, second):
                child.check("settled endpoint owned core starts", child.hc("server", "start").returncode == 0)
                child.check("settled endpoint owned core initially empty", not child.terminals())
            launched = first.launch("blocked")
            first.check("settled endpoint blocked run succeeds", launched.returncode == 0)
            old = rows(launched.stdout)[0]
            first.until("blocked fixture consumes prompt", lambda: (first.root / "blocked.prompt.json").exists())
            prompt = json.loads((first.root / "blocked.prompt.json").read_text())
            first.check("settled endpoint blocked prompt identity", prompt["task_id"] == old["task_id"])
            blocked = first.cli("wait", old["task_id"], "--max-seconds", "2")
            first.check("settled endpoint stores blocked state", blocked.returncode == 0
                        and rows(blocked.stdout)[0]["state"] == "blocked")
            stored = Path(old["task_dir"]) / "state.json"
            before = stored.read_bytes()
            first.cleanup()
            first_cleaned = True
            first.check("settled endpoint first core cleanup succeeds", first.evidence["cleanup"]["ok"])
            binding = json.loads((Path(old["task_dir"]) / "task.json").read_text())["backend"]
            first.check("settled endpoint is unavailable", not Path(binding["endpoint"]).exists())
            launched = second.launch("valid")
            second.check("settled endpoint healthy run succeeds", launched.returncode == 0)
            live = rows(launched.stdout)[0]
            second.until("healthy fixture consumes prompt", lambda: (second.root / "valid.prompt.json").exists())
            prompt = json.loads((second.root / "valid.prompt.json").read_text())
            second.check("settled endpoint healthy prompt identity", prompt["task_id"] == live["task_id"])
            result = Path(live["task_dir"]) / "result.json"
            second.until("healthy fixture writes result", result.exists)
            payload = json.loads(result.read_text())
            second.check("settled endpoint exact nonce result", set(payload) == RESULT_KEYS
                         and payload["task_id"] == live["task_id"] and payload["nonce"] == prompt["nonce"]
                         and payload["status"] == "completed" and payload["files"] == []
                         and payload["question"] is None
                         and payload["summary"] == "Deterministic interactive fixture result.")
            (second.root / "valid.release").write_text("release\n")
            ended = second.until("healthy independent native ended turn", lambda: (
                t if (t := second.get(live["terminal_id"])) and
                (t.get("status") or {}).get("state") == "done" and t.get("turn", 0) > 0 else None))
            (second.root / "independent-ended.json").write_text(json.dumps(ended, indent=2) + "\n")
            second.check("settled endpoint healthy native turn advanced", ended["turn"] > 0)
            batch = second.cli("wait", old["task_id"], live["task_id"], "--max-seconds", "2")
            recheck = second.cli("wait", old["task_id"], "--recheck", "--max-seconds", "2")
            self.evidence["settled_endpoint"].update(
                batch_returncode=batch.returncode, batch_stdout=batch.stdout,
                recheck_returncode=recheck.returncode, recheck_stdout=recheck.stdout)
            actual = rows(batch.stdout)
            second.check("settled endpoint batch delivers stored blocked and healthy done",
                         batch.returncode == 0 and len(actual) == 2
                         and actual[0]["task_id"] == old["task_id"] and actual[0]["state"] == "blocked"
                         and not actual[0]["closed"] and actual[0]["summary"] is None
                         and actual[1]["task_id"] == live["task_id"] and actual[1]["state"] == "done"
                         and actual[1]["closed"] and actual[1]["summary"] == payload["summary"])
            second.check("settled endpoint explicit recheck reports transport error",
                         recheck.returncode == 1 and rows(recheck.stdout)[0].get("error") == "core_error")
            second.check("settled endpoint problem state unchanged", stored.read_bytes() == before)
            healthy = second.cli("wait", live["task_id"], "--max-seconds", "2")
            second.check("settled endpoint healthy delivery remains available", healthy.returncode == 0
                         and rows(healthy.stdout)[0]["state"] == "done" and rows(healthy.stdout)[0]["closed"])
            second.check("settled endpoint healthy terminal is closed", not (t := second.get(live["terminal_id"]))
                         or t.get("state") != "live")
            first.no_guard()
            second.no_guard()
            passed = True
        finally:
            if not first_cleaned:
                first.cleanup()
            second.cleanup()
            for child in (first, second):
                child.evidence["verdict"] = "scenario-pass" if passed and child.evidence["cleanup"]["ok"] else "scenario-fail"
                self.checks.extend(child.checks)
                (child.root / "evidence.json").write_text(json.dumps(child.evidence, indent=2) + "\n")
            self.check("settled endpoint both owned cores cleaned", all(
                child.evidence["cleanup"]["ok"] and not child.runtime.exists() for child in (first, second)))

    def broken_core(self):
        broken = dict(self.env, HC_SESSION="invalid/session")
        probe = self.hc("ls", env=broken)
        self.check("installed real core independently rejects invalid session", probe.returncode != 0)
        before = self.terminals()
        started = set(self.root.glob("fixture-start-*"))
        proc = self.launch("broken", env=broken)
        self.check("installed unusable core fails rather than launching", proc.returncode != 0)
        self.check("broken core does not launch fixture", set(self.root.glob("fixture-start-*")) == started)
        self.check("broken core does not allocate another terminal", self.terminals() == before)
        self.no_guard()

    def viewer(self, herdr_binary, socket_path):
        gui_bin = self.root / "viewer-bin"
        gui_bin.mkdir()
        (gui_bin / "herdr").symlink_to(herdr_binary)
        env = dict(self.env, HERDR_SOCKET_PATH=socket_path,
                   PATH=str(gui_bin) + os.pathsep + self.env["PATH"])

        def gui(*argv):
            proc = self.command([str(herdr_binary), *argv], env=env, timeout=60)
            if proc.returncode:
                raise RuntimeError("Herdr viewer driver command failed: " + proc.stderr)
            return unwrap(json.loads(proc.stdout)) if proc.stdout.strip() else {}

        def focused():
            return [(w["workspace_id"], w["active_tab_id"]) for w in
                    gui("workspace", "list")["workspaces"] if w.get("focused")]

        workspace = None
        self.evidence["viewer"] = {"scope": "owned Herdr workspace; two real attach viewers; no models"}
        before = focused()
        try:
            made = gui("workspace", "create", "--cwd", str(self.root),
                       "--label", "core-viewer-e2e", "--no-focus")
            workspace = made["workspace"]["workspace_id"]
            controller = made["root_pane"]["pane_id"]
            controller_tab = made["tab"]["tab_id"]
            tasks = []
            for mode in ("valid", "missing"):
                # Reuse fixture modes from headless runs but hold both new turns.
                for suffix in (".release", ".prompt.json", ".ended"):
                    (self.root / (mode + suffix)).unlink(missing_ok=True)
                brief = self.root / (mode + "-viewer.md")
                brief.write_text("CORE_E2E_CASE=" + mode + "\n")
                out = self.root / (mode + "-viewer.stdout")
                err = self.root / (mode + "-viewer.stderr")
                rc = self.root / (mode + "-viewer.rc")
                assignments = {k: env[k] for k in (
                    "PATH", "HC_SESSION", "XDG_CONFIG_HOME", "XDG_STATE_HOME",
                    "XDG_RUNTIME_DIR", "CORE_E2E_ROOT", "HERDR_SOCKET_PATH")}
                extra = ["--caller-pane", controller] if mode == "valid" else []
                if mode == "missing":
                    assignments["HERDR_PANE_ID"] = controller
                argv = ["env", "-u", "HERDR_ENV", "-u", "HERDR_PANE_ID",
                        "-u", "HERDR_TAB_ID", "-u", "HERDR_WORKSPACE_ID",
                        *[f"{k}={v}" for k, v in assignments.items()],
                        sys.executable, str(self.args.horch), "run", "fixture",
                        "--brief", str(brief), "--cwd", str(self.root), *extra]
                script = self.root / (mode + "-viewer.sh")
                script.write_text(shlex.join(argv) + " > " + shlex.quote(str(out))
                                  + " 2> " + shlex.quote(str(err))
                                  + '\nprintf "%s" "$?" > ' + shlex.quote(str(rc)) + "\n")
                gui("pane", "run", controller, shlex.join(["sh", str(script)]))
                self.until(mode + " viewer run returns", rc.exists, seconds=120)
                self.check(mode + " viewer run succeeds without HERDR_ENV", rc.read_text() == "0")
                task = rows(out.read_text())[0]
                self.check(mode + " viewer run is working with no warning",
                           task["state"] == "running" and not task["warning"] and task["viewer"])
                viewer = task["viewer"]
                pane = gui("pane", "get", viewer["pane_id"])["pane"]
                tab = gui("tab", "get", viewer["tab_id"])["tab"]
                self.check(mode + " viewer uses same workspace and separate hcOrch tab",
                           pane["workspace_id"] == workspace and tab["workspace_id"] == workspace
                           and viewer["tab_id"] != controller_tab and tab["label"] == "hcOrch")
                read = self.command([str(herdr_binary), "pane", "wait-output", viewer["pane_id"],
                                     "--match", "CORE_E2E_CASE=" + mode, "--timeout", "30000"], env=env)
                self.check(mode + " actual attach displays worker output", read.returncode == 0)
                tasks.append(task)
            self.check("viewers share hcOrch tab with separate panes",
                       tasks[0]["viewer"]["tab_id"] == tasks[1]["viewer"]["tab_id"]
                       and tasks[0]["viewer"]["pane_id"] != tasks[1]["viewer"]["pane_id"])
            self.check("viewer dispatch preserves user focus", focused() == before)
            self.evidence["viewer"]["tasks"] = tasks
            started = set(self.root.glob("fixture-start-*"))
            terminals = self.terminals()
            for command in ("run", "check"):
                extra = ["--brief", str(brief)] if command == "run" else []
                rejected = self.cli(command, "fixture", *extra, env=env)
                self.check(command + " incomplete GUI context rejects before launch",
                           rejected.returncode == 1
                           and rows(rejected.stdout)[0].get("error") == "caller_context_invalid")
            self.check("rejected context creates no workers", self.terminals() == terminals
                       and set(self.root.glob("fixture-start-*")) == started)
            (self.root / "valid.release").write_text("release\n")
            done = self.cli("wait", tasks[0]["task_id"], "--max-seconds", "30", env=env)
            self.check("viewer task delivers and auto-closes", done.returncode == 0
                       and rows(done.stdout)[0]["state"] == "done" and rows(done.stdout)[0]["closed"])
            closed = self.cli("close", tasks[1]["task_id"], env=env)
            self.check("second viewer cancellation closes", closed.returncode == 0)
            panes = gui("pane", "list", "--workspace", workspace)["panes"]
            self.check("viewer cleanup preserves only owned controller pane",
                       {p["pane_id"] for p in panes} == {controller})
            self.no_guard()
        finally:
            if workspace:
                gui("workspace", "close", workspace)
                self.evidence["viewer"]["workspace_closed"] = workspace not in {
                    w["workspace_id"] for w in gui("workspace", "list")["workspaces"]}
                self.check("viewer owned workspace removed", self.evidence["viewer"]["workspace_closed"])

    def cleanup(self):
        errors = []
        for proc, out, err in self.waiters:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            out.close()
            err.close()
        try:
            for terminal in self.terminals():
                address = terminal["address"]
                if terminal.get("state") == "live":
                    self.hc("kill", address)
                self.hc("rm", address)
            remaining = self.terminals()
            if remaining:
                errors.append("owned core terminals remain")
            stopped = self.hc("server", "stop")
            if stopped.returncode:
                errors.append("owned core stop failed")
        except Exception as exc:
            errors.append(str(exc))
        self.evidence["cleanup"] = {"ok": not errors, "errors": errors,
                                    "scope": "owned HC_SESSION and wait processes only"}
        if not errors:
            shutil.rmtree(self.runtime)
        else:
            self.evidence["verdict"] = "fail"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH)
    parser.add_argument("--output", type=Path, required=True, help="artifact parent outside checkout")
    parser.add_argument("--baseline", action="store_true", help="expect current headless rejection")
    parser.add_argument("--core-only", "--headless", action="store_true", default=True,
                        help="owned headless core only; this is also the default")
    parser.add_argument("--viewer", action="store_true",
                        help="also verify two live attach viewers in an owned Herdr workspace")
    args = parser.parse_args()
    args.horch = args.horch.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.output.is_relative_to(HORCH.parents[3]):
        parser.error("keep artifacts outside the checkout")
    core = shutil.which("herdr-core")
    if not core:
        parser.error("official herdr-core executable required; hc alias is not sufficient")
    herdr_binary, socket_path = shutil.which("herdr"), os.environ.get("HERDR_SOCKET_PATH")
    if args.viewer and (os.environ.get("HERDR_ENV") != "1" or not herdr_binary or not socket_path):
        parser.error("--viewer requires HERDR_ENV=1, herdr, and HERDR_SOCKET_PATH")
    args.output.mkdir(parents=True, exist_ok=True)
    run = Run(args, Path(core).resolve())
    try:
        version = run.command([str(run.core), "--version"], timeout=10)
        run.evidence["versions"] = {"core": version.stdout.strip(), "python": sys.version}
        run.check("real core version available", version.returncode == 0)
        started = run.hc("server", "start")
        run.check("owned real core starts", started.returncode == 0)
        run.check("owned core initially empty", not run.terminals())
        if args.baseline:
            run.baseline()
        else:
            for mode, expected in SCENARIOS.items():
                run.scenario(mode, expected)
            run.broken_core()
            run.settled_endpoint()
            if args.viewer:
                run.viewer(Path(herdr_binary).resolve(), socket_path)
                run.evidence["scope"] += "; real Herdr attach viewers in an owned workspace"
                run.evidence["unverified"].remove("visible hcOrch tabs and legacy horch tabs")
                run.evidence["unverified"].append("legacy horch tabs")
            run.evidence["verdict"] = "pass"
    except Exception:
        (run.root / "failure.txt").write_text(traceback.format_exc())
    finally:
        run.cleanup()
        receipt = run.root / "evidence.json"
        receipt.write_text(json.dumps(run.evidence, indent=2) + "\n")
    print(json.dumps({"verdict": run.evidence["verdict"], "evidence": str(receipt)}))
    return 0 if run.evidence["verdict"] in ("pass", "baseline-unsupported") else 1


if __name__ == "__main__":
    raise SystemExit(main())
