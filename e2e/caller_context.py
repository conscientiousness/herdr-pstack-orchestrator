#!/usr/bin/env python3
"""Check caller-context resolution through the real CLI and live Herdr reads.

Check unavailable or missing pane IDs and canonicalization of stale inherited
workspace/tab IDs for both run and check, plus a valid-context control. This
driver does not move real panes or exercise a moved pane's launch-ID alias.

Every invocation uses an empty isolated configuration directory. That second
preflight failure prevents worker creation even on the unfixed implementation.
No model calls, pane mutations, or changes to the user's configuration occur.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HORCH = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-pane", required=True, help="verified live controller pane ID")
    parser.add_argument("--output", type=Path, required=True, help="artifact parent outside the checkout")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.is_relative_to(HORCH.parents[3]):
        parser.error("keep evidence outside the checkout")
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="caller-context-", dir=output))
    checks, observations = [], []
    evidence = {"schema": "horch/caller-context-e2e/v1", "verdict": "fail",
                "scope": "live Herdr reads and CLI preflight; no worker launch",
                "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (HORCH, Path(__file__))},
                "checks": checks, "observations": observations}
    try:
        pane = json.loads(subprocess.check_output(
            ["herdr", "pane", "get", args.controller_pane], text=True, timeout=30))["result"]["pane"]
        env = dict(os.environ, HERDR_ENV="1", HERDR_WORKSPACE_ID=pane["workspace_id"],
                   HERDR_TAB_ID=pane["tab_id"], HERDR_PANE_ID=pane["pane_id"],
                   XDG_CONFIG_HOME=str(root / "empty-config"), XDG_STATE_HOME=str(root / "state"))
        cases = [
            ("stale-pane", {"HERDR_PANE_ID": "missing-controller-pane"}, "caller_context_invalid"),
            ("missing-pane", {"HERDR_PANE_ID": None}, "caller_context_invalid"),
            ("blank-pane", {"HERDR_PANE_ID": ""}, "caller_context_invalid"),
            ("whitespace-pane", {"HERDR_PANE_ID": " \t "}, "caller_context_invalid"),
            ("stale-workspace", {"HERDR_WORKSPACE_ID": "wrong-workspace"}, "config_invalid"),
            ("stale-tab", {"HERDR_TAB_ID": "wrong-tab"}, "config_invalid"),
            ("stale-workspace-and-tab", {"HERDR_WORKSPACE_ID": "wrong-workspace",
                                         "HERDR_TAB_ID": "wrong-tab"}, "config_invalid"),
            ("valid-context", {}, "config_invalid"),
        ]
        for label, overrides, expected in cases:
            for command in (["run", "probe", "--brief", str(root / "unused.md")], ["check", "probe"]):
                case_env = dict(env, **overrides)
                case_env = {key: value for key, value in case_env.items() if value is not None}
                proc = subprocess.run([sys.executable, str(HORCH), *command],
                                      env=case_env, capture_output=True, text=True, timeout=30)
                name = label + "-" + command[0]
                (root / (name + ".stdout")).write_text(proc.stdout)
                (root / (name + ".stderr")).write_text(proc.stderr)
                error = json.loads(proc.stdout).get("error")
                observations.append({"case": name, "expected_error": expected, "actual_error": error})
                checks.append({"name": name, "ok": proc.returncode == 1 and error == expected})
        checks.append({"name": "no task state allocated", "ok": not (root / "state").exists()})
        evidence["verdict"] = "pass" if all(row["ok"] for row in checks) else "fail"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        (root / "failure.txt").write_text(str(exc))
        evidence["problem_category"] = type(exc).__name__
    (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"verdict": evidence["verdict"], "evidence": str(root / "evidence.json")}))
    return 0 if evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
