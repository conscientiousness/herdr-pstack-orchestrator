#!/usr/bin/env python3
"""Real Codex controller E2E; requires an existing trusted repo and Herdr pane.

Isolation covers config and task records, not the global Herdr workspace. Stop
other dispatchers for the duration: the preflight/monitor detect occupied global
slots but cannot reserve them atomically across independent XDG state stores.
Transcript checks recognize literal shell-tool calls, not arbitrary shell/JS
semantics. Unsupported or ambiguous required evidence fails closed. Private
artifacts stay in the run directory; evidence.json contains sanitized facts only.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import review_loop as fixture

HORCH = fixture.HORCH
SKILL = HORCH.parent.parent
sys.path.insert(0, str(HORCH.parent))
import horch  # noqa: E402; importing is read-only, never dispatches a task


class Failure(Exception):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [Path(__file__).resolve(), Path(fixture.__file__).resolve(), HORCH,
             SKILL / 'SKILL.md', *sorted((SKILL / 'references').rglob('*'))]
    return {str(p): digest(p) for p in paths if p.is_file()}


def text_output(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(text_output(v) for v in value)
    if isinstance(value, dict):
        return text_output(value.get('text', value.get('output', '')))
    return ''


def without_literal_file_writes(command):
    """Ignore quoted cat-heredoc bodies: their contents are data, not reads.

    Keep the redirect destination and subsequent commands visible to the audit.
    Unquoted heredocs can execute substitutions and are deliberately not stripped.
    """
    pattern = re.compile(r"(?m)^(cat\s+>\s*[^\n]+?)\s*<<\s*(['\"])([A-Za-z_]\w*)\2\s*\n")
    position = 0
    while match := pattern.search(command, position):
        end = re.search(r'(?m)^' + re.escape(match[3]) + r'\s*$', command[match.end():])
        if not end:
            raise Failure('transcript_incomplete_heredoc')
        stop = match.end() + end.end()
        command = command[:match.start()] + match[1] + '\n' + command[stop:]
        position = match.start() + len(match[1]) + 1
    return command


def output_objects(text):
    """Decode tool envelopes and their stdout without corrupting JSON escapes."""
    for match in re.finditer(r'\{', text):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj
            if isinstance(obj.get('output'), str):
                yield from output_objects(obj['output'])


def literal_calls(source):
    """Extract literal JS object arguments; reject expressions rather than eval JS."""
    calls = []
    for match in re.finditer(r'tools\.(exec_command|write_stdin)\s*\(', source):
        i = match.end()
        while i < len(source) and source[i].isspace():
            i += 1
        if i >= len(source) or source[i] != '{':
            raise Failure('transcript_dynamic_arguments')
        start, depth, quote, escaped = i, 0, None, False
        while i < len(source):
            ch = source[i]
            if quote:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == quote:
                    quote = None
            elif ch in "'\"`":
                quote = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        raw = source[start:i + 1]
        # Literal strings are masked before normalizing bare JS keys/booleans.
        strings = []
        def string(m):
            token = m.group()
            if token.startswith('`'):
                if '${' in token:
                    raise Failure('transcript_dynamic_arguments')
                value = token[1:-1]
            else:
                value = ast.literal_eval(token)
            strings.append(value)
            return f'__STRING_{len(strings)-1}__'
        masked = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", string, raw)
        masked = re.sub(r'([A-Za-z_]\w*)\s*:', r'"\1":', masked)
        masked = re.sub(r'\b(true|false|null)\b', lambda m: {'true':'True','false':'False','null':'None'}[m[0]], masked)
        masked = re.sub(r'__STRING_(\d+)__', lambda m: repr(strings[int(m[1])]), masked)
        try:
            args = ast.literal_eval(masked)
        except (ValueError, SyntaxError):
            raise Failure('transcript_dynamic_arguments') from None
        calls.append((match[1], args))
    return calls


def transcript_path(session, cwd, started):
    root = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions'
    value = session.get('value')
    if value and session.get('kind') == 'path':
        p = Path(value).expanduser()
        if p.is_file():
            return p
        raise Failure('transcript_unavailable')
    candidates = list(root.rglob(f'*{value}*.jsonl')) if value else list(root.rglob('*.jsonl'))
    found = []
    for p in candidates:
        with p.open(encoding='utf-8') as stream:
            row = json.loads(stream.readline())
        meta = row.get('payload', {})
        if row.get('type') != 'session_meta':
            continue
        if value:
            if meta.get('id') == value:
                found.append(p)
        elif meta.get('cwd') == str(cwd):
            stamp = datetime.fromisoformat(meta['timestamp'].replace('Z', '+00:00')).timestamp()
            if started <= stamp <= time.time():
                found.append(p)
    if len(found) != 1:
        raise Failure('transcript_unavailable_or_ambiguous')
    return found[0]


def audit_transcript(path, tasks, counts, delivered_at=None):
    """Ordering is tool-call/output order, never assistant narrative or report."""
    pending, live, done, reads = {}, {}, set(), set()
    cell_calls = {}
    observation_handles = set()
    counts.update({'tool_calls': 0, 'shell_calls': 0, 'wait_launches': 0,
                   'short_waits': 0, 'yielded_waits': 0, 'handle_resumes': 0})
    short = set()
    cell_live = set()
    ordered_cells = set()
    known_ids = {t['task_id'] for t in tasks}
    if delivered_at is None:
        delivered_at = {}
        for task in tasks:
            state_path = Path(task['task_dir']) / 'state.json'
            if fixture.json_file(state_path).get('state') == 'done':
                delivered_at[task['task_id']] = state_path.stat().st_mtime
    if set(delivered_at) != known_ids:
        raise Failure('delivery_state_unavailable')
    for line in path.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row.get('type') != 'response_item':
            continue
        item = row.get('payload', {})
        kind = item.get('type')
        if kind in ('function_call', 'custom_tool_call'):
            counts['tool_calls'] += 1
            name = item.get('name', '').split('.')[-1]
            raw = item.get('input', item.get('arguments', ''))
            if name.lower() in ('agent', 'task', 'spawn_agent', 'send_message', 'followup_task', 'request_user_input') or re.search(r'\btools\.(?:spawn_agent|send_message|followup_task|request_user_input)\s*\(', raw):
                raise Failure('forbidden_controller_tool')
            if name in ('exec_command', 'write_stdin'):
                calls = [(name, json.loads(item['arguments']))]
            elif name == 'exec':
                calls = literal_calls(raw)
                if (len(re.findall(r'text\s*\(\s*await\s+tools\.(?:exec_command|write_stdin)\s*\(', raw)) == len(calls)
                        and 'Promise' not in raw):
                    ordered_cells.add(item['call_id'])
                if re.fullmatch(r'\s*const\s+(\w+)\s*=\s*await\s+Promise\.allSettled\(\[.*\]\);\s*\1\.forEach\(text\);\s*', raw, re.DOTALL):
                    # allSettled preserves input order; this exact printing form
                    # emits one result per call in that same order.
                    ordered_cells.add(item['call_id'])
                # An exec cell must await its calls or the isolate can drop them.
                if calls and 'await' not in raw:
                    raise Failure('transcript_unawaited_calls')
            elif name == 'wait':
                args = json.loads(item.get('arguments', '{}'))
                cell = args.get('cell_id')
                if cell not in cell_live or args.get('terminate'):
                    raise Failure('transcript_cell_continuity')
                calls = [('cell_wait', args)]
            elif name in ('update_plan', 'apply_patch'):
                # Plans and patches do not consume file content. Artifact writes
                # would bypass the workers and cannot serve as delivery evidence.
                if name == 'apply_patch' and any(t['task_dir'] in raw for t in tasks):
                    raise Failure('controller_artifact_write')
                calls = []
            else:
                # Unknown tools touching task artifacts cannot prove delivery gating.
                if any(t['task_id'] in raw for t in tasks) or 'result.json' in raw or 'review.md' in raw:
                    raise Failure('transcript_unsupported_read')
                calls = []
            audited = []
            for tool, args in calls:
                if tool == 'write_stdin':
                    handle = str(args.get('session_id'))
                    if handle not in live or args.get('chars', ''):
                        raise Failure('transcript_handle_continuity')
                    counts['handle_resumes'] += 1
                    audited.append(('resume', handle))
                elif tool == 'cell_wait':
                    audited.append(('cell', str(args['cell_id'])))
                else:
                    counts['shell_calls'] += 1
                    cmd = args.get('cmd')
                    if not isinstance(cmd, str):
                        raise Failure('transcript_dynamic_command')
                    cmd = without_literal_file_writes(cmd)
                    if re.search(r'herdr\s+(?:agent\s+(?:start|prompt)|pane\s+(?:close|send|input|write))', cmd):
                        raise Failure('controller_bypassed_horch')
                    if re.search(r'\bsend-keys\b|\bsend-text\b', cmd):
                        raise Failure('forbidden_controller_tool')
                    # Require a content-reading operation, not a mention in a
                    # brief, plan, listing, or path argument passed to a worker.
                    reads_content = bool(re.search(r'\b(?:cat|head|tail|sed|awk|grep|rg|jq|less|more)\s+(?!>)|\.(?:read_text|read_bytes)\s*\(|\bopen\s*\(', cmd))
                    has_artifact = bool(re.search(r'\b(?:result\.json|review\.md|report\.md)\b', cmd))
                    call_time = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
                    for task in tasks:
                        tid = task['task_id']
                        if reads_content and has_artifact and (tid in cmd or str(Path(task['task_dir'])) in cmd):
                            if tid not in done or call_time < delivered_at[tid]:
                                raise Failure('delivery_order_unproven')
                            reads.add(tid)
                    if reads_content and has_artifact and not any(t['task_id'] in cmd for t in tasks):
                        raise Failure('delivery_dynamic_read_unproven')
                    waits = list(re.finditer(r'(?:horch\.py|\bhorch)\s+wait\b([^\n;&|]*)', cmd))
                    if len(waits) > 1:
                        raise Failure('transcript_combined_waits')
                    waiting = bool(waits)
                    if waiting:
                        counts['wait_launches'] += 1
                        tail = waits[0][1]
                        ids = set(re.findall(r't-[0-9a-f]{6}', tail)) or {t['task_id'] for t in tasks if t['task_id'] not in done}
                        if any(ids & v for v in live.values()):
                            raise Failure('overlapping_wait_handles')
                        cap = re.search(r'--max-seconds(?:\s+|=)(\d+)', tail)
                        if '--max-seconds' in tail and not cap:
                            raise Failure('transcript_dynamic_wait_cap')
                        if cap and int(cap[1]) < 300:
                            counts['short_waits'] += 1
                            if ids & short or not ids:
                                raise Failure('repeated_short_wait_caps')
                            short.update(ids)
                        if re.search(r'\bsleep\b|\b(?:while|for)\b|\$|`|\s&\s*$', cmd):
                            raise Failure('transcript_wait_semantics_unproven')
                        audited.append(('launch', ids))
                    else:
                        audited.append(('observe' if re.search(r'(?:horch\.py|\bhorch)\s+(?:run|list)\b', cmd) else 'shell', set()))
            pending[item['call_id']] = audited
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            calls = pending.pop(item.get('call_id'), None)
            if calls is None:
                raise Failure('transcript_output_unmatched')
            segments = [(calls, text_output(item.get('output', '')))]
            if len(calls) > 1 and item.get('call_id') in ordered_cells:
                frames = []
                for part in item.get('output', []):
                    try:
                        frame = json.loads(part.get('text', ''))
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(frame, dict) and frame.get('status') == 'fulfilled':
                        frame = frame.get('value')
                    if isinstance(frame, dict) and 'chunk_id' in frame:
                        frames.append(frame)
                if len(frames) != len(calls):
                    raise Failure('transcript_output_mapping_ambiguous')
                segments = [([call], json.dumps(frame)) for call, frame in zip(calls, frames)]
            for calls, output in segments:
                sessions = set(re.findall(r'"session_id"\s*:\s*(\d+)|Process running with session ID (\d+)', output))
                handles = {a or b for a, b in sessions}
                cells = set(re.findall(r'Script running with cell ID ([\w-]+)', output))
                if len(calls) > 1 and (handles or cells or any(c[0] == 'launch' for c in calls)):
                    raise Failure('transcript_output_mapping_ambiguous')
                if cells:
                    for cell in cells:
                        if calls and calls[0][0] == 'cell':
                            prior = calls[0][1]
                            if cell != prior:
                                raise Failure('transcript_cell_changed')
                        else:
                            cell_calls[cell] = calls
                    cell_live.update(cells)
                    continue
                expanded = []
                for action, data in calls:
                    if action == 'cell':
                        expanded.extend(cell_calls.pop(data, []))
                        cell_live.discard(data)
                    else:
                        expanded.append((action, data))
                delivery_output = False
                for action, data in expanded:
                    if action in ('launch', 'shell', 'observe'):
                        if handles and action == 'launch':
                            counts['yielded_waits'] += 1
                        if action in ('launch', 'observe'):
                            delivery_output = True
                            observation_handles.update(handles)
                        for h in handles:
                            live[h] = data
                        if action == 'launch' and not handles and not re.search(r'\"exit_code\"\s*:\s*0|Process exited with code 0', output):
                            raise Failure('wait_completion_unproven')
                    elif action == 'resume':
                        delivery_output |= data in observation_handles
                        if handles and handles != {data}:
                            raise Failure('transcript_handle_changed')
                        if not handles:
                            if not re.search(r'"exit_code"\s*:\s*0|Process exited with code 0', output):
                                raise Failure('wait_completion_unproven')
                            live.pop(data)
                            observation_handles.discard(data)
                if not delivery_output:
                    continue
                # JSON done rows must be actual tool output, not call input/assistant text.
                output_time = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
                for event in output_objects(output):
                    tid = event.get('task_id')
                    if event.get('state') == 'done' and tid in known_ids:
                        # A fabricated stdout row cannot establish earlier delivery
                        # than the independently observed state file's write time.
                        if output_time < delivered_at[tid]:
                            raise Failure('delivery_output_precedes_state')
                        done.add(tid)
    if pending or live or cell_live or not counts['wait_launches']:
        raise Failure('wait_continuity_unproven')
    if reads != {t['task_id'] for t in tasks} or not reads <= done:
        raise Failure('delivery_reads_unproven')
    return counts


class Run(fixture.Run):
    def __init__(self, args):
        super().__init__(args)
        self.wall_started = time.time()
        self.deadline = self.started + args.max_seconds
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.directory / 'config'),
                        XDG_STATE_HOME=str(self.directory / 'state'))
        self.root = self.directory / 'state/herdr-orchestrator/tasks'
        self.pane = None
        self.agent = 'ctrl-e2e-' + format(time.time_ns(), 'x')
        self.session = {}
        self.hashes = sources()
        self.config_hash = digest(args.config_path)
        self.repo_head = self.call(['git', '-C', args.repo, 'rev-parse', 'HEAD']).strip()
        self.precleanup = []
        self.counts = {}
        self.categories = []
        self.last_states = {}
        self.delivered_at = {}

    def call(self, argv, *, cleanup=False):
        timeout = 30 if cleanup else min(180, self.deadline - time.monotonic())
        if timeout <= 0:
            raise Failure('overall_timeout')
        proc = subprocess.run([str(a) for a in argv], env=self.env, text=True,
                              capture_output=True, timeout=timeout)
        if proc.returncode:
            raise Failure('command_failed')
        return proc.stdout

    def git(self, *args):
        return self.call(['git', '-C', self.worktree, *args]).strip()

    def setup(self):
        self.call(['git', '-C', self.args.repo, 'worktree', 'add', '--detach', self.worktree, 'HEAD'])
        if self.fixture.exists():
            raise Failure('fixture_already_exists')
        self.fixture.mkdir()
        (self.fixture / 'contract.md').write_text(fixture.CONTRACT)
        (self.fixture / 'invoice.py').write_text(fixture.INVOICE)
        self.revisions['base'] = self.commit('Add disposable invoice CLI fixture')

    def cli(self, mode, data):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Failure('overall_timeout')
        proc = subprocess.run([sys.executable, self.fixture / 'invoice.py', mode],
                              input=json.dumps(data), text=True, capture_output=True,
                              cwd=self.worktree, timeout=remaining)
        if proc.returncode:
            raise Failure('fixture_cli_failed')
        return json.loads(proc.stdout)

    def herdr(self, *argv, cleanup=False):
        return json.loads(self.call(['herdr', *argv], cleanup=cleanup))

    def scan(self):
        rows = []
        for path in sorted(self.root.glob('t-*/task.json')):
            task = fixture.json_file(path)
            if task.get('task_id') != path.parent.name or not horch.TASK_ID_RE.fullmatch(path.parent.name):
                raise Failure('task_identity_invalid')
            if (Path(task.get('task_dir', '')).resolve() != path.parent.resolve()
                    or Path(task.get('result_path', '')).resolve() != path.parent.resolve() / 'result.json'
                    or task.get('agent') != 'horch-' + path.parent.name[2:]):
                raise Failure('isolated_task_identity_invalid')
            state_path = path.parent / 'state.json'
            state = fixture.json_file(state_path) if state_path.exists() else {'state':'unpublished','closed':False}
            if state.get('state') == 'done':
                self.delivered_at.setdefault(task['task_id'], state_path.stat().st_mtime)
            rows.append((task, state))
            key = (state.get('state'), state.get('closed'))
            if self.last_states.get(task['task_id']) != key:
                with (self.directory / 'transitions.jsonl').open('a') as stream:
                    stream.write(json.dumps({'task_id': task['task_id'], 'seconds': round(time.monotonic()-self.started, 3), 'state': key[0], 'closed': key[1]}) + '\n')
                self.last_states[task['task_id']] = key
        self.tasks = [t for t, _ in rows]
        return rows

    def global_slots(self):
        # Normal store is outside our isolated environment. Never call horch list.
        occupied = horch.active_task_count()
        agents = self.herdr('agent', 'list')['result']['agents']
        isolated_agents = {t['agent'] for t in self.tasks}
        unmanaged = sum(a.get('name', a.get('agent')) not in isolated_agents | {self.agent}
                        and str(a.get('name', a.get('agent', ''))).startswith('horch-')
                        for a in agents)
        return max(occupied, unmanaged)

    def scenario(self):
        self.check('global_capacity', self.global_slots() + 2 <= self.args.limit)
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.args.config_path, destination)
        self.root.mkdir(parents=True)
        self.setup()  # Shared fixture text and commit helper; bounded subprocesses.
        line = {'quantity': 7, 'unit_price_cents': 137, 'discount_bp': 250}
        invoice = {'lines': [line, {'quantity': 2, 'unit_price_cents': 1000, 'discount_bp': 500}], 'shipping_cents': 55}
        self.check('base_defects', self.cli('line', line) != {'total_cents': 936}
                   and self.cli('invoice', invoice) != {'subtotal_cents': 2836, 'total_cents': 2891})
        prompt = f'''Read {SKILL / 'SKILL.md'} in full and use it to carry out this task.
The existing disposable worktree is {self.worktree}; its invoice fixture is
{self.fixture}. Read contract.md and invoice.py. Use configured writer
{self.args.writer} and independent reviewers {', '.join(self.args.reviewer)}.
First dispatch an implementation task fixing ONLY line_total's basis-point
calculation, leaving invoice_total unchanged. Have that writer commit only
.horch-fixture/invoice.py and report the revision in report.md. Then dispatch
both reviewers independently, read-only, against that exact pinned revision and
the complete contract, with real CLI checks. Each writes review.md with first
line VERDICT: PASS or VERDICT: FAIL and concrete findings. After these reviews,
dispatch a fresh writer task with their reports to fix accepted findings and
commit only the invoice.py changes, reporting the new revision in report.md.
Dispatch two fresh read-only final reviews pinned to the fix commit, using the
same reviewer roles and verdict format. Verify both CLI modes and edge cases,
the exact file scope, commits, and clean checkout. Finish the six-task scenario.
For these disposable fixture commits use git -c commit.gpgsign=false
-c core.hooksPath=/dev/null -c user.name='horch E2E'
-c user.email=e2e@example.invalid commit, without changing saved git settings.
An optional {self.directory / 'controller-report.json'} may record
implementation_task, first_review_tasks, fix_task, second_review_tasks,
initial_revision and final_revision for cross-checking.
'''
        brief = self.directory / 'controller-brief.md'
        brief.write_text(prompt)
        tab = self.herdr('tab', 'create', '--workspace', os.environ['HERDR_WORKSPACE_ID'],
                         '--cwd', self.worktree, '--label', 'controller-e2e',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'], '--no-focus')
        self.pane = tab['result']['root_pane']['pane_id']
        flags = horch.launch_args(self.args.controller_spec, self.directory)
        flags += ['--add-dir', str(SKILL)]
        start = self.herdr('agent', 'start', self.agent, '--kind', 'codex', '--pane', self.pane,
                          '--timeout', '90000', '--', *flags)
        self.check('controller_started', start['result']['type'] == 'agent_started')
        ack = self.herdr('agent', 'prompt', self.agent, f'Read {brief} in full and follow it.',
                        '--wait', '--until', 'working', '--timeout', '30000')
        self.check('controller_acknowledged', ack['result']['type'] == 'agent_prompted')
        idle_since = None
        while time.monotonic() < self.deadline:
            self.scan()
            self.check_capacity()
            entry = self.herdr('agent', 'get', self.agent)['result']['agent']
            self.session = entry.get('agent_session') or self.session
            status = entry.get('agent_status')
            if status == 'blocked':
                raise Failure('controller_blocked')
            if status in ('idle', 'done'):
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= 10:
                    break
            else:
                idle_since = None
            time.sleep(min(1, max(0, self.deadline-time.monotonic())))
        else:
            raise Failure('overall_timeout')
        self.verify(line, invoice)
        transcript = transcript_path(self.session, self.worktree, self.wall_started)
        self.counts = audit_transcript(transcript, self.tasks, self.counts, self.delivered_at)
        self.check('transcript_waits_and_delivery', True)

    def check_capacity(self):
        live = sum(not s.get('closed') for _, s in self.scan())
        if live + self.global_slots() > self.args.limit:
            raise Failure('global_capacity_exceeded')

    def verify(self, line, invoice):
        rows = sorted(self.scan(), key=lambda pair: pair[0]['created_at'])
        self.check('six_fresh_tasks', len(rows) == 6 and len({t['agent'] for t, _ in rows}) == 6
                   and len({t['nonce'] for t, _ in rows}) == 6)
        expected = [self.args.writer, *self.args.reviewer, self.args.writer, *self.args.reviewer]
        actual = [t['worker'] for t, _ in rows]
        self.check('configured_phase_roles', actual[0] == expected[0] and actual[3] == expected[3]
                   and set(actual[1:3]) == set(self.args.reviewer) and set(actual[4:6]) == set(self.args.reviewer))
        self.check('delivered_and_closed_before_cleanup', all(s.get('state') == 'done' and s.get('closed') is True for _, s in rows))
        for t, _ in rows:
            self.check('isolated_task_paths', Path(t['task_dir']).resolve() == self.root / t['task_id']
                       and Path(t['result_path']).resolve() == self.root / t['task_id'] / 'result.json'
                       and t.get('cwd') == str(self.worktree)
                       and t.get('model') == self.args.specs[t['worker']]['model'])
            result = fixture.json_file(t['result_path'])
            self.check('result_identity_and_status', horch.validate_result(result, t) == 'valid'
                       and result.get('status') == 'completed')
        # Result mtimes give a conservative cross-check that subsequent phases
        # were created only after prior artifacts had been delivered. Transcript
        # ordering remains the authority for the controller's reads.
        for previous, following in ((rows[0:1], rows[1:3]), (rows[1:3], rows[3:4]), (rows[3:4], rows[4:6])):
            last_result = max(Path(t['result_path']).stat().st_mtime for t, _ in previous)
            first_created = min(datetime.fromisoformat(t['created_at'].replace('Z', '+00:00')).timestamp() for t, _ in following)
            # created_at is second-precision; file mtimes can be subsecond.
            self.check('fresh_phase_order', first_created + 1 > last_result)
        commits = self.git('rev-list', '--reverse', self.revisions['base'] + '..HEAD').splitlines()
        self.check('exact_two_commits', len(commits) == 2)
        initial, final = commits
        self.revisions.update(initial=initial, final=final)
        for index, (t, _) in enumerate(rows):
            directory = Path(t['task_dir'])
            if index in (0, 3):
                report = (directory / 'report.md').read_text()
            else:
                report = (directory / 'review.md').read_text()
                self.check('review_verdict', report.splitlines()[0].strip() == 'VERDICT: ' + ('FAIL' if index < 3 else 'PASS'))
            revision = initial if index < 3 else final
            # Task briefs establish review pinning; writer artifacts identify commits.
            artifact = report if index in (0, 3) else (directory / 'brief.md').read_text()
            self.check('artifact_revision_pin', revision in artifact)
        for rev in commits:
            self.check('exact_commit_scope', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', rev) == '.horch-fixture/invoice.py')
        self.check('linear_history', self.git('rev-parse', initial + '^') == self.revisions['base']
                   and self.git('rev-parse', final + '^') == initial)
        self.check('clean_checkout', not self.git('status', '--porcelain'))
        # Execute each committed CLI from git show: never checkout/mutate review HEAD.
        def cli_at(rev, mode, data):
            source = self.git('show', rev + ':.horch-fixture/invoice.py')
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise Failure('overall_timeout')
            proc = subprocess.run([sys.executable, '-c', source, mode], input=json.dumps(data),
                                  text=True, capture_output=True, cwd=self.worktree, timeout=remaining)
            if proc.returncode:
                raise Failure('fixture_cli_failed')
            result = json.loads(proc.stdout)
            keys = {'total_cents'} if mode == 'line' else {'subtotal_cents', 'total_cents'}
            if set(result) != keys or any(type(v) is not int for v in result.values()):
                raise Failure('fixture_output_invalid')
            return result
        self.observations['first_line'] = cli_at(initial, 'line', line)
        self.observations['first_invoice'] = cli_at(initial, 'invoice', invoice)
        self.check('initial_line_fixed_invoice_bug_remains', self.observations['first_line'] == {'total_cents':936}
                   and self.observations['first_invoice'] == {'subtotal_cents':936, 'total_cents':991})
        self.observations['final_invoice'] = cli_at(final, 'invoice', invoice)
        self.check('final_invoice', self.observations['final_invoice'] == {'subtotal_cents':2836, 'total_cents':2891})
        for i, (data, expected_total) in enumerate([
            ({'quantity':1,'unit_price_cents':199,'discount_bp':1},199),
            ({'quantity':3,'unit_price_cents':333,'discount_bp':3333},667),
            ({'quantity':5,'unit_price_cents':101,'discount_bp':10000},0),
            ({'quantity':0,'unit_price_cents':999,'discount_bp':250},0)]):
            outputs = [cli_at(final, 'line', data), cli_at(final, 'invoice', {'lines':[data],'shipping_cents':17})]
            self.observations[f'edge_{i}'] = outputs
            self.check('final_edge_case', outputs == [{'total_cents':expected_total}, {'subtotal_cents':expected_total,'total_cents':expected_total+17}])
        report = self.directory / 'controller-report.json'
        if report.exists():
            r = fixture.json_file(report)
            ids = [r.get('implementation_task'), *r.get('first_review_tasks', []), r.get('fix_task'), *r.get('second_review_tasks', [])]
            self.check('optional_report_crosscheck', ids[0] == rows[0][0]['task_id'] and ids[3] == rows[3][0]['task_id']
                       and set(ids[1:3]) == {t['task_id'] for t, _ in rows[1:3]}
                       and set(ids[4:6]) == {t['task_id'] for t, _ in rows[4:6]}
                       and r.get('initial_revision', initial) == initial and r.get('final_revision', final) == final)

    def finish(self, category):
        if category:
            self.categories.append(category)
        cleanup_ok = True
        # Stop the controller first so it cannot dispatch new work during cleanup.
        known_tasks = {t['task_id']: t for t in self.tasks}
        for pane in ([self.pane] if self.pane else []):
            try:
                screen = self.call(['herdr', 'pane', 'read', pane, '--source', 'recent', '--lines', '40'], cleanup=True)
                (self.directory / 'controller-pane.txt').write_text(screen)
            except Exception:
                cleanup_ok = False
            try:
                self.herdr('pane', 'close', pane, cleanup=True)
            except Exception:
                cleanup_ok = False
        # Collect each task independently after stopping dispatch. A malformed
        # state/diagnostic must not discard the last known owned pane identities.
        for path in self.root.glob('t-*/task.json'):
            try:
                task = fixture.json_file(path)
                if (task.get('task_id') == path.parent.name
                        and horch.TASK_ID_RE.fullmatch(path.parent.name)
                        and task.get('agent') == 'horch-' + path.parent.name[2:]
                        and Path(task.get('task_dir', '')).resolve() == path.parent.resolve()):
                    known_tasks.setdefault(task['task_id'], task)
                else:
                    raise Failure('task_identity_invalid')
            except Exception:
                self.categories.append('task_snapshot_failed')
                cleanup_ok = False
        for task in known_tasks.values():
            try:
                state = fixture.json_file(Path(task['task_dir']) / 'state.json')
            except Exception:
                state = {'state': 'invalid', 'closed': False}
                self.categories.append('state_snapshot_failed')
            self.precleanup.append((task, state))
        try:
            (self.directory / 'pre-cleanup.json').write_text(json.dumps(self.precleanup, indent=2))
        except OSError:
            self.categories.append('diagnostic_write_failed')
        panes = [t['pane_id'] for t, _ in self.precleanup]
        if self.pane:
            panes.append(self.pane)
        for t, state in self.precleanup:
            if not state.get('closed'):
                try:
                    screen = self.call(['herdr', 'pane', 'read', t['pane_id'], '--source', 'recent', '--lines', '40'], cleanup=True)
                    (self.directory / (t['task_id'] + '-pane.txt')).write_text(screen)
                except Exception:
                    cleanup_ok = False
                try:
                    self.call([sys.executable, HORCH, 'close', t['task_id']], cleanup=True)
                except Exception:
                    cleanup_ok = False
        # Require Herdr's actual absent-pane error, not merely a closed state flag.
        for pane in panes:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane],
                                      text=True, capture_output=True, timeout=30, env=self.env)
                reply = json.loads(proc.stdout or proc.stderr)
                error = reply.get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if not proc.returncode or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        unchanged = False
        try:
            unchanged = (sources() == self.hashes and digest(self.args.config_path) == self.config_hash
                         and (not (self.directory / 'config/herdr-orchestrator/workers.toml').exists()
                              or digest(self.directory / 'config/herdr-orchestrator/workers.toml') == self.config_hash)
                         and fixture.checked(['git','rev-parse','HEAD'], cwd=self.args.repo).strip() == self.repo_head)
        except Exception:
            pass
        self.assertions.extend([{'name':'source_and_config_integrity','ok':unchanged}, {'name':'actual_pane_cleanup','ok':cleanup_ok}])
        passed = not self.categories and all(a['ok'] for a in self.assertions)
        evidence = {'schema': 'horch/controller-e2e/v1',
                    'verdict':'pass' if passed else 'fail', 'seconds':round(time.monotonic()-self.started,3),
                    'hashes': {str(Path(p).relative_to(SKILL.parents[1])): h for p, h in self.hashes.items()},
                    'config_sha256':self.config_hash,
                    'models': {role:self.args.specs[name]['model'] for role,name in [('controller',self.args.controller),('writer',self.args.writer),('reviewer_1',self.args.reviewer[0]),('reviewer_2',self.args.reviewer[1])]},
                    'tasks':[{'task_id':t['task_id'],'state':s.get('state') if s.get('state') in horch.SETTLED_STATES | {'running','long_running'} else 'invalid','closed_before_cleanup':bool(s.get('closed'))} for t,s in self.precleanup],
                    'revisions':self.revisions,'assertions':self.assertions,'counts':self.counts,
                    'observations':self.observations,'failure_categories':self.categories}
        (self.directory / 'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {evidence['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='configured Codex worker')
    parser.add_argument('--writer', required=True, help='configured implementation worker')
    parser.add_argument('--reviewer', action='append', required=True, help='configured reviewer; exactly twice')
    parser.add_argument('--repo', type=Path, default=Path('.'), help='existing trusted repository')
    parser.add_argument('--output', type=Path, required=True, help='artifact parent outside repository')
    parser.add_argument('--max-seconds', type=int, default=1800, help='positive overall scenario cap')
    args = parser.parse_args()
    if len(args.reviewer) != 2 or args.max_seconds <= 0:
        parser.error('supply exactly two reviewers and a positive overall cap')
    args.output = args.output.expanduser().resolve()
    try:
        repo = Path(fixture.checked(['git','rev-parse','--show-toplevel'], cwd=args.repo).strip()).resolve()
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        path = args.output / ('controller-preflight-' + str(time.time_ns()) + '.json')
        path.write_text(json.dumps({'verdict':'fail','failure_categories':['repo_invalid']})+'\n')
        print(f'Preflight failed; evidence: {path}')
        return 1
    if args.output == repo or repo in args.output.parents:
        parser.error('--output must be outside repository')
    args.repo = repo
    # Create only failure evidence artifacts before preflight; no repo/config mutation.
    args.output.mkdir(parents=True, exist_ok=True)
    args.config_path = horch.config_path()
    try:
        config = horch.load_config()
        args.specs = config['workers']
        args.limit = config['max_active_workers']
        selected = [args.controller, args.writer, *args.reviewer]
        if any(w not in args.specs for w in selected):
            raise Failure('configured_role_missing')
        args.controller_spec = args.specs[args.controller]
        if args.controller_spec['harness'] != 'codex':
            raise Failure('controller_not_codex')
        if len({args.specs[w]['model'] for w in args.reviewer}) != 2:
            raise Failure('reviewer_models_not_distinct')
        permission_args = args.controller_spec['args']
        sandbox = any(a in ('-s', '--sandbox') or a.startswith('--sandbox=') or 'sandbox_mode=' in a for a in permission_args)
        approval = any(a in ('-a', '--ask-for-approval') or a.startswith('--ask-for-approval=') or 'approval_policy=' in a for a in permission_args)
        if not args.controller_spec['effort'] or not sandbox or not approval:
            raise Failure('controller_explicit_config_required')
        if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_WORKSPACE_ID'):
            raise Failure('herdr_environment_required')
        run = Run(args)
    except (Exception, SystemExit):
        path = args.output / ('controller-preflight-' + str(time.time_ns()) + '.json')
        path.write_text(json.dumps({'verdict':'fail','failure_categories':['preflight_failed']} )+'\n')
        print(f'Preflight failed; evidence: {path}')
        return 1
    print(f'Run directory: {run.directory}', flush=True)
    print('Isolation covers config/task records only; keep other dispatchers stopped. Global free slots are monitored.', flush=True)
    category = None
    try:
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        category = str(exc) if isinstance(exc, Failure) else 'driver_or_assertion_failed'
        # Exception representations can contain secrets: never persist them.
        print(f'Stopped: {category}', flush=True)
    return run.finish(category)


if __name__ == '__main__':
    sys.exit(main())
