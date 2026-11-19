#!/usr/bin/env python3
"""Real Authoring a skill playbook, independent CLI use, and a ready private PR.

Uses existing harness skill-creator guidance, copied privately without changes.
Requires an existing clean private invoice fixture and explicit open parent PR.
Forward-use workers are explicit configured Pi selections, never invented roles.
Sessions are read only from each owned cwd's default Pi directory and captured
UUID. No merge, auto-merge, trust answers, model substitutions or retry loops.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from urllib.parse import unquote
import uuid

import forge_loop as support
import playbook_loop as core

ROOT = Path(__file__).resolve().parents[1]
horch = core.horch
Failure = core.Failure
SKILL = Path('.agents/skills/ledger-operations')
AUTHORED = (str(SKILL / 'SKILL.md'), str(SKILL / 'references/cli-contract.md'))
APP = ('money.py', 'storage.py', 'cli.py', 'e2e_import.py')
READS = ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
         'pstack-herdr/references/herdr-tools.md', 'agent-workers/SKILL.md',
         'poteto-mode/playbooks/authoring-a-skill.md',
         'poteto-mode/playbooks/opening-a-pr.md', 'deslop/SKILL.md',
         'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
         'principle-sequence-verifiable-units/SKILL.md',
         'pstack-herdr/references/agents/comment-sicko.md')
PROTOCOL = '''Use only direct native read, bash, write, edit, grep, find and ls.
Do not use codemode or another tool wrapper: nested results are unauditable.
Do not delegate, use native subagents, change configuration, answer trust dialogs,
substitute models, retry a failed operation or run a whole playbook.'''
LEAD_PROTOCOL = '''Use only direct native read, bash, write, edit, grep, find and ls.
Do not use codemode or another tool wrapper: nested results are unauditable.
Delegate only the two specified forward-use tasks and one mandatory CommentSicko
review through horch. No native subagents, extra tasks, configuration changes,
trust answers, model substitutions, retries or whole-playbook worker assignments.
All three workers remain bounded and must not delegate.'''


def patch_headers(value):
    """Normalize only known Git mnemonic headers for these exact authored files."""
    lines = value.splitlines(keepends=True)
    header = None
    for index, line in enumerate(lines):
        text = line.rstrip('\r\n')
        if text.startswith('diff --git '):
            header = next((name for name in AUTHORED if text in (
                f'diff --git c/{name} i/{name}', f'diff --git a/{name} b/{name}')), None)
        elif text.startswith(('@@', 'GIT binary patch')):
            header = None
        for name in AUTHORED:
            if header != name:
                continue
            for old, new in ((f'diff --git c/{name} i/{name}', f'diff --git a/{name} b/{name}'),
                             (f'--- c/{name}', f'--- a/{name}'),
                             (f'+++ i/{name}', f'+++ b/{name}')):
                if text == old:
                    lines[index] = new + line[len(old):]
    return ''.join(lines)


def fingerprint(root):
    """Hash guidance resources by relative name, without exposing their source."""
    result = {}
    for path in root.rglob('*'):
        if '.git' in path.parts or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise Failure('creator_guidance_symlink_unsupported')
        if path.is_file():
            result[str(path.relative_to(root))] = core.sha(path)
    return result


def text_sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def charged(row):
    amount = Decimal(row['quantity']) * Decimal(row['unit_price_cents']) * (
        Decimal(1) - Decimal(row['discount_bp']) / Decimal(10000))
    return dict(row, total_cents=int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def raw_row(identity, quantity, price, discount=0):
    return {'id': identity, 'quantity': quantity, 'unit_price_cents': price, 'discount_bp': discount}


def decode_result(event):
    """Decode actual Pi 1.2 bash stdout, including its real exit-2 suffix."""
    output = event['output'].strip()
    code = 0
    if not event['successful']:
        suffix = 'Command exited with code 2'
        if not output.endswith(suffix):
            return None
        output, code = output[:-len(suffix)].strip(), 2
    try:
        return code, json.loads(output)
    except ValueError:
        return None


class Run(core.Run):
    git = support.Run.git
    forge = support.Run.forge
    native_events = support.Run.native_events
    stage = support.Run.stage

    def __init__(self, args):
        args.scenario = 'authoring-a-skill'
        super().__init__(args)
        self.branch = 'e2e/authoring-' + format(time.time_ns(), 'x')
        self.guidance = self.directory / 'creator-guidance'
        self.guidance_hashes = {}
        self.worker_sessions, self.worker_native, self.cases = {}, {}, {}
        self.skill_hashes, self.stage_proof, self.task_facts = {}, {}, []
        self.base = self.pr = self.config_path = self.original_fixture = None
        self.app_hashes = {}
        self.agent_dir = Path(self.env.get('PI_CODING_AGENT_DIR') or Path.home() / '.pi/agent').expanduser().resolve()
        self.settings_paths = {'pi-agent-settings': self.agent_dir / 'settings.json',
                               'fixture-pi-settings': args.fixture_repo / '.pi/settings.json'}
        self.settings_hashes = {}

    def preflight(self):
        self.check('positive_duration', self.args.max_seconds > 0)
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=ROOT)).resolve() == self.args.repo == ROOT)
        self.revision = self.git('rev-parse', 'HEAD', repo=ROOT)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT)
        self.hashes = support.identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_pi', self.spec.get('harness') == 'pi')
        self.selected = {'success': self.args.success_worker, 'rollback': self.args.rollback_worker}
        selection = self.config.get('roles', {}).get('judgment and prose')
        reviewers = selection if isinstance(selection, list) else [selection]
        self.check('single_configured_comment_review_role', len(reviewers) == 1
                   and reviewers[0] in self.config['workers'])
        self.comment_worker = reviewers[0]
        for label, name in {**self.selected, 'comment-review': self.comment_worker}.items():
            worker = self.config['workers'].get(name, {})
            self.check('configured_forward_worker_' + label, worker.get('harness') == 'pi')
            overrides = ('--session', '--session-dir', '--session-id', '--no-session', '--continue', '--resume', '-c', '-r')
            self.check('default_scoped_sessions_' + label, not any(arg == flag or arg.startswith(flag + '=')
                       for arg in worker.get('args', []) for flag in overrides))
        self.check('no_session_directory_env_override', not self.env.get('PI_CODING_AGENT_SESSION_DIR'))
        for label, path in self.settings_paths.items():
            self.settings_hashes[label] = core.sha(path) if path.is_file() else None
            if path.is_file():
                settings = core.read_json(path)
                self.check('default_session_setting_' + label, not settings.get('sessionDir'))
        self.check('existing_pyyaml', importlib.util.find_spec('yaml') is not None)
        self.creator_source = self.args.creator_guidance.parent
        self.check('creator_guidance_complete', self.args.creator_guidance.name == 'SKILL.md'
                   and self.args.creator_guidance.is_file() and (self.creator_source / 'scripts/quick_validate.py').is_file())
        self.guidance_hashes = fingerprint(self.creator_source)
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('fixture_clean', not self.original_fixture[1])
        remote = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', remote)
        self.check('fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        repository = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('private_repository', repository.get('isPrivate') is True
                   and repository.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        tips = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('one_existing_remote_base', len(tips) == 1)
        self.base = tips[0].split()[0]
        self.check('exact_clean_baseline', self.base == self.original_fixture[0]
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base)
        self.parent_pr = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                                    'state,isDraft,headRefName,headRefOid,baseRefName')
        self.check('explicit_ready_open_parent', self.parent_pr.get('state') == 'OPEN' and self.parent_pr.get('isDraft') is False
                   and self.parent_pr.get('headRefName') == self.args.base_ref and self.parent_pr.get('headRefOid') == self.base)
        self.check('new_project_skill', not (self.args.fixture_repo / SKILL).exists())
        self.app_hashes = {name: core.sha(self.args.fixture_repo / name) for name in APP}
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                                    'number,state,headRefName,baseRefName,isDraft')

    def invoke(self, cwd, argv, label):
        timeout = min(60, self.deadline - time.monotonic())
        if timeout <= 0:
            raise Failure('overall_timeout')
        result = subprocess.run([sys.executable, '-B', str(cwd / 'cli.py'), *map(str, argv)], cwd=cwd,
                                env=self.env, capture_output=True, text=True, timeout=timeout)
        value = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                 'argv': [str(arg) for arg in argv]}
        (self.directory / (label + '.json')).write_text(json.dumps(value, indent=2) + '\n')
        return value

    def prepare_case(self, label):
        identity = 'usage-a' if label == 'success' else 'usage-b'
        cwd = self.worktree.parent / identity
        self.git('worktree', 'add', '--detach', cwd, self.base, repo=self.args.fixture_repo)
        directory = self.directory / (identity + '-artifacts')
        directory.mkdir()
        seed = [raw_row('existing-03', 2, 49)]
        first = [raw_row('batch-z', 1, 101, 5000), raw_row('batch-zero', 0, 999)]
        second = [raw_row('batch-a', 2, 333, 3333), raw_row('batch-free', 7, 101, 10000),
                  raw_row('batch-last', 3, 137, 250 if label == 'success' else 10001)]
        paths = []
        for name, rows in (('seed', seed), ('first', first), ('second', second)):
            path = directory / (name + '.json')
            path.write_text(json.dumps(rows, sort_keys=True) + '\n')
            paths.append(path)
        store = directory / 'ledger.json'
        seeded = self.invoke(cwd, ['import', store, paths[0]], label + '-seed')
        self.check('case_seeded_through_real_cli_' + label, seeded['exit_code'] == 0
                   and json.loads(seeded['stdout']) == {'count': 1, 'total_cents': 98} and not seeded['stderr'])
        rows = [charged(row) for row in (seed + first + second if label == 'success' else seed)]
        self.cases[label] = {'identity': identity, 'cwd': cwd, 'directory': directory, 'store': store, 'inputs': paths[1:], 'seed': paths[0],
                             'input_sha256': {p.name: core.sha(p) for p in paths}, 'before_bytes': store.read_bytes(),
                             'expected_rows': rows, 'export': sorted(rows, key=lambda row: row['id']),
                             'code': 0 if label == 'success' else 2,
                             'output': {'count': len(rows), 'total_cents': sum(row['total_cents'] for row in rows)}
                             if label == 'success' else {'error': 'invalid discount'}}

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(self.creator_source, self.guidance, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
        self.check('complete_creator_copy', fingerprint(self.guidance) == self.guidance_hashes)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        for label in self.selected:
            self.prepare_case(label)
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'authoring-e2e', '--no-focus', *sum((['--env', key + '=' + self.env[key]] for key in
                         ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL', 'GH_CONFIG_DIR')), []))
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        sessions = self.directory / 'native-sessions'
        sessions.mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(sessions)]
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
        case_requests = {}
        for label, case in self.cases.items():
            case_requests[label] = {
                'worker': self.selected[label], 'cwd': str(case['cwd']),
                'brief': self.forward_brief(label),
                'request': f'''Use ledger-operations at {self.worktree / SKILL / 'SKILL.md'} to import
both supplier files {case['inputs'][0]} and {case['inputs'][1]} into the existing
ledger {case['store']}, then export the current ledger through this checkout's CLI.
Report the operation's actual completion status and exported result.''',
            }
        return f'''Read {self.bundle / 'skills/poteto-mode/SKILL.md'} in full first. You are the
native lead for original Authoring a skill and Opening a PR, not a delegated
prose worker. Full-read original playbook and mappings, then write its exact four
numbered checklist entries to {self.artifacts / 'checklist.md'} before authoring.
Required bundle-relative reads: {json.dumps(list(READS))}. Read every applied file
in a separate full native read (no offset/limit) or literal cat. Use the actual
available harness skill-creator guide at {self.guidance / 'SKILL.md'} as mapped
create-skill guidance; its complete original resources were copied privately.
Read that guide in full before authoring. Do not change guidance or validators.
No mandatory initialization, UI metadata, implicit-disable policy or extra files.

{LEAD_PROTOCOL}
Every worker uses the bounded protocol in its exact brief. Preserve original worker
harness/model/effort/permission args, user configuration and Mise/Git settings.
Controller Bash contract: ONE standalone literal command per native bash call.
Never include newline, ; | & > < backtick, dollar sign or backslash ANYWHERE,
even inside quoted arguments. No pipelines, composition, redirection, environment
expansion, inline interpreters, printf/test wrappers or shell filesystem commands.
Use native ls/read/grep/find for filesystem inspection and local link targets.
The actual isolated unchanged worker configuration is directly readable at
{self.directory / 'config/herdr-orchestrator/workers.toml'}; do not discover it
through printf, XDG variables or a shell. Use native write for multiline PR bodies
and pass --body-file; do not embed newlines in a bash command.
Accepted controller command grammar (all other commands fail proof):
- python or python3, optional -B, then exactly
  {self.guidance / 'scripts/quick_validate.py'} {self.worktree / SKILL};
  or the bundled agent-workers.py with run/wait/list/close/stats/detect and literal args.
- git in the lead cwd, optionally -C {self.worktree}, with status/diff/show/log/
  blame/rev-parse/rev-list/diff-tree/ls-files/ls-remote (no --output option);
  add with only the one or two authored relative paths (optional --);
  commit with normal hooks/signing (no -n, --no-verify or --no-gpg-sign);
  push [-u|--set-upstream] origin {self.branch}; branch --show-current;
  or remote get-url origin. No other Git write operation.
- Only for the owned case cwds {json.dumps([str(case['cwd']) for case in self.cases.values()])},
  git -C ABSOLUTE_CASE_CWD status with optional --short and/or --branch, each at
  most once. No other case Git operation or relative case cwd is accepted.
- gh or origin repo view, pr list, pr view, or pr create. PR creation uses exact
  base {self.args.base_ref}, head {self.branch}, repository {self.args.forge_repo}
  and ready status; preserve the forge-selection and readback requirements below.
- sha256sum followed by exactly one or two authored file paths; cat ONE_FILE
  without flags; pwd; command -v origin; or which origin.
One additional hash form is allowed ONLY AFTER the actual CommentSicko task is
done/closed: sha256sum ABSOLUTE_CANONICAL_COMMENT_TASK_DIR/report.md. It hashes
exactly that one actual owned delivered report, no flags/aliases/extra operands
or other task files. Use this native result for comment-review.report_sha256;
no arbitrary task/path hashing is authorized.
This is the controller grammar; forward workers retain their narrower standalone
real-CLI/cat grammar below. Never bypass these restrictions with a wrapper.
Author only {self.worktree / AUTHORED[0]} and {self.worktree / AUTHORED[1]}.
No application/source changes. The project skill should guide invoice CLI
import/export: per-line half-up money, multi-file atomic rollback, structured
exit 2 as a validation rejection without retry, and deterministic export.
Use concise, decision-changing guidance and default skill discoverability.
Lead owns the voice and writes both files directly. Link the useful contract
reference from SKILL.md and structural sources with portable relative paths.
Frontmatter name ledger-operations and a discriminating description are required.
No unfinished placeholders, private paths, credentials, copied transcripts or
extra auxiliary files. Keep temporary notes/briefs under {self.artifacts}.

Validate with an actual standalone python3 invocation of
{self.guidance / 'scripts/quick_validate.py'} {self.worktree / SKILL} before
forward calls. PyYAML must already exist; never install anything. Full-read both
authored files and confirm local links resolve. Before dispatch write a private
{self.artifacts / 'frozen-skill.json'} mapping the two relative authored paths to
actual SHA256 digests. Use literal sha256sum invocations if needed. Freeze both
skill files through all forward use, review, commit and PR readback. Any required
revision after forward use remains unresolved in this bounded run; no retries.

Two independent forward requests: {json.dumps(case_requests)}.
Write each exact supplied brief body to a separate private file and dispatch
that unchanged body. The evaluator matches it byte for byte, including the
standard horch nonce/result rules appended by horch. Do not append expected
answers or case explanations. Its neutral Case identity is usage-a or usage-b.
Name the actual selected worker and reason: explicit CLI selection for a fresh
independent forward-use process. Do not invent a role/model or infer one from
names. Include absolute references to the installed poteto-agent and poteto-mode
instructions, plus the actual authored skill. Give the realistic request above
and minimum raw input/store paths, no expected answer, desired exit code, known
invalid field, oracle totals or prior conclusions. Do not add behavioral hints
beyond the skill under evaluation. Do not weaken its error semantics in the brief.

Each worker's source checkout is pristine and read-only. Inputs already exist,
and the existing ledger was seeded through the real CLI. Worker mutation is
limited to invoking that checkout's real cli.py on its owned external ledger
and writing report.md/result.json in its own agent-workers task directory. Never write
or edit a ledger or input JSON directly; no fabrication or evaluator/probe helper.
Use standalone literal python3 [-B] ABSOLUTE_CLI_PATH import|export arguments.
Workers full-read authored SKILL.md and references/cli-contract.md before CLI use;
execute import once, export afterwards, inspect the actual ledger with a full
native read, and report actual outcomes. No automatic retries or input repairs.
Expected application failures are real tool failures; do not hide them behind
shell wrappers. Only direct native read/bash/write/edit/grep/find/ls, no codemode.
Worker bash is limited to direct cli.py or literal cat inspection. The worker
brief contains no success/rollback label in its request body; Case header is an
identity label, not an expected answer. Each worker lists report.md in result.json.

Dispatch only through {self.bundle / 'skills/agent-workers/scripts/agent-workers.py'},
with --caller-pane {self.pane} and the case's exact cwd/worker. Use fresh tasks,
no native subagents. Use standalone literal agent-workers wait, wait for state done,
then read result.json and ALL listed artifacts in separate full reads before
reviewing. Wait closes successful tasks. No new role or worker config changes.
The evaluator captures each working Pi session and audits its exact default
cwd directory plus UUID. Overridden/unavailable traces remain unresolved.

After BOTH forward tasks are delivered/closed and all their result/report files
are fully read, perform no-comments' mandatory fresh CommentSicko review BEFORE
commit or PR. This is the third and final task, using the unchanged single
configured judgment and prose worker {self.comment_worker}, cwd {self.worktree}.
Write the exact following brief body to {self.artifacts / 'comment-brief.md'} and
pass that file to agent-workers run (no extra hints or restated agent rules). The supplied
bootstrap is required execution-boundary disclosure, not copied agent content:
--- BEGIN EXACT COMMENT BRIEF ---
{self.comment_brief()}--- END EXACT COMMENT BRIEF ---
Read both no-comments and CommentSicko guidance yourself before dispatch.
Stage exactly the two authored paths before this review so its complete cached
diff includes both new files; do not commit yet.
Wait until done/closed, then full-read result.json and ALL listed artifacts before
assessing findings. Write {self.artifacts / 'comment-review.json'} with task_id,
report_sha256, decision ('accept' or 'unresolved'), summary, findings_assessment,
deletion_count, restored_comments, reruns, architect_sketch, fixes, encoding_offers,
encodings, unenforced_constraints, skips and open_work. Use actual report facts;
All these fields are arrays except task_id/report_sha256/decision/summary strings
and deletion_count integer. With no accepted revision, findings_assessment,
reruns, architect_sketch, fixes and encodings are empty arrays, not prose/null.
do not invent zero findings or waive the review. Explain accepted/rejected findings
against original no-comments exceptions and scoped evidence. A proposed revision,
rerun, deeper hunt or encoding approval after frozen forward use is unresolved:
STOP before commit/PR, retain artifacts, no retries or frozen-file changes. The
bounded lane can proceed only when the real report requires no scope revision
and no unresolved comment flags/constraints remain. Include its disposition and
all no-comments summary fields in the final reply by preserving the complete
comment-review.json content verbatim under a No-comments heading. This task has no
permission to edit skill/application files or perform forge operations.

Worktree branch {self.branch}, exact base {self.base}; existing ready parent PR
{self.args.parent_pr} at {self.args.base_ref} stays unchanged and unmerged.
You may push ONLY {self.branch} to origin and create ONE ready child PR on
{self.args.forge_repo}, base {self.args.base_ref}. No other forge mutation,
branch deletion, merge, auto-merge or babysit. Resolve one forge via actual
command -v origin and repository resolution; record forge/reason in
{self.artifacts / 'forge.json'} before first PR operation. Prefer Origin if it
resolves; otherwise record gh fallback and retain the chosen forge throughout.
Read actual Opening a PR and deslop/no-comments/technical-writing/unslop/sequence
sources before diff review and commit. Review the complete actual git diff,
including untracked authored files (git add names both paths explicitly first),
and write {self.artifacts / 'review.json'} with actual findings/decision after
all forward reports AND the CommentSicko report/disposition. Keep exactly one
reviewed skill commit, conventional title.
No Git hook/signature bypass. Create ready, then actual pr view JSON includes
headRefName,headRefOid,baseRefName,isDraft. Origin create uses --status open last.
Write {self.artifacts / 'reply.md'} only after actual ready PR readback, with
summary, key design decisions, validation notes and actual PR URL. Disclose that
explicit forward use does not prove native automatic skill discovery. Do not
write evidence.json or change any evaluator. Preserve all failed artifacts and
report unresolved stages honestly.
'''

    def scan(self):
        rows = super().scan()
        if rows and not self.skill_hashes:
            self.skill_hashes = {name: core.sha(self.worktree / name) for name in AUTHORED}
            (self.directory / 'frozen-skill-observed.json').write_text(json.dumps(self.skill_hashes, indent=2) + '\n')
        for task, _ in rows:
            if task['task_id'] not in self.worker_sessions:
                try:
                    entry = self.herdr('agent', 'get', task['agent'])['agent']
                    session = entry.get('agent_session') or {}
                    if (entry.get('agent_status') == 'working' and session.get('agent') == 'pi'
                            and session.get('source') == 'herdr:pi' and session.get('value')):
                        self.worker_sessions[task['task_id']] = session
                        (self.directory / 'working-worker-sessions.json').write_text(json.dumps(self.worker_sessions, indent=2) + '\n')
                except Failure:
                    pass
        return rows

    def scoped_session(self, task):
        session = self.worker_sessions.get(task['task_id'])
        if not session:
            raise Failure('working_worker_session_unavailable')
        cwd = Path(task['cwd']).resolve()
        encoded = '--' + re.sub(r'[/\\:]', '-', str(cwd).lstrip('/\\')) + '--'
        directory = self.agent_dir / 'sessions' / encoded
        value = session['value']
        if session.get('kind') == 'path':
            path = Path(value).expanduser().resolve()
            if path.parent != directory:
                raise Failure('worker_session_location_overridden')
            identity = path.stem.rsplit('_', 1)[-1]
        else:
            identity = value
        try:
            canonical = str(uuid.UUID(identity))
        except (ValueError, AttributeError):
            raise Failure('worker_session_uuid_unavailable') from None
        if canonical != identity:
            raise Failure('worker_session_uuid_not_canonical')
        # Never enumerate any other cwd or UUID, including on a lookup failure.
        paths = list(directory.glob('*_' + canonical + '.jsonl'))
        if len(paths) != 1 or session.get('kind') == 'path' and paths[0].resolve() != Path(value).resolve():
            raise Failure('owned_worker_native_session_unavailable')
        return paths[0]

    def written(self, events, filename, before=float('inf'), after=-1):
        matches = core.workflow_writes(events, self.worktree, self.artifacts / filename,
                                        after=after, before=before, final=True)
        self.check('native_artifact_' + filename, len(matches) == 1)
        return matches[0]

    def validate_structure(self):
        import yaml
        path = self.worktree / AUTHORED[0]
        text = path.read_text()
        match = re.match(r'\A---\n(.*?)\n---(?:\n|\Z)', text, re.S)
        self.check('frontmatter_present', match is not None)
        frontmatter = yaml.safe_load(match[1])
        self.check('frontmatter_identity_and_discovery', isinstance(frontmatter, dict)
                   and frontmatter.get('name') == 'ledger-operations'
                   and isinstance(frontmatter.get('description'), str) and bool(frontmatter['description'].strip()))
        private = (str(ROOT), str(self.args.fixture_repo), str(self.directory), str(Path.home()))
        linked_contract = False
        for name in AUTHORED:
            document = self.worktree / name
            content = document.read_text()
            self.check('complete_portable_document_' + Path(name).name, bool(content.strip())
                       and not any(value in content for value in private)
                       and not re.search(r'(?m)^\s*\[(?:TODO|TBD):|<(?:(?:your|insert)[^>]+)>|\bFIXME\b', content))
            links = re.findall(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', content)
            links += re.findall(r'(?m)^\[[^\]]+\]:\s*(\S+)', content)
            for link in links:
                target = unquote(link.split('#', 1)[0])
                if not target:
                    continue
                self.check('portable_local_link', not re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target) and not Path(target).is_absolute())
                resolved = (document.parent / target).resolve()
                self.check('local_link_resolves', self.worktree in resolved.parents and resolved.is_file())
                linked_contract |= document == path and resolved == self.worktree / AUTHORED[1]
        self.check('contract_reference_discoverable', linked_contract)
        self.check('only_two_authored_resources', {str(p.relative_to(self.worktree)) for p in (self.worktree / SKILL).rglob('*') if p.is_file()} == set(AUTHORED))
        self.call([sys.executable, self.guidance / 'scripts/quick_validate.py', self.worktree / SKILL])

    def direct_cli(self, event, case):
        if event['name'] != 'bash':
            return None
        argv = support.literal(event['args'].get('command', ''))
        if not argv or Path(argv[0]).name not in ('python', 'python3'):
            return None
        words = argv[1:]
        if words[:1] == ['-B']:
            words = words[1:]
        if not words or (case['cwd'] / words[0]).resolve() != case['cwd'] / 'cli.py':
            return None
        return words[1:]

    def replay(self, label, case):
        directory = self.directory / ('replay-' + label)
        directory.mkdir()
        paths = []
        for source in (case['seed'], *case['inputs']):
            path = directory / source.name
            path.write_bytes(source.read_bytes())
            paths.append(path)
        store = directory / 'ledger.json'
        seed = self.invoke(case['cwd'], ['import', store, paths[0]], label + '-replay-seed')
        self.check('replay_seed_' + label, seed['exit_code'] == 0 and store.read_bytes() == case['before_bytes'])
        imported = self.invoke(case['cwd'], ['import', store, *paths[1:]], label + '-replay-import')
        exported = self.invoke(case['cwd'], ['export', store], label + '-replay-export')
        self.check('independent_cli_replay_' + label, imported['exit_code'] == case['code']
                   and json.loads(imported['stdout']) == case['output'] and not imported['stderr']
                   and exported['exit_code'] == 0 and json.loads(exported['stdout']) == case['export']
                   and not exported['stderr'] and not store.with_suffix('.pending').exists()
                   and store.read_bytes() == case['store'].read_bytes())
        if label == 'rollback':
            self.check('replay_exact_rollback_bytes', store.read_bytes() == case['before_bytes'])

    def audit_forward(self, task, label):
        case = self.cases[label]
        worker = self.config['workers'][self.selected[label]]
        self.check('forward_settings_argv_cwd_' + label, task.get('worker') == self.selected[label]
                   and task.get('cwd') == str(case['cwd']) and task.get('harness') == worker['harness']
                   and task.get('model') == worker['model'] and task.get('workspace_id') == self.caller['workspace_id']
                   and task.get('argv') == horch.launch_args(worker, Path(task['task_dir']))
                   and Path(task['result_path']).resolve() == Path(task['task_dir']) / 'result.json')
        result = core.read_json(Path(task['result_path']))
        self.check('forward_nonce_result_' + label, horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed')
        source = self.scoped_session(task)
        saved = self.directory / ('forward-' + label + '.jsonl')
        shutil.copy2(source, saved)
        self.worker_native[label] = {'sha256': core.sha(saved), 'audit_completed': False}
        audit = core.audit_pi(source, self.worker_sessions[task['task_id']], case['cwd'], core.stamp(task['created_at']),
                              worker, [], [], [], self.bundle)
        self.check('forward_native_identity_model_effort_' + label, all(check['ok'] for check in audit['checks']) and core.sha(saved) == audit['sha256'])
        events = self.native_events(saved, include_errors=True)
        cli = []
        for event in events:
            if event['name'] in ('write', 'edit'):
                value = event['args'].get('path')
                self.check('worker_no_ledger_or_source_fabrication_' + label, isinstance(value, str)
                           and (case['cwd'] / value).resolve() in {Path(task['task_dir']) / 'report.md', Path(task['result_path'])})
            if event['name'] == 'bash':
                invocation = self.direct_cli(event, case)
                argv = support.literal(event['args'].get('command', ''))
                self.check('forward_direct_cli_only_' + label, invocation is not None or len(argv) == 2 and argv[0] == 'cat' and not argv[1].startswith('-'))
                if invocation is not None:
                    self.check('forward_cli_owned_arguments_' + label, invocation == ['import', str(case['store']), *map(str, case['inputs'])]
                               or invocation == ['export', str(case['store'])])
                    cli.append((event, invocation))
        imports = [event for event, argv in cli if argv[0] == 'import']
        exports = [event for event, argv in cli if argv[0] == 'export' and imports and event['call_row'] > imports[0]['result_row']]
        self.check('one_import_no_retry_' + label, len(imports) == 1)
        self.check('native_actual_import_' + label, decode_result(imports[0]) == (case['code'], case['output']))
        self.check('native_actual_sorted_export_' + label, bool(exports) and all(decode_result(event) == (0, case['export']) for event in exports))
        successful = [event for event in events if event['successful']]
        reads = []
        for name in AUTHORED:
            evidence = core.workflow_reads(successful, case['cwd'], self.worktree / name, before=imports[0]['call_row'])
            self.check('forward_full_authored_read_' + label + '_' + Path(name).name, bool(evidence))
            reads.append(evidence[0])
        ledger = core.workflow_reads(successful, case['cwd'], case['store'], after=imports[0]['result_row'])
        self.check('forward_inspects_real_ledger_' + label, bool(ledger))
        self.check('forward_actual_store_' + label, core.read_json(case['store']) == case['expected_rows']
                   and not case['store'].with_suffix('.pending').exists())
        if label == 'rollback':
            self.check('forward_exact_rollback_bytes', case['store'].read_bytes() == case['before_bytes'])
        self.check('forward_frozen_inputs_and_app_' + label, all(core.sha(case['directory'] / name) == digest for name, digest in case['input_sha256'].items())
                   and {name: core.sha(case['cwd'] / name) for name in APP} == self.app_hashes
                   and self.git('rev-parse', 'HEAD', repo=case['cwd']) == self.base
                   and not self.git('status', '--porcelain=v1', '--untracked-files=all', repo=case['cwd']))
        self.replay(label, case)
        self.worker_native[label] = dict(audit, audit_completed=True, skill_and_reference_read=True, actual_cli_verified=True,
                                         import_calls=len(imports), post_import_exports=len(exports),
                                         store_sha256=core.sha(case['store']))
        self.task_facts.append({'case': case['identity'], 'task_id_sha256': text_sha(task['task_id']),
                                'model': worker['model'], 'effort': worker.get('effort'), 'harness': worker['harness'],
                                'argv_sha256': text_sha(json.dumps(task['argv'])), 'result_sha256': core.sha(Path(task['result_path'])),
                                'nonce_validated': True, 'working_session_captured': True})

    def forward_brief(self, label):
        case = self.cases[label]
        return f'''Role: explicit configured worker
Case: {case['identity']}
Worker: {self.selected[label]}
Reason: explicit CLI selection for one fresh independent forward-use process.
{PROTOCOL}
Read {self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'} and
{self.bundle / 'skills/poteto-mode/SKILL.md'} as bounded worker instructions.
Use ledger-operations at {self.worktree / AUTHORED[0]} for this request:
Import both supplier files {case['inputs'][0]} and {case['inputs'][1]} into the
existing ledger {case['store']}, then export the current ledger through this
checkout's CLI. Report the operation's actual completion status and exported result.
Read that skill and its cli-contract.md reference fully before CLI use.
The checkout is {case['cwd']}; its application source and supplied inputs are
read-only. Only the real CLI may mutate the owned ledger. Do not write/edit ledger
or input JSON, use a probe/helper, repair inputs or run shell wrappers. Use literal
standalone python3 [-B] {case['cwd'] / 'cli.py'} invocations, not redirects or pipelines.
Native bash is limited to that real CLI and literal cat of one file. Inspect the
actual ledger with native read after the operation. Write report.md and result.json
only in your actual agent-workers task directory and list report.md in the result files.
No Git, forge, configuration or other external writes. Do not infer permission
from a successful check. Complete this request yourself without further delegation.
'''

    def comment_brief(self):
        return f'''Role: judgment and prose
Agent: CommentSicko
Worker: {self.comment_worker}
Reason: configured judgment and prose role fits this bounded comment/prose audit.
{PROTOCOL}
Runtime bootstrap: BEFORE ANY nonempty assistant natural-language text, use
native tools to FULL-read the original no-comments skill and CommentSicko agent
below. No preamble or acknowledgment before both reads finish. Then follow the
original agent's first-output rule: the ENTIRE first nonempty assistant
natural-text block must contain ONLY the original agent's required greeting,
with no prefix, suffix or explanation. Make the next action a separate native
read tool call of an assigned required source/input; wait for that tool result
before any further assistant prose. This supplied bootstrap declares a native
serialization boundary, not replacement agent rules. Do not copy, paraphrase
or replace the original agent rules.
Read the complete bundled instructions:
{self.bundle / 'skills/no-comments/SKILL.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/comment-sicko.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'}
{self.bundle / 'skills/poteto-mode/SKILL.md'}
Scope: only {self.worktree / AUTHORED[0]} and {self.worktree / AUTHORED[1]}.
Base: {self.base}; checkout: {self.worktree}. Full-read both actual authored files
and inspect the complete actual scoped staged diff with this literal command:
git -C {self.worktree} diff --cached -- {' '.join(AUTHORED)}
This is a report-only review after frozen forward use. Do not edit skill,
application, ledger, input, configuration or other files. No Git writes, forge,
CLI execution, nested delegation, wrappers or retries. Bash is limited to that
exact diff command and literal cat of one declared guide or scoped file.
Native reads/grep/find/ls are limited to the declared guides, scoped skill
directory and your own task directory. Write only report.md, review.json and
result.json in your own actual agent-workers task directory; list report.md and
review.json in result.files, question null, normal actual task nonce.
Apply the original report-only agent to this Markdown skill scope. Report real
findings, including no applicable comments when supported; never invent flags.
report.md gives the original touched files, deletion count, MUST KILL flags and
skips, with reasons grounded in the actual scope. Also write review.json with:
inspections: one object per scoped relative path, with path, excerpt (a verbatim
nonempty passage at least 20 characters) and conclusion explaining actual review;
findings: actual objects with path, excerpt, reason and action; deletion_count:
actual nonnegative integer; restored_comments, must_kill, skips, encoding_offers,
unenforced_constraints and open_work: arrays. Record all recommended work rather
than applying it. findings means actionable proposed changes, not supported keeps.
Record supported keeps in skips with their scoped evidence and reasons; preserve
every actual recommendation and open issue, never manufacture a clean review.
This bounded worker cannot run deeper How/Why/Architect or seek
approval: report those needs as open_work. Complete this review yourself.
'''

    def audit_comment(self, task):
        worker = self.config['workers'][self.comment_worker]
        directory = Path(task['task_dir']).resolve()
        self.check('comment_configured_role_settings_scope', task.get('worker') == self.comment_worker
                   and task.get('cwd') == str(self.worktree) and task.get('harness') == 'pi'
                   and task.get('model') == worker['model'] and task.get('workspace_id') == self.caller['workspace_id']
                   and task.get('argv') == horch.launch_args(worker, directory)
                   and Path(task['result_path']).resolve() == directory / 'result.json')
        expected = self.comment_brief().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
            result_path=Path(task['result_path']), task_id=task['task_id'], nonce=task['nonce'])
        self.check('comment_exact_bounded_role_brief', Path(task['brief_path']).read_text() == expected)
        result = core.read_json(Path(task['result_path']))
        self.check('comment_valid_completed_nonce', horch.validate_result(result, task) == 'valid'
                   and result.get('status') == 'completed' and result.get('question') is None
                   and isinstance(result.get('files'), list) and len(result['files']) == 2
                   and all(isinstance(name, str) for name in result['files'])
                   and set(result['files']) == {'report.md', 'review.json'})
        source = self.scoped_session(task)
        saved = self.directory / 'comment-review-native.jsonl'
        shutil.copy2(source, saved)
        guides = [self.bundle / 'skills' / name for name in (
            'no-comments/SKILL.md', 'pstack-herdr/references/agents/comment-sicko.md',
            'pstack-herdr/references/agents/poteto-agent.md', 'poteto-mode/SKILL.md')]
        audit = core.audit_pi(source, self.worker_sessions[task['task_id']], self.worktree,
                              core.stamp(task['created_at']), worker, guides, [], [], self.bundle)
        self.check('comment_native_identity_model_effort_guides', all(item['ok'] for item in audit['checks'])
                   and core.sha(saved) == audit['sha256'])
        rows = [json.loads(line) for line in saved.read_text().splitlines() if line.strip()]
        texts = [(index, block.get('text', '')) for index, row in enumerate(rows)
                 if row.get('message', {}).get('role') == 'assistant'
                 for block in row['message'].get('content', []) if block.get('type') == 'text'
                 and block.get('text', '').strip()]
        self.check('comment_original_agent_first_output', bool(texts)
                   and texts[0][1].strip() == 'Yes... Ha ha ha... Yes!')
        all_events = self.native_events(saved, include_errors=True)
        events = [event for event in all_events if event['successful']]
        for guide in guides[:2]:
            self.check('comment_original_bootstrap_before_text_' + guide.name, bool(core.workflow_reads(
                events, self.worktree, guide, before=texts[0][0])))
        outputs = {directory / name for name in ('report.md', 'review.json', 'result.json')}
        scoped = {self.worktree / name for name in AUTHORED}
        allowed = {*guides, *scoped, directory / 'brief.md', directory / 'task.json', *outputs}
        diff_argv = ['git', '-C', str(self.worktree), 'diff', '--cached', '--', *AUTHORED]
        entries = self.git('ls-files', '--stage', '--', *AUTHORED).splitlines()
        self.check('comment_exact_authored_index_paths', len(entries) == len(AUTHORED)
                   and {line.split('\t', 1)[1] for line in entries if '\t' in line} == set(AUTHORED)
                   and all(line.split('\t', 1)[0].endswith(' 0') for line in entries))
        for name in AUTHORED:
            indexed = subprocess.run(['git', '-C', str(self.worktree), 'show', ':' + name],
                                     capture_output=True, timeout=20, check=True).stdout
            self.check('comment_index_matches_frozen_authored_bytes_' + Path(name).name,
                       hashlib.sha256(indexed).hexdigest() == self.skill_hashes[name])
        indexed_diff = self.git('diff', '--cached', self.base, '--', *AUTHORED)
        self.check('comment_nonempty_complete_index_scope', bool(indexed_diff.strip())
                   and set(self.git('diff', '--cached', '--name-only', self.base, '--', *AUTHORED).splitlines()) == set(AUTHORED))
        diffs = []
        for event in all_events:
            args = event['args']
            if event['name'] in ('write', 'edit'):
                self.check('comment_report_only_writes', isinstance(args.get('path'), str)
                           and (self.worktree / args['path']).resolve() in outputs)
            elif event['name'] in ('read', 'grep', 'find', 'ls'):
                raw = args.get('path', '.')
                self.check('comment_read_path_known', isinstance(raw, str))
                target = (self.worktree / raw).resolve()
                self.check('comment_owned_read_scope', target in allowed or target == self.worktree / SKILL
                           or self.worktree / SKILL in target.parents or target == directory or directory in target.parents)
            elif event['name'] == 'bash':
                argv = support.literal(args.get('command', ''))
                self.check('comment_literal_read_only_commands', argv == diff_argv
                           or len(argv) == 2 and argv[0] == 'cat' and (self.worktree / argv[1]).resolve() in allowed)
                if argv == diff_argv and event['successful']:
                    self.check('comment_complete_actual_diff', patch_headers(event['output']).strip()
                               == patch_headers(indexed_diff).strip())
                    diffs.append(event)
        self.check('comment_actual_diff_inspected', bool(diffs))
        writes = []
        for name in ('report.md', 'review.json'):
            native = core.workflow_writes(events, self.worktree, directory / name, final=True)
            self.check('comment_native_full_report_' + name, len(native) == 1
                       and native[0]['args']['content'] == (directory / name).read_text())
            writes.append(native[0])
        report_start = min(event['call_row'] for event in writes)
        for path in [*guides, *scoped]:
            self.check('comment_full_scope_read_' + path.name, bool(core.workflow_reads(
                events, self.worktree, path, before=report_start)))
        self.check('comment_diff_before_report', diffs[0]['result_row'] < report_start)
        facts = core.read_json(directory / 'review.json')
        inspections = facts.get('inspections', [])
        self.check('comment_actual_scope_review_evidence', isinstance(inspections, list) and len(inspections) == 2
                   and {item.get('path') for item in inspections if isinstance(item, dict)} == set(AUTHORED)
                   and all(isinstance(item.get('excerpt'), str) and len(item['excerpt']) >= 20
                           and item['excerpt'] in (self.worktree / item['path']).read_text()
                           and isinstance(item.get('conclusion'), str) and bool(item['conclusion'].strip())
                           for item in inspections))
        report = (directory / 'report.md').read_text()
        self.check('comment_original_report_scope', all(name in report for name in AUTHORED)
                   and all(word in report.lower() for word in ('deletion', 'must kill', 'skip')))
        self.check('comment_typed_report_summary', type(facts.get('deletion_count')) is int
                   and facts['deletion_count'] >= 0 and all(isinstance(facts.get(key), list) for key in (
                       'findings', 'restored_comments', 'must_kill', 'skips', 'encoding_offers',
                       'unenforced_constraints', 'open_work')))
        self.check('comment_no_frozen_revision_or_open_flags', facts['deletion_count'] == 0
                   and all(not facts[key] for key in ('findings', 'restored_comments', 'must_kill',
                                                     'encoding_offers', 'unenforced_constraints', 'open_work')))
        self.check('comment_frozen_skill_unchanged', {name: core.sha(self.worktree / name) for name in AUTHORED} == self.skill_hashes)
        self.worker_native['comment-review'] = dict(audit, audit_completed=True, report_only=True,
                                                    reviewed_file_count=len(inspections))
        self.task_facts.append({'case': 'comment-review', 'role': 'judgment and prose',
                                'task_id_sha256': text_sha(task['task_id']), 'model': worker['model'],
                                'effort': worker.get('effort'), 'harness': worker['harness'],
                                'argv_sha256': text_sha(json.dumps(task['argv'])),
                                'result_sha256': core.sha(Path(task['result_path'])),
                                'nonce_validated': True, 'working_session_captured': True})
        return facts

    def delivered_comment_report(self):
        reports = []
        for task in self.tasks.values():
            directory = Path(task['task_dir']).resolve()
            if (task.get('worker') != self.comment_worker or task.get('cwd') != str(self.worktree)
                    or self.task_root.resolve() not in directory.parents):
                continue
            state = core.read_json(directory / 'state.json')
            if state.get('state') == 'done' and state.get('closed') is True:
                report = directory / 'report.md'
                if report.resolve() == report and report.is_file():
                    reports.append(report)
        return reports[0] if len(reports) == 1 else None

    def command_allowed(self, command):
        argv = support.literal(command)
        if not argv or any(word in ('--no-verify', '--no-gpg-sign') for word in argv):
            return False
        binary = Path(argv[0]).name
        if binary in ('python', 'python3'):
            words = argv[1:]
            if words[:1] == ['-B']:
                words = words[1:]
            if len(words) < 2:
                return False
            script = (self.worktree / words[0]).resolve()
            if script == self.guidance / 'scripts/quick_validate.py':
                return words[1:] == [str(self.worktree / SKILL)]
            return script == self.bundle / 'skills/agent-workers/scripts/agent-workers.py' and words[1] in ('run', 'wait', 'list', 'close', 'stats', 'detect')
        if binary == 'git':
            words = argv[1:]
            if words[:1] == ['-C'] and len(words) > 2:
                target = Path(words[1])
                if target.is_absolute() and target.resolve() in {case['cwd'] for case in self.cases.values()}:
                    status = words[2:]
                    return (bool(status) and status[0] == 'status'
                            and len(status[1:]) == len(set(status[1:]))
                            and set(status[1:]) <= {'--short', '--branch'})
                if target.resolve() != self.worktree:
                    return False
                words = words[2:]
            if not words:
                return False
            if words[0] in ('status', 'diff', 'show', 'log', 'blame', 'rev-parse', 'rev-list', 'diff-tree', 'ls-files', 'ls-remote'):
                return not any(word.startswith('--output') for word in words)
            if words[0] == 'add':
                files = [word for word in words[1:] if word != '--']
                return bool(files) and all(word in AUTHORED for word in files)
            if words[0] == 'commit':
                return '-n' not in words[1:]
            if words[0] == 'push':
                return [word for word in words[1:] if word not in ('-u', '--set-upstream')] == ['origin', self.branch]
            return words == ['branch', '--show-current'] or words == ['remote', 'get-url', 'origin']
        if binary in ('gh', 'origin'):
            if argv[1:3] == ['pr', 'create']:
                return ('--base' in argv and argv.index('--base') + 1 < len(argv) and argv[argv.index('--base') + 1] == self.args.base_ref
                        and '--draft' not in argv and ('--head' not in argv or argv.index('--head') + 1 < len(argv)
                             and argv[argv.index('--head') + 1] == self.branch)
                        and ('--repo' not in argv or argv.index('--repo') + 1 < len(argv)
                             and argv[argv.index('--repo') + 1] == self.args.forge_repo))
            return argv[1:3] in (['pr', 'view'], ['pr', 'list'], ['repo', 'view'])
        if binary == 'sha256sum':
            authored = len(argv) in (2, 3) and all((self.worktree / word).resolve() in {self.worktree / name for name in AUTHORED} for word in argv[1:])
            report = self.delivered_comment_report()
            return authored or report is not None and argv == ['sha256sum', str(report)]
        return argv in (['command', '-v', 'origin'], ['which', 'origin'], ['pwd']) or binary == 'cat' and len(argv) == 2 and not argv[1].startswith('-')

    def verify(self):
        rows = self.scan()
        self.check('three_fresh_delivered_closed_tasks', len(rows) == 3
                   and all(state.get('state') == 'done' and state.get('closed') is True for _, state in rows))
        tasks = [task for task, _ in rows]
        forward_tasks = [task for task in tasks if task.get('cwd') in {str(case['cwd']) for case in self.cases.values()}]
        comment_tasks = [task for task in tasks if task.get('cwd') == str(self.worktree)]
        self.check('exact_two_usage_one_comment_review', len(forward_tasks) == 2 and len(comment_tasks) == 1)
        paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_controller_native_session', len(paths) == 1)
        self.native = core.audit_pi(paths[0], self.session, self.worktree, self.wall_started, self.spec,
                                    [self.bundle / 'skills' / name for name in READS], [], tasks, self.bundle,
                                    allowed_artifact_hashes=((Path(comment_tasks[0]['task_dir']) / 'report.md'),))
        self.check('controller_native_model_effort_reads_delivery', all(check['ok'] for check in self.native['checks']))
        events, all_events = self.native_events(paths[0]), self.native_events(paths[0], include_errors=True)
        self.check('controller_authorized_literal_commands', all(self.command_allowed(e['args'].get('command', '')) for e in all_events if e['name'] == 'bash'))
        launches, deliveries = core.workflow_launches(events, tasks, self.worktree, self.bundle)
        self.check('all_forward_launches_deliveries_bound', set(launches) == set(deliveries) == {task['task_id'] for task in tasks})
        first = min(event['call_row'] for event in launches.values())
        authored = []
        for event in all_events:
            if event['name'] not in ('write', 'edit'):
                continue
            value = event['args'].get('path')
            self.check('controller_write_path_known', isinstance(value, str))
            target = (self.worktree / value).resolve()
            if target in {self.worktree / name for name in AUTHORED}:
                self.check('lead_authors_before_forward_freeze', event['successful'] and event['result_row'] < first)
                authored.append(event)
            else:
                self.check('controller_no_source_ledger_or_guidance_fabrication', self.artifacts in target.parents)
        self.check('lead_authored_both_complete_resources', {str((self.worktree / event['args']['path']).resolve().relative_to(self.worktree)) for event in authored} == set(AUTHORED))
        checklist = self.written(events, 'checklist.md', before=min(e['call_row'] for e in authored))
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/authoring-a-skill.md').read_text(), re.M)
        self.check('exact_original_four_step_checklist', len(steps) == 4 and re.findall(r'^\d+\. (.+)$', checklist['args']['content'], re.M) == steps)
        for resource in READS[:5]:
            self.check('initial_full_read_' + resource.replace('/', '_'), bool(core.workflow_reads(events, self.worktree,
                       self.bundle / 'skills' / resource, before=checklist['call_row'])))
        creator_reads = core.workflow_reads(events, self.worktree, self.guidance / 'SKILL.md', before=min(e['call_row'] for e in authored))
        self.check('actual_creator_guidance_read_before_authoring', bool(creator_reads))
        self.validate_structure()
        self.check('observed_authored_skill_frozen', bool(self.skill_hashes)
                   and {name: core.sha(self.worktree / name) for name in AUTHORED} == self.skill_hashes)
        frozen = self.written(events, 'frozen-skill.json', before=first, after=max(e['result_row'] for e in authored))
        self.check('native_frozen_skill_fingerprint', json.loads(frozen['args']['content']) == self.skill_hashes)
        validations = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if argv and Path(argv[0]).name in ('python', 'python3'):
                words = argv[1:]
                if words[:1] == ['-B']:
                    words = words[1:]
                if (words == [str(self.guidance / 'scripts/quick_validate.py'), str(self.worktree / SKILL)]
                        and event['output'].strip() == 'Skill is valid!' and event['call_row'] > max(e['result_row'] for e in authored)
                        and event['result_row'] < first):
                    validations.append(event)
        self.check('native_actual_creator_validation', len(validations) == 1)
        authored_reads = []
        for name in AUTHORED:
            reads = core.workflow_reads(events, self.worktree, self.worktree / name,
                                        after=max(e['result_row'] for e in authored), before=first)
            self.check('lead_full_authored_read_' + Path(name).name, bool(reads))
            authored_reads.append(reads[0])
        self.stage('authoring_1_guidance_voice', [checklist, creator_reads[0], *authored])
        self.stage('authoring_2_validation', [validations[0], frozen, *authored_reads])
        used, report_reads = set(), []
        for task in forward_tasks:
            label = next((name for name, case in self.cases.items() if task.get('cwd') == str(case['cwd'])), None)
            self.check('unique_forward_case_assignment', label is not None and label not in used)
            used.add(label)
            expected = self.forward_brief(label).rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
                result_path=Path(task['result_path']), task_id=task['task_id'], nonce=task['nonce'])
            self.check('blind_realistic_immutable_forward_brief', Path(task['brief_path']).read_text() == expected)
            result = core.read_json(Path(task['result_path']))
            self.check('forward_report_listed', 'report.md' in result.get('files', []))
            for filename in ['result.json', *result.get('files', [])]:
                path = (Path(task['task_dir']) / filename).resolve()
                self.check('forward_artifact_scope', Path(task['task_dir']).resolve() in path.parents)
                reads = core.workflow_reads(events, self.worktree, path, after=deliveries[task['task_id']]['result_row'])
                self.check('all_forward_artifacts_read_after_done', bool(reads))
                report_reads.append(reads[0])
            self.audit_forward(task, label)
        self.check('both_fresh_forward_cases', used == set(self.cases))
        self.stage('authoring_3_real_forward_usage', [*(launches[t['task_id']] for t in forward_tasks),
                   *(deliveries[t['task_id']] for t in forward_tasks), *report_reads])
        comment = comment_tasks[0]
        launch, delivery = launches[comment['task_id']], deliveries[comment['task_id']]
        self.check('comment_review_after_both_forward_deliveries_reads',
                   max(event['result_row'] for event in report_reads) < launch['call_row'])
        for resource in ('no-comments/SKILL.md', 'pstack-herdr/references/agents/comment-sicko.md'):
            self.check('comment_lead_guidance_before_delegation_' + resource, bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=launch['call_row'])))
        comment_reads = []
        for name in ('result.json', 'report.md', 'review.json'):
            reads = core.workflow_reads(events, self.worktree, Path(comment['task_dir']) / name,
                                        after=delivery['result_row'])
            self.check('comment_lead_complete_delivered_read_' + name, bool(reads))
            comment_reads.append(reads[0])
        report_path = (Path(comment['task_dir']) / 'report.md').resolve()
        hash_argv = ['sha256sum', str(report_path)]
        hash_calls = [event for event in all_events if event['name'] == 'bash'
                      and support.literal(event['args'].get('command', '')) == hash_argv]
        self.check('comment_report_hash_after_actual_delivery', bool(hash_calls)
                   and all(event['call_row'] > delivery['result_row'] for event in hash_calls))
        hash_results = [event for event in hash_calls if event['successful']
                        and event['output'].strip() == core.sha(report_path) + '  ' + str(report_path)]
        self.check('comment_actual_native_report_hash', bool(hash_results))
        facts = self.audit_comment(comment)
        disposition = self.written(events, 'comment-review.json', after=max(event['result_row'] for event in comment_reads))
        self.check('comment_native_report_hash_before_disposition', any(
            event['result_row'] < disposition['call_row'] for event in hash_results))
        resolved = json.loads(disposition['args']['content'])
        self.check('comment_lead_actual_disposition', resolved.get('task_id') == comment['task_id']
                   and resolved.get('report_sha256') == core.sha(Path(comment['task_dir']) / 'report.md')
                   and resolved.get('decision') == 'accept' and isinstance(resolved.get('summary'), str)
                   and bool(resolved['summary'].strip()) and isinstance(resolved.get('findings_assessment'), list)
                   and not resolved['findings_assessment']
                   and all(resolved.get(key) == facts[key] for key in (
                       'deletion_count', 'restored_comments', 'skips', 'encoding_offers',
                       'unenforced_constraints', 'open_work'))
                   and all(resolved.get(key) == [] for key in ('reruns', 'architect_sketch', 'fixes', 'encodings')))
        self.comment_disposition = disposition['args']['content']
        self.stage('no_comments_fresh_review', [launch, delivery, *comment_reads, disposition])
        self.verify_pr(events, all_events, disposition['result_row'])

    def verify_pr(self, events, all_events, reports_done):
        self.check('clean_owned_integration_branch', not self.git('status', '--porcelain=v1', '--untracked-files=all')
                   and self.git('branch', '--show-current') == self.branch)
        commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('one_ordered_skill_commit', len(commits) == 1 and self.git('rev-parse', commits[0] + '^') == self.base)
        head = commits[0]
        self.check('exact_two_file_commit_scope', set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', head).splitlines()) == set(AUTHORED))
        self.check('app_source_and_baseline_unchanged', {name: core.sha(self.worktree / name) for name in APP} == self.app_hashes)
        for name in AUTHORED:
            actual = subprocess.run(['git', '-C', str(self.worktree), 'show', head + ':' + name], capture_output=True, timeout=20, check=True).stdout
            self.check('committed_skill_matches_forward_tested_bytes', hashlib.sha256(actual).hexdigest() == self.skill_hashes[name])
        commit_events, pushes, creates, views = [], [], [], []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if not argv:
                continue
            if argv[0] == 'git' and 'commit' in argv:
                commit_events.append(event)
            if argv[0] == 'git' and 'push' in argv:
                pushes.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'create']:
                creates.append(event)
            if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']:
                views.append(event)
        self.check('single_native_commit_push_create', len(commit_events) == len(pushes) == len(creates) == 1)
        commit, push, create = commit_events[0], pushes[0], creates[0]
        review = self.written(events, 'review.json', before=commit['call_row'], after=reports_done)
        self.check('native_reviewed_commit_output', bool(json.loads(review['args']['content']).get('decision')) and head[:7] in commit['output'])
        diff = self.git('diff', self.base, 'HEAD')
        diffs = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if len(argv) > 3 and argv[:2] == ['git', '-C'] and Path(argv[2]).resolve() == self.worktree:
                argv = ['git', *argv[3:]]
            if (argv[:2] == ['git', 'diff'] and patch_headers(event['output']).strip() == patch_headers(diff).strip()
                    and reports_done < event['call_row'] and event['result_row'] < review['call_row']):
                diffs.append(event)
        self.check('native_full_diff_review', bool(diffs))
        for resource in READS[5:]:
            self.check('pr_guidance_before_review_' + resource.replace('/', '_'), bool(core.workflow_reads(events, self.worktree,
                       self.bundle / 'skills' / resource, before=review['call_row'])))
        forge_choice = self.written(events, 'forge.json', before=min(e['call_row'] for e in creates + views))
        chosen = json.loads(forge_choice['args']['content'])
        discovery = [e for e in all_events if e['name'] == 'bash' and support.literal(e['args'].get('command', '')) in
                     (['command', '-v', 'origin'], ['which', 'origin']) and e['result_row'] < forge_choice['call_row']]
        self.check('actual_single_forge_selection', bool(discovery) and chosen.get('forge') in ('origin', 'gh') and chosen.get('reason')
                   and all(support.literal(e['args']['command'])[0] == chosen['forge'] for e in creates + views))
        if chosen['forge'] == 'origin':
            self.check('origin_available', discovery[0]['successful'] and bool(discovery[0]['output'].strip()))
        elif discovery[0]['successful'] and discovery[0]['output'].strip():
            self.check('actual_origin_resolution_fallback', any(e['name'] == 'bash' and support.literal(e['args'].get('command', ''))[:1] == ['origin']
                       and not e['successful'] and e['result_row'] < forge_choice['call_row'] for e in all_events))
        create_argv = support.literal(create['args']['command'])
        self.check('ready_creation_order', commit['result_row'] < push['call_row'] and push['result_row'] < create['call_row']
                   and '--draft' not in create_argv and (chosen['forge'] != 'origin' or create_argv[-2:] == ['--status', 'open']))
        readback = [e for e in views if e['call_row'] > create['result_row'] and head in e['output']
                    and self.branch in e['output'] and self.args.base_ref in e['output']]
        self.check('native_real_head_base_readback', bool(readback))
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        self.check('only_owned_remote_branch_added', sorted(remote) == sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch]))
        current = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                             'number,state,headRefName,baseRefName,isDraft')
        added = [pr for pr in current if pr['number'] not in {pr['number'] for pr in self.prs_before}]
        self.check('only_one_ready_child_added', len(added) == 1 and all(pr in current for pr in self.prs_before))
        self.pr = self.forge('pr', 'view', str(added[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('independent_ready_unmerged_child_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        parent = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                            'state,isDraft,headRefName,headRefOid,baseRefName')
        self.check('original_parent_pr_unchanged', parent == self.parent_pr)
        reply = self.written(events, 'reply.md', after=readback[-1]['result_row'])
        self.check('reply_links_verified_real_pr', self.pr['url'] in reply['args']['content'])
        self.check('reply_preserves_actual_no_comments_summary', 'No-comments' in reply['args']['content']
                   and self.comment_disposition in reply['args']['content'])
        self.stage('opening_a_pr', [review, forge_choice, commit, push, create, *readback, reply])
        self.stage('authoring_4_opening_a_pr', [create, *readback, reply])

    def finish(self):
        cleanup_ok = True
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
            core.Run.scan(self)
        except Exception:
            self.categories.append('owned_task_snapshot_failed')
        for task in self.tasks.values():
            try:
                if task['task_id'] in self.worker_sessions:
                    path = self.scoped_session(task)
                    shutil.copy2(path, self.directory / ('retained-' + task['task_id'] + '.jsonl'))
            except Exception:
                self.categories.append('owned_worker_trace_snapshot_failed')
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
        for pane in ([self.pane] if self.pane else []) + [task['pane_id'] for task in self.tasks.values()]:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env, capture_output=True, text=True, timeout=15)
                error = json.loads(proc.stdout or proc.stderr).get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if proc.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        after, config_after = {}, None
        integrity = fixture_integrity = guidance_integrity = settings_integrity = False
        try:
            after = support.identity()
            config_after = core.sha(self.config_path)
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            integrity = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                         and self.git('rev-parse', 'HEAD', repo=ROOT, cleanup=True) == self.revision
                         and self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT, cleanup=True) == self.source_status
                         and (not copied.exists() or core.sha(copied) == self.config_hash))
            if self.bundle.exists():
                integrity = integrity and all(core.sha(self.bundle / name) == digest for name, digest in self.hashes.items() if name.startswith('skills/'))
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
            guidance_integrity = (bool(self.guidance_hashes) and fingerprint(self.creator_source) == self.guidance_hashes
                                  and (not self.guidance.exists() or fingerprint(self.guidance) == self.guidance_hashes))
            settings_integrity = {label: core.sha(path) if path.is_file() else None for label, path in self.settings_paths.items()} == self.settings_hashes
            if self.skill_hashes:
                integrity = integrity and {name: core.sha(self.worktree / name) for name in AUTHORED} == self.skill_hashes
        except Exception:
            pass
        self.checks += [{'name': 'public_source_config_bundle_skill_integrity', 'ok': integrity},
                        {'name': 'original_fixture_checkout_unchanged', 'ok': fixture_integrity},
                        {'name': 'original_and_copied_creator_guidance_unchanged', 'ok': guidance_integrity},
                        {'name': 'user_pi_settings_unchanged', 'ok': settings_integrity},
                        {'name': 'owned_panes_absent', 'ok': cleanup_ok}]
        passed = bool(self.checks) and not self.categories and all(check.get('ok') is True for check in self.checks)
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory = {name: 'not_run' for name in core.INVENTORY}
        inventory['authoring-a-skill'] = verdict
        if 'opening_a_pr' in self.stage_proof:
            inventory['opening-a-pr'] = verdict
        if not self.native:
            paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(paths) == 1:
                self.native = {'sha256': core.sha(paths[0]), 'audit_completed': False}
        receipt = {
            'schema': 'horch/authoring-playbook-e2e/v1', 'verdict': 'pass' if passed else 'fail',
            'workflow_verdict': verdict, 'full_inventory_verdict': 'not_run', 'inventory': inventory,
            'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
            'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
            'pi_settings_sha256': self.settings_hashes, 'creator_guidance_sha256': self.guidance_hashes,
            'fixture_source_sha256': self.app_hashes, 'authored_skill_sha256': self.skill_hashes,
            'controller': {key: self.spec.get(key) for key in ('harness', 'provider', 'model', 'effort')},
            'native_transcript': self.native, 'forward_native': self.worker_native,
            'native_stages': self.stage_proof, 'tasks': self.task_facts, 'checks': self.checks,
            'outcomes': {'creator_guidance_applied': 'authoring_1_guidance_voice' in self.stage_proof,
                         'creator_validation_verified': 'authoring_2_validation' in self.stage_proof,
                         'independent_forward_usage_verified': 'authoring_3_real_forward_usage' in self.stage_proof,
                         'mandatory_comment_sicko_review_verified': 'no_comments_fresh_review' in self.stage_proof,
                         'automatic_skill_discovery_verified': False,
                         'authoring_complete': passed, 'ready_child_pr_verified': passed and self.pr is not None},
            'failure_categories': self.categories, 'last_phase': self.phase,
            'seconds': round(time.monotonic() - self.started, 3),
            'limitations': [
                'Explicit independent forward usage proves the exercised skill-guided operations, not native automatic skill discovery or causal improvement.',
                'Only this Authoring a skill and Opening a PR route is attempted; the full inventory is not run.',
                'Forward workers are explicit existing configured selections; reused models provide independent processes rather than cross-model validation.',
                'Only default Pi cwd-scoped session storage and captured canonical UUIDs are supported; overrides or unavailable traces remain unresolved.',
                'The creator validator checks structure, not authoring quality; the real CLI cases supply separate behavior evidence.',
                'Authored skill revisions after forward use require a new explicitly initiated run; no failed run is promoted.',
                'One configured judgment and prose worker supplies the mandatory report-only CommentSicko review; any required frozen-file revision or deeper follow-up leaves this bounded run unresolved.',
                'Private artifacts, owned worktrees/branch and ready PR are retained; merges and auto-merge are never authorized.',
            ],
        }
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='existing configured Pi lead worker')
    parser.add_argument('--success-worker', required=True, help='explicit existing configured Pi worker for first independent usage')
    parser.add_argument('--rollback-worker', required=True, help='explicit existing configured Pi worker for second independent usage')
    parser.add_argument('--repo', type=Path, default=ROOT, help='trusted orchestrator source root')
    parser.add_argument('--fixture-repo', type=Path, required=True, help='existing clean private invoice fixture clone')
    parser.add_argument('--forge-repo', required=True, help='private fixture owner/name')
    parser.add_argument('--base-ref', required=True, help='existing exact remote parent branch, never trunk')
    parser.add_argument('--parent-pr', type=int, required=True, help='existing ready open PR whose head is base-ref')
    parser.add_argument('--creator-guidance', type=Path, default=Path.home() / '.codex/skills/.system/skill-creator/SKILL.md',
                        help='existing harness skill-creator SKILL.md; complete resources copied privately at run time')
    parser.add_argument('--output', type=Path, required=True, help='private external artifact parent')
    parser.add_argument('--caller-pane', required=True, help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=3000, help='overall deadline; no retry loops')
    args = parser.parse_args()
    for key in ('repo', 'fixture_repo', 'creator_guidance', 'output'):
        setattr(args, key, getattr(args, key).expanduser().resolve())
    if args.repo != ROOT:
        parser.error('--repo must identify this driver source checkout')
    if any(args.output == root or root in args.output.parents for root in (ROOT, args.fixture_repo, args.creator_guidance.parent)):
        parser.error('--output must be outside source, fixture and creator guidance directories')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.forge_repo):
        parser.error('--forge-repo must be owner/name')
    if args.parent_pr <= 0 or args.base_ref in ('main', 'master') or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', args.base_ref) or '..' in args.base_ref:
        parser.error('provide a positive existing parent PR and non-trunk base ref')
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
