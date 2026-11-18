#!/usr/bin/env python3
"""Live two-session Pause safely / Session pickup E2E, with private evidence.

Uses unchanged configured Pi settings, one local disposable feature branch,
and owned background tabs. Never pushes, opens a PR, merges, or changes trust.
Retains the worktree, raw sessions, briefs, and rerunnable CLI input artifacts.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import traceback

import playbook_loop as base
import playbook_cases as cases

MONEY_INPUTS = [
    {'quantity': 7, 'unit_price_cents': 137, 'discount_bp': 250},
    {'quantity': 3, 'unit_price_cents': 333, 'discount_bp': 3333},
    {'quantity': 1, 'unit_price_cents': 101, 'discount_bp': 5000},
    {'quantity': 5, 'unit_price_cents': 101, 'discount_bp': 10000},
    {'quantity': 0, 'unit_price_cents': 999, 'discount_bp': 250},
]
LINE_CLI = '''import json
import sys
from money import line_total

for raw in sys.stdin:
    if raw.strip():
        row = json.loads(raw)
        print(json.dumps({"total_cents": line_total(
            row["quantity"], row["unit_price_cents"], row["discount_bp"])}))
'''
CONTRACT = '''# Invoice continuity goal

The originating workstream is Feature. This fixture supplies only a bounded
implementation checkpoint, not evidence of earlier Feature grounding or design.
Implement integer half-up rounding independently for each invoice line, then
verify the complete importer using persisted state and two input files.
The implementation checkpoint completes only money.py and the money-only
JSON-lines observation. Complete importer behavior verification stays pending.
No PR, push, merge, production deployment or configuration change is authorized.
Any later delivery workflow remains outside this continuity evaluation.
'''
NOTE_HEADINGS = ('Goal', 'Progress', 'Verified', 'Pending', 'Current state',
                 'Next action', 'Key files', 'Gotchas')
PICKUP_VERDICTS = ('continue the execution', 'ship a finished recommendation',
                   'ratify or override a prior conclusion', 'postmortem a failed run')
NATIVE_PROTOCOL = '''This evaluator supports only the native read, bash, write, edit, grep, find and
ls tools. Do not use codemode or another tool wrapper: its nested calls are not
visible to this auditor. Use separate native calls for report reads and brief
writes, even when combining the data would be convenient.'''


def digest_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def all_sources():
    return dict(base.source_hashes(), **{'e2e/pause_pickup.py': base.sha(Path(__file__))})


def money(row):
    return int((Decimal(row['quantity']) * row['unit_price_cents']
                * (10000 - row['discount_bp']) / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def native_events(path):
    """Base audit validates binding/branch/tool identity before these are used."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    calls, events, pending, users = [], [], {}, []
    for index, row in enumerate(rows):
        message = row.get('message', {})
        if message.get('role') == 'user':
            users.append({'row': index, 'text': base.text_content(message)})
        elif message.get('role') == 'assistant':
            for block in message.get('content', []):
                if block.get('type') == 'toolCall':
                    call = {'name': block['name'], 'args': block['arguments'], 'call_row': index}
                    calls.append(call)
                    pending[block['id']] = call
        elif message.get('role') == 'toolResult':
            call = pending.pop(message.get('toolCallId'), None)
            if call is None:
                raise base.Failure('native_result_unbound')
            events.append(dict(call, result_row=index, output=base.text_content(message),
                               is_error=message.get('isError') is not False))
    if pending:
        raise base.Failure('native_result_missing')
    return rows, calls, events, users


def direct_cli(command, cwd):
    lines = command.strip().splitlines()
    if not lines:
        return None
    first, stdin = lines[0], None
    heredoc = re.search(r"\s*<<\s*(['\"])([A-Za-z_]\w*)\1\s*$", first)
    if heredoc:
        if len(lines) < 3 or lines[-1].strip() != heredoc[2]:
            return None
        first, stdin = first[:heredoc.start()], '\n'.join(lines[1:-1])
    elif len(lines) != 1:
        return None
    argv = base.literal_python_argv(first)
    return ((cwd / argv[1]).resolve(), argv[2:], stdin) if argv else None


def git_command(event, worktree):
    if event['name'] != 'bash':
        return None
    command = event['args'].get('command', '')
    if any(token in command for token in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or argv.pop(0) != 'git':
        return None
    location = worktree
    while argv and argv[0] in ('-C', '-c'):
        if len(argv) < 2:
            return None
        option, value = argv[:2]
        argv = argv[2:]
        if option == '-C':
            location = Path(value).resolve()
    return argv if location == worktree else None


def clean_status_witness(event, worktree):
    # Pi emits this exact marker for successful empty bash stdout. Accept it only
    # for the literal clean-status command, never as generic empty tool output.
    return (not event['is_error'] and git_command(event, worktree) == ['status', '--porcelain']
            and event['output'].strip() in {'', '(no output)'})


def successful(events):
    return [event for event in events if not event['is_error']]


def first_write(events, cwd, path, after=-1, before=float('inf'), final=True):
    return next(iter(base.workflow_writes(successful(events), cwd, path,
                                          after=after, before=before, final=final)), None)


def full_read(events, cwd, path, after=-1, before=float('inf')):
    return next(iter(base.workflow_reads(successful(events), cwd, path,
                                         after=after, before=before)), None)


def fixture_row(identity, quantity, price, discount=0):
    return {'id': identity, 'quantity': quantity, 'unit_price_cents': price, 'discount_bp': discount}


def build_import_cases(root, script):
    root.mkdir(parents=True, exist_ok=True)
    original = fixture_row('z-prev', 2, 1000, 500)
    original['total_cents'] = money(original)
    good_a = [fixture_row('r-21', 7, 137, 250), fixture_row('r-03', 3, 333, 3333)]
    good_b = [fixture_row('r-11', 1, 199, 1), fixture_row('r-half', 1, 101, 5000),
              fixture_row('r-05', 0, 999, 250)]
    scenarios = {
        'success': (good_a, good_b, None),
        'duplicate-old': ([fixture_row('new-before-old', 1, 101, 5000)], [fixture_row('z-prev', 1, 100)], 'duplicate transaction: z-prev'),
        'duplicate-within': ([fixture_row('dup-within', 1, 101), fixture_row('dup-within', 2, 109)], good_b, 'duplicate transaction: dup-within'),
        'duplicate-across': ([fixture_row('dup-across', 1, 101)], [fixture_row('dup-across', 2, 109)], 'duplicate transaction: dup-across'),
        'late-validation': (good_a, [fixture_row('valid-last-file', 1, 199), fixture_row('invalid-late', -1, 199)], 'invalid money field'),
    }
    expectations, manifest = {}, []
    for label, (first, second, error) in scenarios.items():
        directory = root / label
        directory.mkdir()
        store, a, b = (directory / filename for filename in ('store.json', 'first.json', 'second.json'))
        initial_store = directory / 'initial-store.json'
        for path, value in ((store, [original]), (initial_store, [original]), (a, first), (b, second)):
            path.write_text(json.dumps(value, sort_keys=True) + '\n')
        final = [original, *[dict(row, total_cents=money(row)) for row in first + second]] if error is None else [original]
        expected = {'error': error} if error else {'count': len(final), 'total_cents': sum(row['total_cents'] for row in final)}
        expectations[label] = {'args': ['import', str(store), str(a), str(b)], 'store': store,
                               'output': expected, 'exit_code': 2 if error else 0, 'final': final,
                               'initial_sha256': base.sha(store), 'initial_store': initial_store}
        manifest.append({'name': label, 'arguments': ['import', str(store), str(a), str(b)],
                         'store': str(store), 'reset_from': str(initial_store), 'purpose': label})
    export = sorted(expectations['success']['final'], key=lambda row: row['id'])
    expectations['export'] = {'args': ['export', str(root / 'success/store.json')],
                              'output': export, 'exit_code': 0}
    manifest.append({'name': 'export', 'arguments': expectations['export']['args'], 'purpose': 'deterministic export after success'})
    (root / 'manifest.json').write_text(json.dumps({'script': str(script), 'cases': manifest}, indent=2) + '\n')
    return expectations


class ContinuityRun(base.Run):
    def __init__(self, args):
        args.scenario = 'pause-pickup'
        super().__init__(args)
        self.case = {'expected_roles': ['feature, refactoring']}
        self.branch = 'e2e/pause-' + secrets.token_hex(6)
        self.fixture = self.worktree / '.pause-pickup-fixture'
        self.money_relative = '.pause-pickup-fixture/money.py'
        self.phases = {}
        self.phase_receipts = {}
        self.controllers = []
        self.current = None
        self.seed = self.wip = self.money_blob = None
        self.expectations = {}
        self.ordered = {}
        self.started_tasks = set()
        self.note = self.artifacts / 'resume.md'
        self.pause_reply = self.artifacts / 'pause-reply.md'
        self.pickup_reply = self.artifacts / 'pickup-reply.md'
        self.route = self.artifacts / 'pickup-route.json'
        self.pause_checklist = self.artifacts / 'pause-checklist.md'
        self.pickup_checklist = self.artifacts / 'pickup-checklist.md'
        self.checkpoint_reply = self.artifacts / 'checkpoint.md'
        self.source_files = {}
        self.suite_hashes = {}
        self.phase_success = {'pause-safely': False, 'session-pickup': False}
        self.implementation_proof = {}
        self.frozen_note_sha256 = self.frozen_trail_sha256 = None

    def preflight(self):
        super().preflight()
        self.hashes = all_sources()
        selection = self.config.get('roles', {}).get('feature, refactoring')
        self.check('single_configured_implementation_worker', isinstance(selection, str)
                   and selection in self.config['workers'])
        self.writer = selection

    def git(self, *args, cleanup=False):
        return self.call(['git', '-C', self.worktree, *args], cleanup=cleanup).strip()

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(base.ROOT / 'skills', self.bundle / 'skills',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.call(['git', '-C', self.args.repo, 'worktree', 'add', '-b', self.branch,
                   self.worktree, 'HEAD'])
        self.fixture.mkdir()
        sources = dict(cases.LEDGER_FILES)
        sources['money.py'] = 'def line_total(quantity, unit_price_cents, discount_bp):\n    raise NotImplementedError("Money rounding is pending")\n'
        sources.update({'line_cli.py': LINE_CLI, 'contract.md': CONTRACT})
        for filename, content in sources.items():
            (self.fixture / filename).write_text(content)
        self.git('add', '--', '.pause-pickup-fixture')
        self.git('commit', '-m', 'Add disposable invoice continuity fixture')
        self.seed = self.git('rev-parse', 'HEAD')
        self.source_files = {name: base.sha(self.fixture / name) for name in sources if name != 'money.py'}
        self.expectations = build_import_cases(self.artifacts / 'import-cases', self.fixture / 'cli.py')
        self.suite_hashes = {str(path.relative_to(self.artifacts / 'import-cases')): base.sha(path)
                             for path in (self.artifacts / 'import-cases').rglob('*')
                             if path.is_file() and path.name != 'store.json'}
        (self.directory / 'run-private.json').write_text(json.dumps({
            'worktree': str(self.worktree), 'branch': self.branch,
            'config_root': self.env['XDG_CONFIG_HOME'], 'state_root': self.env['XDG_STATE_HOME']}, indent=2) + '\n')
        self.check('seed_checkpoint_clean', not self.git('status', '--porcelain'))

    def begin(self, label):
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'],
                         '--cwd', self.worktree, '--label', 'continuity-' + label, '--no-focus',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'],
                         '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                         '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'],
                         '--env', 'GIT_CONFIG_GLOBAL=' + self.env['GIT_CONFIG_GLOBAL'],
                         '--env', 'PYTHONDONTWRITEBYTECODE=1')
        pane = tab['root_pane']['pane_id']
        controller = {'label': label, 'pane': pane, 'agent': 'continuity-' + label.lower() + '-' + secrets.token_hex(5),
                      'started_at': time.time(), 'session': {}, 'closed': False}
        self.controllers.append(controller)
        self.current = controller
        self.pane, self.agent, self.session = pane, controller['agent'], {}
        directory = self.directory / ('session-' + label)
        directory.mkdir()
        controller['session_dir'] = directory
        flags = base.horch.launch_args(self.spec, self.directory) + ['--session-dir', str(directory)]
        result = self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', pane,
                            '--timeout', '90000', '--', *flags)
        self.check('controller_' + label + '_started', result.get('type') == 'agent_started')
        deadline = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < deadline:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if entry.get('agent_status') == 'blocked':
                raise base.Failure('controller_start_blocked')
            if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi'
                    and session.get('value') and entry.get('agent_status') in ('idle', 'done')):
                self.session = controller['session'] = session
                return
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise base.Failure('controller_session_not_ready')

    def prompt(self, label, message):
        (self.directory / (label + '-request.md')).write_text(message)
        self.phases[label] = {'requested_at': time.time()}
        result = self.herdr('agent', 'prompt', self.agent, message,
                            '--wait', '--until', 'working', '--timeout', '30000')
        self.check(label + '_prompt_acknowledged', result.get('type') == 'agent_prompted')
        self.monitor()
        self.current['session'] = self.session
        self.phases[label]['idle_at'] = time.time()
        if self.started_tasks:
            self.check(label + '_no_new_task', {task['task_id'] for task, _ in self.scan()} == self.started_tasks)

    def transcript(self, controller):
        candidates = list(controller['session_dir'].glob('*.jsonl'))
        self.check('controller_' + controller['label'] + '_native_unique', len(candidates) == 1)
        return candidates[0]

    def close_controller(self, controller):
        self.call(['herdr', 'pane', 'read', controller['pane'], '--source', 'recent', '--lines', '80'], cleanup=True)
        self.herdr('pane', 'close', controller['pane'], cleanup=True)
        self.check('controller_' + controller['label'] + '_closed', self.pane_absent(controller['pane']))
        controller['closed'] = True
        controller['closed_at'] = time.time()

    def pane_absent(self, pane):
        proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env,
                              capture_output=True, text=True, timeout=15)
        (self.directory / ('pane-check-' + secrets.token_hex(5) + '.json')).write_text(json.dumps(
            {'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}, indent=2))
        reply = json.loads(proc.stdout or proc.stderr)
        error = reply.get('error', {})
        code = error.get('code') if isinstance(error, dict) else error
        return proc.returncode != 0 and code in base.horch.MISSING_PANE_CODES

    def common(self):
        return [self.bundle / path for path in ('skills/poteto-mode/SKILL.md',
                'skills/pstack-herdr/SKILL.md', 'skills/pstack-herdr/references/herdr-tools.md',
                'skills/herdr-orchestrator/SKILL.md')]

    def audit_controller(self, controller, tasks, reads):
        path = self.transcript(controller)
        self.phase_receipts[controller['label']] = {'sha256': base.sha(path), 'audit_completed': False}
        audit = base.audit_pi(path, controller['session'], self.worktree,
                              controller['started_at'], self.spec,
                              [Path(p).resolve() for p in reads], [], tasks, self.bundle)
        self.check('controller_' + controller['label'] + '_native_prerequisites',
                   all(check['ok'] for check in audit['checks']))
        self.phase_receipts[controller['label']] = dict(audit, audit_completed=True)
        return native_events(path)

    def run_cli(self, script, args=(), stdin=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise base.Failure('overall_timeout')
        proc = subprocess.run([sys.executable, str(script), *map(str, args)], env=self.env,
                              cwd=self.worktree, input=stdin, capture_output=True,
                              text=True, timeout=min(30, remaining))
        (self.directory / ('cli-' + secrets.token_hex(5) + '.json')).write_text(json.dumps(
            {'argv': [str(script), *map(str, args)], 'returncode': proc.returncode,
             'stdout': proc.stdout, 'stderr': proc.stderr}, indent=2))
        return proc

    def implementation_checkpoint(self):
        records = self.scan()
        self.check('one_fresh_implementation_task', len(records) == 1)
        task, state = records[0]
        worker = self.config['workers'][self.writer]
        self.check('configured_nonce_bound_delivery', task['worker'] == self.writer
                   and task['cwd'] == str(self.worktree) and task['harness'] == worker['harness']
                   and task['model'] == worker['model']
                   and task['workspace_id'] == self.caller['workspace_id']
                   and Path(task['result_path']).resolve() == Path(task['task_dir']) / 'result.json'
                   and task['argv'] == base.horch.launch_args(worker, Path(task['task_dir']))
                   and state.get('state') == 'done' and state.get('closed') is True
                   and base.horch.validate_result(base.read_json(Path(task['result_path'])), task) == 'valid'
                   and base.read_json(Path(task['result_path'])).get('status') == 'completed')
        assignment = Path(task['brief_path']).read_text().split('## Worker rules', 1)[0]
        self.check('bounded_implementation_assignment',
                   'feature, refactoring' in assignment and self.writer in assignment
                   and re.search(r'\b(?:reason|because)\b', assignment, re.I)
                   and str(self.fixture / 'money.py') in assignment
                   and str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md') in assignment
                   and str(self.bundle / 'skills/poteto-mode/SKILL.md') in assignment
                   and re.search(r'\b(?:do not|must not|never)\s+(?:delegate|spawn|use\s+(?:native\s+)?subagents)|\bno\s+(?:delegation|subagents)', assignment, re.I))
        self.check('checkpoint_only_money_dirty', self.git('rev-parse', 'HEAD') == self.seed
                   and self.git('diff', '--name-only') == self.money_relative
                   and not self.git('diff', '--cached', '--name-only')
                   and self.git('status', '--porcelain') == 'M ' + self.money_relative)
        proc = self.run_cli(self.fixture / 'line_cli.py', stdin='\n'.join(json.dumps(row) for row in MONEY_INPUTS) + '\n')
        actual_money = [json.loads(line) for line in proc.stdout.splitlines()]
        self.check('checkpoint_integer_half_up_cli', proc.returncode == 0
                   and actual_money == [{'total_cents': money(row)} for row in MONEY_INPUTS]
                   and all(type(row.get('total_cents')) is int for row in actual_money))
        self.started_tasks = {task['task_id']}
        rows, calls, events, _ = self.audit_controller(self.current, [task], self.common()
            + [self.bundle / 'skills/poteto-mode/playbooks/feature.md'])
        observed = self.money_observation(events)
        self.check('checkpoint_actual_native_money_observation', observed is not None)
        launches, deliveries = base.workflow_launches(successful(events), [task], self.worktree, self.bundle)
        reports = base.workflow_report_reads(successful(events), task, self.worktree,
                                             deliveries.get(task['task_id']), before=observed['call_row'])
        checkpoint = first_write(events, self.worktree, self.checkpoint_reply, after=observed['result_row'])
        self.check('checkpoint_observation_follows_delivered_report', task['task_id'] in launches
                   and task['task_id'] in deliveries and bool(reports) and checkpoint is not None)
        self.implementation_proof = {'launch_call_row': launches[task['task_id']]['call_row'],
                                     'delivery_result_row': deliveries[task['task_id']]['result_row'],
                                     'report_read_result_row': reports[0][0]['result_row'],
                                     'money_observation_result_row': observed['result_row'],
                                     'checkpoint_write_result_row': checkpoint['result_row'],
                                     'dirty_money_sha256': base.sha(self.fixture / 'money.py')}
        self.check('checkpoint_pending_full_importer_not_run', not any(
            event['name'] == 'bash' and (invocation := direct_cli(event['args'].get('command', ''), self.worktree))
            and invocation[0] == self.fixture / 'cli.py' for event in events))
        self.check('checkpoint_report_records_pending_work', self.checkpoint_reply.is_file()
                   and 'pending' in self.checkpoint_reply.read_text().lower())
        self.checkpoint_rows = len(rows)
        self.checkpoint_task = task
        self.checkpoint_native = self.transcript(self.current)
        shutil.copy2(self.checkpoint_native, self.directory / 'session-A-checkpoint.jsonl')

    def money_observation(self, events):
        for event in successful(events):
            if event['name'] != 'bash':
                continue
            invocation = direct_cli(event['args'].get('command', ''), self.worktree)
            if not invocation or invocation[:2] != (self.fixture / 'line_cli.py', []):
                continue
            try:
                data = [json.loads(line) for line in (invocation[2] or '').splitlines()]
                output = [json.loads(line) for line in event['output'].splitlines()]
            except ValueError:
                continue
            if (data == MONEY_INPUTS and output == [{'total_cents': money(row)} for row in MONEY_INPUTS]
                    and all(type(row.get('total_cents')) is int for row in output)):
                return event
        return None

    def assert_source_files(self):
        self.check('nonmoney_fixture_sources_unchanged', all(
            base.sha(self.fixture / name) == value for name, value in self.source_files.items()))
        self.check('pending_suite_inputs_unchanged', all(
            base.sha(self.artifacts / 'import-cases' / name) == value for name, value in self.suite_hashes.items()))

    def verify_pause(self):
        self.wip = self.git('rev-parse', 'HEAD')
        self.money_blob = self.git('rev-parse', 'HEAD:' + self.money_relative)
        self.check('pause_one_wip_commit', self.git('rev-list', '--count', self.seed + '..HEAD') == '1'
                   and self.git('show', '-s', '--format=%s', 'HEAD').startswith('wip:')
                   and self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD') == self.money_relative
                   and self.git('rev-parse', 'HEAD^') == self.seed)
        self.check('pause_clean_local_branch', not self.git('status', '--porcelain')
                   and self.git('branch', '--show-current') == self.branch)
        committed_money = self.call(['git', '-C', self.worktree, 'show', 'HEAD:' + self.money_relative])
        self.check('pause_commits_verified_atomic_unit',
                   base.sha(self.fixture / 'money.py') == self.implementation_proof['dirty_money_sha256']
                   and digest_text(committed_money) == self.implementation_proof['dirty_money_sha256'])
        self.assert_source_files()
        self.check('pause_preserves_pending_import_cases', all(
            base.sha(expectation['store']) == expectation['initial_sha256']
            for expectation in self.expectations.values() if 'store' in expectation))
        content = self.git('show', 'HEAD:' + self.money_relative) + self.git('show', '-s', '--format=%B', 'HEAD')
        self.check('pause_commit_has_no_private_paths', not any(str(path) in content for path in
                   (Path.home(), self.directory, self.args.repo, self.worktree)))
        rows, calls, events, users = self.audit_controller(self.current, [self.checkpoint_task],
            self.common() + [self.bundle / 'skills/poteto-mode/playbooks/pause-safely.md'])
        requests = [user for user in users if user['row'] >= self.checkpoint_rows
                    and 'Pause safely now' in user['text']]
        self.check('pause_separate_explicit_user_request', len(requests) == 1)
        boundary = requests[0]['row']
        self.check('pause_starts_no_new_task', not any(
            call['call_row'] > boundary and (operation := base.literal_horch_command(
                call['name'], call['args'], self.worktree, self.bundle)) and operation[0] == 'run'
            for call in calls))
        pause_read = full_read(events, self.worktree,
                               self.bundle / 'skills/poteto-mode/playbooks/pause-safely.md', after=boundary)
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/pause-safely.md').read_text(), re.M)
        commits = [event for event in successful(events) if event['call_row'] > boundary
                   and (operation := git_command(event, self.worktree)) and operation[0] == 'commit'
                   and any(argument.startswith('wip:') for argument in operation)]
        self.check('pause_actual_local_wip_commit', len(commits) == 1 and 'wip:' in commits[0]['output'])
        commit = commits[0]
        checklist = first_write(events, self.worktree, self.pause_checklist, after=boundary, before=commit['call_row'], final=False)
        self.check('pause_original_four_stage_checklist', len(steps) == 4 and pause_read and checklist
                   and pause_read['result_row'] < checklist['call_row']
                   and all(step in checklist['args']['content'] for step in steps))
        note = first_write(events, self.worktree, self.note, after=commit['result_row'])
        reply = first_write(events, self.worktree, self.pause_reply, after=note['result_row'] if note else float('inf'))
        self.check('pause_durable_off_context_note', note and reply)
        note_text = self.note.read_text()
        self.check('pause_note_preserves_operational_state', all(
            (section := re.search(r'(?ms)^## ' + re.escape(heading) + r'\s*\n(.*?)(?=^## |\Z)', note_text))
            and section[1].strip() for heading in NOTE_HEADINGS)
                   and all(value in note_text for value in (self.wip, self.checkpoint_task['task_id'],
                       str(self.checkpoint_native), str(self.artifacts / 'import-cases/manifest.json'),
                       str(self.fixture / 'money.py'))))
        self.check('pause_note_preserves_originating_workstream',
                   re.search(r'\bFeature\b', note_text) is not None)
        clean = next((event for event in successful(events) if event['call_row'] > commit['result_row']
                      and event['result_row'] < reply['call_row']
                      and clean_status_witness(event, self.worktree)), None)
        self.check('pause_native_clean_state_checked', clean is not None)
        self.ordered['pause-safely'] = [
            {'step': 1, 'instruction': steps[0], 'explicit_request_row': boundary,
             'safe_checkpoint_native_rows': self.checkpoint_rows, 'pause_read_result_row': pause_read['result_row']},
            {'step': 2, 'instruction': steps[1], 'remote_actions': 0},
            {'step': 3, 'instruction': steps[2], 'commit_call_row': commit['call_row'],
             'commit_result_row': commit['result_row'], 'clean_state_result_row': clean['result_row']},
            {'step': 4, 'instruction': steps[3], 'note_result_row': note['result_row'], 'reply_result_row': reply['result_row']},
        ]
        self.guard_native(calls)

    def guard_native(self, calls):
        allowed_sessions = {path.resolve() for controller in self.controllers
                            for path in controller['session_dir'].glob('*.jsonl')}
        for call in calls:
            target = base.read_target(call['name'], call['args'], self.worktree)
            if target and target.suffix == '.jsonl' and target not in allowed_sessions:
                raise base.Failure('unscoped_session_read')
            arguments = json.dumps(call['args'])
            if call['name'] in {'read', 'bash', 'grep', 'find', 'ls'} and any(
                    fragment in arguments for fragment in ('.pi/agent/sessions', '.codex/sessions', '.cursor/projects')):
                raise base.Failure('unscoped_session_search')
            if call['name'] != 'bash':
                continue
            command = call['args'].get('command', '')
            operation = git_command(call, self.worktree)
            if operation and operation[0] not in {'status', 'diff', 'log', 'show', 'rev-parse', 'branch', 'add', 'commit'}:
                raise base.Failure('unauthorized_git_operation')
            if re.search(r'\b(?:gh|origin)\s+(?:pr|api|publish)|\b(?:mise|pi)\s+(?:trust|auth)|\bgit\s+push\b', command):
                raise base.Failure('unauthorized_external_or_trust_operation')

    def verify_pickup(self):
        self.check('pickup_no_duplicate_task', set(self.tasks) == self.started_tasks)
        self.check('pickup_prior_note_and_trail_unchanged', base.sha(self.note) == self.frozen_note_sha256
                   and base.sha(self.checkpoint_native) == self.frozen_trail_sha256)
        self.check('pickup_preserves_wip_and_money_blob', self.git('rev-parse', 'HEAD') == self.wip
                   and self.git('rev-parse', 'HEAD:' + self.money_relative) == self.money_blob
                   and self.git('branch', '--show-current') == self.branch
                   and not self.git('status', '--porcelain'))
        self.assert_source_files()
        reads = self.common() + [self.bundle / ('skills/' + skill + '/SKILL.md') for skill in
                 ('principle-prove-it-works',)] + [self.bundle / 'skills/poteto-mode/playbooks/session-pickup.md',
                                                self.bundle / 'skills/poteto-mode/playbooks/feature.md']
        _, calls, events, _ = self.audit_controller(self.current, [], reads)
        self.guard_native(calls)
        self.check('pickup_no_dispatch_or_repeated_money_probe', not any(
            (operation := base.literal_horch_command(call['name'], call['args'], self.worktree, self.bundle))
            and operation[0] == 'run' for call in calls)
            and not any(event['name'] == 'bash'
                        and (invocation := direct_cli(event['args'].get('command', ''), self.worktree))
                        and invocation[0] == self.fixture / 'line_cli.py' for event in events))
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/session-pickup.md').read_text(), re.M)
        pickup_read = full_read(events, self.worktree, self.bundle / 'skills/poteto-mode/playbooks/session-pickup.md')
        note = full_read(events, self.worktree, self.note)
        trail = self.trail_reads(events)
        self.check('pickup_reads_scoped_prior_trail_in_order', note and trail
                   and note['result_row'] < trail['head']['call_row'])
        raw_early = []
        for call in calls:
            target = base.read_target(call['name'], call['args'], self.worktree)
            touches = target == self.checkpoint_native
            if call['name'] == 'bash':
                command = call['args'].get('command', '')
                try:
                    argv = shlex.split(command)
                except ValueError:
                    argv = []
                touches = touches or (str(self.checkpoint_native) in command
                                      and not (argv and argv[0] in {'ls', 'stat'}))
            if (touches and call['call_row'] < trail['tail']['result_row']
                    and call['call_row'] not in {trail['head']['call_row'], trail['tail']['call_row']}):
                raw_early.append(call)
        self.check('pickup_metadata_and_last_messages_precede_scanning', not raw_early)
        checklist = first_write(events, self.worktree, self.pickup_checklist,
                                 before=min(note['call_row'], trail['head']['call_row']), final=False)
        self.check('pickup_original_five_stage_checklist', len(steps) == 5 and pickup_read and checklist
                   and pickup_read['result_row'] < checklist['call_row']
                   and all(step in checklist['args']['content'] for step in steps))
        native_git = {}
        expected_git = {
            'log': (['log', '-2', '--format=%H:%s'], self.git('log', '-2', '--format=%H:%s')),
            'diff': (['diff', self.wip + '^', self.wip, '--', self.money_relative],
                     self.git('diff', self.wip + '^', self.wip, '--', self.money_relative)),
            'status': (['status', '--porcelain'], ''),
            'blob': (['rev-parse', 'HEAD:' + self.money_relative], self.money_blob),
        }
        for label, (arguments, output) in expected_git.items():
            native_git[label] = next((event for event in successful(events)
                if event['call_row'] > trail['scan']['result_row']
                and git_command(event, self.worktree) == arguments
                and (clean_status_witness(event, self.worktree) if label == 'status'
                     else event['output'].strip() == output)), None)
        self.check('pickup_reconstructs_actual_git_state', all(native_git.values()))
        after = max(event['result_row'] for event in native_git.values())
        route = first_write(events, self.worktree, self.route, after=after)
        self.check('pickup_records_done_pending_route', route is not None)
        route_data = base.read_json(self.route)
        self.check('pickup_retains_completed_work_and_routes_pending_verification',
                   route_data.get('inherited_revision') == self.wip
                   and route_data.get('completed_task_ids') == [self.checkpoint_task['task_id']]
                   and route_data.get('redone_task_ids') == []
                   and route_data.get('playbook_id') == 'feature'
                   and route_data.get('verdict') == PICKUP_VERDICTS[0]
                   and type(route_data.get('resume_step')) is int and route_data['resume_step'] == 5
                   and route_data.get('routed_workflow_complete') is False)
        feature_read = full_read(events, self.worktree, self.bundle / 'skills/poteto-mode/playbooks/feature.md',
                                 before=route['call_row'])
        self.check('pickup_loads_matching_route', feature_read is not None)
        observations = self.import_observations(events, route['result_row'])
        reply = first_write(events, self.worktree, self.pickup_reply,
                             after=max(event['result_row'] for event in observations.values()))
        self.check('pickup_final_reply_follows_real_artifact_verification', reply is not None)
        self.check('pickup_reply_names_boundary', all(section in self.pickup_reply.read_text()
                   for section in ('Inherited', 'Resume point', 'Verification', 'Remaining', 'Feature', 'PR')))
        self.ordered['session-pickup'] = [
            {'step': 1, 'instruction': steps[0], 'note_read_result_row': note['result_row'],
             'metadata_result_row': trail['head']['result_row'], 'last_messages_result_row': trail['tail']['result_row'],
             'decision_scan_result_row': trail['scan']['result_row']},
            {'step': 2, 'instruction': steps[1], 'state_result_rows': {label: event['result_row'] for label, event in native_git.items()}},
            {'step': 3, 'instruction': steps[2], 'done_pending_record_result_row': route['result_row'], 'duplicate_tasks': 0},
            {'step': 4, 'instruction': steps[3], 'feature_read_result_row': feature_read['result_row'], 'route_result_row': route['result_row']},
            {'step': 5, 'instruction': steps[4], 'cli_result_rows': {label: event['result_row'] for label, event in observations.items()},
             'reply_result_row': reply['result_row']},
        ]
        self.independent_import_verification()

    def trail_reads(self, events):
        raw_lines = self.checkpoint_native.read_text().splitlines()
        task_id = self.checkpoint_task['task_id']
        matched = ['%d:%s' % (index + 1, line) for index, line in enumerate(raw_lines) if task_id in line][:3]
        expected = {'head': (['head', '-n', '1', str(self.checkpoint_native)], raw_lines[0]),
                    'tail': (['tail', '-n', '8', str(self.checkpoint_native)], '\n'.join(raw_lines[-8:])),
                    'scan': (['grep', '-n', '-m', '3', task_id, str(self.checkpoint_native)], '\n'.join(matched))}
        result = {}
        after = -1
        for label, (argv, output) in expected.items():
            for event in successful(events):
                if event['name'] != 'bash' or event['call_row'] <= after:
                    continue
                try:
                    actual = shlex.split(event['args'].get('command', ''))
                except ValueError:
                    continue
                if actual == argv and event['output'].strip() == output.strip():
                    result[label], after = event, event['result_row']
                    break
        return result if len(result) == 3 else None

    def import_observations(self, events, after):
        observed = {}
        for label, expectation in self.expectations.items():
            for event in events:
                if event['name'] != 'bash' or event['call_row'] <= after:
                    continue
                invocation = direct_cli(event['args'].get('command', ''), self.worktree)
                if not invocation or invocation != (self.fixture / 'cli.py', expectation['args'], None):
                    continue
                output = event['output'].strip()
                if expectation['exit_code']:
                    suffix = 'Command exited with code 2'
                    if not event['is_error'] or not output.endswith(suffix):
                        continue
                    output = output[:-len(suffix)].strip()
                elif event['is_error']:
                    continue
                try:
                    actual = json.loads(output)
                except ValueError:
                    continue
                if actual == expectation['output']:
                    observed[label] = event
                    break
            self.check('pickup_native_cli_' + label, label in observed)
            if 'store' in expectation:
                store = expectation['store']
                self.check('pickup_store_artifact_' + label,
                           base.read_json(store) == expectation['final'] and not store.with_suffix('.pending').exists()
                           and (expectation['exit_code'] == 0 or base.sha(store) == expectation['initial_sha256']))
                inspected = full_read(events, self.worktree, store, after=observed[label]['result_row'])
                self.check('pickup_inspects_actual_store_' + label, inspected is not None)
                observed[label + '_store'] = inspected
        self.check('pickup_export_follows_success', observed['success']['result_row'] < observed['export']['call_row'])
        return observed

    def independent_import_verification(self):
        expectations = build_import_cases(self.artifacts / 'independent-import-cases', self.fixture / 'cli.py')
        for label, expectation in expectations.items():
            proc = self.run_cli(self.fixture / 'cli.py', expectation['args'])
            self.check('independent_cli_' + label,
                       proc.returncode == expectation['exit_code'] and json.loads(proc.stdout) == expectation['output'])
            if 'store' in expectation:
                self.check('independent_persisted_state_' + label,
                           base.read_json(expectation['store']) == expectation['final']
                           and not expectation['store'].with_suffix('.pending').exists()
                           and (expectation['exit_code'] == 0 or base.sha(expectation['store']) == expectation['initial_sha256']))

    def write_replay(self):
        lines = ['# Rerun the retained complete importer scenario', '',
                 'Use the retained fixture and reset each isolated store before its import.',
                 'The rejection cases must exit with code 2 and preserve the store.', '']
        for label, expectation in self.expectations.items():
            lines += ['## ' + label, '', '```sh']
            if 'store' in expectation:
                lines.append(shlex.join(['cp', '--', str(expectation['initial_store']), str(expectation['store'])]))
            lines.append(shlex.join([sys.executable, str(self.fixture / 'cli.py'), *expectation['args']]))
            lines += ['```', '', 'Expected exit: ' + str(expectation['exit_code']) + '.', '',
                      'Expected JSON: ' + json.dumps(expectation['output'], sort_keys=True) + '.', '']
        (self.artifacts / 'REPLAY.md').write_text('\n'.join(lines))

    def scenario(self):
        self.begin('A')
        money_inputs = '\n'.join(json.dumps(row) for row in MONEY_INPUTS)
        initial = f'''Current Feature workstream goal: implement integer half-up per-line invoice rounding and verify the complete persisted two-file importer.
This first request stops at an implementation checkpoint. Do not run the complete delivery workflow or commit yet.
Earlier Feature grounding/design stages are outside this checkpoint evaluation;
do not claim that they were completed or invent prior work.
{NATIVE_PROTOCOL}
Read these bundled documents in full with separate native reads: {', '.join(map(str, self.common()))}.
Read the originating workstream at {self.bundle / 'skills/poteto-mode/playbooks/feature.md'} in full too.
Read {self.fixture / 'contract.md'}. Delegate exactly one bounded implementation of ONLY {self.fixture / 'money.py'}
through {self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'}, role feature, refactoring, configured worker {self.writer}.
Every brief names role, selected worker and reason, includes the absolute paths {self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'}
and {self.bundle / 'skills/poteto-mode/SKILL.md'}, forbids delegation/native subagents and any commit, and permits only money.py edits.
Use your actual pane {self.pane} as --caller-pane. Use separate literal python3 <absolute horch.py> run/wait commands.
Wait for actual state done, then read the worker's complete report.md, listed in result.json files. Do not accept an early result as delivery.
Observe only the money surface yourself using one direct command python3 {self.fixture / 'line_cli.py'} with quoted JSON heredoc stdin:
{money_inputs}
Write the pending full-importer verification state to {self.checkpoint_reply} with a native write, then end your turn.
Do not run the complete importer yet. Pending cases are at {self.artifacts / 'import-cases/manifest.json'}; preserve that pointer.
After that one task, start no further tasks. No commits, push, PR, merge, configuration/trust/model changes, or evaluator/evidence edits.
All notes outside the worktree. The driver will issue a separate explicit pause request after you stop.
'''
        self.prompt('implementation', initial)
        self.implementation_checkpoint()
        pause = f'''Pause safely now. This is a separate explicit user request after the completed checkpoint.
{NATIVE_PROTOCOL}
Read {self.bundle / 'skills/poteto-mode/playbooks/pause-safely.md'} in full, then native-write its exact original four-step checklist to {self.pause_checklist}.
Start no new task. Make the completed money-only change durable as exactly one local wip: commit on the existing branch, with no unrelated edits.
Use separate native shell calls for git add and git commit, without semicolons or &&.
Use the existing project Git identity and configuration for commits; do not override signing or hooks, and never edit saved Git configuration. Do not include private absolute paths in committed source/messages. No push, PR or merge.
Check the actual clean state with a separate git -C {self.worktree} status --porcelain.
Write {self.note} off-context with exact Markdown headings {', '.join('## ' + heading for heading in NOTE_HEADINGS)}.
Give each heading a nonempty section. Include actual goal/progress/verified/pending, exact WIP revision,
the originating workstream from the original request,
actual completed task ID, next action, key file paths and gotchas. Preserve the pending manifest pointer and actual native session trail at {self.checkpoint_native}.
Do not duplicate the transcript; point at it. Record the actual completed boundary and remaining work from the goal and observed state.
Native-write a short pause reply to {self.pause_reply}, including disk state, exact commit, clean state, and first resume action. This is a pause, not a final delivery.
No model/permission/trust/config changes, nested workers, evaluator edits or remote mutations.
'''
        self.prompt('pause', pause)
        self.verify_pause()
        a = self.current
        self.close_controller(a)
        self.frozen_note_sha256 = base.sha(self.note)
        self.frozen_trail_sha256 = base.sha(self.checkpoint_native)
        self.check('pause_native_transcript_finalized_before_pickup',
                   self.frozen_trail_sha256 == self.phase_receipts['A']['sha256'])
        self.phase_success['pause-safely'] = True
        self.begin('B')
        self.check('pickup_new_session_after_closed_A', a['closed_at'] <= self.current['started_at']
                   and self.current['session'].get('value') != a['session'].get('value'))
        pickup = f'''Original full goal: implement integer half-up per-line invoice rounding and verify the complete persisted two-file importer.
Resume from the authoritative prior note {self.note} and the explicitly scoped native prior session {self.checkpoint_native}.
{NATIVE_PROTOCOL}
Reconstruct operational state and decide what remains from the prior artifacts and actual repository, rather than a supplied recovery summary. Do not search unrelated sessions.
Read the bundled {self.bundle / 'skills/poteto-mode/playbooks/session-pickup.md'} in full and native-write its exact five-step checklist to {self.pickup_checklist} before reading the note/trail.
Read these bundled documents in full: {', '.join(map(str, self.common()))}, {self.bundle / 'skills/principle-prove-it-works/SKILL.md'}.
First native-read the note; then use three separate literal shell calls: head -n 1 <prior transcript>, tail -n 8 <prior transcript>,
grep -n -m 3 <task ID discovered in prior artifacts> <prior transcript>. These show metadata, last messages, then scoped historical decision points.
Inspect actual git state with four separate literal native shell calls, no semicolons or &&, filling placeholders from the trail and repository:
git -C {self.worktree} log -2 --format=%H:%s
git -C {self.worktree} diff <inherited checkpoint>^ <inherited checkpoint> -- <inherited changed file relative path>
git -C {self.worktree} status --porcelain
git -C {self.worktree} rev-parse HEAD:<inherited changed file relative path>
Read the matching bundled playbook you discover before recording your route; do not choose a route just to match a suggested answer.
Native-write {self.route} with discovered inherited_revision, completed_task_ids, redone_task_ids, playbook_id, verdict, resume_step, routed_workflow_complete.
Use the selected original playbook's source-file stem (without .md) as playbook_id.
Choose verdict from these neutral alternatives: {json.dumps(PICKUP_VERDICTS)}.
Use the 1-based numbered step in that selected original playbook where pending
work resumes as resume_step. An optional resume_point can explain it in prose.
Derive those values from the prior trail, current state, and original goal. A prior statement is input to reconstruct, not proof of completion.
After recording reconstruction and route, verify inherited claims against the original full goal on its actual CLI/artifacts.
The retained scenario manifest is discoverable through the prior artifacts. Use one separate direct python3 <absolute cli.py> command per selected manifest entry, no wrapper, pipeline or error masking.
Observe actual command exit status and JSON. After each import, native-read its complete store.json and check for a surviving .pending file. Run any export against the store created by the appropriate preceding import.
Do not repeat completed work. Preserve inherited commits, branch and sources; this pickup is read-only and does not authorize dispatch, edits, commits, external writes, configuration/trust/model changes, or evaluator changes.
Native-write your final reply to {self.pickup_reply}, with Inherited / Resume point / Verification / Remaining sections.
Report what you inherited, what you actually performed, the discovered resume point, verification outcome, and any remaining work. Claim workflow completion only when supported by actual evidence.
Name the routed playbook and any remaining PR or review steps and their authorization boundary.
All notes stay outside the checkout.
'''
        self.prompt('pickup', pickup)
        self.verify_pickup()
        self.write_replay()
        self.phase_success['session-pickup'] = True

    def record_failure(self, category):
        self.categories.append(category)
        (self.directory / 'failure.txt').write_text(traceback.format_exc())

    def finish(self):
        cleanup_ok = True
        for controller in self.controllers:
            if controller['closed']:
                continue
            try:
                self.close_controller(controller)
            except Exception:
                cleanup_ok = False
        for controller in self.controllers:
            audit = self.phase_receipts.get(controller['label'])
            if audit is not None:
                paths = list(controller['session_dir'].glob('*.jsonl'))
                unchanged = len(paths) == 1 and base.sha(paths[0]) == audit.get('sha256')
                self.checks.append({'name': 'native_session_finalized_' + controller['label'], 'ok': unchanged})
        try:
            self.scan()
        except Exception:
            self.categories.append('task_snapshot_failed')
        task_facts = []
        for task in self.tasks.values():
            try:
                state = base.read_json(Path(task['task_dir']) / 'state.json')
                task_facts.append({'task_id': task['task_id'], 'worker': task['worker'],
                                   'harness': task['harness'], 'model': task['model'],
                                   'state': state.get('state') if state.get('state') in base.horch.SETTLED_STATES | {'running', 'long_running'} else 'invalid', 'closed_before_cleanup': state.get('closed') is True})
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task['pane_id']:
                        raise base.Failure('cleanup_ownership_unproven')
                    self.call(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'], cleanup=True)
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py', 'close', task['task_id']], cleanup=True)
                cleanup_ok = cleanup_ok and self.pane_absent(task['pane_id'])
            except Exception:
                cleanup_ok = False
        after, config_after, integrity = {}, None, False
        try:
            after, config_after = all_sources(), base.sha(self.config_path)
            integrity = (after == self.hashes and config_after == self.config_hash
                         and self.call(['git', '-C', self.args.repo, 'rev-parse', 'HEAD'], cleanup=True).strip() == self.revision
                         and base.sha(self.directory / 'config/herdr-orchestrator/workers.toml') == self.config_hash
                         and all(base.sha(self.bundle / path) == value for path, value in self.hashes.items() if path.startswith('skills/')))
        except Exception:
            pass
        self.checks.extend([{'name': 'source_configuration_and_parent_head_unchanged', 'ok': integrity},
                            {'name': 'owned_pane_cleanup', 'ok': cleanup_ok}])
        passed = not self.categories and bool(self.ordered.get('pause-safely')) and bool(self.ordered.get('session-pickup')) and all(check['ok'] for check in self.checks)
        inventory = {name: 'not_run' for name in sorted(set(self.inventory_names) | set(base.INVENTORY))}
        for name in ('pause-safely', 'session-pickup'):
            requested = 'pause' in self.phases if name == 'pause-safely' else 'pickup' in self.phases
            label = 'A' if name == 'pause-safely' else 'B'
            finalized = all(check['ok'] for check in self.checks if check['name'] == 'native_session_finalized_' + label)
            inventory[name] = ('pass' if self.phase_success[name] and integrity and cleanup_ok and finalized
                               else 'fail' if requested else 'not_run')
        receipt = {'schema': 'horch/pause-pickup-e2e/v1', 'verdict': 'pass' if passed else 'fail',
                   'inventory': inventory, 'full_inventory_verdict': 'not_run',
                   'phase_timestamps': self.phases,
                   'session_lifecycle': [{'phase': controller['label'], 'started_at': controller['started_at'],
                                          'closed_at': controller.get('closed_at'),
                                          'identity_sha256': digest_text(str(controller['session'].get('value', '')))}
                                         for controller in self.controllers],
                   'native_sessions': self.phase_receipts, 'implementation_checkpoint': self.implementation_proof,
                   'pending_input_manifest_sha256': digest_text(json.dumps(self.suite_hashes, sort_keys=True)),
                   'ordered_workflows': self.ordered, 'checks': self.checks, 'tasks': task_facts,
                   'source_revision': self.revision, 'source_sha256_before': self.hashes,
                   'source_sha256_after': after, 'config_sha256_before': self.config_hash,
                   'config_sha256_after': config_after, 'fixture_commits': {'seed': self.seed, 'wip': self.wip},
                   'money_blob': self.money_blob, 'controller': {key: self.spec.get(key) for key in ('harness', 'model', 'provider', 'effort')},
                   'failure_categories': self.categories, 'last_phase': self.phase,
                   'artifacts': {'pause_note': 'artifacts/resume.md', 'pause_reply': 'artifacts/pause-reply.md',
                                 'pickup_reply': 'artifacts/pickup-reply.md', 'rerun_instructions': 'artifacts/REPLAY.md', 'rerunnable_cases': 'artifacts/import-cases/manifest.json'},
                   'limitations': ['Only the witnessed local Pause/Pickup sequence is assessed; the routed Feature PR/review workflow is not complete.',
                                   'The starting implementation checkpoint does not establish earlier Feature grounding or design stages.',
                                   'Native evidence recognizes literal commands; arbitrary script semantics are not inferred.'],
                   'seconds': round(time.monotonic() - self.started, 3)}
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='existing configured Pi controller')
    parser.add_argument('--repo', type=Path, default=Path('.'), help='existing trusted repository root')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside checkout')
    parser.add_argument('--caller-pane', required=True, help='verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=2400, help='overall deadline')
    args = parser.parse_args()
    args.repo = args.repo.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.output == args.repo or args.repo in args.output.parents:
        parser.error('--output must be outside repository')
    base.require_historical_fixture_source(parser)
    run = ContinuityRun(args)
    try:
        run.preflight()
        run.phase = 'setup'
        run.setup()
        run.phase = 'two-session-continuity'
        run.scenario()
    except base.Failure as exc:
        run.record_failure(str(exc))
    except KeyboardInterrupt:
        run.record_failure('operator_interrupted')
    except (SystemExit, Exception):
        run.record_failure('preflight_or_runtime_error')
    return run.finish()


if __name__ == '__main__':
    raise SystemExit(main())
