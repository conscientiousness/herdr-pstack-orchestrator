#!/usr/bin/env python3
"""Real Pi/Herdr Bug fix and Opening a PR E2E against a private fixture.

Creates a retained child branch/worktree and a ready PR on an existing private
baseline branch. Never merges, retries, answers trust prompts, or changes models.
Raw sessions, forge identities and application outputs remain in private artifacts.
Only evidence.json is a candidate for publication after human review.
This snapshot/gateway lane does not establish original live-source Why or full
Bug fix eligibility. Its post-execution audit is not credential containment.

Use --prepare-fixture DIRECTORY for local-only portable baseline files, without
controller, Herdr, Git or forge calls. Follow the generated README to create your
own private repository and ready bootstrap PR 1 manually, keep that PR unmerged,
then run this driver against your exact baseline branch and configured Pi worker.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import inspect
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import urllib.request

import playbook_loop as core

horch = core.horch
ROOT = Path(__file__).resolve().parents[1]
Failure = core.Failure
BASE_STORAGE = 'c32037b76d52e28908e2a46b40e77bf46be109fdb7fb25afd702070e7d74bfc2'
READS = (
    'poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
    'pstack-herdr/references/herdr-tools.md', 'agent-workers/SKILL.md',
    'poteto-mode/playbooks/bug-fix.md', 'control-cli/SKILL.md',
    'how/SKILL.md', 'how/references/explainer-prompt.md', 'why/SKILL.md',
    'why/references/epistemics.md', 'why/references/investigator-prompt.md',
    'why/references/synthesizer-prompt.md', 'why/references/sources/code-archaeology.md',
    'why/references/source-playbook.md', 'why/references/sources/linear.md',
    'why/references/sources/incident-postmortem.md',
    'poteto-mode/playbooks/opening-a-pr.md', 'deslop/SKILL.md',
    'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
    'principle-sequence-verifiable-units/SKILL.md',
)

# The probe executes the application's real CLI and always reports app failures
# as data. A native successful tool result can therefore witness a failed app.
PROBE = r'''#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--mode', choices=['missing-field', 'e2e'], required=True)
a = p.parse_args()
r = a.repo.resolve()
d = a.output.resolve()
d.mkdir(parents=True, exist_ok=False, mode=0o700)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def invoke(argv):
    x = subprocess.run(argv, cwd=r, capture_output=True, text=True, timeout=90)
    return {'argv': list(map(str, argv)), 'exit_code': x.returncode,
            'stdout': x.stdout, 'stderr': x.stderr}
sources = {name: digest(r / name) for name in ['cli.py', 'storage.py', 'money.py', 'e2e_import.py']}
if a.mode == 'e2e':
    result = invoke([sys.executable, '-B', str(r / 'e2e_import.py'), '--output', str(d / 'suite')])
    receipt = d / 'suite/evidence.json'
    result['suite'] = json.loads(receipt.read_text()) if receipt.exists() else None
else:
    store = d / 'ledger.json'
    seed = d / 'seed.json'
    seed.write_text(json.dumps([{'id': 'persisted', 'quantity': 2, 'unit_price_cents': 49, 'discount_bp': 0}]))
    cli = [sys.executable, '-B', str(r / 'cli.py')]
    seeded = invoke([*cli, 'import', str(store), str(seed)])
    before = digest(store)
    first, second = d / 'first.json', d / 'second.json'
    first.write_text(json.dumps([{'id': 'first', 'quantity': 1, 'unit_price_cents': 101, 'discount_bp': 5000}]))
    second.write_text(json.dumps([{'id': 'middle', 'quantity': 2, 'unit_price_cents': 333, 'discount_bp': 3333},
                                  {'id': 'last', 'quantity': 1, 'unit_price_cents': 200}]))
    result = invoke([*cli, 'import', str(store), str(first), str(second)])
    result.update(seed=seeded, store_before=before, store_after=digest(store),
                  pending_exists=store.with_suffix('.pending').exists(),
                  export=invoke([*cli, 'export', str(store)]))
result.update(mode=a.mode, source_sha256=sources)
(d / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
'''


FIXTURE_ORACLE = r'''#!/usr/bin/env python3
"""Exercise the real multi-file import CLI and retain its replayable evidence."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(identity, quantity, price, discount=0):
    return {"id": identity, "quantity": quantity,
            "unit_price_cents": price, "discount_bp": discount}


def charged(value):
    amount = (Decimal(value["quantity"]) * Decimal(value["unit_price_cents"])
              * (Decimal(1) - Decimal(value["discount_bp"]) / Decimal(10000)))
    return dict(value, total_cents=int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    directory = args.output.expanduser().resolve()
    if directory == ROOT or ROOT in directory.parents:
        parser.error("--output must be outside the fixture checkout")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    inputs = directory / "inputs"
    inputs.mkdir()
    store = directory / "ledger.json"
    sources = {name: digest(ROOT / name) for name in ("money.py", "storage.py", "cli.py")}
    checks, flows = [], []
    failure = None

    def observe(name, ok):
        checks.append({"name": name, "ok": bool(ok)})

    def invoke(label, command, groups=()):
        paths = []
        for number, values in enumerate(groups):
            path = inputs / f"{label}-{number}.json"
            path.write_text(json.dumps(values, sort_keys=True) + "\n")
            paths.append(path)
        argv = [sys.executable, "-B", str(ROOT / "cli.py"), command, str(store),
                *map(str, paths)]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30, cwd=ROOT)
        (directory / f"{label}.stdout").write_text(result.stdout)
        (directory / f"{label}.stderr").write_text(result.stderr)
        value = json.loads(result.stdout)
        flows.append({"name": label, "command": command, "input_files": len(paths),
                      "exit_code": result.returncode, "output": value})
        return result.returncode, value

    try:
        old = row("old-01", 2, 49)
        code, value = invoke("seed", "import", [[old]])
        observe("existing store seeded through the real CLI", code == 0 and value == {
            "count": 1, "total_cents": 98})
        first = [row("txn-z", 1, 101, 5000), row("txn-a", 2, 333, 3333)]
        second = [row("txn-m", 3, 137, 250), row("txn-0", 0, 999),
                  row("txn-free", 7, 101, 10000)]
        expected = sorted(map(charged, [old, *first, *second]), key=lambda item: item["id"])
        expected_total = sum(item["total_cents"] for item in expected)
        code, value = invoke("two-files", "import", [first, second])
        observe("two input files preserve independent integer money results",
                code == 0 and value == {"count": len(expected), "total_cents": expected_total})
        baseline = store.read_bytes()
        rejected = [
            ("persisted-duplicate", [[row("candidate", 1, 200), old]], "duplicate transaction"),
            ("within-file-duplicate", [[row("new-dup", 1, 200), row("new-dup", 2, 300)]],
             "duplicate transaction"),
            ("across-file-duplicate", [[row("cross-dup", 1, 200)], [row("cross-dup", 2, 300)]],
             "duplicate transaction"),
            ("late-invalid-discount", [[row("valid-first", 1, 200)],
                                       [row("invalid-last", 1, 200, 10001)]], "invalid discount"),
        ]
        for label, groups, error in rejected:
            code, value = invoke(label, "import", groups)
            observe(label + " rejects without changing persisted bytes",
                    code == 2 and isinstance(value, dict) and error in value.get("error", "")
                    and store.read_bytes() == baseline and not store.with_suffix(".pending").exists())
        code, value = invoke("export", "export")
        observe("export matches the complete sorted independent ledger",
                code == 0 and value == expected and store.read_bytes() == baseline)
    except Exception as error:
        failure = type(error).__name__
    after = {name: digest(ROOT / name) for name in sources}
    observe("fixture source unchanged", sources == after)
    passed = failure is None and len(flows) == 7 and all(item["ok"] for item in checks)
    receipt = {"schema": "invoice/import-e2e/v1", "verdict": "pass" if passed else "fail",
               "checks": checks, "flows": flows, "source_sha256_before": sources,
               "source_sha256_after": after, "failure_category": failure}
    (directory / "evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"verdict": receipt["verdict"], "flows": len(flows),
                      "evidence": str(directory / "evidence.json")}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

FIXTURE_SUPPORT = {
    'README.md': r'''# Invoice CLI playbook fixture

This synthetic Python standard-library application supports private, unmerged
playbook E2E pull requests. It contains no production data or credentials.
Raw sessions, worker configuration and generated evidence belong outside Git.

The importer charges each line in integer cents with half-up discount rounding.
It rejects duplicate transaction IDs across stored state and all input files,
then commits the complete batch with one atomic replacement. Export sorts by ID.
The baseline intentionally retains the observed missing-discount validation gap;
its seven-flow E2E oracle does not cover that gap yet.

Run the real CLI oracle with a fresh external output directory:

```sh
python3 -B e2e_import.py --output /tmp/invoice-proof-UNIQUE
```

The artifact records seven CLI flows, independent decimal expected results,
source hashes and persisted-byte checks. Keep the output for review and replay.

## Manual private bootstrap

Fixture preparation does not invoke Git, Herdr, models or a forge. To use the
live driver, create your own private repository and its ready baseline PR 1.
Start in this prepared directory; replace OWNER/NAME with your private repository.
The default branch contains only this README. Do not merge the baseline PR.

```sh
git init -b main
git add README.md
git commit -m "docs: initialize fixture repository"
gh repo create OWNER/NAME --private --source . --remote origin --push
git switch -c feat/fixture-baseline
git add AGENTS.md .gitignore .github money.py storage.py cli.py e2e_import.py
git commit -m "feat(invoice): add import and export fixture"
git push -u origin feat/fixture-baseline
gh pr create --repo OWNER/NAME --base main --head feat/fixture-baseline \
  --title "feat(invoice): add import and export fixture" \
  --body "Add a synthetic multi-file invoice CLI and its seven-flow E2E oracle."
gh pr view 1 --repo OWNER/NAME
```

The create command opens a ready PR by default. Leave PR 1 open and unmerged.
The live driver checks repository privacy, the exact remote baseline tip,
canonical source hashes and a clean local baseline checkout. It creates a child
branch and a separate ready PR targeting feat/fixture-baseline, and retains both.
Bootstrap PR 1 is setup only; it is not playbook execution evidence.

Run the orchestrator driver from its trusted checkout with your configured Pi
controller and verified caller pane. Use this prepared checkout as --fixture-repo,
OWNER/NAME as --forge-repo, feat/fixture-baseline as --base-ref, and an external
private directory as --output. Authenticate and establish trust yourself before
running. The driver never answers trust dialogs or changes models or Git config.
''',
    'AGENTS.md': r'''# Fixture work rules

Keep all work in the assigned feature branch or worktree and within the
assignment's files. Use configured workers through the supplied Herdr adapter.
Never alter worker configuration, model choices, authentication or trust.

Use the real CLI for behavior verification. E2E drivers must retain a receipt
and rerunnable artifact. Do not add unit tests or inferred safety changes.
Write code, comments, docs and commits in English. Keep source changes separate
from generated outputs. Never commit raw sessions, private paths, credentials
or worker configuration.

Do not merge, enable auto-merge, change the default branch or push directly to
main. Open a ready PR only when the assigned playbook or controller asks for it.
A passing check never authorizes a merge.
''',
    '.gitignore': r'''__pycache__/
*.py[cod]
artifacts/
.audit/
''',
    '.github/workflows/invoice.yml': r'''name: Invoice CLI behavior

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  import:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.14']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Exercise the real multi-file CLI
        run: python3 e2e_import.py --output "$RUNNER_TEMP/invoice-proof"
''',
}


def prepare_fixture(directory):
    """Write a portable synthetic baseline without Git, configuration or network."""
    directory = directory.expanduser().resolve()
    files = dict(core.cases.LEDGER_FILES, **{'e2e_import.py': FIXTURE_ORACLE})
    files.update(FIXTURE_SUPPORT)
    if hashlib.sha256(files['storage.py'].encode()).hexdigest() != BASE_STORAGE:
        raise Failure('canonical_fixture_storage_changed')
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    hashes = {}
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        hashes[name] = core.sha(path)
    print(json.dumps({'prepared_fixture': str(directory), 'sha256': hashes}, indent=2))
    return 0


def identity():
    paths = [*ROOT.joinpath('skills').rglob('*'),
             *ROOT.joinpath('e2e').glob('*.py')]
    return {str(p.relative_to(ROOT)): core.sha(p) for p in paths
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def literal(command):
    if not isinstance(command, str) or any(c in command for c in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def observation_ok(value, fixed):
    if value.get('mode') != 'missing-field':
        return False
    same = (value.get('store_before') == value.get('store_after')
            and value.get('pending_exists') is False
            and value.get('seed', {}).get('exit_code') == 0
            and value.get('export', {}).get('exit_code') == 0)
    if not fixed:
        return same and value.get('exit_code') == 1 and not value.get('stdout') and 'KeyError' in value.get('stderr', '') and 'discount_bp' in value.get('stderr', '')
    try:
        result = json.loads(value['stdout'])
    except (ValueError, KeyError):
        return False
    return same and value.get('exit_code') == 2 and isinstance(result, dict) and bool(result.get('error')) and not value.get('stderr')


def suite_ok(value, fixed):
    suite = value.get('suite') or {}
    if not fixed:
        return value.get('exit_code') != 0 and suite.get('verdict') == 'fail'
    flows = suite.get('flows', [])
    return (value.get('exit_code') == 0 and suite.get('verdict') == 'pass'
            and len(flows) == 8 and all(c.get('ok') is True for c in suite.get('checks', []))
            and any('missing' in str(flow.get('name', '')).lower() and flow.get('exit_code') == 2 for flow in flows))


def outside_function(text):
    tree = ast.parse(text)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch']
    if len(functions) != 1:
        raise Failure('fixture_function_missing')
    functions[0].body = [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def retained_oracle(before, after):
    """Allow exactly the missing-field flow and seven-to-eight flow count edit."""
    original, changed = ast.parse(before), ast.parse(after)
    removed, counts = 0, 0
    for node in ast.walk(changed):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'rejected' for t in node.targets):
            if not isinstance(node.value, ast.List):
                return False
            additions = [item for item in node.value.elts if isinstance(item, ast.Tuple)
                         and item.elts and isinstance(item.elts[0], ast.Constant)
                         and 'missing' in str(item.elts[0].value)]
            if len(additions) != 1:
                return False
            addition = additions[0]
            for expression in ast.walk(addition):
                if isinstance(expression, ast.Call) and not (
                    isinstance(expression.func, ast.Name) and expression.func.id == 'row'
                    and all(isinstance(arg, ast.Constant) for arg in expression.args)
                    and not expression.keywords):
                    return False
                if isinstance(expression, (ast.Attribute, ast.Subscript, ast.NamedExpr, ast.Lambda,
                                           ast.ListComp, ast.DictComp, ast.GeneratorExp)):
                    return False
            node.value.elts.remove(addition)
            removed += 1
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name) and node.left.func.id == 'len'
                and len(node.left.args) == 1 and isinstance(node.left.args[0], ast.Name)
                and node.left.args[0].id == 'flows' and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value == 8):
            node.comparators[0].value = 7
            counts += 1
    return removed == counts == 1 and ast.dump(original, include_attributes=False) == ast.dump(changed, include_attributes=False)


def local_git(argv, cwd, refs):
    """Recognize only local read commands and owned paths for this fixture."""
    if not argv or argv[0] != 'git':
        return None
    rest = argv[1:]
    if rest[:1] == ['-C']:
        if len(rest) < 3 or '~' in rest[1] or Path(rest[1]).resolve() != cwd:
            return None
        rest = rest[2:]
    if not rest or rest[0] not in ('log','blame','show','diff','status','rev-parse','ls-files','rev-list','diff-tree'):
        return None
    operation, tokens = rest[0], rest[1:]
    plain = {'--oneline','--follow','-p','--patch','--stat','--name-only','--name-status','--short',
             '--porcelain','--porcelain=v1','--no-patch','--all','--reverse','--abbrev-commit',
             '--no-renames','--no-color','--color=never','--show-toplevel','--show-prefix',
             '--no-commit-id','-r','--stage','-s','--no-ext-diff','--no-textconv',
             '--decorate','--graph'}
    valued = {'-L','-n','--max-count','--format','--pretty','-S','-G','--since','--until'}
    index = 0
    paths = False
    while index < len(tokens):
        token = tokens[index]
        if token == '--':
            paths = True
        elif not paths and token in valued:
            index += 1
            if index >= len(tokens):
                return None
            if token=='-L' and not re.fullmatch(r'\d+(?:,\+?\d+)?',tokens[index]):
                return None
            if token in ('-n','--max-count') and not tokens[index].isdigit():
                return None
        elif not paths and (token in plain or re.fullmatch(r'-\d+',token)
              or any(token.startswith(flag+'=') for flag in (
                  '--max-count','--format','--pretty','--since','--until','--unified', '--grep'))):
            pass
        elif token.startswith('-'):
            return None
        elif not paths and (token in refs or re.fullmatch(r'HEAD(?:[~^]\d*)*|[a-fA-F0-9]{7,64}',token)):
            pass
        else:
            # No external path, rev:path ambiguity, URL, implicit remote or
            # --no-index pair may escape this exact owned cwd.
            if ':' in token or '@' in token or '~' in token:
                return None
            target = (cwd/token).resolve()
            if target != cwd and cwd not in target.parents:
                return None
        index += 1
    return operation


def reader_tree(root):
    """Record a symlink-free owned tree without following directory links."""
    import os
    entries = []
    if root.is_symlink():
        raise ValueError('reader_tree_symlink')
    def fail(_error):
        raise ValueError('reader_tree_unreadable')
    for directory, folders, files in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted(folders + files):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError('reader_tree_symlink')
            entries.append(str(path.relative_to(root)))
    return {'symlink_count': 0, 'entries': len(entries),
            'paths_sha256': hashlib.sha256('\n'.join(sorted(entries)).encode()).hexdigest()}


# Query mode has no network/subprocess path. Delivery mode suppresses horch's
# untrusted summary/question before a complete post-execution native audit.
SCOPE_GATE = r'''#!/usr/bin/env python3
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

home=Path(__file__).resolve().parent
active_task=None
class Rejected(Exception):
    pass
class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise Rejected('invalid_arguments')
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):
    return json.loads(path.read_text())
def check(value,code):
    if not value:
        raise Rejected(code)
def inside(path,root):
    return path==root or root in path.parents
def stamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def literal(command):
    if not isinstance(command,str) or any(c in command for c in ('\n',';','|','&','>','<',chr(96),'$','\\')):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []
def integrity():
    manifest=load(home/'manifest.json')
    for name,sha in manifest['files'].items():
        path=(home/name).resolve()
        check(inside(path,home) and path.is_file() and digest(path)==sha,'snapshot_integrity')
    policy=load(home/'policy.json')
    check(digest(Path(policy['config']))==policy['config_sha256'],'config_integrity')
    for name,sha in policy['bundle_sha256'].items():
        check(digest(Path(policy['bundle'])/name)==sha,'bundle_integrity')
    return manifest,policy
def make_parser():
    p=Parser()
    sub=p.add_subparsers(dest='mode',required=True)
    q=sub.add_parser('query')
    q.add_argument('operation',choices=['list','search','read'])
    q.add_argument('kind',choices=['issues','comments','labels','pr','pr-comments','pr-reviews','pr-review-comments'])
    q.add_argument('--text')
    q.add_argument('--id',type=int)
    for name in ('audit','wait-audit'):
        x=sub.add_parser(name)
        x.add_argument('--task',required=True)
        if name=='wait-audit':
            x.add_argument('--max-seconds',type=int,required=True)
    return p
def query(args):
    manifest,policy=integrity()
    rows=load(home/'dataset.json')[args.kind]
    if args.operation=='search':
        check(args.text is not None and args.id is None,'invalid_query')
        rows=[row for row in rows if args.text.casefold() in json.dumps(row,ensure_ascii=False).casefold()]
    elif args.operation=='read':
        check(args.id is not None and args.text is None,'invalid_query')
        rows=[row for row in rows if row.get('number',row.get('id'))==args.id]
    else:
        check(args.id is None and args.text is None,'invalid_query')
    return {'schema':'forge/snapshot-query/v1','kind':args.kind,'operation':args.operation,
            'count':len(rows),'records':rows,'snapshot_sha256':digest(home/'dataset.json'),
            'captured_at':manifest['completed_at'],'coverage':'exact-repository snapshot; no live worker query'}
def scoped_session(task,binding,policy):
    session=binding['session']
    cwd=Path(task['cwd']).resolve()
    encoded='--'+re.sub(r'[/\\:]','-',str(cwd).lstrip('/\\'))+'--'
    directory=Path(policy['agent_dir'])/'sessions'/encoded
    value=session.get('value')
    if session.get('kind')=='path':
        supplied=Path(value).expanduser().resolve()
        check(supplied.parent==directory,'session_location')
        identity=supplied.stem.rsplit('_',1)[-1]
    else:
        identity=value
    canonical=str(uuid.UUID(identity))
    check(canonical==identity,'session_uuid')
    paths=list(directory.glob('*_'+canonical+'.jsonl'))
    check(len(paths)==1 and (session.get('kind')!='path' or paths[0].resolve()==supplied),'session_unavailable')
    return paths[0],session
def approved_report(path,policy):
    root=Path(policy['task_root'])
    if root not in path.parents:
        return False
    relative=path.relative_to(root)
    if len(relative.parts)!=2 or not re.fullmatch(r't-[0-9a-f]{6}',relative.parts[0]):
        return False
    receipt=home/'gates'/(relative.parts[0]+'.json')
    return (receipt.is_file() and load(receipt).get('verdict')=='pass'
            and load(receipt).get('reports',{}).get(str(path))==digest(path))
def audit(task_id):
    manifest,policy=integrity()
    check(re.fullmatch(r't-[0-9a-f]{6}',task_id),'task_id')
    task_dir=Path(policy['task_root'])/task_id
    protected={task_dir/name for name in ('task.json','state.json','brief.md')}
    task=load(task_dir/'task.json');state=load(task_dir/'state.json')
    check(task.get('task_id')==task_id and Path(task['task_dir']).resolve()==task_dir
          and Path(task['brief_path']).resolve()==task_dir/'brief.md'
          and Path(task['result_path']).resolve()==task_dir/'result.json','task_identity')
    check(state.get('state')=='done' and state.get('closed') is True,'not_delivered_closed')
    binding=load(home/'bindings'/(task_id+'.json'))
    check(binding['task_sha256']==digest(task_dir/'task.json')
          and binding['brief_sha256']==digest(task_dir/'brief.md'),'session_assignment_binding')
    native,session=scoped_session(task,binding,policy)
    rows=[json.loads(line) for line in native.read_text().splitlines() if line.strip()]
    header=rows[0];cwd=Path(task['cwd']).resolve()
    check(header.get('type')=='session' and header.get('version')==3 and header.get('id')
          and Path(header.get('cwd','')).resolve()==cwd
          and stamp(task['created_at'])<=stamp(header['timestamp'])<=binding['captured_at'],'session_header')
    check((session.get('kind')=='path' and Path(session['value']).resolve()==native.resolve())
          or session.get('value')==header['id'],'session_identity')
    assignment=Path(task['brief_path']).read_text().split('## Worker rules',1)[0]
    match=re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)',assignment)
    check(match is not None,'role_header');role=match[1]
    check(role in policy['roles'] and task['worker'] in policy['roles'][role],'role_worker')
    spec=policy['workers'][task['worker']]
    check(task.get('harness')=='pi' and task.get('model')==spec['model'] and task.get('argv')==spec['argv'],'configured_worker')
    check('Repository boundary: '+policy['repository'] in assignment
          and 'Host boundary: snapshot only; no direct network' in assignment
          and 'Do not delegate' in assignment,'brief_boundary')
    reader=role!='bug-fix'
    check((reader and str(cwd) in policy['readers']) or (not reader and str(cwd)==policy['worktree']),'owned_cwd')
    tree_before=policy['reader_trees'].get(str(cwd)) if reader else None
    tree_after=reader_tree(cwd) if reader else None
    if reader:
        check(tree_before is not None and tree_before['symlink_count']==0
              and policy['reader_trees_captured_at']<=stamp(task['created_at']),'reader_tree_before_dispatch')
    category=None;allowed_source=None
    if role=='why investigators':
        match=re.search(r'^Evidence category: (Source control history|Issue / ticket tracker)$',assignment,re.M)
        check(match is not None,'category');category=match[1]
    if not reader:
        scopes=re.findall(r'^Allowed source: (e2e_import\.py|storage\.py)$',assignment,re.M)
        check(len(scopes)==1,'source_scope');allowed_source=cwd/scopes[0]
    bundle=Path(policy['bundle'])
    inputs=[]
    for raw in re.findall(r'^Input artifact: (.+)$',assignment,re.M):
        item=Path(raw).resolve()
        check(any(inside(item,Path(root)) for root in policy['input_roots'])
              and item.is_file(),'input_artifact_boundary')
        inputs.append(item)
    def readable(raw,directory=False):
        check(isinstance(raw,str) and '~' not in raw,'path_argument')
        path=(cwd/raw).resolve()
        if inside(path,cwd) or inside(path,task_dir) or inside(path,bundle):
            return True
        return not directory and path.is_file() and (path in inputs or path==home/'gateway.py'
                                                    or approved_report(path,policy))
    pending={};models=set();efforts=set();seen=set();last=None;count=0;used={};queries=[];git_operations=[]
    for row in rows[1:]:
        identity=row.get('id')
        check(identity and identity not in seen and row.get('parentId')==last,'native_chain')
        seen.add(identity);last=identity
        if row.get('type')=='model_change':
            models.add((row.get('provider'),row.get('modelId')))
        if row.get('type')=='thinking_level_change':
            efforts.add(row.get('thinkingLevel'))
        message=row.get('message',{})
        if message.get('role')=='assistant':
            if message.get('model'):
                models.add((message.get('provider'),message['model']))
            for block in message.get('content',[]):
                if block.get('type')!='toolCall':
                    continue
                name,args,call_id=block.get('name'),block.get('arguments'),block.get('id')
                check((name in ('read','write','edit','grep','find','ls','bash')
                       or reader and name in ('fffind','ffgrep')) and isinstance(args,dict)
                      and call_id and call_id not in pending,'native_tool')
                count+=1;query_call=None;git_operation=None
                fields={'read':{'path','offset','limit'},'write':{'path','content'},
                        'edit':{'path','oldText','newText','edits'},'bash':{'command','timeout'},
                        'grep':{'pattern','path','glob','ignoreCase','literal','context','limit'},
                        'find':{'pattern','path','limit'},'ls':{'path','limit'},
                        'fffind':{'pattern','path','exclude','limit'},
                        'ffgrep':{'pattern','path','exclude','limit','caseSensitive','context'}}
                check(set(args)<=fields[name],'native_argument_schema')
                if name in ('fffind','ffgrep'):
                    check(isinstance(args.get('pattern'),str),'fff_pattern')
                    raw=args.get('path','.')
                    check(isinstance(raw,str) and bool(raw) and raw==raw.strip() and '\ufeff' not in raw
                          and not any(char in raw for char in ('\\','~','\x00','{','}',',','!'))
                          and '..' not in raw.split('/') and not raw.startswith('-'),'fff_path_syntax')
                    target=Path(raw) if raw.startswith('/') else cwd/raw
                    check(target.resolve()==cwd or cwd in target.resolve().parents,'fff_owned_root')
                    if 'exclude' in args:
                        check(isinstance(args['exclude'],str) or isinstance(args['exclude'],list)
                              and all(isinstance(item,str) for item in args['exclude']),'fff_exclude_type')
                    for key in ('limit','context'):
                        if key in args:
                            check(type(args[key]) is int and args[key]>= (1 if key=='limit' else 0),'fff_numeric_type')
                    if 'caseSensitive' in args:
                        check(type(args['caseSensitive']) is bool,'fff_case_type')
                elif name in ('read','grep','find','ls'):
                    check(readable(args.get('path','.' if name in ('grep','find','ls') else None),
                                   name in ('grep','find','ls')),'read_boundary')
                elif name in ('write','edit'):
                    if name=='edit':
                        if set(args)=={'path','edits'}:
                            check(isinstance(args['edits'],list) and bool(args['edits'])
                                  and all(isinstance(item,dict) and set(item)=={'oldText','newText'}
                                          and all(isinstance(item[key],str) for key in ('oldText','newText'))
                                          for item in args['edits']),'native_edit_array')
                        else:
                            check(set(args)=={'path','oldText','newText'}
                                  and all(isinstance(args[key],str) for key in ('oldText','newText')),
                                  'native_edit_replacement')
                    check(isinstance(args.get('path'),str) and '~' not in args['path'],'write_path')
                    target=(cwd/args['path']).resolve()
                    check(target not in protected,'protected_task_identity')
                    check(task_dir in target.parents or not reader and target==allowed_source,'write_boundary')
                else:
                    argv=literal(args.get('command'));check(bool(argv),'literal_command')
                    binary=argv[0]
                    if binary=='git':
                        operation=local_git(argv,cwd,policy['revisions'])
                        check(operation is not None,'local_git_grammar')
                        check(category!='Issue / ticket tracker','issues_source_only')
                        git_operation=operation
                    elif binary in ('cat','sha256sum'):
                        check(len(argv)==2 and readable(argv[1]),'literal_read')
                    elif binary=='pwd':
                        check(argv==['pwd'],'literal_pwd')
                    elif binary in ('python','python3'):
                        rest=argv[1:]
                        if rest[:1]==['-B']:
                            rest=rest[1:]
                        check(bool(rest) and '~' not in rest[0],'python_script');script=(cwd/rest[0]).resolve()
                        if script==home/'gateway.py':
                            check(rest[1:2]==['query'],'gateway_query_only')
                            parsed=make_parser().parse_args(rest[1:])
                            check(parsed.mode=='query','gateway_mode')
                            check(category!='Issue / ticket tracker' or parsed.kind in ('issues','comments','labels'),'issues_category')
                            check(category!='Source control history' or parsed.kind in ('pr','pr-comments','pr-reviews','pr-review-comments'),'git_category')
                            query_call=parsed
                        else:
                            check(script in (cwd/'cli.py',cwd/'e2e_import.py'),'owned_cli_only')
                            check(all('~' not in token for token in rest[2:]),'application_path_syntax')
                            check(not any(word in ('-c','-m') for word in rest),'no_interpreter_wrapper')
                            if script.name=='e2e_import.py':
                                check(len(rest)==3 and rest[1]=='--output','oracle_grammar')
                                output=(cwd/rest[2]).resolve()
                                check(task_dir in output.parents and not any(inside(output,path) or inside(path,output)
                                      for path in protected),'oracle_output_owned')
                            else:
                                check(len(rest)>=3 and rest[1] in ('import','export'),'cli_grammar')
                                store=(cwd/rest[2]).resolve()
                                check(task_dir in store.parents and not any(inside(store,path) or inside(path,store)
                                      for path in protected),'store_owned')
                                check((rest[1]=='export' and len(rest)==3) or
                                      (rest[1]=='import' and len(rest)>=4),'cli_inputs')
                                check(all(not token.startswith('-') and
                                          (inside((cwd/token).resolve(),cwd)
                                           or inside((cwd/token).resolve(),task_dir)
                                           or (cwd/token).resolve() in inputs)
                                          for token in rest[3:]),'cli_input_paths')
                            used[str(script)]=digest(script)
                    else:
                        raise Rejected('no_direct_forge_network_or_wrapper')
                pending[call_id]=(name,query_call,git_operation)
        elif message.get('role')=='toolResult':
            check(message.get('toolCallId') in pending,'native_result_binding')
            name,query_call,git_operation=pending.pop(message['toolCallId'])
            check(message.get('toolName')==name,'native_result_name')
            if git_operation and message.get('isError') is False:
                output='\n'.join(item.get('text','') for item in message.get('content',[]) if item.get('type')=='text')
                if output.strip() not in ('','(no output)'):
                    git_operations.append(git_operation)
            if query_call and message.get('isError') is False:
                output='\n'.join(item.get('text','') for item in message.get('content',[]) if item.get('type')=='text')
                check(json.loads(output)==query(query_call),'actual_snapshot_query_result')
                queries.append((query_call.kind,query_call.operation))
    check(not pending,'native_pending')
    check(models and all(model==spec['model'] and (not spec.get('provider') or provider==spec['provider'])
                         for provider,model in models),'native_model')
    check(not spec.get('effort') or efforts=={spec['effort']},'native_effort')
    if category=='Issue / ticket tracker':
        check(all((kind,'list') in queries for kind in ('issues','comments','labels'))
              and ('issues','search') in queries,'real_issues_snapshot_search')
    if category=='Source control history':
        check({'log','blame'}<=set(git_operations)
              and ('pr','read') in queries and all((kind,'list') in queries for kind in (
                  'pr-comments','pr-reviews','pr-review-comments')),'real_git_and_pr_snapshot_investigation')
    result=load(task_dir/'result.json')
    check(set(result)=={'task_id','nonce','status','summary','files','question'} and result['task_id']==task_id
          and result['nonce']==task['nonce'] and result['status']=='completed' and result['question'] is None
          and isinstance(result['summary'],str) and result['files']==['report.md'],'nonce_result')
    reports={}
    for filename in result['files']:
        check(isinstance(filename,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',filename),'report_name')
        item=(task_dir/filename).resolve()
        check(task_dir==item.parent and item.is_file(),'report_owned');reports[str(item)]=digest(item)
    check(any(Path(filename).suffix=='.md' for filename in reports),'markdown_report')
    return {'schema':'forge/scope-audit/v1','verdict':'pass','task_id':task_id,'role':role,'category':category,
            'calls_audited':count,'task_sha256':digest(task_dir/'task.json'),'native_sha256':digest(native),
            'result_sha256':digest(task_dir/'result.json'),'brief_sha256':binding['brief_sha256'],
            'binding_sha256':digest(home/'bindings'/(task_id+'.json')),
            'reader_tree_before':tree_before,'reader_tree_after':tree_after,
            'reports':reports,'successful_local_git_operations':git_operations,
            'successful_snapshot_queries':queries,'executed_source_sha256':used,'snapshot_sha256':digest(home/'dataset.json'),
            'manifest_sha256':digest(home/'manifest.json'),'policy_sha256':digest(home/'policy.json')}
def save_gate(task_id):
    try:
        facts=audit(task_id)
    except Exception:
        facts={'schema':'forge/scope-audit/v1','verdict':'fail','task_id':task_id,
               'category':'native_boundary_or_identity_rejected'}
    target=home/'gates'/(task_id+'.json')
    if target.exists():
        check(load(target)==facts,'gate_changed')
    else:
        target.write_text(json.dumps(facts,indent=2)+'\n');target.chmod(0o444)
    return facts
def metadata(facts,task):
    value={'schema':'forge/safe-delivery/v1','task_id':facts['task_id'],'verdict':facts['verdict'],
           'gate_sha256':digest(home/'gates'/(facts['task_id']+'.json')),
           'calls_audited':facts.get('calls_audited',0)}
    if facts['verdict']=='pass':
        value.update(state='done',closed=True,result_path=task['result_path'],
                     native_sha256=facts['native_sha256'],snapshot_sha256=facts['snapshot_sha256'])
    else:
        value.update(state='quarantined',closed=True)
    return value
def main():
    global active_task
    args=make_parser().parse_args()
    if args.mode=='query':
        return query(args)
    manifest,policy=integrity()
    check(re.fullmatch(r't-[0-9a-f]{6}',args.task),'task_id')
    active_task=args.task
    directory=Path(policy['task_root'])/args.task;task=load(directory/'task.json')
    check(Path(task['task_dir']).resolve()==directory and task['task_id']==args.task,'task_identity')
    if args.mode=='wait-audit':
        check(1<=args.max_seconds<=120,'wait_bound')
        destination=home/'waits'/args.task;destination.mkdir(parents=True,exist_ok=True)
        argv=[sys.executable,str(Path(policy['bundle'])/'skills/agent-workers/scripts/agent-workers.py'),
              'wait',args.task,'--max-seconds',str(args.max_seconds)]
        began=time.time()
        try:
            proc=subprocess.run(argv,text=True,capture_output=True,timeout=args.max_seconds+20)
            raw={'argv':argv,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,
                 'started_at':began,'completed_at':time.time()}
        except subprocess.TimeoutExpired as exc:
            decode=lambda value:value.decode('utf-8',errors='replace') if isinstance(value,bytes) else str(value or '')
            raw={'argv':argv,'returncode':None,'stdout':decode(exc.stdout),'stderr':decode(exc.stderr),
                 'started_at':began,'completed_at':time.time()}
        (destination/(str(time.time_ns())+'.json')).write_text(json.dumps(raw,indent=2)+'\n')
        check(raw['returncode']==0,'wait_failed')
        delivered=[json.loads(line) for line in raw['stdout'].splitlines() if line.strip()]
        check(len(delivered)==1 and delivered[0].get('task_id')==args.task,'wait_identity')
        state=delivered[0].get('state')
        if state in ('running','starting','long_running'):
            return {'schema':'forge/safe-delivery/v1','task_id':args.task,'state':'pending','verdict':'pending','closed':False}
        check(state=='done' and delivered[0].get('closed') is True,'wait_not_done')
    return metadata(save_gate(args.task),task)
if __name__=='__main__':
    try:
        output=main()
    except Exception:
        output={'schema':'forge/safe-delivery/v1','verdict':'fail','state':'quarantined',
                'category':'scope_or_lifecycle_rejected'}
        if active_task:
            try:
                target=home/'gates'/(active_task+'.json')
                if not target.exists():
                    target.write_text(json.dumps(dict(output,task_id=active_task),indent=2)+'\n')
                    target.chmod(0o444)
            except Exception:
                pass
    print(json.dumps(output,sort_keys=True))
'''

SCOPE_GATE = inspect.getsource(local_git) + '\n' + inspect.getsource(reader_tree) + '\n' + SCOPE_GATE

class Run(core.Run):
    """Reuse the maintained lifecycle, never its scenario registry or evaluator."""

    def __init__(self, args):
        args.scenario = 'forge-bug-fix'
        super().__init__(args)
        self.branch = 'e2e/bug-fix-' + format(time.time_ns(), 'x')
        old_directory = self.directory
        self.directory.rename(self.directory.with_name(self.directory.name.replace('playbook-', 'forge-', 1)))
        self.directory = self.directory.with_name(self.directory.name.replace('playbook-', 'forge-', 1))
        if self.env['GIT_CONFIG_GLOBAL'] == str(old_directory / 'git-global.config'):
            self.env['GIT_CONFIG_GLOBAL'] = str(self.directory / 'git-global.config')
        self.env.update(XDG_CONFIG_HOME=str(self.directory / 'config'), XDG_STATE_HOME=str(self.directory / 'state'))
        self.task_root = self.directory / 'state/herdr-orchestrator/tasks'
        self.bundle = self.directory / 'bundle'
        self.artifacts = self.directory / 'artifacts'
        self.worktree = args.repo / 'handoff' / self.directory.name / 'worktree'
        self.probe = self.directory / 'cli-probe.py'
        self.stage_proof = {}
        self.base = None
        self.config_path = None
        self.original_fixture = None
        self.snapshot = {}
        self.pr = None
        self.scope = self.directory/'forge-scope'
        self.scope_helper = self.scope/'gateway.py'
        self.scope_hashes = {}
        self.worker_sessions = {}
        self.scope_facts = {}
        self.agent_dir = Path(self.env.get('PI_CODING_AGENT_DIR') or Path.home()/'.pi/agent').expanduser().resolve()

    def git(self, *args, repo=None, cleanup=False):
        return self.call(['git', '-C', repo or self.worktree, *args], cleanup=cleanup).strip()

    def forge(self, *args):
        # The independent oracle uses gh read-only. The controller resolves its
        # own single forge, including Origin preference, from the original text.
        return json.loads(self.call(['gh', *args]))

    def preflight(self):
        self.check('positive_deadline', self.args.max_seconds > 0)
        self.check('fixed_github_host',self.env.get('GH_HOST') in (None,'','github.com'))
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == self.args.repo)
        self.revision = self.git('rev-parse', 'HEAD', repo=self.args.repo)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.repo)
        self.hashes = identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_is_pi', self.spec.get('harness') == 'pi')
        self.role_workers = {}
        for role in ('bug-fix', 'how explainer', 'why investigators', 'why synthesizer'):
            selected = self.config.get('roles', {}).get(role)
            names = selected if isinstance(selected, list) else [selected]
            self.check('role_' + role.replace(' ', '_'), bool(names) and all(
                name in self.config['workers'] and self.config['workers'][name].get('harness') == 'pi' for name in names))
            self.role_workers[role] = names
        self.check('single_code_and_simple_how_worker', len(self.role_workers['bug-fix']) == len(self.role_workers['how explainer']) == 1)
        self.check('snapshot_investigator_roster_supported',1<=len(self.role_workers['why investigators'])<=2
                   and len(self.role_workers['why synthesizer'])==1)
        overrides=('--session','--session-dir','--session-id','--no-session','--continue','--resume','-c','-r')
        self.check('no_session_env_override',not self.env.get('PI_CODING_AGENT_SESSION_DIR'))
        self.check('absolute_existing_pi_agent_directory',
                   not self.env.get('PI_CODING_AGENT_DIR') or
                   Path(self.env['PI_CODING_AGENT_DIR']).expanduser().is_absolute())
        for worker in {name for names in self.role_workers.values() for name in names}:
            self.check('owned_worker_session_settings',not any(arg==flag or arg.startswith(flag+'=')
                for arg in self.config['workers'][worker].get('args',[]) for flag in overrides))
        for path in (self.agent_dir/'settings.json',self.args.fixture_repo/'.pi/settings.json'):
            if path.is_file():
                self.check('owned_cwd_session_directory',not core.read_json(path).get('sessionDir'))
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('fixture_clean', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        remote = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('forge_private_identity', remote.get('isPrivate') is True and remote.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        base_rows = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('remote_base_unique', len(base_rows) == 1)
        self.base = base_rows[0].split()[0]
        self.check('canonical_fixture_source', all(core.sha(self.args.fixture_repo / name)
                   == hashlib.sha256(content.encode()).hexdigest()
                   for name, content in dict(core.cases.LEDGER_FILES, **{'e2e_import.py': FIXTURE_ORACLE}).items()))
        self.check('exact_clean_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base
                   and core.sha(self.args.fixture_repo / 'storage.py') == BASE_STORAGE)
        bootstrap = self.forge('pr', 'view', '1', '--repo', self.args.forge_repo, '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('baseline_pr_retained_open', bootstrap.get('state') == 'OPEN' and bootstrap.get('headRefOid') == self.base
                   and bootstrap.get('headRefName') == self.args.base_ref and bootstrap.get('baseRefName') == 'main')
        self.bootstrap = bootstrap
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json', 'number,state,headRefName,baseRefName,isDraft')

    def capture_forge_snapshot(self):
        self.scope.mkdir()
        for name in ('requests','bindings','gates','waits'):
            (self.scope/name).mkdir()
        self.scope_helper.write_text(SCOPE_GATE)
        self.scope_helper.chmod(0o444)
        requests=[]
        repository=self.args.forge_repo
        prefix='/repos/'+repository
        # Use existing credentials only in root memory. No token enters a log,
        # model prompt, environment modification, snapshot or worker message.
        proc=subprocess.run(['gh','auth','token','--hostname','github.com'],env=self.env,
                            text=True,capture_output=True,timeout=max(1,min(30,self.deadline-time.monotonic())))
        self.check('snapshot_existing_credential',proc.returncode==0 and bool(proc.stdout.strip()))
        token=proc.stdout.strip()
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                return None
        opener=urllib.request.build_opener(NoRedirect())
        def request(endpoint):
            # All endpoints and page numbers are locally constructed. Never
            # follow Link headers, issue URLs, repository links or search leads.
            self.check('fixed_snapshot_endpoint',endpoint.startswith(prefix+'/')
                       and not any(word in endpoint for word in ('..','://','#','\n')))
            started=time.time()
            req=urllib.request.Request('https://api.github.com'+endpoint,headers={
                'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                'X-GitHub-Api-Version':'2022-11-28','User-Agent':'herdr-owned-fixture-snapshot'})
            with opener.open(req,timeout=max(1,min(60,self.deadline-time.monotonic()))) as response:
                self.check('snapshot_response_host',response.geturl()=='https://api.github.com'+endpoint)
                body=response.read(128*1024*1024+1)
                self.check('snapshot_response_bounded',len(body)<=128*1024*1024)
                raw=body.decode('utf-8')
            path=self.scope/'requests'/('%05d.json'%len(requests))
            path.write_text(raw)
            requests.append({'method':'GET','host':'api.github.com','endpoint':endpoint,
                             'started_at':started,'completed_at':time.time(),
                             'response_sha256':core.sha(path),'file':str(path.relative_to(self.scope))})
            return json.loads(raw)
        def pages(route,query=''):
            records=[]
            for number in range(1,1001):
                page=request(prefix+route+'?'+(query+'&' if query else '')+'per_page=100&page='+str(number))
                self.check('snapshot_page_is_array',isinstance(page,list) and len(page)<=100)
                if not page:
                    return records
                records.extend(page)
            raise Failure('snapshot_pagination_not_complete')
        issue_records=pages('/issues','state=all')
        self.check('exact_issue_repository_records',all(
            type(item.get('number')) is int and item['number']>0
            and item.get('repository_url','').lower()==('https://api.github.com'+prefix).lower()
            for item in issue_records))
        comments=[]
        for issue in (item for item in issue_records if 'pull_request' not in item):
            for comment in pages('/issues/'+str(issue['number'])+'/comments'):
                self.check('exact_comment_repository',comment.get('url','').lower().startswith(
                    ('https://api.github.com'+prefix+'/issues/comments/').lower()))
                comments.append(dict(comment,issue_number=issue['number']))
        labels=pages('/labels')
        self.check('exact_label_repository',all(item.get('url','').lower().startswith(
            ('https://api.github.com'+prefix+'/labels/').lower()) for item in labels))
        anchor=request(prefix+'/pulls/1')
        self.check('exact_pr1_anchor_repository',anchor.get('number')==1 and anchor.get('head',{}).get('sha')==self.base
                   and anchor.get('base',{}).get('repo',{}).get('full_name','').lower()==repository.lower()
                   and anchor.get('head',{}).get('repo',{}).get('full_name','').lower()==repository.lower())
        pr_comments=pages('/issues/1/comments')
        pr_reviews=pages('/pulls/1/reviews')
        pr_review_comments=pages('/pulls/1/comments')
        dataset={'issues':[item for item in issue_records if 'pull_request' not in item],
                 'comments':comments,'labels':labels,'pr':[anchor],
                 'pr-comments':pr_comments,'pr-reviews':pr_reviews,'pr-review-comments':pr_review_comments}
        (self.scope/'dataset.json').write_text(json.dumps(dataset,indent=2)+'\n')
        policy={'repository':repository,'host':'api.github.com','agent_dir':str(self.agent_dir),
                'task_root':str(self.task_root),'bundle':str(self.bundle),'worktree':str(self.worktree),
                'readers':list(map(str,self.readers)),
                'reader_trees':{str(path):reader_tree(path) for path in self.readers},
                'reader_trees_captured_at':time.time(),'roles':self.role_workers,
                'revisions':[self.base,self.args.base_ref,self.branch,'main'],
                'input_roots':[str(self.artifacts),*(str(self.directory/name) for name in (
                    'native-before','native-after','native-failing-suite','native-passing-suite'))],
                'config':str(self.directory/'config/herdr-orchestrator/workers.toml'),'config_sha256':self.config_hash,
                'workers':{name:{'provider':spec.get('provider'),'model':spec['model'],'effort':spec.get('effort'),
                                 'argv':horch.launch_args(spec,self.directory)}
                           for name,spec in self.config['workers'].items()},
                'bundle_sha256':{key:value for key,value in self.hashes.items() if key.startswith('skills/')}}
        (self.scope/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
        files={str(path.relative_to(self.scope)):core.sha(path)
               for path in [self.scope_helper,self.scope/'policy.json',self.scope/'dataset.json',
                            *(self.scope/'requests').glob('*.json')]}
        manifest={'schema':'forge/exact-repository-snapshot/v1','repository':repository,'host':'api.github.com',
                  'completed_at':time.time(),'fixture_revision':self.base,
                  'pagination':'fixed local page numbers through empty terminal page',
                  'requests':requests,'counts':{key:len(value) for key,value in dataset.items()},
                  'files':files,'driver_source_sha256':self.hashes,
                  'limitations':['Snapshot captured before dispatch; no live worker forge query.',
                                 'No external linked leads fetched. Original live-source Why eligibility unresolved.',
                                 'Capture spans completed REST requests; it is not a transactionally atomic live snapshot.']}
        (self.scope/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for name in [*files,'manifest.json']:
            (self.scope/name).chmod(0o444)
        self.scope_hashes={name:core.sha(self.scope/name) for name in [*files,'manifest.json']}

    def scan(self):
        rows=super().scan()
        if self.scope_hashes:
            if not all((self.scope/name).is_file() and core.sha(self.scope/name)==sha
                       for name,sha in self.scope_hashes.items()):
                raise Failure('owned_snapshot_or_gate_changed')
        for task,state in rows:
            path=self.scope/'gates'/(task['task_id']+'.json')
            if path.is_file() and core.read_json(path).get('verdict')!='pass':
                raise Failure('scope_gate_failed_report_quarantined')
            if task['task_id'] in self.worker_sessions or state.get('closed'):
                continue
            try:
                entry=self.herdr('agent','get',task['agent'])['agent']
            except Failure:
                continue
            if entry.get('pane_id')==task['pane_id'] and entry.get('agent_session',{}).get('value'):
                session=entry['agent_session']
                binding={'session':session,'captured_at':time.time(),
                         'task_sha256':core.sha(Path(task['task_dir'])/'task.json'),
                         'brief_sha256':core.sha(Path(task['task_dir'])/'brief.md')}
                destination=self.scope/'bindings'/(task['task_id']+'.json')
                destination.write_text(json.dumps(binding,indent=2)+'\n');destination.chmod(0o444)
                self.worker_sessions[task['task_id']]=session
        return rows

    def probe_run(self, repo, label, mode):
        output = self.directory / label
        value = json.loads(self.call([sys.executable, '-B', self.probe, '--repo', repo, '--output', output, '--mode', mode]))
        return value

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(PROBE)
        self.probe_hash = core.sha(self.probe)
        self.probe.chmod(0o444)
        self.check('baseline_reproduces_real_failure', observation_ok(self.probe_run(self.args.fixture_repo, 'independent-before', 'missing-field'), False))
        baseline_suite = self.probe_run(self.args.fixture_repo, 'independent-baseline-suite', 'e2e')
        self.check('existing_seven_flows_pass', baseline_suite.get('exit_code') == 0 and len((baseline_suite.get('suite') or {}).get('flows', [])) == 7)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        self.readers = []
        for number in range(4):
            path = self.worktree.parent / f'reader-{number}'
            self.git('worktree', 'add', '--detach', path, self.base, repo=self.args.fixture_repo)
            self.readers.append(path)
        self.capture_forge_snapshot()
        pi_env=(['--env','PI_CODING_AGENT_DIR='+self.env['PI_CODING_AGENT_DIR']]
                if self.env.get('PI_CODING_AGENT_DIR') else [])
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'forge-e2e', '--no-focus',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'],
                         '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                         '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'],
                         '--env', 'GIT_CONFIG_GLOBAL=' + self.env['GIT_CONFIG_GLOBAL'],
                         '--env', 'GH_CONFIG_DIR=' + self.env['GH_CONFIG_DIR'], *pi_env)
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        (self.directory / 'native-sessions').mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(self.directory / 'native-sessions')]
        self.controller_argv = flags
        self.check('controller_started', self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
                                                    '--timeout', '90000', '--', *flags).get('type') == 'agent_started')
        ready = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < ready:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and session.get('value') and entry.get('agent_status') in ('idle', 'done'):
                self.session = session
                break
            if entry.get('agent_status') == 'blocked':
                raise Failure('controller_start_blocked')
            time.sleep(1)
        else:
            raise Failure('controller_session_not_ready')
        self.check('controller_prompted', self.herdr('agent', 'prompt', self.agent, f'Read {brief} in full and execute it.',
                                                    '--wait', '--until', 'working', '--timeout', '30000').get('type') == 'agent_prompted')

    def prompt(self):
        return f'''Read {self.bundle / 'skills/poteto-mode/SKILL.md'} in full first. You are the
native lead controller for the original Bug fix playbook and its Opening a PR
stage, in a disclosed exact-repository SNAPSHOT investigation lane. Original
live-source Why and full original Bug fix eligibility remain UNRESOLVED; never
claim those workflows passed. The local fixture behavior and independently
complete Opening a PR stage can be verified separately. This post-execution,
pre-forwarding gate is NOT credential containment or a hard sandbox.
Read the required mapping and original playbook. Write the exact six-step
checklist to {self.artifacts / 'checklist.md'} before other work. Follow all six
steps. Evaluation tool protocol: call only the native read, bash, write, edit,
grep, find and ls tools directly. Do not use codemode or any tool wrapper;
nested tool results cannot be bound by this evaluator's native call/result audit.
This is an evidence constraint; preserve the configured harness, tool flags and
worker configuration. Put the same tool protocol in every worker brief.
Read every applied document in a separate full native read (no limit or offset)
or a literal cat of one file. Required documents: {json.dumps(list(READS))}
relative to {self.bundle / 'skills'}. Read deslop, no-comments, technical-writing,
unslop and principle-sequence-verifiable-units before the FIRST commit too.

Work in {self.worktree}, own branch {self.branch}, exact baseline {self.base}.
This is an explicitly authorized stacked child of the existing unmerged PR 1,
whose base branch is {self.args.base_ref}. Do not change PR 1 or main. You may push
ONLY {self.branch} to origin and create ONE ready PR with head {self.branch},
base {self.args.base_ref}, repository {self.args.forge_repo}. No other forge
writes, merges, auto-merge, babysit, trust answers, configuration changes, model
substitution, failure retries or native subagents. Preserve all worker flags.
Only controller forge discovery and OWN child PR creation/readback are authorized.
Investigators and all other workers have NO direct forge or network permission.
Root already captured the complete paginated exact-repo issue/comment/label
snapshot and PR1 anchor. No worker may broaden an empty result to owner/global/
cross-repository/host searches or fetch links; record broader leads without
fetching. All worker native calls, including failed attempts, are audited.
Resolve ONE forge
according to Opening a PR, recording actual Origin discovery/resolution or the
gh fallback in {self.artifacts / 'forge.json'} (object with forge and reason) before any PR operation. Read back
actual PR status after creation; request headRefName, baseRefName, headRefOid,
isDraft in JSON so the native result contains both branch names and full head SHA. Use full original PR writing/review guidance. Use standalone literal commands
for git commit, push, and forge create/view so native witnesses bind their outputs.
Use literal command -v origin for executable discovery (a missing-command
result is evidence, not an invitation to retry). For Origin creation put
--status open last. Do not chain commands. Use native read/grep/find/ls for
inspection; bash commands must be literal Git, resolved forge, command -v origin,
pwd, bundled agent-workers RUN only, the frozen snapshot gateway/wait-audit, or
external probe invocations. Direct agent-workers wait/list/stats and task-state inspection
can expose untrusted summary/question fields and are forbidden. Do not run interpreter inline
programs or other shell utilities in the controller. Git add names each owned
file explicitly (no add-all). Use Git diff without an --output argument.

Observed user bug: a missing discount_bp in the last row of the second input
file crashes import with KeyError, exit 1 and empty stdout. Expected: structured
JSON validation error, exit 2, unchanged persisted bytes. Existing state and
other valid rows must survive rollback. No injected source changes are needed.
The existing real CLI oracle e2e_import.py has seven flows and lacks this case.
Only source changes authorized: first extend e2e_import.py with an eighth flow
for late missing discount_bp by appending one tuple to rejected and changing
len(flows) == 7 to len(flows) == 8; keep all other existing oracle AST unchanged.
Use a missing-field row dict literal and row() calls with literal arguments,
without helper functions or executable expressions in the new tuple. Retain the
existing independent decimal oracle,
half-cent rows, multi-file, duplicate and rollback/export checks; then fix ONLY
storage.py apply_batch. Do not change money.py, cli.py or any other tracked file.

Observe the failing baseline probe result yourself BEFORE dispatching any how
or why investigation worker. Reproduce through control-cli with this immutable
external probe:
{self.probe}. Its --repo PATH --output NEW_EXTERNAL_DIRECTORY --mode missing-field
invokes the real CLI, emits actual exit/stdout/stderr and store hashes as JSON,
and returns zero even for a failed app. --mode e2e runs the real e2e_import.py and
emits actual suite output/receipt, also returning zero. Use standalone literal
python3 invocations, not shell wrappers. Do not modify or copy the probe or write
evidence.json. Use {self.directory / 'native-before'}, {self.directory / 'native-failing-suite'},
{self.directory / 'native-after'}, {self.directory / 'native-passing-suite'} as output
directories in that order. The driver independently replays both commit states.

Use simple how: one configured how explainer, no explorers, for the narrow
apply_batch field-validation question. Why: build an inline source/blame/history
anchor, including PR1 via this fixed local command:
python3 {self.scope_helper} query read pr --id 1
This gateway has list/search/read over ONLY the frozen captured dataset. It accepts
NO owner/repository/host/URL argument, makes NO network or forge subprocess query,
and does not follow links. Read capture provenance through the controller-owned
manifest {self.scope / 'manifest.json'}; disclose capture time and snapshot scope.
Record exactly seven original categories in {self.artifacts / 'coverage.json'}:
Source control history; Issue / ticket tracker; Long-form documents; Real-time
team chat; Infrastructure observability; Error / exception tracking; Product
analytics warehouse. Each object has category, available boolean, evidence,
reason, access='snapshot' or 'local-git' or 'unavailable'. First two are available
within this lane, even when Issues returns zero; all other five are unavailable
within this explicitly limited lane, not proof of absence across live systems.
Always run TWO separate fresh why investigators, using configured why workers
in order (reuse one if only one is configured). Source-control investigator
header Evidence category: Source control history; owns local Git log/blame plus PR1 snapshot read and literal list queries for
pr-comments, pr-reviews, pr-review-comments (even empty). Issues investigator header Evidence category: Issue / ticket tracker;
owns only gateway issues/comments/labels. It MUST run literal list issues,
list comments, list labels, and search issues --text <target terms>, even empty.
Use the original investigator template and all seven original report sections;
append the matching code-archaeology or adapted issue-source guidance and
incident-postmortem guidance for defensive validation. No external source access.
Each uses a distinct existing detached reader worktree.
Delegate separate configured synthesis ONLY after all investigators pass their
audit gates and all full reports have actually been read. Include the full
nonempty reports and null results plus all seven coverage entries in its brief.
Use the original synthesizer template and epistemics; preserve all eight
synthesis sections and its confidence language. Include its Confidence Summary
verbatim in the final private reply. Disclose snapshot-only source coverage;
original live-source Why eligibility is unresolved. After reading how and why reports and reproducing, write
{self.artifacts / 'diagnosis.json'} BEFORE any code-worker launch: hypotheses
(at least two objects with mechanism, status (eliminated or survives; exactly
one survives), runtime_evidence referencing actual observed output),
surviving_mechanism and scope_reason (single-function fix; architect
unnecessary). A short deterministic hunt needs no Cursor loop.

Write EVERY full worker brief with native write to a unique .md file under
{self.artifacts}, then pass that EXACT path as --brief on its one agent-workers run.
The last prelaunch brief mutation MUST be a native write of its complete final
content. If you edit it before launch, rewrite the complete final brief with
native write before run. Freeze the brief at launch; do not reuse or edit it
after launch. A task report/result/brief from the internal
task store or an external file is NEVER an allowed --brief input, even if no
native read occurred. Every run supplies exactly --brief, --cwd and --caller-pane.
Delegate all coding through {self.bundle / 'skills/agent-workers/scripts/agent-workers.py'};
pass --caller-pane {self.pane} on run. NEVER use direct agent-workers wait/list/stats.
For each started task, use this ONLY delivery command (real agent-workers wait runs
privately inside it, bounded to 120 seconds; pending permits continued waiting):
python3 {self.scope_helper} wait-audit --task TASK_ID --max-seconds 120
It suppresses ALL raw summary/files/question/error/stdout payload until the
worker is actually done+closed and its stable native transcript passes audit.
Only pass/done/closed metadata permits reading result.json and every listed
Markdown report fully, or quoting/forwarding any content into another brief.
On fail/quarantined/blocked, STOP without reading any result/report, launching
synthesis/coding, or opening a PR. Do not retry a failed gate/task or work around it.
Every worker brief MUST contain the exact lines:
Repository boundary: {self.args.forge_repo}
Host boundary: snapshot only; no direct network
Readers may native-read only their own cwd, bundled skills, own task dir and
already-audited report files, plus individually declared approved Input artifact
files. No OTHER controller artifacts/config/global paths.
Only literal bare git read commands (own cwd; no network/config overrides),
cat/sha256sum of owned files, pwd, fixed gateway QUERY commands or own canonical
cli.py/e2e_import.py may run. No inline interpreters/shell wrappers, direct
gh/origin/curl/wget/network commands or nested delegation, even failed attempts.
Every worker brief MUST state: use one literal Bash command per call. The parser
rejects newline, semicolon, pipe, ampersand, redirects, backticks, dollar signs
and backslashes, including inside quoted arguments. Do not combine commands:
pwd and a directory listing are separate calls. Use native Pi ls for listings;
bash ls is not supported. Filesystem paths must contain no tilde, including
~user home syntax; valid HEAD~ / HEAD^ Git ancestry remains supported.
Every worker brief MUST declare the supported local Git grammar: git with an
optional -C EXACT_OWN_CWD, then log/blame/show/diff/status/rev-parse/ls-files/
rev-list/diff-tree. Only owned paths and supplied local refs/HEAD/hashes are
accepted; no remote, config override, --no-index or external path. Allowed bare
flags are --oneline --follow -p --patch --stat --name-only --name-status --short
--porcelain --porcelain=v1 --no-patch --all --reverse --abbrev-commit --no-renames
--no-color --color=never --show-toplevel --show-prefix --no-commit-id -r --stage
-s --no-ext-diff --no-textconv --decorate --graph. Value flags -L (numeric range),
-n/--max-count (integer), --format/--pretty/-S/-G/--since/--until take one value;
equals forms --max-count= --format= --pretty= --since= --until= --unified= and
--grep=TEXT are accepted, as are numeric -N and -- before owned paths.
Controller and coding writers retain the original seven native tools only.
Every read-only worker brief MUST explicitly permit this narrow reader exception:
fffind(pattern: string, path?: string, exclude?: string|string[], limit?: integer)
ffgrep has those same fields plus caseSensitive?: boolean and context?: integer.
No cursor or other fields. limit must be positive; context must be nonnegative.
pattern is query text, not a root. path defaults to own cwd; it may be an own
absolute path or own relative path/glob such as **/**/storage.py. Reject home,
traversal (any .. component), backslashes, NUL, braces, commas, ! or leading -
in path. No surrounding whitespace or BOM characters: FFF trims paths before
root routing. It must resolve within EXACT_OWN_CWD. No auxiliary/external roots.
exclude is only a string/string-array filter. Readers may not write their tree.
This lane records symlink-free reader trees before dispatch and after delivery;
it assumes no external concurrent mutation between checks and is not a sandbox
or universal FFF support. Audit covers failed attempts too; no retry workaround.
Every worker brief MUST state these exact accepted application CLI forms:
python3 [-B] OWN_CWD/e2e_import.py --output OWN_TASK_SUBDIR
python3 [-B] OWN_CWD/cli.py import OWN_TASK_STORE INPUT [INPUT ...]
python3 [-B] OWN_CWD/cli.py export OWN_TASK_STORE
Here python may replace python3, and [-B] means one optional literal -B flag.
Scripts must resolve to that worker's own canonical cwd scripts. Output and
store paths must resolve strictly below its own task directory, never overlap
brief.md/task.json/state.json, and must not contain any of those protected files.
Each import input must resolve inside its own cwd/task directory or equal an
existing file explicitly declared by an Input artifact: ABSOLUTE_PATH line in
that brief. No wrappers, extra flags or input tokens starting with '-' are
accepted. These application commands cannot use the controller's script copy.
Source-control and Issues investigators must remain in their assigned category.
For each bug-fix brief include exactly one explicit line Allowed source: e2e_import.py
for the first writer, or Allowed source: storage.py for the second. Each brief's first nonblank line must be exactly Role: followed by one space
and its own configured role (bug-fix, how explainer, why investigators or why
synthesizer). Put this header before pasted findings, reports or configuration.
Each brief names its configured worker, selection reason, scope, success criteria,
and absolute references to
{self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'} and
{self.bundle / 'skills/poteto-mode/SKILL.md'}, and says: Do not delegate, use
native subagents, or run a whole playbook. Complete this assignment yourself.
Each worker writes ONLY report.md as its declared report and result.files MUST
equal ['report.md']; result.question is null. The gate validates this schema
but NEVER forwards model-authored summary/files/question in its delivery metadata. Optional local input files need explicit
Input artifact: ABSOLUTE_PATH lines in the assignment, limited to controller
artifacts and owned repro-output directories; no global/private config paths.
Configured roles: {json.dumps(self.role_workers)}. Reader tasks use distinct
existing detached worktrees {json.dumps(list(map(str, self.readers)))}; no reader
source writes. If additional discovered categories need more readers, create
distinct detached worktrees under {self.worktree.parent} at {self.base}.
This snapshot lane has exactly the two investigated categories; no extra readers
or broader data sources are authorized.
Exactly two fresh configured bug-fix workers serialize in {self.worktree}:
first changes only e2e_import.py with the missing-field case; wait/read/review,
run failing e2e probe yourself, then commit that failing repro BEFORE dispatching
the second worker. Second changes only storage.py/apply_batch. Retain the test
file exactly from the failing-test commit. Controller reviews/verifies/commits,
and never writes source. Keep exactly two ordered commits over the baseline,
first only e2e_import.py, second only storage.py. Follow deslop/no-comments and
technical-writing/unslop before committing/reviewing/opening the ready PR.
Review the actual diff. Run same-surface probe and full eight-flow suite yourself.
Write {self.artifacts / 'reply.md'} after actual PR readback and verified artifacts,
including what broke, mechanism, fix, verbatim failing and passing repro output,
actual PR URL and unmodified synthesis Confidence Summary. State this was the
snapshot fixture lane; never claim original live-source Why or full Bug fix pass. No raw transcripts or private artifacts in Git. On failure preserve
all artifacts and report blocked; do not work around the failed stage.
'''

    def native_events(self, path, include_errors=False):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        pending, events = {}, []
        for index, row in enumerate(rows):
            message = row.get('message', {})
            if message.get('role') == 'assistant':
                for block in message.get('content', []):
                    if block.get('type') == 'toolCall':
                        pending[block['id']] = (block['name'], block['arguments'], index, row.get('id'))
            if message.get('role') == 'toolResult':
                pair = pending.pop(message.get('toolCallId'), None)
                if pair and (message.get('isError') is False or include_errors):
                    events.append({'name': pair[0], 'args': pair[1], 'call_row': pair[2],
                                   'result_row': index, 'call_id': pair[3], 'result_id': row.get('id'),
                                   'output': core.text_content(message), 'successful': message.get('isError') is False})
        return events

    def event_probes(self, events, mode, fixed):
        matches = []
        for event in events:
            words = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if (len(words) != 8 or Path(words[0]).name not in ('python3', 'python')
                    or Path(words[1]).resolve() != self.probe or words[2] != '--repo'
                    or Path(words[3]).resolve() != self.worktree or words[4] != '--output'
                    or words[6:] != ['--mode', mode]):
                continue
            target = Path(words[5]).resolve()
            if self.directory not in target.parents:
                continue
            try:
                value = json.loads(event['output'])
                on_disk = core.read_json(target / 'observation.json')
            except (OSError, ValueError):
                continue
            expected = self.snapshot['final' if fixed else ('test' if mode == 'e2e' else 'base')]
            if value != on_disk or value.get('source_sha256') != expected:
                continue
            if (observation_ok(value, fixed) if mode == 'missing-field' else suite_ok(value, fixed)):
                matches.append(event)
        return matches

    def run_brief(self, argv):
        if len(argv)!=10 or argv[2]!='run' or argv[3] not in {
                worker for workers in self.role_workers.values() for worker in workers}:
            return None
        pairs=list(zip(argv[4::2],argv[5::2]))
        if len(pairs)!=3 or {key for key,_ in pairs}!={'--brief','--cwd','--caller-pane'}:
            return None
        options=dict(pairs)
        source=(self.worktree/options['--brief']).resolve()
        cwd=(self.worktree/options['--cwd']).resolve()
        if (self.artifacts not in source.parents or source.suffix!='.md'
                or cwd not in {self.worktree,*self.readers} or options['--caller-pane']!=self.pane):
            return None
        return source

    def controller_command_allowed(self, command):
        """Constrain lead mutations to Git staging/commits and owned PR delivery."""
        argv = literal(command)
        if not argv:
            return False
        binary = Path(argv[0]).name if argv[0]==sys.executable else argv[0]
        if binary in ('python', 'python3'):
            if len(argv) < 3:
                return False
            script = (self.worktree / argv[1]).resolve()
            if script == self.probe:
                expected={'native-before':'missing-field','native-after':'missing-field',
                          'native-failing-suite':'e2e','native-passing-suite':'e2e'}
                return (len(argv)==8 and argv[2:3]==['--repo'] and Path(argv[3]).resolve()==self.worktree
                        and argv[4]=='--output' and argv[6]=='--mode' and any(
                            Path(argv[5]).resolve()==self.directory/name and argv[7]==mode
                            for name,mode in expected.items()))
            if script == self.scope_helper:
                return self.scope_command(argv) is not None
            return (script == self.bundle / 'skills/agent-workers/scripts/agent-workers.py'
                    and self.run_brief(argv) is not None)
        if binary == 'git':
            rest = argv[1:]
            if rest[:1] == ['-C'] and len(rest) > 2:
                if Path(rest[1]).resolve() != self.worktree:
                    return False
                rest = rest[2:]
            if not rest:
                return False
            operation = rest[0]
            if operation in ('status','diff','show','log','blame','rev-parse','rev-list','ls-files','diff-tree'):
                return local_git(argv,self.worktree,[self.base,self.args.base_ref,self.branch,'main']) is not None
            if operation == 'ls-remote':
                return rest[1:] in (['--heads','origin'],['origin'])
            if operation == 'branch':
                return rest[1:] == ['--show-current']
            if operation == 'remote':
                return rest[1:] == ['get-url', 'origin']
            if operation == 'add':
                files = [word for word in rest[1:] if word != '--']
                return bool(files) and all(word in ('storage.py', 'e2e_import.py') for word in files)
            if operation=='commit':
                return len(rest)==3 and rest[1]=='-m' and bool(rest[2])
            if operation=='push':
                return rest[1:] in (['origin',self.branch],['-u','origin',self.branch],
                                    ['--set-upstream','origin',self.branch])
            return False
        if binary in ('gh', 'origin'):
            if argv[1:3] == ['repo','view']:
                return len(argv)>3 and argv[3]==self.args.forge_repo
            if argv[1:3] not in (['pr','view'],['pr','create']):
                return False
            return ('--repo' in argv and argv.index('--repo')+1<len(argv)
                    and argv[argv.index('--repo')+1]==self.args.forge_repo)
        if binary == 'cat':
            return len(argv) == 2 and not argv[1].startswith('-')
        return argv in (['command', '-v', 'origin'], ['which', 'origin'], ['pwd'])

    def scope_command(self, argv):
        if argv[:2] not in (['python3',str(self.scope_helper)],['python',str(self.scope_helper)],
                            [sys.executable,str(self.scope_helper)]):
            return None
        if len(argv)==7 and argv[2:3]==['wait-audit'] and argv[3]=='--task' and argv[5]=='--max-seconds':
            if horch.TASK_ID_RE.fullmatch(argv[4]) and argv[6].isdigit() and 1<=int(argv[6])<=120:
                return 'wait-audit',argv[4],int(argv[6])
        if len(argv)>=5 and argv[2]=='query' and argv[3] in ('list','search','read'):
            kinds=('issues','comments','labels','pr','pr-comments','pr-reviews','pr-review-comments')
            if argv[4] not in kinds:
                return None
            if argv[3]=='list' and len(argv)==5:
                return 'query',argv[4],None
            if argv[3]=='search' and len(argv)==7 and argv[5]=='--text':
                return 'query',argv[4],argv[6]
            if argv[3]=='read' and len(argv)==7 and argv[5]=='--id' and argv[6].isdigit():
                return 'query',argv[4],int(argv[6])
        return None

    def verify_scope_delivery(self, rows):
        # Do not read a worker result/report here until every independently
        # rerun native audit has passed. Raw wait payload stays in this process.
        self.check('snapshot_gate_integrity',bool(self.scope_hashes) and all(
            (self.scope/name).is_file() and core.sha(self.scope/name)==sha for name,sha in self.scope_hashes.items()))
        paths=list((self.directory/'native-sessions').glob('*.jsonl'))
        self.check('one_scoped_controller_session',len(paths)==1)
        path=paths[0]
        tasks=[task for task,_ in rows]
        self.native=core.audit_pi(path,self.session,self.worktree,self.wall_started,self.spec,
                                 [self.bundle/'skills'/p for p in READS],[],[],self.bundle)
        self.check('controller_native_identity_model_guidance',all(c['ok'] for c in self.native['checks']))
        events=self.native_events(path)
        all_events=self.native_events(path,include_errors=True)
        self.check('controller_literal_scope_before_payload_consumption',all(
            self.controller_command_allowed(e['args'].get('command','')) for e in all_events if e['name']=='bash'))
        self.check('controller_writes_only_assigned_artifacts',all(
            isinstance(e['args'].get('path'),str)
            and self.artifacts in (self.worktree/e['args']['path']).resolve().parents
            for e in all_events if e['name'] in ('write','edit')))
        launches,_=core.workflow_launches(events,tasks,self.worktree,self.bundle)
        self.check('all_owned_launches_bound',set(launches)=={task['task_id'] for task in tasks})
        run_events=[event for event in all_events if
                    (core.literal_horch_command(event['name'],event['args'],self.worktree,self.bundle) or [None])[0]=='run']
        self.check('every_native_run_bound_once',len(run_events)==len(tasks)
                   and all(event in launches.values() for event in run_events))
        sources=set()
        for task in tasks:
            launch=launches[task['task_id']]
            argv=literal(launch['args'].get('command',''))
            source=self.run_brief(argv)
            self.check('unique_controller_authored_brief_path',source is not None and source not in sources)
            sources.add(source)
            writes=core.workflow_writes(events,self.worktree,source,before=launch['call_row'],final=True)
            expected=source.read_text().rstrip('\n')+'\n\n'+horch.WORKER_RULES.format(
                result_path=Path(task['task_dir'])/'result.json',task_id=task['task_id'],nonce=task['nonce'])
            self.check('native_full_brief_content_bound_before_launch',bool(writes)
                       and Path(task['brief_path']).read_text()==expected
                       and all(event['result_row']<launch['call_row'] for event in all_events
                           if event['name'] in ('write','edit') and isinstance(event['args'].get('path'),str)
                           and (self.worktree/event['args']['path']).resolve()==source))
        native_rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        deliveries={}
        audited={}
        for task in tasks:
            # The frozen helper emits fixed codes/counts/hashes only. It audits
            # complete failed calls as well as successful ones before any read.
            value=json.loads(self.call([sys.executable,self.scope_helper,'audit','--task',task['task_id']]))
            self.check('independent_worker_scope_gate',value.get('verdict')=='pass'
                       and value.get('task_id')==task['task_id'] and value.get('state')=='done')
            facts=core.read_json(self.scope/'gates'/(task['task_id']+'.json'))
            self.check('gate_bound_snapshot_task_and_model',facts['snapshot_sha256']==self.scope_hashes['dataset.json']
                       and facts['manifest_sha256']==self.scope_hashes['manifest.json']
                       and facts['policy_sha256']==self.scope_hashes['policy.json']
                       and facts['task_sha256']==core.sha(Path(task['task_dir'])/'task.json')
                       and facts['brief_sha256']==core.sha(Path(task['task_dir'])/'brief.md')
                       and facts['binding_sha256']==core.sha(self.scope/'bindings'/(task['task_id']+'.json')))
            receipts=[]
            matched=set()
            wait_events=[]
            for event in all_events:
                argv=literal(event['args'].get('command','')) if event['name']=='bash' else []
                operation=self.scope_command(argv)
                if not operation or operation[0]!='wait-audit' or operation[1]!=task['task_id']:
                    continue
                self.check('no_failed_native_wait_wrapper',event['successful'])
                output=json.loads(event['output'])
                allowed={'schema','task_id','verdict','gate_sha256','calls_audited','state','closed','result_path',
                         'native_sha256','snapshot_sha256'}
                self.check('no_untrusted_wait_payload_forwarded',set(output)<=allowed
                           and output.get('schema')=='forge/safe-delivery/v1' and output.get('task_id')==task['task_id']
                           and output.get('verdict') in ('pass','pending'))
                start=core.stamp(native_rows[event['call_row']]['timestamp'])
                end=core.stamp(native_rows[event['result_row']]['timestamp'])
                candidates=[]
                for receipt in (self.scope/'waits'/task['task_id']).glob('*.json'):
                    raw=core.read_json(receipt)
                    if (receipt not in matched and start-.05<=raw['started_at']<=raw['completed_at']<=end+.05):
                        candidates.append((receipt,raw))
                self.check('actual_horch_wait_receipt_unique',len(candidates)==1)
                receipt,raw=candidates[0];matched.add(receipt)
                self.check('actual_private_horch_wait_argv_and_success',raw.get('returncode')==0
                           and len(raw['argv'])==6 and Path(raw['argv'][0]).name.startswith('python')
                           and raw['argv'][1:]==[str(self.bundle/'skills/agent-workers/scripts/agent-workers.py'),
                               'wait',task['task_id'],'--max-seconds',str(operation[2])])
                raw_lines=[json.loads(line) for line in raw['stdout'].splitlines() if line.strip()]
                self.check('actual_wait_single_owned_task',len(raw_lines)==1 and raw_lines[0].get('task_id')==task['task_id'])
                if output['verdict']=='pass':
                    self.check('actual_done_closed_before_audit_delivery',raw_lines[0].get('state')=='done'
                               and raw_lines[0].get('closed') is True and output==value)
                    wait_events.append(event)
                else:
                    self.check('pending_does_not_forward_data',output=={
                        'schema':'forge/safe-delivery/v1','task_id':task['task_id'],
                        'state':'pending','verdict':'pending','closed':False})
                receipts.append(core.sha(receipt))
            self.check('one_audited_delivery_no_extra_wait_receipts',len(wait_events)==1 and
                       len(matched)==len(list((self.scope/'waits'/task['task_id']).glob('*.json'))))
            deliveries[task['task_id']]=wait_events[0]
            audited[task['task_id']]=facts
            self.scope_facts[hashlib.sha256(task['task_id'].encode()).hexdigest()]={
                'verdict':'pass','native_sha256':facts['native_sha256'],'calls_audited':facts['calls_audited'],
                'gate_sha256':value['gate_sha256'],'brief_sha256':facts['brief_sha256'],
                'binding_sha256':facts['binding_sha256'],'wait_receipt_sha256':receipts}
        # Only trusted fixed-path metadata was consumed above. Now prove every
        # attempted lead artifact access, including failed reads, followed gate.
        for event in all_events:
            if event['name'] not in ('read','grep','find','ls','bash'):
                continue
            target=core.read_target(event['name'],event['args'],self.worktree)
            argv=literal(event['args'].get('command','')) if event['name']=='bash' else []
            if argv and (self.scope_command(argv) or core.literal_horch_command(
                    event['name'],event['args'],self.worktree,self.bundle)):
                continue
            raw=event['args'].get('path') if event['name']!='bash' else None
            if target is None and isinstance(raw,str):
                target=(self.worktree/raw).resolve()
            if target is None:
                self.check('no_opaque_task_artifact_access',not any(
                    task['task_dir'] in json.dumps(event['args']) or task['task_id'] in json.dumps(event['args']) for task in tasks))
                continue
            owned_roots=[self.worktree,self.bundle,self.artifacts,self.args.fixture_repo,*self.readers,
                         *(self.directory/name for name in ('native-before','native-after',
                           'native-failing-suite','native-passing-suite'))]
            owned_files={self.probe,self.scope_helper,self.scope/'manifest.json',
                         self.directory/'controller-brief.md',
                         self.directory/'config/herdr-orchestrator/workers.toml'}
            self.check('controller_read_path_owned',target in owned_files or any(
                target==root or root in target.parents for root in owned_roots)
                or any(target==Path(task['task_dir']) or Path(task['task_dir']) in target.parents for task in tasks))
            for task in tasks:
                directory=Path(task['task_dir'])
                accesses=(directory==target or directory in target.parents or target in directory.parents)
                if accesses and target not in (directory/'brief.md',directory/'task.json'):
                    self.check('all_payload_access_after_passing_scope_gate',
                               event['call_row']>deliveries[task['task_id']]['result_row'])
            protected=(self.scope/'waits',self.scope/'bindings')
            self.check('raw_delivery_and_identity_never_read_by_lead',not any(
                target==root or root in target.parents or target in root.parents for root in protected))
        # After all gates pass, reading report content for ordering/forwarding is safe.
        def strings(value):
            if isinstance(value,str):
                yield value
            elif isinstance(value,dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value,list):
                for item in value:
                    yield from strings(item)
        for task in tasks:
            facts=audited[task['task_id']]
            for filename in facts['reports']:
                content=Path(filename).read_text().strip()
                for event in all_events:
                    if event['name'] in ('write','edit') and content and any(
                            content in value for value in strings(event['args'])):
                        self.check('no_payload_in_new_brief_before_audit',
                                   event['call_row']>deliveries[task['task_id']]['result_row'])
        self.stage('scope_gate_before_all_worker_payload_consumption',list(deliveries.values()))
        return path,events,all_events,launches,deliveries,audited

    def stage(self, name, events, condition=True):
        self.check('native_' + name, condition and bool(events))
        self.stage_proof[name] = [{'call_row': e['call_row'], 'result_row': e['result_row'],
                                   'call_id_sha256': hashlib.sha256(str(e['call_id']).encode()).hexdigest(),
                                   'result_id_sha256': hashlib.sha256(str(e['result_id']).encode()).hexdigest(),
                                   'output_sha256': hashlib.sha256(e['output'].encode()).hexdigest()}
                                  for e in events]

    def verify(self):
        rows = self.scan()
        path,events,all_events,scope_launches,scope_deliveries,scope_audits=self.verify_scope_delivery(rows)
        self.check('tasks_delivered_closed', bool(rows) and all(s.get('state') == 'done' and s.get('closed') is True for _, s in rows))
        self.check('probe_immutable', core.sha(self.probe) == self.probe_hash)
        self.check('feature_clean', not self.git('status', '--porcelain=v1', '--untracked-files=all'))
        self.check('feature_branch', self.git('branch', '--show-current') == self.branch)
        commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('two_ordered_commits', len(commits) == 2 and self.git('rev-parse', commits[0] + '^') == self.base
                   and self.git('rev-parse', commits[1] + '^') == commits[0])
        self.commits = commits
        self.check('test_only_first_commit', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commits[0]).splitlines() == ['e2e_import.py'])
        self.check('storage_only_second_commit', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commits[1]).splitlines() == ['storage.py'])
        self.check('single_function_scope', outside_function(self.git('show', self.base + ':storage.py')) == outside_function((self.worktree / 'storage.py').read_text()))
        self.check('small_fix', len(self.git('diff', '--unified=0', commits[0], commits[1], '--', 'storage.py').splitlines()) <= 45)
        self.check('test_frozen_after_failure', self.git('rev-parse', commits[0] + ':e2e_import.py') == self.git('rev-parse', commits[1] + ':e2e_import.py'))
        self.check('existing_oracle_retained', retained_oracle(
            self.git('show', self.base + ':e2e_import.py'), (self.worktree / 'e2e_import.py').read_text()))
        for label, revision in (('base', self.base), ('test', commits[0]), ('final', commits[1])):
            directory = self.directory / ('snapshot-' + label)
            directory.mkdir()
            for name in ('cli.py', 'storage.py', 'money.py', 'e2e_import.py'):
                data = subprocess.run(['git', '-C', str(self.worktree), 'show', revision + ':' + name],
                                      capture_output=True, timeout=20, check=True).stdout
                (directory / name).write_bytes(data)
            self.snapshot[label] = {name: core.sha(directory / name) for name in ('cli.py', 'storage.py', 'money.py', 'e2e_import.py')}
        self.check('baseline_snapshot_reproduces', observation_ok(self.probe_run(self.directory / 'snapshot-base', 'replay-baseline', 'missing-field'), False))
        self.check('committed_repro_fails', suite_ok(self.probe_run(self.directory / 'snapshot-test', 'replay-failing-suite', 'e2e'), False))
        self.check('final_original_repro_passes', observation_ok(self.probe_run(self.directory / 'snapshot-final', 'replay-fixed', 'missing-field'), True))
        self.check('final_eight_flows_pass', suite_ok(self.probe_run(self.directory / 'snapshot-final', 'replay-passing-suite', 'e2e'), True))
        self.check('runtime_source_matches_commits', all(core.sha(self.worktree / name) == digest for name, digest in self.snapshot['final'].items()))
        tasks = [task for task, _ in rows]
        self.task_facts = []
        for task in tasks:
            worker = self.config['workers'].get(task.get('worker'), {})
            self.check('task_configuration_binding', task.get('model') == worker.get('model') and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir']))
                       and Path(task.get('result_path', '')).resolve() == Path(task['task_dir']) / 'result.json')
            result = core.read_json(Path(task['result_path']))
            self.check('task_nonce_and_result_binding', horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed')
            brief = Path(task['brief_path']).read_text()
            role_header = re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)', brief)
            own_role = role_header[1] if role_header else None
            self.check('bounded_worker_role_header', own_role in self.role_workers
                       and task['worker'] in self.role_workers[own_role])
            self.check('bounded_worker_brief', all(word in brief for word in (task['worker'], 'Do not delegate',
                       str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'),
                       str(self.bundle / 'skills/poteto-mode/SKILL.md'))) and bool(re.search(r'reason|because', brief, re.I)))
            self.task_facts.append({'task_id_sha256': hashlib.sha256(task['task_id'].encode()).hexdigest(),
                                    'model': task.get('model'), 'effort': worker.get('effort'), 'harness': task.get('harness'),
                                    'task_sha256': core.sha(Path(task['task_dir']) / 'task.json'),
                                    'result_sha256': core.sha(Path(task['result_path'])), 'nonce_validated': True})
        # Specialized safe-wrapper delivery proof above replaces the shared
        # direct-horch-wait assumption; model/session/guidance audit is retained.
        source_roots = {self.worktree, self.args.fixture_repo,
                        *(Path(task['cwd']).resolve() for task in tasks)}
        source_paths = {root / name for root in source_roots
                        for name in ('storage.py', 'e2e_import.py', 'cli.py', 'money.py')}
        self.check('controller_does_not_write_source', all(
            isinstance(event['args'].get('path'), str)
            and (self.worktree / event['args']['path']).resolve() not in source_paths
            for event in all_events if event['name'] in ('write', 'edit')))
        self.check('lead_mutations_within_authorization', all(
            self.controller_command_allowed(e['args'].get('command', ''))
            for e in all_events if e['name'] == 'bash'))
        launches, deliveries = scope_launches,scope_deliveries
        self.check('all_native_launches_bound', set(launches) == {t['task_id'] for t in tasks})
        report_reads = {task['task_id']: core.workflow_report_reads(events, task, self.worktree,
                        deliveries.get(task['task_id'])) for task in tasks}
        self.check('all_delivered_reports_read', all(report_reads.values()))
        full_result_reads = [core.workflow_reads(events, self.worktree, Path(t['result_path']),
                             after=deliveries[t['task_id']]['result_row']) for t in tasks]
        self.check('all_delivered_results_read', all(full_result_reads))
        before = self.event_probes(events, 'missing-field', False)
        after = self.event_probes(events, 'missing-field', True)
        failing = self.event_probes(events, 'e2e', False)
        passing = self.event_probes(events, 'e2e', True)
        checklist = core.workflow_writes(events, self.worktree, self.artifacts / 'checklist.md')
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/bug-fix.md').read_text(), re.M)
        checklist = [e for e in checklist if re.findall(r'^\d+\. (.+)$', e['args']['content'], re.M) == steps]
        first_launch = min(e['call_row'] for e in launches.values())
        initial_reads = []
        for resource in ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
                         'pstack-herdr/references/herdr-tools.md', 'poteto-mode/playbooks/bug-fix.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource,
                                        before=checklist[0]['call_row'] if checklist else -1)
            self.check('initial_read_' + resource.replace('/', '_'), bool(reads))
            initial_reads.extend(reads)
        self.stage('bug_fix_1', initial_reads + before + checklist, bool(before and checklist)
                   and checklist[0]['result_row'] < min(before[0]['call_row'], first_launch)
                   and before[0]['result_row'] < first_launch)
        writers = [t for t in tasks if Path(t['cwd']).resolve() == self.worktree]
        writers.sort(key=lambda t: launches[t['task_id']]['call_row'])
        self.check('two_configured_serial_writers', len(writers) == 2 and all(
            t['worker'] == self.role_workers['bug-fix'][0]
            and re.match(r'\A\s*Role: bug-fix(?:\r?\n|\Z)', Path(t['brief_path']).read_text())
            for t in writers)
                   and deliveries[writers[0]['task_id']]['result_row'] < launches[writers[1]['task_id']]['call_row'])
        readers = [t for t in tasks if t not in writers]
        self.check('distinct_detached_readers', len({t['cwd'] for t in readers}) == len(readers) and all(
            Path(t['cwd']).resolve().parent == self.worktree.parent and not self.git('status', '--porcelain=v1', '--untracked-files=all', repo=t['cwd'])
            and self.git('rev-parse', 'HEAD', repo=t['cwd']) == self.base for t in readers))
        reader_roles = {}
        for role in ('how explainer', 'why investigators', 'why synthesizer'):
            matched = [t for t in readers if re.match(
                r'\A\s*Role: ' + re.escape(role) + r'(?:\r?\n|\Z)',
                Path(t['brief_path']).read_text()) and t['worker'] in self.role_workers[role]]
            self.check('native_role_' + role.replace(' ', '_'), bool(matched) and set(t['worker'] for t in matched) == set(self.role_workers[role]))
            reader_roles[role] = matched
        self.check('simple_how_route', len(reader_roles['how explainer']) == 1)
        investigators=reader_roles['why investigators']
        self.check('two_real_snapshot_investigation_categories',len(investigators)==2
                   and {scope_audits[t['task_id']]['category'] for t in investigators}==
                       {'Source control history','Issue / ticket tracker'})
        original_sections=['Source','What I Searched','Direct Evidence Found','Indirect / Circumstantial Evidence',
                           'Contradictions','Gaps','Additional Leads']
        for task in investigators:
            text=Path(task['task_dir']).joinpath('report.md').read_text()
            sections=re.findall(r'^#{2,3} (.+)$',text,re.M)
            self.check('original_seven_investigator_sections',[head for head in sections if head in original_sections]==original_sections)
        synth=reader_roles['why synthesizer'][0]
        assignment=Path(synth['brief_path']).read_text().split('## Worker rules',1)[0]
        self.check('separate_synthesis_full_audited_findings',all(
            Path(task['task_dir']).joinpath('report.md').read_text().strip() in assignment for task in investigators)
            and str(self.bundle/'skills/why/references/epistemics.md') in assignment)
        synthesis=Path(synth['task_dir']).joinpath('report.md').read_text()
        synthesis_sections=['The Question','The Code in Question','What We Found','What We Can Reasonably Infer',
                            'Competing Hypotheses',"What We Don't Know",'Sources Consulted','Confidence Summary']
        self.check('original_synthesis_confidence_separation',
                   [head for head in re.findall(r'^#{2,3} (.+)$',synthesis,re.M) if head in synthesis_sections]==synthesis_sections)
        confidence=re.split(r'^#{2,3} Confidence Summary\s*$',synthesis,flags=re.M)[-1].strip()
        self.check('confidence_language_preserved_in_private_reply',bool(confidence)
                   and confidence in (self.artifacts/'reply.md').read_text()
                   and 'snapshot' in (self.artifacts/'reply.md').read_text().lower())
        for role, resource in (('how explainer', 'how/SKILL.md'), ('why investigators', 'why/SKILL.md')):
            self.check('skill_before_' + role.replace(' ', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource,
                before=min(launches[t['task_id']]['call_row'] for t in reader_roles[role]))))
        synthesis_start = min(launches[t['task_id']]['call_row'] for t in reader_roles['why synthesizer'])
        self.check('why_synthesis_after_reports', all(max(e['result_row'] for e, _ in report_reads[t['task_id']]) < synthesis_start
                   for t in reader_roles['why investigators']))
        diagnosis = core.workflow_writes(events, self.worktree, self.artifacts / 'diagnosis.json', before=launches[writers[0]['task_id']]['call_row'], final=True)
        coverage = core.workflow_writes(events, self.worktree, self.artifacts / 'coverage.json', before=synthesis_start, final=True)
        data = core.read_json(self.artifacts / 'diagnosis.json')
        hypotheses = data.get('hypotheses', [])
        self.check('competing_runtime_hypotheses', len(hypotheses) >= 2 and all(isinstance(h, dict) and h.get('mechanism') and h.get('runtime_evidence') for h in hypotheses)
                   and sum(h.get('status') == 'survives' for h in hypotheses) == 1
                   and all(h.get('status') in ('survives', 'eliminated') for h in hypotheses)
                   and bool(data.get('surviving_mechanism')) and bool(data.get('scope_reason')))
        categories = core.read_json(self.artifacts / 'coverage.json')
        self.check('why_seven_evidence_categories', isinstance(categories, list) and len(categories) == 7
                   and len({c.get('category') for c in categories}) == 7 and all(type(c.get('available')) is bool
                   and c.get('reason') and (not c['available'] or c.get('evidence')) for c in categories))
        original_categories={'Source control history','Issue / ticket tracker','Long-form documents',
            'Real-time team chat','Infrastructure observability','Error / exception tracking','Product analytics warehouse'}
        self.check('honest_snapshot_seven_category_disclosure',
                   {c['category'] for c in categories}==original_categories and all(
                       c['available']==(c['category'] in ('Source control history','Issue / ticket tracker'))
                       and c.get('access')==('local-git' if c['category']=='Source control history' else
                           'snapshot' if c['category']=='Issue / ticket tracker' else 'unavailable')
                       and c['category'] in assignment for c in categories))
        self.stage('snapshot_why_categories_and_separate_confidence_synthesis',
                   [scope_deliveries[t['task_id']] for t in investigators+[synth]])
        history = []
        anchor_pr = []
        for event in events:
            argv = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if argv and argv[0] == 'git' and any(word in argv for word in ('blame', 'log')) and 'storage.py' in argv and event['output'].strip():
                history.append(event)
            if (argv in (['python3',str(self.scope_helper),'query','read','pr','--id','1'],
                          ['python',str(self.scope_helper),'query','read','pr','--id','1'])
                    and event['output'].strip()):
                observed=json.loads(event['output'])
                self.check('actual_pr1_snapshot_anchor',observed.get('snapshot_sha256')==self.scope_hashes['dataset.json']
                           and observed.get('count')==1 and observed.get('kind')=='pr')
                anchor_pr.append(event)
        investigator_start = min(launches[t['task_id']]['call_row'] for t in reader_roles['why investigators'])
        self.check('why_runtime_anchor_before_investigators',
                   bool(anchor_pr) and {kind for kind in ('blame', 'log') if any(
                       kind in literal(e['args']['command']) and e['result_row'] < investigator_start for e in history)} == {'blame', 'log'}
                   and anchor_pr[0]['result_row'] < investigator_start)
        self.stage('bug_fix_2', diagnosis + coverage + history,
                   bool(diagnosis and coverage and history) and bool(before)
                   and before[0]['result_row'] < diagnosis[0]['call_row']
                   and all(max(e['result_row'] for e, _ in report_reads[t['task_id']]) < diagnosis[0]['call_row'] for t in readers))
        self.stage('bug_fix_3', [launches[t['task_id']] for t in writers], bool(diagnosis))
        self.stage('bug_fix_4', after + passing, bool(after and passing) and deliveries[writers[1]['task_id']]['result_row'] < min(after[0]['call_row'], passing[0]['call_row']))
        commit_events = []
        push_events = []
        create_events = []
        view_events = []
        for event in events:
            argv = literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if not argv:
                continue
            if argv[0] == 'git' and 'commit' in argv:
                commit_events.append(event)
            if argv[0] == 'git' and 'push' in argv:
                push_events.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'create']:
                create_events.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']:
                view_events.append(event)
        self.check('writer_reports_before_verification', bool(failing and passing) and all(
            max(e['result_row'] for e, _ in report_reads[t['task_id']]) < boundary
            for t, boundary in ((writers[0], failing[0]['call_row']), (writers[1], passing[0]['call_row']))))
        self.stage('bug_fix_5', failing + commit_events, bool(failing) and len(commit_events) == 2
                   and deliveries[writers[0]['task_id']]['result_row'] < failing[0]['call_row']
                   and failing[0]['result_row'] < commit_events[0]['call_row']
                   and commits[0][:7] in commit_events[0]['output']
                   and commit_events[0]['result_row'] < launches[writers[1]['task_id']]['call_row']
                   and bool(passing) and passing[0]['result_row'] < commit_events[1]['call_row']
                   and commits[1][:7] in commit_events[1]['output'])
        guidance = []
        for resource in ('deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md', 'principle-sequence-verifiable-units/SKILL.md'):
            reads = core.workflow_reads(events, self.worktree, self.bundle / 'skills' / resource, before=commit_events[0]['call_row'])
            self.check('pr_guidance_before_commit_' + resource.split('/')[0], bool(reads))
            guidance.extend(reads)
        forge_notes = core.workflow_writes(events, self.worktree, self.artifacts / 'forge.json', final=True)
        forge = core.read_json(self.artifacts / 'forge.json')
        self.check('resolved_one_forge', forge.get('forge') in ('gh', 'origin') and forge.get('reason'))
        selected = forge['forge']
        discovery = [e for e in self.native_events(path, include_errors=True)
                     if e['name'] == 'bash' and e['result_row'] < min(
                         [item['call_row'] for item in create_events + view_events])
                     and literal(e['args'].get('command', '')) in (['command', '-v', 'origin'], ['which', 'origin'])]
        self.check('actual_forge_discovery', bool(discovery))
        if selected == 'origin':
            self.check('origin_discovery_resolves', discovery[0]['successful'] and bool(discovery[0]['output'].strip()))
        elif discovery[0]['successful'] and discovery[0]['output'].strip():
            failed_origin = [e for e in self.native_events(path, include_errors=True)
                             if e['name'] == 'bash' and literal(e['args'].get('command', ''))[:1] == ['origin']
                             and not e['successful'] and e['result_row'] < min(item['call_row'] for item in create_events + view_events)]
            self.check('gh_fallback_after_origin_resolution_failure', bool(failed_origin))
        self.check('one_ready_creation', len(create_events) == 1 and literal(create_events[0]['args']['command'])[0] == selected
                   and '--draft' not in literal(create_events[0]['args']['command'])
                   and (selected != 'origin' or ['--status', 'open'] == literal(create_events[0]['args']['command'])[-2:]))
        self.check('single_forge_for_pr_operations', all(literal(e['args']['command'])[0] == selected for e in create_events + view_events))
        self.check('one_owned_branch_push', len(push_events) == 1 and self.branch in literal(push_events[0]['args']['command'])
                   and 'origin' in literal(push_events[0]['args']['command'])
                   and all(not word.startswith('--force') and word not in ('--all', '--mirror', '-f', '--tags', '--delete')
                           for word in literal(push_events[0]['args']['command'])))
        self.check('native_pr_explicit_base', '--base' in literal(create_events[0]['args']['command'])
                   and literal(create_events[0]['args']['command'])[literal(create_events[0]['args']['command']).index('--base') + 1] == self.args.base_ref)
        readback = [event for event in view_events if event['call_row'] > create_events[0]['result_row']]
        self.check('native_readback_identity', any(
            self.branch in event['output'] and self.args.base_ref in event['output']
            and commits[-1] in event['output'] for event in readback))
        reply = core.workflow_writes(events, self.worktree, self.artifacts / 'reply.md', final=True)
        self.stage('opening_pr', guidance + forge_notes + push_events + create_events + readback + reply,
                   bool(forge_notes and readback and reply) and forge_notes[0]['result_row'] < create_events[0]['call_row']
                   and commit_events[-1]['result_row'] < push_events[0]['call_row']
                   and push_events[0]['result_row'] < create_events[0]['call_row']
                   and readback[-1]['result_row'] < reply[0]['call_row'])
        self.stage('bug_fix_6', create_events + readback + reply, 'opening_pr' in self.stage_proof)
        self.verify_remote(commits[-1])
        self.check('reply_links_verified_pr', self.pr['url'] in (self.artifacts / 'reply.md').read_text())
        for label in ('native-before', 'native-after'):
            observed = core.read_json(self.directory / label / 'observation.json')
            self.check('reply_verbatim_' + label, json.dumps(observed, sort_keys=True) in (self.artifacts / 'reply.md').read_text())

    def verify_remote(self, head):
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        expected = sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch])
        self.check('only_owned_remote_branch_added', sorted(remote) == expected)
        prs = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json', 'number,state,headRefName,baseRefName,isDraft')
        created = [p for p in prs if p['number'] not in {p['number'] for p in self.prs_before}]
        self.check('only_one_owned_pr_added', len(created) == 1 and all(p in prs for p in self.prs_before))
        self.pr = self.forge('pr', 'view', str(created[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'number,url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('real_ready_stacked_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        baseline = self.forge('pr', 'view', '1', '--repo', self.args.forge_repo, '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('baseline_pr_unchanged_unmerged', baseline == self.bootstrap)

    def finish(self):
        cleanup_ok = True
        # Stop the lead before the final task scan so cleanup cannot race dispatch.
        if self.pane:
            try:
                screen = self.call(['herdr', 'pane', 'read', self.pane, '--source', 'recent', '--lines', '80'], cleanup=True)
                (self.directory / 'controller-pane.json').write_text(screen)
            except Exception:
                cleanup_ok = False
            try:
                self.herdr('pane', 'close', self.pane, cleanup=True)
            except Exception:
                cleanup_ok = False
        try:
            self.scan()
        except Exception:
            self.categories.append('task_snapshot_failed')
        for task in self.tasks.values():
            try:
                state = core.read_json(Path(task['task_dir']) / 'state.json')
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task.get('pane_id'):
                        raise Failure('cleanup_ownership_unproven')
                    screen = self.call(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'], cleanup=True)
                    (self.directory / (task['task_id'] + '-pane.json')).write_text(screen)
                    self.call([sys.executable, self.bundle / 'skills/agent-workers/scripts/agent-workers.py', 'close', task['task_id']], cleanup=True)
            except Exception:
                cleanup_ok = False
        panes = ([self.pane] if self.pane else []) + [t['pane_id'] for t in self.tasks.values()]
        for pane in panes:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env, text=True, capture_output=True, timeout=15)
                value = json.loads(proc.stdout or proc.stderr)
                error = value.get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if proc.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        after, config_after = {}, None
        integrity = fixture_integrity = False
        try:
            after = identity()
            config_after = core.sha(self.config_path)
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            integrity = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                         and self.git('rev-parse', 'HEAD', repo=self.args.repo, cleanup=True) == self.revision
                         and self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.repo, cleanup=True) == self.source_status
                         and (not copied.exists() or core.sha(copied) == self.config_hash))
            if self.bundle.exists():
                integrity = integrity and all(core.sha(self.bundle / p) == digest for p, digest in self.hashes.items() if p.startswith('skills/'))
            if self.probe.exists():
                integrity = integrity and core.sha(self.probe) == self.probe_hash
            integrity = integrity and bool(self.scope_hashes) and all(
                (self.scope/name).is_file() and core.sha(self.scope/name)==sha for name,sha in self.scope_hashes.items())
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
        except Exception:
            pass
        self.checks.extend([{'name': 'source_head_config_bundle_probe_integrity', 'ok': integrity},
                            {'name': 'original_fixture_checkout_untouched', 'ok': fixture_integrity},
                            {'name': 'owned_panes_absent', 'ok': cleanup_ok}])
        passed = bool(self.checks) and not self.categories and all(c.get('ok') is True for c in self.checks)
        inventory = {name: 'not_run' for name in core.INVENTORY}
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        original_bugfix='unresolved' if passed else verdict
        opening_verdict='pass' if passed and 'opening_pr' in self.stage_proof else verdict
        inventory.update({'bug-fix':original_bugfix,'opening-a-pr':opening_verdict})
        if not self.native:
            sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(sessions) == 1:
                self.native = {'sha256': core.sha(sessions[0]), 'audit_completed': False}
        receipt = {
            'schema':'horch/forge-snapshot-fixture-e2e/v2','verdict':'pass' if passed else 'fail',
            'verdict_scope':'bounded snapshot fixture experiment; not original full Bug fix',
            'workflow_verdict':original_bugfix,'original_bugfix_eligibility':original_bugfix,
            'behavior_verdict':'pass' if passed else 'unverified',
            'snapshot_stage_verdict':'pass' if passed else verdict,
            'original_live_source_why_eligibility':'unresolved',
            'opening_pr_verdict':opening_verdict,
            'full_inventory_verdict':'not_run','inventory':inventory,
            'evidence_lane':'controller exact-repository snapshot plus local Git',
            'worker_live_forge_queries_verified':False,
            'credential_containment_claim':False,
            'snapshot_sha256':self.scope_hashes.get('dataset.json'),
            'snapshot_manifest_sha256':self.scope_hashes.get('manifest.json'),
            'worker_scope_audits':self.scope_facts,
            'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
            'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
            'controller': {k: self.spec.get(k) for k in ('harness', 'provider', 'model', 'effort')},
            'native_transcript': self.native, 'native_stages': self.stage_proof,
            'tasks': getattr(self, 'task_facts', []), 'checks': self.checks,
            'fixture_snapshots': self.snapshot, 'commit_count': len(getattr(self, 'commits', [])),
            'forge': {'ready_pr_verified': passed and self.pr is not None,
                      'retained': True if self.pr is not None else 'unconfirmed'},
            'failure_categories': self.categories, 'last_phase': self.phase,
            'seconds': round(time.monotonic() - self.started, 3),
            'limitations': [
                'Why uses controller-captured exact-repository issues/comments/labels and PR1 plus local Git, not live worker forge queries.',
                'REST capture spans completed requests, not an atomic database snapshot.',
                'Original live-source Why and full original Bug fix eligibility remain unresolved.',
                'The gate detects native-call boundary violations after execution and before forwarding; it is not a sandbox or credential containment.',
                'Owned CLI execution is allowed; this native-command gate does not inspect network system calls hidden inside application code.',
                'Reader-only FFF support is limited to typed own-cwd queries without cursor on trees checked symlink-free before dispatch and after delivery; external concurrent mutation between checks is assumed absent.',
                'Other playbooks and the complete inventory are not run.',
                'Only this two-commit fixture graph and literal native tool grammar are accepted.',
                'Branch, detached reader worktrees, private artifacts and ready PR are retained for inspection.',
                'No live external system is replayed from a controller self-report; native and independent checks are required.',
            ],
        }
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-fixture', type=Path, help='write a fresh local synthetic baseline; no Git, forge, Herdr or model calls')
    parser.add_argument('--controller', help='existing configured Pi controller worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='existing trusted orchestrator checkout')
    parser.add_argument('--fixture-repo', type=Path, help='existing clean private fixture clone')
    parser.add_argument('--forge-repo', help='private fixture GitHub owner/name')
    parser.add_argument('--base-ref', help='existing unmerged fixture baseline branch')
    parser.add_argument('--output', type=Path, help='private artifact parent outside both checkouts')
    parser.add_argument('--caller-pane', help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=2400, help='overall run deadline; never retries')
    args = parser.parse_args()
    if args.prepare_fixture is not None:
        try:
            return prepare_fixture(args.prepare_fixture)
        except (OSError, Failure) as exc:
            parser.error(str(exc))
    required = ('controller', 'fixture_repo', 'forge_repo', 'base_ref', 'output', 'caller_pane')
    missing = ['--' + name.replace('_', '-') for name in required if getattr(args, name) is None]
    if missing:
        parser.error('run mode requires: ' + ', '.join(missing))
    for name in ('repo', 'fixture_repo', 'output'):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.repo != ROOT:
        parser.error('--repo must identify this driver source checkout')
    if any(args.output == repo or repo in args.output.parents for repo in (args.repo, args.fixture_repo)):
        parser.error('--output must be outside source and fixture repositories')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.forge_repo):
        parser.error('--forge-repo must be owner/name')
    if args.base_ref in ('main', 'master') or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', args.base_ref) or '..' in args.base_ref:
        parser.error('--base-ref must be an existing non-trunk baseline branch')
    core.require_historical_fixture_source(parser)
    run = Run(args)
    try:
        run.preflight()
        run.phase = 'setup'
        run.setup()
        run.phase = 'runtime'
        run.monitor()
        run.phase = 'verify'
        run.verify()
    except Failure as exc:
        run.categories.append(str(exc))
    except KeyboardInterrupt:
        run.categories.append('operator_interrupted')
    except (SystemExit, Exception):
        (run.directory / 'failure.txt').write_text(traceback.format_exc())
        run.categories.append('preflight_or_runtime_error')
    return run.finish()


if __name__ == '__main__':
    raise SystemExit(main())
