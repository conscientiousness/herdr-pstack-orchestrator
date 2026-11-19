"""Independent artifact checks for live, original pstack playbook scenarios."""
from __future__ import annotations

import ast
import cProfile
import hashlib
import importlib.util
import json
from pathlib import Path
import pstats
import re
import sqlite3
import subprocess
import sys


CASES = {
    "investigation": {
        "playbook": "investigation",
        "workflow_complete": True,
        "claims": ["read-only multi-module Investigation core workflow",
                   "configured parallel how exploration and synthesis"],
        "required_stages": ["source and supplied captures unchanged",
                            "investigation identifies duplicate_scope",
                            "investigation identifies commit_operation",
                            "investigation identifies rounding_scope",
                            "investigation identifies failure_effect",
                            "investigation identifies export_order",
                            "investigation source citations resolve across all modules",
                            "how output explains flow and gotchas",
                            "investigation checklist copies all four steps",
                            "investigation reports the read-only throughput checkpoint",
                            "investigation reply follows concrete unslop rules",
                            "investigation checklist precedes how delegation",
                            "investigation how loaded before delegation",
                            "investigation configured parallel explorer routing",
                            "investigation delivered explorer reports precede synthesis",
                            "investigation synthesis includes both explorer reports",
                            "investigation findings and reply follow synthesis",
                            "investigation unslop follows synthesis before reply",
                            "investigation reply preserves the delivered explanation"],
    },
    "prototype": {
        "playbook": "prototype",
        "workflow_complete": True,
        "claims": ["fixed-direction Prototype core workflow", "observable alternative behavior",
                   "isolated throwaway decision"],
        "required_stages": ["source and supplied captures unchanged",
                            "per-line variant observed through shared CLI",
                            "invoice variant observed through shared CLI",
                            "per-line prototype implements the billing contract",
                            "invoice prototype is an independent rounding alternative",
                            "workload separates the alternatives",
                            "recommendation follows observed contract behavior",
                            "alternatives have a shared labeled runner",
                            "prototype handoff identifies tradeoffs and throwaway scope",
                            "prototype checklist copies all six steps",
                            "prototype reference skip follows supplied direction",
                            "prototype outputs are independent of the decision",
                            "prototype decision carries concrete tradeoff facts",
                            "prototype checklist precedes delegation",
                            "prototype scripts inspected before observations",
                            "variant observations share a discriminating input",
                            "prototype decision and reply follow observations",
                            "prototype bounded implementation routing"],
    },
    "trace-forensics": {
        "playbook": "trace-forensics",
        "workflow_complete": True,
        "claims": ["paired-capture Trace forensics core workflow",
                   "queryable preserved profile and call tree", "source attribution"],
        "required_stages": ["source and supplied captures unchanged",
                            "capture transformed into queryable SQLite",
                            "capture queried through SQLite",
                            "capture call tree queried through SQLite",
                            "paired captures queried through SQLite",
                            "native required invocation order",
                            "SQLite rows exactly preserve both captured profiles",
                            "SQLite edges exactly preserve captured call trees",
                            "diagnosis maps dominant own-time frame to exact source",
                            "profile format identified",
                            "mechanism distinguishes repeated linear lookup",
                            "paired capture confirms lookup elimination with equal results",
                            "trace checklist copies all six steps",
                            "trace reply cites source and both capture artifacts",
                            "trace reports the read-only throughput checkpoint",
                            "trace checklist precedes conversion",
                            "trace conversion precedes raw inspection and queries",
                            "trace ranked query supports source attribution",
                            "trace captured call tree supports hot path",
                            "trace paired query confirms lookup elimination",
                            "trace source inspected after conversion before diagnosis",
                            "trace diagnosis and reply follow supported observations"],
    },
}


LEDGER_FILES = {
    "money.py": '''def line_total(quantity, unit_price_cents, discount_bp):
    numerator = quantity * unit_price_cents * (10000 - discount_bp)
    return (numerator + 5000) // 10000
''',
    "storage.py": '''import json
import os
from pathlib import Path
from money import line_total


def apply_batch(store, batches):
    path = Path(store)
    current = json.loads(path.read_text()) if path.exists() else []
    seen = {row["id"] for row in current}
    staged = list(current)
    for batch in batches:
        for row in batch:
            if row["id"] in seen:
                raise ValueError("duplicate transaction: " + row["id"])
            if any(type(row[k]) is not int or row[k] < 0
                   for k in ("quantity", "unit_price_cents", "discount_bp")):
                raise ValueError("invalid money field")
            if row["discount_bp"] > 10000:
                raise ValueError("invalid discount")
            seen.add(row["id"])
            staged.append(dict(row, total_cents=line_total(
                row["quantity"], row["unit_price_cents"], row["discount_bp"])))
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(staged, sort_keys=True))
    os.replace(temporary, path)
    return {"count": len(staged), "total_cents": sum(r["total_cents"] for r in staged)}
''',
    "cli.py": '''import json
from pathlib import Path
import sys
from storage import apply_batch


def main():
    command, store, *files = sys.argv[1:]
    if command == "import":
        try:
            result = apply_batch(store, [json.loads(Path(p).read_text()) for p in files])
        except ValueError as error:
            print(json.dumps({"error": str(error)}))
            return 2
    elif command == "export":
        rows = json.loads(Path(store).read_text())
        result = sorted(rows, key=lambda row: row["id"])
    else:
        raise ValueError("unknown command")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
}


PROFILE_SOURCE = '''def lookup_reference(references, account):
    for key, value in references:
        if key == account:
            return value
    raise KeyError(account)


def reconcile_linear(references, payments):
    return sum(lookup_reference(references, account) * amount for account, amount in payments)


def reconcile_indexed(references, payments):
    index = dict(references)
    return sum(index[account] * amount for account, amount in payments)
'''


PROFILE_TOOL = '''import argparse
import json
import pstats
import sqlite3


parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("import", "query"))
parser.add_argument("--db", required=True)
parser.add_argument("--before")
parser.add_argument("--after")
parser.add_argument("--sql")
args = parser.parse_args()
if args.action == "import":
    counts = {}
    with sqlite3.connect(args.db) as database:
        database.execute("CREATE TABLE profile_samples (capture TEXT, file TEXT, line INTEGER, function TEXT, calls INTEGER, self_seconds REAL, cumulative_seconds REAL)")
        database.execute("CREATE TABLE profile_edges (capture TEXT, caller_file TEXT, caller_line INTEGER, caller_function TEXT, callee_file TEXT, callee_line INTEGER, callee_function TEXT, calls INTEGER, self_seconds REAL, cumulative_seconds REAL)")
        for label, path in (("before", args.before), ("after", args.after)):
            stats = pstats.Stats(path)
            rows = [(label, file, line, function, calls, own, cumulative)
                    for (file, line, function), (_, calls, own, cumulative, _) in stats.stats.items()]
            edges = []
            for callee, (_, _, _, _, callers) in stats.stats.items():
                for caller, values in callers.items():
                    if not isinstance(values, tuple) or len(values) != 4:
                        raise ValueError("Unsupported captured caller statistics")
                    calls, _, own, cumulative = values
                    edges.append((label, *caller, *callee, calls, own, cumulative))
            database.executemany("INSERT INTO profile_samples VALUES (?,?,?,?,?,?,?)", rows)
            database.executemany("INSERT INTO profile_edges VALUES (?,?,?,?,?,?,?,?,?,?)", edges)
            counts[label] = len(rows)
    print(json.dumps({"capture_rows": counts}, sort_keys=True))
else:
    if not args.sql or not args.sql.lstrip().lower().startswith("select "):
        raise ValueError("Only a SELECT query is accepted")
    with sqlite3.connect("file:" + args.db + "?mode=ro", uri=True) as database:
        cursor = database.execute(args.sql)
        print(json.dumps({"columns": [item[0] for item in cursor.description],
                          "rows": cursor.fetchmany(100)}))
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare(name, worktree, artifacts, bundle):
    fixture = worktree / ".playbook-fixture"
    fixture.mkdir()
    artifacts.mkdir(parents=True, exist_ok=True)
    required = ["skills/poteto-mode/SKILL.md", "skills/pstack-herdr/SKILL.md",
                "skills/pstack-herdr/references/herdr-tools.md",
                "skills/agent-workers/SKILL.md",
                "skills/unslop/SKILL.md",
                f"skills/poteto-mode/playbooks/{CASES[name]['playbook']}.md"]
    context = {"fixture": str(fixture)}
    roles = []
    commands = []
    invocations = []
    order = []
    workflow = {}
    if name == "investigation":
        for filename, content in LEDGER_FILES.items():
            (fixture / filename).write_text(content)
        required += ["skills/how/SKILL.md", "skills/how/references/explorer-prompt.md",
                     "skills/how/references/explainer-prompt.md"]
        roles = ["how explorer", "how explainer"]
        steps = re.findall(r"^\d+\. (.+)$", (bundle / "skills/poteto-mode/playbooks/investigation.md").read_text(), re.M)
        if len(steps) != 4:
            raise ValueError("investigation_stage_inventory_changed")
        context["investigation_steps"] = steps
        workflow = {"type": "investigation", "steps": steps,
                    "checklist": str(artifacts / "checklist.md"),
                    "findings": str(artifacts / "findings.json"),
                    "reply": str(artifacts / "reply.md"),
                    "explorer_role": "how explorer", "explainer_role": "how explainer",
                    "angles": ["transaction_boundaries", "command_money_export"],
                    "throughput": "throughput checkpoint: n/a, read-only investigation",
                    "source_paths": [str(fixture / filename) for filename in LEDGER_FILES]}
        prompt = f'''Explain the complete import transaction path in {fixture}, across
the command boundary, money rules and storage. We need to understand duplicate
IDs across old state and multiple input files, a validation failure late in a
batch, the exact rounding boundary, and why deterministic export is possible.
This is an architecture investigation with a cited explanation, not a request
to change code. If executing examples, put all scratch inputs/state under
{artifacts / 'examples'}, never inside the source fixture.
The architectural slices are transaction_boundaries, covering staging, duplicate
state and commit/rollback, and command_money_export, covering CLI errors, money
rounding and deterministic export. Keep these two exploration assignments
distinct. Put `Angle: transaction_boundaries` or `Angle: command_money_export`
in the respective submitted brief. Give the synthesizing explainer both full
delivered explorer reports, including their angle labels, rather than a summary
or a path that the explainer cannot see. Keep each assignment read-only and
bounded, with no nested delegation. Write the original four-step checklist
to {artifacts / 'checklist.md'} before assignments.
Alongside your final explanation, write {artifacts / 'findings.json'} with this
machine-readable summary (discover the values from the source):
{{"duplicate_scope": {{"persisted": true or false, "within_batch": true or false,
                      "across_files": true or false}},
 "commit_operation": {{"module": "...", "function": "...", "calls_per_success": integer}},
 "rounding_scope": {{"scope": "line" or "invoice", "mode": "half_up" or "half_even" or "floor"}},
 "failure_effect": {{"store_unchanged": true or false, "pending_file_created": true or false}},
 "export_order": {{"key": "...", "direction": "ascending" or "descending"}}, "evidence": [
   {{"file": "<fixture-relative file>", "line": 1, "symbol": "<symbol>"}}]}}
Use machine-readable values for the five facts. Include at least one accurate source
citation for each of cli.py, storage.py and money.py. Use all five How sections,
with Markdown headings: Overview, Key Concepts, How It Works, Where Things Live,
and Gotchas. Include the original read-only throughput checkpoint as one line.
Ask the explainer to apply unslop before delivering its complete report.md.
Present that delivered explanation verbatim, adding only the original exact
one-line throughput checkpoint. Keep findings.json separate. This evaluation
uses an unchanged explanation as a deterministic, narrower witness for How's
preservation rule. If substantive corrections are needed, leave the stage
unresolved rather than rewriting the explanation yourself.
After reading the delivered synthesis, reread {bundle / 'skills/unslop/SKILL.md'}
in full as the native witness for that final editing step, then write the reply.
Do not change source or open a PR for this read-only task.'''
    elif name == "prototype":
        required += ["skills/principle-exhaust-the-design-space/SKILL.md"]
        roles = ["feature, refactoring"]
        steps = re.findall(r"^\d+\. (.+)$", (bundle / "skills/poteto-mode/playbooks/prototype.md").read_text(), re.M)
        if len(steps) != 6:
            raise ValueError("prototype_stage_inventory_changed")
        context["prototype_steps"] = steps
        context["reference_direction_fixed"] = True
        workflow = {"type": "prototype", "checklist": str(artifacts / "checklist.md"),
                    "decision": str(artifacts / "decision.json"), "reply": str(artifacts / "reply.md"),
                    "steps": steps, "reference_direction_fixed": True,
                    "required_artifact_reads": [str(artifacts / "variants" / filename)
                                                for filename in ("per_line.py", "per_invoice.py", "compare.py")]}
        (fixture / "contract.md").write_text('''# Discount rounding decision

An invoice is a list of lines with nonnegative integer quantity and price in
cents, and a discount in integer basis points, from 0 through 10000.
The exact JSON input is {"lines": [{"quantity": 1, "unit_price_cents": 101,
"discount_bp": 5000}]}. Preserve these field names in both alternatives and
the shared runner. An empty lines array has a total of zero.
Each separately charged line rounds half-up to a whole cent. The invoice is the
sum of the separately charged lines. Quantity zero and a full discount cost zero.
We are choosing a rounding implementation before building the production CLI.
''')
        prompt = f'''Before implementing our invoice CLI, make a throwaway behavioral
sketch to choose between rounding each line and rounding only the invoice sum.
Use the billing contract in {fixture / 'contract.md'}. Compare both approaches
with one runner/switcher that labels the alternatives. Exercise multiple lines
with fractional-cent discounts, zero quantity, full discount and an ordinary
invoice. Observe actual outputs and recommend an approach with tradeoffs.
Keep all throwaway code under {artifacts / 'variants'}; do not edit the source
fixture or build a production implementation. Each alternative must be directly
rerunnable as a Python script reading {{"lines": [...]}} JSON from stdin and
printing {{"total_cents": integer}} JSON. Name them per_line.py and per_invoice.py.
The shared runner must be variants/compare.py, read the same JSON input, select
the variant using --variant per_line or --variant per_invoice, and print
{{"variant": "<selected label>", "total_cents": integer}} JSON.
Observe both choices yourself, using one separate shell tool call per choice,
with the exact command form python3 <absolute compare.py> --variant <choice>
followed by a quoted JSON heredoc as stdin. Use at least one multi-line invoice
with fractional-cent discounts. Do not use a wrapper or pipeline for these two
observations; they must show the runner's labeled JSON output directly.
Keep the original playbook checklist at {artifacts / 'checklist.md'}, before
any implementation assignment. State the reason for any permitted reference skip.
Write {artifacts / 'decision.json'} with {{"recommendation": "per_line" or
"per_invoice", "reason": "...", "artifact_scope": "throwaway",
"handoff": "Feature", "tradeoffs": {{
"per_line": {{"matches_contract": true or false, "reconciles_line_items": true or false,
             "rounding_adjustments_can_accumulate": true or false}},
"per_invoice": {{"rounds_once": true or false, "matches_contract": true or false}}}}}}.
Discover the facts from the contract and observations. Keep the recommendation
separate from the independent implementations, and explain those tradeoffs and
the Feature handoff in your final answer. No PR is appropriate for a throwaway prototype.'''
        invocations = [{"name": label, "script": str(artifacts / "variants/compare.py"),
                        "arguments": ["--variant", variant], "oracle": "rounding", "variant": variant}
                       for variant, label in (("per_line", "per-line variant observed through shared CLI"),
                                              ("per_invoice", "invoice variant observed through shared CLI"))]
        workflow["observations"] = [item["name"] for item in invocations]
    elif name == "trace-forensics":
        source = fixture / "reconcile.py"
        source.write_text(PROFILE_SOURCE)
        (fixture / "profile_query.py").write_text(PROFILE_TOOL)
        spec = importlib.util.spec_from_file_location("playbook_reconcile", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        references = [(f"account-{i}", i % 31 + 1) for i in range(2500)]
        payments = [(f"account-{(i * 173) % 2500}", i % 19 + 1) for i in range(6000)]
        totals = {}
        for label, function in (("before", module.reconcile_linear),
                                ("after", module.reconcile_indexed)):
            profiler = cProfile.Profile()
            totals[label] = profiler.runcall(function, references, payments)
            profiler.dump_stats(str(fixture / f"{label}.prof"))
        context["capture_totals"] = totals
        write_json(fixture / "capture_manifest.json", {
            "format": "cProfile", "workload": {"references": 2500, "payments": 6000},
            "results": totals,
            "capture_sha256": {label: sha(fixture / f"{label}.prof") for label in totals},
            "source_sha256": sha(source)})
        counts = {label: len(pstats.Stats(str(fixture / f"{label}.prof")).stats)
                  for label in ("before", "after")}
        hot_sql = "SELECT file,line,function,calls,self_seconds,cumulative_seconds FROM profile_samples WHERE capture='before' ORDER BY self_seconds DESC LIMIT 10"
        edge_sql = "SELECT caller_file,caller_line,caller_function,callee_file,callee_line,callee_function,calls FROM profile_edges WHERE capture='before' AND callee_function='lookup_reference' ORDER BY caller_file,caller_line,caller_function"
        pair_sql = "SELECT capture,SUM(CASE WHEN function='lookup_reference' THEN calls ELSE 0 END) AS lookup_calls FROM profile_samples GROUP BY capture ORDER BY capture"
        steps = re.findall(r"^\d+\. (.+)$", (bundle / "skills/poteto-mode/playbooks/trace-forensics.md").read_text(), re.M)
        if len(steps) != 6:
            raise ValueError("trace_stage_inventory_changed")
        context["trace_steps"] = steps
        workflow = {"type": "trace-forensics", "steps": steps,
                    "checklist": str(artifacts / "checklist.md"),
                    "diagnosis": str(artifacts / "diagnosis.json"),
                    "reply": str(artifacts / "reply.md"), "source": str(source),
                    "profile_tool": str(fixture / "profile_query.py"),
                    "captures": [str(fixture / f"{label}.prof") for label in ("before", "after")],
                    "database": str(artifacts / "profile.sqlite"),
                    "hot_sql": hot_sql, "edge_sql": edge_sql, "pair_sql": pair_sql,
                    "throughput": "throughput checkpoint: n/a, read-only forensics"}
        invocations = [
            {"name": "capture transformed into queryable SQLite", "script": str(fixture / "profile_query.py"),
             "arguments": ["import", "--db", str(artifacts / "profile.sqlite"),
                           "--before", str(fixture / "before.prof"), "--after", str(fixture / "after.prof")],
             "oracle": "json_equals", "expected_output": {"capture_rows": counts}},
            {"name": "capture queried through SQLite", "script": str(fixture / "profile_query.py"),
             "arguments": ["query", "--db", str(artifacts / "profile.sqlite"), "--sql"],
             "oracle": "sqlite_query", "database": str(artifacts / "profile.sqlite"),
             "sql": hot_sql,
             "required_read_columns": ["file", "line", "function", "calls", "self_seconds", "cumulative_seconds"]},
            {"name": "capture call tree queried through SQLite", "script": str(fixture / "profile_query.py"),
             "arguments": ["query", "--db", str(artifacts / "profile.sqlite"), "--sql"],
             "oracle": "sqlite_query", "database": str(artifacts / "profile.sqlite"),
             "sql": edge_sql,
             "required_table": "profile_edges",
             "required_read_columns": ["caller_file", "caller_line", "caller_function", "callee_file", "callee_line", "callee_function", "calls"]},
            {"name": "paired captures queried through SQLite", "script": str(fixture / "profile_query.py"),
             "arguments": ["query", "--db", str(artifacts / "profile.sqlite"), "--sql"],
             "oracle": "sqlite_query", "database": str(artifacts / "profile.sqlite"),
             "sql": pair_sql,
             "required_read_columns": ["capture", "function", "calls"]},
        ]
        order = [item["name"] for item in invocations]
        prompt = f'''Diagnose these already captured Python profiles. The same
6000-payment reconciliation workload was captured in {fixture / 'before.prof'}
and {fixture / 'after.prof'}; the corresponding source is {source}.
Identify the format, dominant hot path, source location and mechanism. Decide
whether the paired capture supports the mechanism. These captures are the fixed
input; do not rerun the workload or change source/captures. These bounded
captures fit in the controller. Keep parsing, queries and diagnosis in this
controller so their native order is observable; no worker delegation is needed.
Transform BOTH captures into {artifacts / 'profile.sqlite'} before investigating.
Use a table profile_samples(capture TEXT, file TEXT, line INTEGER,
function TEXT, calls INTEGER, self_seconds REAL, cumulative_seconds REAL), one
row per pstats function per capture, with capture values before and after.
The importer also preserves captured caller relationships in profile_edges.
Use queries on that database to narrow the cause. Keep full file names from the
captures in the private database; they will not be published.
The supplied generic profile tool is {fixture / 'profile_query.py'}.
Use it with python3 <absolute profile_query.py> import --db <absolute database>
--before <absolute before.prof> --after <absolute after.prof>, then query with
python3 <absolute profile_query.py> query --db <absolute database> --sql
'SELECT ...'. Choose your own useful queries. Use separate direct shell tool
calls, no wrapper or pipeline, and no trailing SQL semicolon, so the native
result records the actual imported row counts and query outputs.
Keep the original six-step checklist at {artifacts / 'checklist.md'} before
conversion. For this replayable evidence surface, run these two queries after
import to rank frames and walk the captured caller relationship:
{hot_sql}
{edge_sql}
Then read {source} in full to map the hot frame to source. Read the immutable
{fixture / 'capture_manifest.json'} for the workload and captured result checks.
After mapping source, use this paired comparison query:
{pair_sql}
You may run additional useful queries. Keep the original captures fixed and
do not inspect raw profiles with a different parser before conversion.
Write {artifacts / 'diagnosis.json'} containing {{"format": "...",
"hot_function": "...", "file": "<fixture-relative source>", "line": 1,
"mechanism": "...", "paired_capture_confirms": true or false,
"before_strategy": "...", "after_strategy": "...",
"before_lookup_calls": integer, "after_lookup_calls": integer}} alongside the
cited explanation and artifact paths. Use strategy values linear_scan_per_payment
or dictionary_index, as supported by source and queries. Cite the exact source
as reconcile.py:<line>, name both capture paths and profile.sqlite, say whether
the paired capture confirmed the diagnosis, and include the original one-line
read-only forensics throughput checkpoint. This task is diagnosis only, no fix or PR.'''
    else:
        raise ValueError("scenario_not_implemented")
    context["source_hashes"] = hashes(fixture)
    return {"prompt": prompt, "required_reads": required, "expected_roles": roles,
            "required_commands": commands, "required_invocations": invocations,
            "required_order": order, "workflow": workflow, "context": context, "read_only": True,
            "claims": CASES[name]["claims"]}


def load_object(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("artifact_not_object")
    return value


def check(name, ok, **observed):
    row = {"name": name, "ok": bool(ok)}
    if observed:
        row["observed"] = observed
    return row


def run_json(script, data):
    process = subprocess.run([sys.executable, "-B", str(script)], input=json.dumps(data),
                             text=True, capture_output=True, timeout=20)
    if process.returncode:
        raise ValueError("prototype_process_failed")
    value = json.loads(process.stdout)
    if not isinstance(value, dict) or set(value) != {"total_cents"} or type(value["total_cents"]) is not int:
        raise ValueError("prototype_output_invalid")
    return value["total_cents"]


def verify(name, worktree, artifacts, context):
    fixture = Path(context["fixture"])
    checks = [check("source and supplied captures unchanged", hashes(fixture) == context["source_hashes"])]
    observations = {}
    if name == "investigation":
        facts = load_object(artifacts / "findings.json")
        predicates = {
            "duplicate_scope": {"persisted": True, "within_batch": True, "across_files": True},
            "commit_operation": {"module": "os", "function": "replace", "calls_per_success": 1},
            "rounding_scope": {"scope": "line", "mode": "half_up"},
            "failure_effect": {"store_unchanged": True, "pending_file_created": False},
            "export_order": {"key": "id", "direction": "ascending"},
        }
        for key, expected in predicates.items():
            value = facts.get(key)
            checks.append(check(f"investigation identifies {key}", value == expected
                                and isinstance(value, dict)
                                and all(type(value.get(k)) is type(v) for k,v in expected.items())))
        cited = set()
        for item in facts.get("evidence", []):
            filename, line, symbol = item.get("file"), item.get("line"), item.get("symbol")
            if filename not in LEDGER_FILES or type(line) is not int or not isinstance(symbol, str) or not symbol:
                continue
            source = (fixture / filename).read_text()
            tree = ast.parse(source)
            scopes = [node for node in ast.walk(tree)
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and node.name == symbol]
            references = [node for node in ast.walk(tree)
                          if isinstance(node, (ast.Name, ast.Attribute)) and ast.unparse(node) == symbol]
            if any(node.lineno <= line <= node.end_lineno for node in scopes + references):
                cited.add(filename)
        checks.append(check("investigation source citations resolve across all modules", cited == set(LEDGER_FILES),
                            cited_modules=sorted(cited)))
        report = (artifacts / "reply.md").read_text()
        headings = ("Overview", "Key Concepts", "How It Works", "Where Things Live", "Gotchas")
        checks.append(check("how output explains flow and gotchas", all(
            re.search(r"(?im)^#{1,6}\s+" + re.escape(heading) + r"\s*$", report)
            for heading in headings)))
        checks.append(check("investigation checklist copies all four steps", all(
            step in (artifacts / "checklist.md").read_text() for step in context["investigation_steps"])))
        checkpoints = [line.strip() for line in report.splitlines()
                       if line.strip().startswith("throughput checkpoint:")]
        checks.append(check("investigation reports the read-only throughput checkpoint",
                            checkpoints == ["throughput checkpoint: n/a, read-only investigation"]))
        checks.append(check("investigation reply follows concrete unslop rules",
                            not any(character in report for character in ("\u2014", "\u201c", "\u201d", "\u2018", "\u2019"))
                            and not re.search(r"I hope this helps|let me know if|certainly!|great question!", report, re.I)))
        observations = {"cited_modules": sorted(cited), "fact_checks": len(predicates)}
    elif name == "prototype":
        vectors = [
            {"lines": [{"quantity": 1, "unit_price_cents": 101, "discount_bp": 5000}] * 2},
            {"lines": [{"quantity": 3, "unit_price_cents": 333, "discount_bp": 3333},
                       {"quantity": 2, "unit_price_cents": 137, "discount_bp": 250}]},
            {"lines": [{"quantity": 0, "unit_price_cents": 999, "discount_bp": 250},
                       {"quantity": 5, "unit_price_cents": 101, "discount_bp": 10000}]},
            {"lines": []},
        ]
        outputs = {}
        for variant in ("per_line", "per_invoice"):
            outputs[variant] = [run_json(artifacts / "variants" / f"{variant}.py", v) for v in vectors]
        line_expected, invoice_expected = [], []
        for vector in vectors:
            numerators = [r["quantity"] * r["unit_price_cents"] * (10000-r["discount_bp"])
                          for r in vector["lines"]]
            line_expected.append(sum((n+5000)//10000 for n in numerators))
            invoice_expected.append((sum(numerators)+5000)//10000)
        checks += [check("per-line prototype implements the billing contract", outputs["per_line"] == line_expected),
                   check("invoice prototype is an independent rounding alternative", outputs["per_invoice"] == invoice_expected),
                   check("workload separates the alternatives", outputs["per_line"][0] != outputs["per_invoice"][0])]
        decision = load_object(artifacts / "decision.json")
        checks.append(check("recommendation follows observed contract behavior", decision.get("recommendation") == "per_line"
                            and isinstance(decision.get("reason"), str) and len(decision["reason"]) > 30))
        runner_outputs = {}
        for variant in ("per_line", "per_invoice"):
            runner_outputs[variant] = []
            for vector in vectors:
                process = subprocess.run([sys.executable, "-B", str(artifacts / "variants/compare.py"),
                                          "--variant", variant], input=json.dumps(vector),
                                         text=True, capture_output=True, timeout=20)
                if process.returncode:
                    raise ValueError("shared_runner_process_failed")
                runner_outputs[variant].append(json.loads(process.stdout))
        checks.append(check("alternatives have a shared labeled runner", all(
            runner_outputs[v] == [{"variant": v, "total_cents": total} for total in outputs[v]]
            and all(type(row.get("total_cents")) is int for row in runner_outputs[v])
            for v in runner_outputs)))
        report = (artifacts / "reply.md").read_text()
        checks.append(check("prototype handoff identifies tradeoffs and throwaway scope",
                            bool(re.search(r"(?:trade.?off|alternative)", report, re.I))
                            and bool(re.search(r"(?:throwaway|disposable)", report, re.I))
                            and bool(re.search(r"\bFeature\b", report))
                            and str(artifacts / "variants") in report))
        checklist = (artifacts / "checklist.md").read_text()
        checks.append(check("prototype checklist copies all six steps",
                            all(step in checklist for step in context["prototype_steps"])))
        checks.append(check("prototype reference skip follows supplied direction",
                            context["reference_direction_fixed"] is True
                            and bool(re.search(r"(?is)2\..*?skip:.*?(?:direction|contract|alternatives).*?3\.", checklist))))
        expected_facts = {"per_line": {"matches_contract": True, "reconciles_line_items": True,
                                       "rounding_adjustments_can_accumulate": True},
                          "per_invoice": {"rounds_once": True, "matches_contract": False}}
        checks.append(check("prototype decision carries concrete tradeoff facts",
                            decision.get("tradeoffs") == expected_facts
                            and decision.get("artifact_scope") == "throwaway"
                            and decision.get("handoff") == "Feature"
                            and all(type(v) is bool for row in decision.get("tradeoffs", {}).values()
                                    if isinstance(row, dict) for v in row.values())))
        decision_path = artifacts / "decision.json"
        backup = artifacts / "decision.json.e2e-saved"
        if backup.exists():
            raise ValueError("decision_backup_already_exists")
        decision_path.rename(backup)
        try:
            independent = all(run_json(artifacts / "variants" / f"{variant}.py", vectors[0]) == outputs[variant][0]
                              for variant in outputs)
            for variant in outputs:
                process = subprocess.run([sys.executable, "-B", str(artifacts / "variants/compare.py"),
                                          "--variant", variant], input=json.dumps(vectors[0]),
                                         text=True, capture_output=True, timeout=20)
                independent = independent and process.returncode == 0 and json.loads(process.stdout) == {
                    "variant": variant, "total_cents": outputs[variant][0]}
        finally:
            backup.rename(decision_path)
        checks.append(check("prototype outputs are independent of the decision", independent))
        observations = {"inputs": vectors, "observed_totals": outputs, "runner_outputs": runner_outputs}
    elif name == "trace-forensics":
        expected = {}
        expected_edges = {}
        for label in ("before", "after"):
            stats = pstats.Stats(str(fixture / f"{label}.prof"))
            expected[label] = {(str(file), line, function): (calls, own, cumulative)
                               for (file, line, function), (_, calls, own, cumulative, _) in stats.stats.items()}
            expected_edges[label] = {}
            for callee, (_, _, _, _, callers) in stats.stats.items():
                for caller, values in callers.items():
                    if not isinstance(values, tuple) or len(values) != 4:
                        raise ValueError("unsupported_captured_callers")
                    expected_edges[label][(*caller, *callee)] = (values[0], values[2], values[3])
        with sqlite3.connect(f"file:{artifacts / 'profile.sqlite'}?mode=ro", uri=True) as database:
            records = database.execute("SELECT capture,file,line,function,calls,self_seconds,cumulative_seconds FROM profile_samples").fetchall()
            edge_records = database.execute("SELECT capture,caller_file,caller_line,caller_function,callee_file,callee_line,callee_function,calls,self_seconds,cumulative_seconds FROM profile_edges").fetchall()
        observed = {label: {} for label in expected}
        duplicate = False
        for label, file, line, function, calls, own, cumulative in records:
            if label not in observed or (file, line, function) in observed.get(label, {}):
                duplicate = True
                continue
            observed[label][(file, line, function)] = (calls, own, cumulative)
        checks.append(check("SQLite rows exactly preserve both captured profiles", not duplicate and observed == expected,
                            capture_rows={k: len(v) for k, v in observed.items()}))
        observed_edges = {label: {} for label in expected_edges}
        duplicate_edge = False
        for label, *values in edge_records:
            identity, metrics = tuple(values[:6]), tuple(values[6:])
            if label not in observed_edges or identity in observed_edges.get(label, {}):
                duplicate_edge = True
                continue
            observed_edges[label][identity] = metrics
        checks.append(check("SQLite edges exactly preserve captured call trees",
                            not duplicate_edge and observed_edges == expected_edges,
                            capture_edges={label: len(edges) for label, edges in observed_edges.items()}))
        diagnosis = load_object(artifacts / "diagnosis.json")
        source = fixture / "reconcile.py"
        own_frames = {key: values for key, values in expected["before"].items() if key[0] == str(source)}
        hottest = max(own_frames, key=lambda key: own_frames[key][1])
        reported_file = diagnosis.get("file")
        source_cited = isinstance(reported_file, str) and any(
            (base / reported_file).is_file() and (base / reported_file).resolve() == source.resolve()
            for base in (fixture, worktree))
        checks.append(check("diagnosis maps dominant own-time frame to exact source", diagnosis.get("hot_function") == hottest[2]
                            and source_cited
                            and type(diagnosis.get("line")) is int and diagnosis["line"] == hottest[1]))
        checks.append(check("profile format identified", bool(re.search(r"(?:cprofile|pstats)", str(diagnosis.get("format")), re.I))))
        checks.append(check("mechanism distinguishes repeated linear lookup", bool(re.search(
            r"(?:linear|scan|search).*?(?:repeat|payment|lookup)|(?:repeat|payment|lookup).*?(?:linear|scan|search)",
            str(diagnosis.get("mechanism")), re.I))
                            and diagnosis.get("before_strategy") == "linear_scan_per_payment"
                            and diagnosis.get("after_strategy") == "dictionary_index"))
        before_calls = sum(v[0] for k,v in expected["before"].items() if k[2] == "lookup_reference")
        after_calls = sum(v[0] for k,v in expected["after"].items() if k[2] == "lookup_reference")
        checks.append(check("paired capture confirms lookup elimination with equal results", before_calls == 6000 and after_calls == 0
                            and context["capture_totals"]["before"] == context["capture_totals"]["after"]
                            and diagnosis.get("paired_capture_confirms") is True
                            and type(diagnosis.get("before_lookup_calls")) is int
                            and type(diagnosis.get("after_lookup_calls")) is int
                            and diagnosis["before_lookup_calls"] == before_calls
                            and diagnosis["after_lookup_calls"] == after_calls))
        checks.append(check("trace checklist copies all six steps", all(
            step in (artifacts / "checklist.md").read_text() for step in context["trace_steps"])))
        report = (artifacts / "reply.md").read_text()
        checks.append(check("trace reply cites source and both capture artifacts",
                            f"reconcile.py:{hottest[1]}" in report
                            and str(fixture / "before.prof") in report
                            and str(fixture / "after.prof") in report
                            and str(artifacts / "profile.sqlite") in report
                            and bool(re.search(r"(?:cProfile|pstats)", report, re.I))
                            and bool(re.search(r"(?:paired|before.*after).*confirm|confirm.*(?:paired|before.*after)", report, re.I))))
        checkpoints = [line.strip() for line in report.splitlines()
                       if line.strip().startswith("throughput checkpoint:")]
        checks.append(check("trace reports the read-only throughput checkpoint",
                            checkpoints == ["throughput checkpoint: n/a, read-only forensics"]))
        observations = {"workload": {"references": 2500, "payments": 6000}, "capture_rows": {k: len(v) for k,v in expected.items()},
                        "capture_edges": {label: len(edges) for label, edges in expected_edges.items()},
                        "hot_function": hottest[2], "source_line": hottest[1], "lookup_calls": {"before": before_calls, "after": after_calls},
                        "equal_reconciliation_results": len(set(context["capture_totals"].values())) == 1}
    else:
        raise ValueError("scenario_not_implemented")
    return {"checks": checks, "observations": observations, "limitations": []}
