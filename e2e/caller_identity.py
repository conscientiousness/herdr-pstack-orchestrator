#!/usr/bin/env python3
"""Check that horch proves which Herdr pane is its controller before dispatch.

Incident: a Codex controller's tools ran in a shared `codex app-server` daemon
that had been started from another pane. The daemon (parent PID 1) carried that
pane's HERDR_PANE_ID, the named pane was still live as a plain shell, and
`horch run` placed workers in the wrong workspace.

Ways the identity check can fail, each exercised below:
1. A stale HERDR_PANE_ID names another live pane while horch runs inside the
   controller's process tree: dispatch must stop and name the proven pane.
2. An explicit --caller-pane contradicts the pane proven by the process tree.
3. horch runs outside every pane's process tree (simulated daemon: detached
   with setsid, parent PID 1): HERDR_PANE_ID alone, stale or correct, cannot be
   trusted, so dispatch must stop.
4. An explicit --caller-pane without process proof names a pane whose foreground
   is not the controller's harness (the incident's plain-shell pane).
5. An explicit --caller-pane without conversation-specific text, or with text
   absent from the controller's visible screen, is insufficient in a daemon.
6. An explicit --caller-pane names a pane whose reported agent session differs
   from the controller's own session ID.
7. Over-rejection: a correct in-tree controller, a confirmed --caller-pane from
   a detached process, and a pane moved to another workspace (launch-time ID
   kept as a Herdr alias) must still reach the configuration check.
8. A controller session carried by a process still beneath an old pane shell
   cannot use that ancestry to bypass conversation evidence. A confirmed real
   conversation must be accepted even when its tools run beneath that old shell.

Accepted preflight stops at an empty isolated configuration (config_invalid),
so no worker or model starts. The driver creates one scratch tab and one
scratch workspace in Herdr and closes both at the end.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import uuid


REPO_HORCH = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SESSION_ENV = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID"}


def herdr(*args):
    return json.loads(subprocess.check_output(["herdr", *args], text=True, timeout=30))["result"]


def last_json(text):
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def wait_files(rc_file, out_file, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if rc_file.is_file() and rc_file.read_text().strip():
            return last_json(out_file.read_text(errors="replace"))
        time.sleep(0.5)
    return {"error": "driver_timeout"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--controller-pane", required=True, help="verified live controller pane ID")
    parser.add_argument("--controller-text", required=True,
                        help="unique text of at least 16 characters currently visible in the controller conversation")
    parser.add_argument("--output", type=Path, required=True, help="artifact parent outside the checkout")
    parser.add_argument("--horch", type=Path, default=REPO_HORCH, help="horch.py under test")
    args = parser.parse_args()
    horch = args.horch.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.is_relative_to(REPO_HORCH.parents[3]):
        parser.error("keep evidence outside the checkout")
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="caller-identity-", dir=output))
    harness = next((h for h, var in SESSION_ENV.items() if os.environ.get(var)), None)
    checks, observations, unverified = [], [], []
    evidence = {"schema": "horch/caller-identity-e2e/v1", "verdict": "fail",
                "scope": "live Herdr panes, real process trees, run/check preflight; no worker launch",
                "controller_harness": harness,
                "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (horch, Path(__file__))},
                "checks": checks, "observations": observations, "unverified": unverified}
    scratch_tab = moved_workspace = None
    try:
        controller = herdr("pane", "get", args.controller_pane)["pane"]
        made = herdr("tab", "create", "--workspace", controller["workspace_id"],
                     "--label", "horch-identity-e2e", "--cwd", str(Path.cwd()), "--no-focus")
        scratch_tab = made["tab"]["tab_id"]
        shell_pane = made["root_pane"]["pane_id"]
        mover = herdr("pane", "split", shell_pane, "--direction", "right", "--no-focus")["pane"]["pane_id"]
        probe_pane = herdr("pane", "split", shell_pane, "--direction", "down", "--no-focus")["pane"]["pane_id"]
        time.sleep(1.5)  # let both shells reach their prompts
        (root / "empty-config").mkdir()
        brief = root / "unused.md"
        base_env = dict(os.environ, HERDR_ENV="1", XDG_CONFIG_HOME=str(root / "empty-config"),
                        XDG_STATE_HOME=str(root / "state"),
                        HERDR_WORKSPACE_ID=controller["workspace_id"], HERDR_TAB_ID=controller["tab_id"],
                        HERDR_PANE_ID=controller["pane_id"])

        def record(case, command, expected, result, must_name=None):
            actual = (result or {}).get("error")
            ok = actual == expected
            if ok and must_name:
                ok = must_name in (result.get("message") or "")
            checks.append({"name": f"{case}-{command}", "ok": ok})
            observations.append({"case": case, "command": command, "expected_error": expected,
                                 "actual_error": actual, "names_required_pane": bool(must_name) and ok})

        def commands(extra):
            yield "run", ["run", "probe", "--brief", str(brief), *extra]
            yield "check", ["check", "probe", *extra]

        def in_tree(case, overrides, extra, expected, must_name=None):
            env = dict(base_env, HERDR_PANE_ID=probe_pane)
            env.update(overrides)
            for name, argv in commands(extra):
                stem = root / f"{case}-{name}"
                out, rc = stem.with_suffix(".out"), stem.with_suffix(".rc")
                runner = stem.with_suffix(".sh")
                assignments = [f"{key}={env[key]}" for key in (
                    "HERDR_ENV", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID",
                    "XDG_CONFIG_HOME", "XDG_STATE_HOME")]
                assignments.extend(f"{key}={env[key]}" for key in SESSION_ENV.values() if key in overrides)
                clear_sessions = [item for key in SESSION_ENV.values() for item in ("-u", key)]
                runner.write_text(shlex.join(["env", *clear_sessions, *assignments,
                                             sys.executable, str(horch), *argv])
                                  + " > " + shlex.quote(str(out)) + " 2>&1\n"
                                  + "echo $? > " + shlex.quote(str(rc)) + "\n")
                subprocess.run(["herdr", "pane", "run", probe_pane, shlex.join(["sh", str(runner)])],
                               capture_output=True, timeout=30, check=True)
                record(case, name, expected, wait_files(rc, out), must_name)

        def detached(case, overrides, extra, expected):
            env = dict(base_env, **overrides)
            for name, argv in commands(extra):
                stem = root / f"{case}-{name}"
                out, rc = stem.with_suffix(".out"), stem.with_suffix(".rc")
                script = (f"{shlex.join([sys.executable, str(horch), *argv])} > {shlex.quote(str(out))} 2>&1; "
                          f"echo $? > {shlex.quote(str(rc))}")
                subprocess.run(["setsid", "-f", "sh", "-c", script], env=env, check=True)
                record(case, name, expected, wait_files(rc, out))

        in_tree("valid-in-tree", {}, [], "config_invalid")
        in_tree("stale-live-shell", {"HERDR_PANE_ID": shell_pane}, [], "caller_context_invalid",
                must_name=probe_pane)
        in_tree("claim-contradicts-tree", {}, ["--caller-pane", shell_pane], "caller_context_invalid",
                must_name=probe_pane)
        detached("detached-env-stale", {"HERDR_PANE_ID": shell_pane}, [], "caller_context_invalid")
        detached("detached-env-correct", {}, [], "caller_context_invalid")
        detached("detached-claim-shell", {}, ["--caller-pane", shell_pane], "caller_context_invalid")
        detached("detached-claim-without-text", {}, ["--caller-pane", controller["pane_id"]],
                 "caller_context_invalid")
        detached("detached-claim-short-text", {},
                 ["--caller-pane", controller["pane_id"], "--caller-text", "too short"],
                 "caller_context_invalid")
        detached("detached-claim-wrong-text", {},
                 ["--caller-pane", controller["pane_id"], "--caller-text", "absent-" + uuid.uuid4().hex],
                 "caller_context_invalid")
        confirmed = ["--caller-pane", controller["pane_id"], "--caller-text", args.controller_text]
        detached("detached-claim-controller", {}, confirmed, "config_invalid")
        session_var = SESSION_ENV[harness] if harness else SESSION_ENV["codex"]
        session_override = {session_var: os.environ.get(session_var) or "synthetic-e2e-controller-session"}
        in_tree("controller-session-under-old-shell-without-proof", session_override, [],
                "caller_context_invalid")
        if harness:
            in_tree("controller-session-under-old-shell-confirmed", session_override, confirmed, "config_invalid")
        else:
            unverified.append("controller-session-under-old-shell-confirmed: no actual exported controller session")
        session = controller.get("agent_session") or {}
        if harness and session.get("agent") == harness and session.get("value"):
            detached("detached-claim-other-session", {SESSION_ENV[harness]: str(uuid.uuid4())},
                     confirmed, "caller_context_invalid")
        else:
            unverified.append("detached-claim-other-session: live controller has no matching agent_session")

        moved = herdr("pane", "move", mover, "--new-workspace", "--no-focus")["move_result"]["pane"]
        moved_workspace = moved["workspace_id"]
        observations.append({"case": "moved-alias", "pane_id_changed": moved["pane_id"] != mover})
        for name, argv in commands([]):
            stem = root / f"moved-alias-{name}"
            out, rc = stem.with_suffix(".out"), stem.with_suffix(".rc")
            runner = stem.with_suffix(".sh")
            # The pane's shell keeps its launch-time HERDR_PANE_ID (the pre-move alias).
            runner.write_text(f"XDG_CONFIG_HOME={shlex.quote(str(root / 'empty-config'))} "
                              f"XDG_STATE_HOME={shlex.quote(str(root / 'state'))} "
                              f"{shlex.join([sys.executable, str(horch), *argv])} > {shlex.quote(str(out))} 2>&1\n"
                              f"echo $? > {shlex.quote(str(rc))}\n")
            subprocess.run(["herdr", "pane", "run", moved["pane_id"], f"sh {shlex.quote(str(runner))}"],
                           capture_output=True, timeout=30, check=True)
            record("moved-alias", name, "config_invalid", wait_files(rc, out))
        evidence["verdict"] = "pass" if checks and all(c["ok"] for c in checks) else "fail"
    except Exception as exc:
        evidence["driver_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup = []
        if moved_workspace:
            cleanup.append(subprocess.run(["herdr", "workspace", "close", moved_workspace],
                                          capture_output=True, timeout=30).returncode == 0)
        if scratch_tab:
            cleanup.append(subprocess.run(["herdr", "tab", "close", scratch_tab],
                                          capture_output=True, timeout=30).returncode == 0)
        evidence["cleanup_ok"] = all(cleanup)
        if not evidence["cleanup_ok"]:
            evidence["verdict"] = "fail"
    artifact = root / "caller-identity.json"
    artifact.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"verdict": evidence["verdict"], "artifact": str(artifact),
                      "failed": [c["name"] for c in checks if not c["ok"]],
                      "driver_error": evidence.get("driver_error")}))
    return 0 if evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
