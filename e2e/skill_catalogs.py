#!/usr/bin/env python3
"""Read real Pi and Codex skill catalogs after a disposable package installation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time


def catalog(command, cwd, env, requests, log):
    with log.open("w") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=stderr)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b""
        try:
            for request in requests:
                process.stdin.write(json.dumps(request).encode() + b"\n")
                process.stdin.flush()
                if "id" not in request:
                    continue
                deadline = time.monotonic() + 30
                while True:
                    if b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        row = json.loads(line)
                        if row.get("id") == request["id"]:
                            if "error" in row or row.get("success") is False:
                                raise RuntimeError(f"Catalog request failed: {row}")
                            break
                        continue
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Catalog request timed out; inspect the retained log")
                    if selector.select(1):
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError("Harness exited before catalog response")
                        buffer += chunk
            return row
        finally:
            selector.close()
            process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consumer", type=Path, help="Disposable project populated by npx skills add")
    args = parser.parse_args()
    consumer = args.consumer.resolve()
    skills = consumer / ".agents/skills"
    expected = {path.parent.name for path in skills.glob("*/SKILL.md")}
    if not {"poteto-mode", "how", "unslop", "pstack-herdr", "herdr-orchestrator"} <= expected:
        parser.error("Install the complete prepared package into consumer first")
    output = Path(tempfile.mkdtemp(prefix="pstack-catalogs-"))
    pi_user = output / "pi"
    pi_user.mkdir()
    (pi_user / "skills").symlink_to(skills, target_is_directory=True)
    codex_user = output / "codex"
    codex_user.mkdir()
    receipt = {"verdict": "fail", "expected_skills": sorted(expected), "checks": {}}
    try:
        pi = catalog(
            ["pi", "--mode", "rpc", "--no-session", "--no-extensions"], output,
            dict(os.environ, PI_CODING_AGENT_DIR=str(pi_user)),
            [{"id": "catalog", "type": "get_commands"}], output / "pi.stderr",
        )
        codex = catalog(
            ["codex", "app-server", "--stdio"], consumer,
            dict(os.environ, CODEX_HOME=str(codex_user)),
            [{"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "pstack_catalog_check", "version": "1.0"}}},
             {"method": "initialized", "params": {}},
             {"id": 2, "method": "skills/list", "params": {
                 "cwds": [str(consumer)], "forceReload": True}}], output / "codex.stderr",
        )
        (output / "pi.json").write_text(json.dumps(pi, indent=2) + "\n")
        (output / "codex.json").write_text(json.dumps(codex, indent=2) + "\n")
        pi_names = {row["name"].removeprefix("skill:") for row in pi["data"]["commands"]
                    if row.get("source") == "skill" and row.get("description")
                    and Path(row["sourceInfo"]["path"]).resolve().is_relative_to(skills)}
        groups = codex["result"]["data"]
        codex_names = {row["name"] for group in groups for row in group["skills"]
                       if row["enabled"] and row.get("description")
                       and Path(row["path"]).resolve().is_relative_to(skills)}
        receipt["checks"] = {"pi_catalog": pi_names == expected,
                              "codex_catalog": codex_names == expected,
                              "codex_no_errors": not any(group["errors"] for group in groups)}
        receipt["discovered"] = {"pi": sorted(pi_names), "codex": sorted(codex_names)}
        receipt["installed_entry_sha256"] = {
            name: hashlib.sha256((skills / name / "SKILL.md").read_bytes()).hexdigest()
            for name in sorted(expected)}
        receipt["verdict"] = "pass" if all(receipt["checks"].values()) else "fail"
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        receipt["error"] = str(exc)
    (output / "evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"verdict": receipt["verdict"], "checks": receipt["checks"],
                      "evidence": str(output / "evidence.json")}))
    return 0 if receipt["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
