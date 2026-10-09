#!/usr/bin/env python3
"""Run a real implementation/review/fix/review loop through horch.

Requires Herdr, a configured writer, and two configured reviewers. Uses real
model calls, a disposable git worktree, and the caller's existing worker limit.
Evidence contains assertions and CLI output, never worker transcripts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


HORCH = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
CONTRACT = """# Invoice CLI contract

The CLI reads JSON on stdin. `line` accepts quantity, unit_price_cents, and
discount_bp (integer basis points). Gross is quantity times unit price;
discount is floor(gross * discount_bp / 10000); total is gross minus discount.
`invoice` accepts a nonempty list of lines and shipping_cents. Subtotal sums
EVERY line, including the final or only line. Total adds shipping once.
All inputs are nonnegative integers; discount_bp is at most 10000.
"""
INVOICE = '''import json
import sys


def line_total(quantity, unit_price_cents, discount_bp):
    gross = quantity * unit_price_cents
    return gross - gross * (discount_bp // 100) // 100


def invoice_total(lines, shipping_cents):
    subtotal = sum(line_total(**line) for line in lines[:-1])
    return {"subtotal_cents": subtotal, "total_cents": subtotal + shipping_cents}


data = json.load(sys.stdin)
if sys.argv[1] == "line":
    print(json.dumps({"total_cents": line_total(**data)}))
else:
    print(json.dumps(invoice_total(**data)))
'''


def command(argv, *, cwd=None, input=None, timeout=180):
    return subprocess.run(
        [str(arg) for arg in argv], cwd=cwd, input=input, text=True,
        capture_output=True, timeout=timeout,
    )


def checked(argv, **kwargs):
    proc = command(argv, **kwargs)
    if proc.returncode:
        # Keep potentially sensitive process output out of the evidence file.
        raise RuntimeError(f"{Path(str(argv[0])).name} failed (exit {proc.returncode})")
    return proc.stdout


def json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Run:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.directory = Path(tempfile.mkdtemp(prefix="horch-e2e-", dir=args.output)).resolve()
        self.worktree = self.directory / "worktree"
        self.fixture = self.worktree / ".horch-fixture"
        self.tasks = []
        self.assertions = []
        self.observations = {}
        self.revisions = {}
        self.source_hashes = {
            "horch_sha256": hashlib.sha256(HORCH.read_bytes()).hexdigest(),
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }

    def check(self, name, ok):
        self.assertions.append({"name": name, "ok": bool(ok)})
        print(f"{'PASS' if ok else 'FAIL'}: {name}", flush=True)
        if not ok:
            raise RuntimeError(name)

    def git(self, *args):
        return checked(["git", *args], cwd=self.worktree).strip()

    def commit(self, message):
        self.git("add", "--", ".horch-fixture")
        self.git("-c", "user.name=horch E2E", "-c", "user.email=e2e@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                 "commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def setup(self):
        repo = checked(["git", "rev-parse", "--show-toplevel"], cwd=self.args.repo).strip()
        checked(["git", "worktree", "add", "--detach", str(self.worktree), "HEAD"], cwd=repo)
        if self.fixture.exists():
            raise RuntimeError("repository already contains .horch-fixture")
        self.fixture.mkdir()
        (self.fixture / "contract.md").write_text(CONTRACT, encoding="utf-8")
        (self.fixture / "invoice.py").write_text(INVOICE, encoding="utf-8")
        self.revisions["base"] = self.commit("Add disposable invoice CLI fixture")

    def cli(self, mode, data):
        return json.loads(checked(
            [sys.executable, str(self.fixture / "invoice.py"), mode],
            cwd=self.worktree, input=json.dumps(data),
        ))

    def start(self, worker, brief):
        path = self.directory / f"brief-{len(self.tasks)}.md"
        path.write_text(brief, encoding="utf-8")
        proc = command([sys.executable, HORCH, "run", worker, "--cwd", self.worktree, "--brief", path])
        row = json.loads(proc.stdout)
        if "task_id" in row:
            self.tasks.append(row)
        if proc.returncode or row.get("state") != "running":
            raise RuntimeError(f"worker {worker} could not start: {row.get('state') or row.get('error')}")
        print(f"Started {worker}: {row['task_id']}", flush=True)
        return row

    def wait(self, tasks):
        deadline = time.monotonic() + self.args.max_seconds
        pending = {t["task_id"]: t for t in tasks}
        while pending and time.monotonic() < deadline:
            output = checked([sys.executable, HORCH, "wait", *pending, "--max-seconds", "30"])
            for line in output.splitlines():
                row = json.loads(line)
                if row["state"] == "done":
                    result = json_file(row["result_path"])
                    self.check(f"{row['task_id']} completed", result.get("status") == "completed")
                    pending.pop(row["task_id"], None)
                elif row["state"] not in ("running", "long_running"):
                    raise RuntimeError(f"{row['task_id']}: {row['state']}; inspect its pane")
        if pending:
            raise RuntimeError("wait limit reached; incomplete test workers will be cleaned up")

    def writer(self, instruction):
        task = self.start(self.args.writer, f"""Work on the disposable fixture {self.fixture}.
Read its contract.md and invoice.py. {instruction}
Ownership: only {self.fixture / 'invoice.py'}. Do not edit any other file,
repository configuration, or commit. The driver owns commits. Verify the real
CLI with multiple inputs. Do not ask questions or use subagents. Output a short
report.md in your task directory. This is a small fixture: use at most 20 CLI
invocations, no exhaustive sweeps, and finish within five minutes. Stop after
writing your result.
""")
        self.wait([task])
        changed = self.git("diff", "--name-only").splitlines()
        untracked = self.git("ls-files", "--others", "--exclude-standard").splitlines()
        self.check("writer respected file scope", changed == [".horch-fixture/invoice.py"] and not untracked)
        return task

    def review(self, revision, expected):
        before = self.git("status", "--porcelain")
        tasks = []
        # Sequential launch calls still run both reviewers concurrently. The
        # configured slot limit is enforced by horch, never bypassed here.
        for worker in self.args.reviewer:
            tasks.append(self.start(worker, f"""Independently review commit {revision} in {self.worktree}.
Scope: {self.fixture / 'invoice.py'} against {self.fixture / 'contract.md'}.
Read the complete contract, inspect both CLI modes, and verify arithmetic and
edge cases by running the CLI. This is read-only: do not modify any repository
file or external state. Do not commit or delegate. Write review.md in your task
directory. Its first line must be VERDICT: PASS when the contract is satisfied,
or VERDICT: FAIL with concrete inputs, expected/actual output, and a precise
finding. Use the same pinned commit above; do not follow branch movement.
Use at most 20 CLI invocations covering representative boundaries. Do not run
exhaustive or combinatorial subprocess sweeps. Finish within five minutes.
"""))
        self.wait(tasks)
        self.check("reviewers left checkout unchanged", self.git("status", "--porcelain") == before)
        verdicts = []
        for task in tasks:
            report = Path(task["task_dir"]) / "review.md"
            lines = report.read_text(encoding="utf-8").splitlines()
            verdicts.append(lines[0].strip() if lines else "")
        self.check(f"both reviewers returned {expected}", verdicts == [f"VERDICT: {expected}"] * 2)
        return tasks

    def scenario(self):
        self.setup()
        line = {"quantity": 7, "unit_price_cents": 137, "discount_bp": 250}
        invoice = {"lines": [line, {"quantity": 2, "unit_price_cents": 1000, "discount_bp": 500}], "shipping_cents": 55}
        self.check("fixture exposes a real line calculation defect", self.cli("line", line) != {"total_cents": 936})
        self.writer("Fix ONLY line_total's basis-point discount calculation. Leave invoice_total unchanged.")
        self.revisions["initial"] = self.commit("Fix line discount calculation")
        self.observations["first_line"] = self.cli("line", line)
        self.check("first implementation fixes the line CLI", self.observations["first_line"] == {"total_cents": 936})
        self.observations["first_invoice"] = self.cli("invoice", invoice)
        self.check("full invoice still exposes a separate defect", self.observations["first_invoice"] != {"subtotal_cents": 2836, "total_cents": 2891})
        reviews = self.review(self.revisions["initial"], "FAIL")
        reports = "\n".join(str(Path(t["task_dir"]) / "review.md") for t in reviews)
        self.writer(f"Read these review reports:\n{reports}\nFix the accepted correctness findings so both CLI modes satisfy the full contract.")
        self.revisions["final"] = self.commit("Fix whole invoice calculation")
        self.observations["final_invoice"] = self.cli("invoice", invoice)
        self.check("final implementation fixes the full invoice", self.observations["final_invoice"] == {"subtotal_cents": 2836, "total_cents": 2891})
        cases = [
            ({"quantity": 1, "unit_price_cents": 199, "discount_bp": 1}, 199),
            ({"quantity": 3, "unit_price_cents": 333, "discount_bp": 3333}, 667),
            ({"quantity": 5, "unit_price_cents": 101, "discount_bp": 10000}, 0),
            ({"quantity": 0, "unit_price_cents": 999, "discount_bp": 250}, 0),
        ]
        for index, (data, expected) in enumerate(cases):
            self.check(f"line edge case {index + 1}", self.cli("line", data) == {"total_cents": expected})
            self.check(f"single-line invoice edge case {index + 1}", self.cli("invoice", {"lines": [data], "shipping_cents": 17}) == {"subtotal_cents": expected, "total_cents": expected + 17})
        self.review(self.revisions["final"], "PASS")
        self.check("six fresh tasks were used", len({t["task_id"] for t in self.tasks}) == 6)

    def finish(self, problem):
        cleanup_ok = True
        for task in self.tasks:
            state_path = Path(task["task_dir"]) / "state.json"
            try:
                state = json_file(state_path)
                if not state.get("closed"):
                    # Inspect each problem pane before cleanup. Do not copy its
                    # screen (which may contain private data) into public evidence.
                    command(["herdr", "pane", "read", task["pane_id"], "--source", "recent", "--lines", "40"])
                    checked([sys.executable, HORCH, "close", task["task_id"]])
                cleanup_ok = cleanup_ok and json_file(state_path).get("closed") is True
            except Exception:
                cleanup_ok = False
        self.assertions.append({"name": "all test worker panes closed", "ok": cleanup_ok})
        unchanged = (self.source_hashes["horch_sha256"] == hashlib.sha256(HORCH.read_bytes()).hexdigest()
                     and self.source_hashes["driver_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.assertions.append({"name": "tested source stayed unchanged during the run", "ok": unchanged})
        passed = not problem and cleanup_ok and all(a["ok"] for a in self.assertions)
        evidence = {
            "schema": "horch/public-review-e2e/v1", "verdict": "pass" if passed else "fail",
            "seconds": round(time.monotonic() - self.started),
            **self.source_hashes,
            "workers": {"writer": self.args.writer, "reviewers": self.args.reviewer},
            "models": self.args.models,
            "tasks": [{"task_id": t["task_id"], "worker": t["worker"]} for t in self.tasks],
            "revisions": self.revisions, "assertions": self.assertions,
            "observations": self.observations, "problem": problem,
        }
        path = self.directory / "evidence.json"
        path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {path}\nVerdict: {evidence['verdict']}", flush=True)
        print(f"Retained worktree: {self.worktree}", flush=True)
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", required=True, help="configured worker to implement and fix")
    parser.add_argument("--reviewer", action="append", required=True, help="configured reviewer; supply exactly twice")
    parser.add_argument("--repo", default=".", help="trusted git repository used to create a detached worktree")
    parser.add_argument("--output", required=True, type=Path, help="local artifact parent directory (outside the repository)")
    parser.add_argument("--max-seconds", type=int, default=1200, help="wait cap for each stage")
    args = parser.parse_args()
    if os.environ.get("HERDR_ENV") != "1" or not os.environ.get("HERDR_WORKSPACE_ID"):
        parser.error("run inside a Herdr pane")
    if len(args.reviewer) != 2 or args.max_seconds < 1:
        parser.error("supply exactly two reviewers and a positive wait cap")
    # Validate configuration before creating a worktree or launching a worker.
    sys.path.insert(0, str(HORCH.parent))
    import horch
    config = horch.load_config()
    if any(w not in config["workers"] for w in [args.writer, *args.reviewer]):
        parser.error("every selected worker must exist in workers.toml")
    if config["max_active_workers"] - horch.active_task_count() < 2:
        parser.error("the review panel needs two free worker slots")
    if len({(config["workers"][w]["harness"], config["workers"][w]["provider"], config["workers"][w]["model"]) for w in args.reviewer}) != 2:
        parser.error("choose reviewers with distinct model definitions")
    args.models = {w: {key: config["workers"][w][key] for key in ("harness", "provider", "model", "effort")}
                   for w in dict.fromkeys([args.writer, *args.reviewer])}
    repo = Path(checked(["git", "rev-parse", "--show-toplevel"], cwd=args.repo).strip()).resolve()
    output = args.output.expanduser().resolve()
    if output == repo or repo in output.parents:
        parser.error("--output must be outside the repository so artifacts cannot be committed accidentally")
    output.mkdir(parents=True, exist_ok=True)
    args.output = output
    run = Run(args)
    print(f"Run directory: {run.directory}", flush=True)
    problem = None
    try:
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        problem = f"{type(exc).__name__}: {exc}"
        print(f"Stopped: {problem}", flush=True)
    return run.finish(problem)


if __name__ == "__main__":
    sys.exit(main())
