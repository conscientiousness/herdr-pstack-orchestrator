#!/usr/bin/env python3
"""Live Pi playbook evaluation, with private artifacts and conservative receipts.

Runs a real controller in an owned Herdr tab. It never retries, edits worker
configuration, grants trust, or performs forge writes. Retains its worktree.
Only evidence.json is intended for review for eventual sanitized publication.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/herdr-orchestrator/scripts'))
import horch  # noqa: E402
import playbook_cases as cases  # noqa: E402

INVENTORY = ('investigation', 'bug-fix', 'perf-issue', 'hillclimb',
             'runtime-forensics', 'trace-forensics', 'feature', 'refactoring',
             'prototype', 'visual-parity', 'authoring-a-skill', 'eval', 'babysit',
             'shipping', 'autonomous-run', 'autopilot-full',
             'autopilot-stack', 'session-pickup', 'pause-safely',
             'multi-phase-plan', 'worktree-cleanup', 'opening-a-pr')
HISTORICAL_FIXTURE_SOURCE = 'e5136d82418d2db3165ea1050d17577cd618cc05'


class Failure(Exception):
    """A public, fixed failure category; never arbitrary subprocess output."""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_historical_fixture_source(parser):
    manifest = read_json(ROOT / 'skills/pstack-herdr/references/upstream.json')
    if manifest.get('revision') != HISTORICAL_FIXTURE_SOURCE:
        parser.error('This live fixture targets pstack 0.15.25 (e5136d8) and the legacy Herdr pane protocol. '
                     'See e2e/PLAYBOOKS.md for the recorded checkout and replay instructions.')


def source_hashes():
    paths = [*ROOT.joinpath('skills').rglob('*'), Path(__file__).resolve(),
             Path(cases.__file__).resolve(), ROOT / 'e2e/controller_loop.py',
             ROOT / 'e2e/review_loop.py']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def text_content(message):
    return '\n'.join(c.get('text', '') for c in message.get('content', [])
                     if isinstance(c, dict) and c.get('type') == 'text')


def read_target(name, args, cwd):
    """Recognize literal read/cat/sed only; mentioning a path is insufficient."""
    if name == 'read' and isinstance(args.get('path'), str):
        return (cwd / args['path']).resolve()
    if name != 'bash' or not isinstance(args.get('command'), str):
        return None
    command = args['command']
    # Fail closed for substitutions, pipelines, redirects and compound commands.
    if any(t in command for t in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) == 2 and words[0] == 'cat' and not words[1].startswith('-'):
        return (cwd / words[1]).resolve()
    if (len(words) == 4 and words[:2] == ['sed', '-n']
            and re.fullmatch(r'\d+,\d+p', words[2]) and not words[3].startswith('-')):
        return (cwd / words[3]).resolve()
    return None


def invocation_result(command, output, cwd, requirement):
    """Match one actual Python CLI invocation and independently check its result."""
    lines = command.strip().splitlines()
    if not lines:
        return False
    first, stdin = lines[0], None
    heredoc = re.search(r"\s*<<\s*(['\"])([A-Za-z_]\w*)\1\s*$", first)
    if heredoc:
        if len(lines) < 3 or lines[-1].strip() != heredoc[2]:
            return False
        first, stdin = first[:heredoc.start()], '\n'.join(lines[1:-1])
    elif len(lines) != 1:
        return False
    if any(token in first for token in (';', '|', '&', '>', '<', '`', '$', '\\')):
        return False
    try:
        argv = shlex.split(first)
        if (len(argv) < 2 or Path(argv[0]).name not in {'python', 'python3'}
                or (cwd / argv[1]).resolve() != Path(requirement['script']).resolve()):
            return False
        prefix = requirement.get('arguments', [])
        if argv[2:2 + len(prefix)] != prefix:
            return False
        actual = json.loads(output.strip())
        oracle = requirement['oracle']
        if oracle == 'json_equals':
            return len(argv) == 2 + len(prefix) and actual == requirement['expected_output']
        if oracle == 'rounding':
            if len(argv) != 2 + len(prefix) or stdin is None:
                return False
            data = json.loads(stdin)
            numerators = [r['quantity'] * r['unit_price_cents'] * (10000 - r['discount_bp'])
                          for r in data['lines']]
            if not numerators or not any(n % 10000 for n in numerators):
                return False
            variant = requirement['variant']
            total = (sum((n + 5000) // 10000 for n in numerators) if variant == 'per_line'
                     else (sum(numerators) + 5000) // 10000)
            return actual == {'variant': variant, 'total_cents': total}
        if oracle == 'sqlite_query':
            if len(argv) != 3 + len(prefix):
                return False
            sql = argv[-1]
            if requirement.get('sql') is not None and sql != requirement['sql']:
                return False
            if not sql.lstrip().lower().startswith('select '):
                return False
            with sqlite3.connect(f"file:{requirement['database']}?mode=ro", uri=True) as database:
                deadline = time.monotonic() + 3
                database.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                accessed = set()
                def authorize(action, table, column, *_):
                    if action == sqlite3.SQLITE_READ:
                        if table == requirement.get('required_table', 'profile_samples'):
                            accessed.add(column)
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_OK if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION} else sqlite3.SQLITE_DENY
                database.set_authorizer(authorize)
                cursor = database.execute(sql)
                expected = {'columns': [item[0] for item in cursor.description],
                            'rows': [list(row) for row in cursor.fetchmany(100)]}
            required_columns = requirement.get('required_read_columns')
            columns_ok = (set(required_columns) <= accessed if required_columns is not None
                          else 'function' in accessed and bool(accessed & {'self_seconds', 'cumulative_seconds'}))
            return bool(expected['rows']) and actual == expected and columns_ok
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        return False
    return False



def literal_horch_command(name, args, cwd, bundle):
    if name != 'bash':
        return None
    command = args.get('command', '')
    if not isinstance(command, str) or any(t in command for t in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if (len(words) >= 3 and Path(words[0]).name in {'python', 'python3'}
            and (cwd / words[1]).resolve() == (bundle / 'skills/herdr-orchestrator/scripts/horch.py').resolve()):
        return words[2:]
    return None

def rounding_observation(event, cwd, requirement):
    """Decode only the same direct CLI/quoted-heredoc grammar as its oracle."""
    if event['name'] != 'bash' or not invocation_result(
            event['args'].get('command', ''), event['output'], cwd, requirement):
        return None
    lines = event['args']['command'].strip().splitlines()
    if len(lines) < 3:
        return None
    try:
        data = json.loads('\n'.join(lines[1:-1]))
        rows = data['lines']
        if not isinstance(rows, list) or not rows:
            return None
        for row in rows:
            if any(type(row[key]) is not int or row[key] < 0
                   for key in ('quantity', 'unit_price_cents', 'discount_bp')) or row['discount_bp'] > 10000:
                return None
        numerators = [row['quantity'] * row['unit_price_cents'] * (10000 - row['discount_bp']) for row in rows]
        totals = {'per_line': sum((value + 5000) // 10000 for value in numerators),
                  'per_invoice': (sum(numerators) + 5000) // 10000}
        return {'input': data, 'totals': totals, 'event': event}
    except (ValueError, TypeError, KeyError):
        return None


def audit_prototype(events, calls, cwd, tasks, bundle, requirements, workflow, implementation_workers):
    """Witness this Prototype sequence using native successful result/call rows."""
    names = ('prototype checklist precedes delegation',
             'prototype scripts inspected before observations',
             'variant observations share a discriminating input',
             'prototype decision and reply follow observations',
             'prototype bounded implementation routing')
    checks = {name: False for name in names}
    metadata_ok = (workflow.get('type') == 'prototype' and len(workflow.get('steps', [])) == 6
                   and len(workflow.get('observations', [])) == 2
                   and len(workflow.get('required_artifact_reads', [])) == 3)
    proof = {'type': 'prototype', 'stages': [], 'sequence_verified': False}
    if not metadata_ok:
        return [{'name': name, 'ok': False} for name in names], proof
    steps = workflow['steps']
    source_steps = re.findall(r'^\d+\. (.+)$',
                             (bundle / 'skills/poteto-mode/playbooks/prototype.md').read_text(), re.M)
    if [re.sub(r'^\d+\.\s*', '', step) for step in steps] != source_steps:
        return [{'name': name, 'ok': False} for name in names], proof
    checklist = Path(workflow['checklist']).resolve()
    scripts = [Path(path).resolve() for path in workflow['required_artifact_reads']]
    writes = [event for event in events if event['name'] == 'write'
              and isinstance(event['args'].get('path'), str)
              and isinstance(event['args'].get('content'), str)]
    runs = [(call, literal_horch_command(call['name'], call['args'], cwd, bundle)) for call in calls]
    runs = [(call, argv) for call, argv in runs if argv and argv[0] == 'run']
    first_run = min((call['call_row'] for call, _ in runs), default=-1)
    checklist_event, skip_reason = None, None
    for event in writes:
        content = event['args']['content']
        if ((cwd / event['args']['path']).resolve() != checklist or event['result_row'] >= first_run
                or not all(step in content for step in source_steps)):
            continue
        start, stop = content.find(source_steps[1]), content.find(source_steps[2])
        match = re.search(r'(?im)\bskip:\s*([^\n]+)', content[start:stop]) if stop > start else None
        if (workflow.get('reference_direction_fixed') is True and match
                and re.search(r'\b(?:set|fixed|supplied|contract|specified)\b', match[1], re.I)):
            checklist_event, skip_reason = event, match[1].strip()
            break
    checks[names[0]] = checklist_event is not None
    inspected = {}
    for event in events:
        target = read_target(event['name'], event['args'], cwd)
        if target in scripts and target.is_file():
            content = target.read_text().strip()
            if content and content in event['output']:
                inspected.setdefault(target, event['result_row'])
    required = {item['name']: item for item in requirements}
    matched_requirements = [required.get(name, {}) for name in workflow['observations']]
    shared_cli = (all(item.get('script') for item in matched_requirements)
                  and len({str(Path(item['script']).resolve()) for item in matched_requirements}) == 1
                  and {item.get('variant') for item in matched_requirements} == {'per_line', 'per_invoice'}
                  and Path(matched_requirements[0]['script']).resolve() in scripts)
    candidates = []
    for name in workflow['observations']:
        requirement = required.get(name, {})
        if requirement.get('oracle') != 'rounding' or requirement.get('variant') not in {'per_line', 'per_invoice'}:
            candidates.append([])
            continue
        candidates.append([observation for event in events
                           if (observation := rounding_observation(event, cwd, requirement)) is not None])
    pairs = [(left, right) for left in candidates[0] for right in candidates[1]
             if left['input'] == right['input']
             and left['totals']['per_line'] != left['totals']['per_invoice']]
    # Prefer a pair that also has all script inspections complete before either
    # call. Do not replace call ordering with successful-result list positions.
    def inspections_before(pair):
        return len(inspected) == len(scripts) and all(
            inspected[path] < min(item['event']['call_row'] for item in pair) for path in scripts)
    pair = next((item for item in pairs if inspections_before(item)), pairs[0] if pairs else None)
    checks[names[2]] = pair is not None and shared_cli
    checks[names[1]] = pair is not None and inspections_before(pair)
    completion = {}
    if pair:
        after = max(item['event']['result_row'] for item in pair)
        for label in ('decision', 'reply'):
            path = Path(workflow[label]).resolve()
            completion[label] = next((event for event in writes
                                      if (cwd / event['args']['path']).resolve() == path
                                      and event['call_row'] > after and bool(event['args']['content'].strip())
                                      and path.is_file() and event['args']['content'] == path.read_text()), None)
        checks[names[3]] = all(completion.values())
    agent_path = str((bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md').resolve())
    mode_path = str((bundle / 'skills/poteto-mode/SKILL.md').resolve())
    routing = bool(tasks) and bool(implementation_workers)
    for task in tasks:
        brief = Path(task['brief_path']).read_text()
        # Check the controller's assignment, before horch appends generic worker
        # instructions; the bounded playbook assignment must forbid delegation.
        assignment = brief.split('## Worker rules', 1)[0]
        routing &= (task['worker'] in implementation_workers and 'feature, refactoring' in assignment
                    and task['worker'] in assignment and bool(re.search(r'\b(?:reason|because)\b', assignment, re.I))
                    and agent_path in assignment and mode_path in assignment
                    and bool(re.search(r'\b(?:do not|must not|never)\s+(?:delegate|spawn\s+(?:sub)?agents?|use\s+(?:native\s+)?subagents?)\b|\bno\s+(?:delegation|subagents)\b', assignment, re.I))
                    and bool(re.search(r'\b(?:bounded|scoped|only implementing|whole playbook)\b', assignment, re.I)))
    launched = []
    known_tasks = {task['task_id']: task for task in tasks}
    for event in events:
        argv = literal_horch_command(event['name'], event['args'], cwd, bundle)
        if not argv or len(argv) < 2 or argv[0] != 'run':
            continue
        try:
            result = json.loads(event['output'].strip())
        except ValueError:
            continue
        if not isinstance(result, dict):
            continue
        task = known_tasks.get(result.get('task_id'))
        if task and argv[1] == task['worker'] and result.get('worker') == task['worker']:
            launched.append((event, task['task_id']))
    launch_ids = {task_id for _, task_id in launched}
    checks[names[4]] = bool(routing) and launch_ids == set(known_tasks)
    first_launch = min((event for event, _ in launched), key=lambda event: event['call_row'], default=None)
    # Keep six records even on a failed sequence, so absent evidence is visible.
    proof['stages'] = [
        {'step': 1, 'instruction': steps[0],
         'checklist_result_row': checklist_event['result_row'] if checklist_event else None},
        {'step': 2, 'instruction': steps[1], 'status': 'skip' if skip_reason else 'unverified',
         'reason': 'The supplied scenario fixes the behavioral design direction.' if skip_reason else None,
         'reason_sha256': hashlib.sha256(skip_reason.encode()).hexdigest() if skip_reason else None,
         'checklist_result_row': checklist_event['result_row'] if checklist_event else None},
        {'step': 3, 'instruction': steps[2], 'launch_call_row': first_launch['call_row'] if first_launch else None,
         'launch_result_row': first_launch['result_row'] if first_launch else None},
        {'step': 4, 'instruction': steps[3], 'script_read_result_rows': sorted(inspected.values())},
        {'step': 5, 'instruction': steps[4],
         'observations': [{'name': name, 'call_row': item['event']['call_row'],
                           'result_row': item['event']['result_row']}
                          for name, item in zip(workflow['observations'], pair)] if pair else [],
         'input_sha256': hashlib.sha256(json.dumps(pair[0]['input'], sort_keys=True).encode()).hexdigest() if pair else None,
         'oracle_totals': pair[0]['totals'] if pair else None},
        {'step': 6, 'instruction': steps[5],
         'decision_call_row': completion['decision']['call_row'] if completion.get('decision') else None,
         'decision_result_row': completion['decision']['result_row'] if completion.get('decision') else None,
         'reply_call_row': completion['reply']['call_row'] if completion.get('reply') else None,
         'reply_result_row': completion['reply']['result_row'] if completion.get('reply') else None},
    ]
    proof['sequence_verified'] = all(checks.values())
    return [{'name': name, 'ok': ok} for name, ok in checks.items()], proof


def workflow_steps(workflow, bundle, name, count):
    expected = re.findall(r'^\d+\. (.+)$',
                          (bundle / f'skills/poteto-mode/playbooks/{name}.md').read_text(), re.M)
    supplied = workflow.get('steps', [])
    return expected if len(expected) == count and [
        re.sub(r'^\d+\.\s*', '', step) for step in supplied] == expected else []


def workflow_writes(events, cwd, path, after=-1, before=float('inf'), final=False):
    target = Path(path).resolve()
    return [event for event in events if event['name'] == 'write'
            and isinstance(event['args'].get('path'), str)
            and (cwd / event['args']['path']).resolve() == target
            and isinstance(event['args'].get('content'), str)
            and event['args']['content'].strip()
            and event['call_row'] > after and event['result_row'] < before
            and (not final or target.is_file() and event['args']['content'] == target.read_text())]


def workflow_reads(events, cwd, path, after=-1, before=float('inf')):
    target = Path(path).resolve()
    if not target.is_file():
        return []
    content = target.read_text().strip()
    return [event for event in events if content and read_target(event['name'], event['args'], cwd) == target
            and content in event['output'] and event['call_row'] > after and event['result_row'] < before]


def workflow_launches(events, tasks, cwd, bundle):
    known = {task['task_id']: task for task in tasks}
    launches, deliveries = {}, {}
    for event in events:
        argv = literal_horch_command(event['name'], event['args'], cwd, bundle)
        if not argv:
            continue
        for line in event['output'].splitlines():
            try:
                result = json.loads(line)
            except ValueError:
                continue
            if not isinstance(result, dict):
                continue
            task = known.get(result.get('task_id'))
            if not task:
                continue
            if (argv[0] == 'run' and len(argv) > 1 and argv[1] == task['worker']
                    and result.get('worker') == task['worker']):
                launches.setdefault(task['task_id'], event)
            if (argv[0] == 'wait' and result.get('state') == 'done'
                    and result.get('result_path') == task['result_path']):
                deliveries.setdefault(task['task_id'], event)
    return launches, deliveries


def workflow_report_reads(events, task, cwd, delivery, before=float('inf'), report_name=None):
    if delivery is None:
        return []
    result = read_json(Path(task['result_path']))
    directory = Path(task['task_dir']).resolve()
    reads = []
    for filename in result.get('files', []):
        path = (directory / filename).resolve()
        if directory not in path.parents or path.suffix.lower() not in {'.md', '.txt'}:
            continue
        if report_name is not None and path != directory / report_name:
            continue
        for event in workflow_reads(events, cwd, path, after=delivery['result_row'], before=before):
            reads.append((event, path.read_text().strip()))
    return sorted(reads, key=lambda item: item[0]['result_row'])


def audit_investigation(events, calls, cwd, tasks, bundle, workflow, roles):
    names = ('investigation checklist precedes how delegation',
             'investigation how loaded before delegation',
             'investigation configured parallel explorer routing',
             'investigation delivered explorer reports precede synthesis',
             'investigation synthesis includes both explorer reports',
             'investigation findings and reply follow synthesis',
             'investigation unslop follows synthesis before reply',
             'investigation reply preserves the delivered explanation')
    checks = dict.fromkeys(names, False)
    steps = workflow_steps(workflow, bundle, 'investigation', 4)
    proof = {'type': 'investigation', 'stages': [], 'sequence_verified': False,
             'quality_scope': 'Verbatim delivered explanation plus one checkpoint; no generic prose-quality guarantee.'}
    if not steps:
        return [{'name': name, 'ok': False} for name in names], proof
    launches, deliveries = workflow_launches(events, tasks, cwd, bundle)
    first_run = min((call['call_row'] for call in calls
                     if (argv := literal_horch_command(call['name'], call['args'], cwd, bundle))
                     and argv[0] == 'run'), default=-1)
    initial = next((event for event in workflow_writes(events, cwd, workflow['checklist'], before=first_run)
                    if all(step in event['args']['content'] for step in steps)), None)
    how_reads = workflow_reads(events, cwd, bundle / 'skills/how/SKILL.md', before=first_run)
    checks[names[0]], checks[names[1]] = initial is not None, bool(how_reads)
    explorer_role, explainer_role = workflow['explorer_role'], workflow['explainer_role']
    expected_roles = (explorer_role, explainer_role)
    assignments, classified = {}, {role: [] for role in expected_roles}
    routing = len(tasks) == 3 and len(launches) == 3
    for task in tasks:
        assignment = Path(task['brief_path']).read_text().split('## Worker rules', 1)[0]
        assignments[task['task_id']] = assignment
        # The assignment's own role comes before any pasted explorer reports.
        mentions = [(assignment.find(role), role) for role in expected_roles if role in assignment]
        role = min(mentions)[1] if mentions else None
        configured = roles.get(role)
        selected = configured if isinstance(configured, list) else [configured]
        valid = (role is not None and task['worker'] in selected
                 and task['worker'] in assignment and re.search(r'\b(?:reason|because)\b', assignment, re.I)
                 and re.search(r'\bread[- ]only\b', assignment, re.I)
                 and re.search(r'\b(?:do not|must not|never)\s+(?:delegate|spawn\s+(?:sub)?agents?|use\s+(?:native\s+)?subagents?)\b|\bno\s+(?:delegation|subagents)\b', assignment, re.I))
        routing = routing and bool(valid)
        if role is not None:
            classified[role].append(task)
    explorers, explainers = classified[explorer_role], classified[explainer_role]
    angles = workflow.get('angles', [])
    actual_angles = []
    for task in explorers:
        matches = re.findall(r'(?m)^Angle:\s*([a-z_]+)\s*$', assignments[task['task_id']])
        actual_angles.extend(matches)
        routing = routing and len(matches) == 1
    scope = workflow.get('source_paths', [])
    routing = routing and all(any(
        str(Path(path).resolve()) in assignments[task['task_id']]
        or str(Path(path).resolve().parent) in assignments[task['task_id']]
        for path in scope) for task in explorers)
    routing = routing and len(scope) == 3 and all(any(
        str(Path(path).resolve()) in assignments[task['task_id']]
        or str(Path(path).resolve().parent) in assignments[task['task_id']]
        for task in explorers) for path in scope)
    first_wait = min((call['call_row'] for call in calls
                      if (argv := literal_horch_command(call['name'], call['args'], cwd, bundle))
                      and argv[0] == 'wait'), default=-1)
    parallel = (len(explorers) == 2 and len(explainers) == 1 and len(angles) == 2
                and sorted(actual_angles) == sorted(angles)
                and all(task['task_id'] in launches and launches[task['task_id']]['call_row'] < first_wait
                        for task in explorers))
    checks[names[2]] = bool(routing and parallel)
    explainer = explainers[0] if len(explainers) == 1 else None
    synthesis = launches.get(explainer['task_id']) if explainer else None
    reports = {}
    if synthesis:
        for task in explorers:
            reads = workflow_report_reads(events, task, cwd, deliveries.get(task['task_id']),
                                          before=synthesis['call_row'], report_name='report.md')
            if reads:
                reports[task['task_id']] = reads[0]
    checks[names[3]] = len(explorers) == 2 and len(reports) == 2
    if synthesis and len(reports) == 2:
        assignment = assignments[explainer['task_id']]
        checks[names[4]] = (all(content in assignment for _, content in reports.values())
                            and all(angle in assignment for angle in angles))
    synthesized = workflow_report_reads(events, explainer, cwd, deliveries.get(explainer['task_id']),
                                         report_name='report.md') if explainer else []
    synthesis_read = synthesized[0][0] if synthesized else None
    findings, reply, unslop = None, None, None
    if synthesis_read:
        after = synthesis_read['result_row']
        findings = next(iter(workflow_writes(events, cwd, workflow['findings'], after=after, final=True)), None)
        reply = next(iter(workflow_writes(events, cwd, workflow['reply'], after=after, final=True)), None)
        checks[names[5]] = bool(findings and reply
                                and workflow['throughput'] in reply['args']['content'].splitlines())
        if reply:
            unslop = next(iter(workflow_reads(events, cwd, bundle / 'skills/unslop/SKILL.md',
                                              after=after, before=reply['call_row'])), None)
        checks[names[6]] = unslop is not None
        if reply:
            checkpoint = workflow['throughput']
            final_lines = reply['args']['content'].splitlines()
            delivered = '\n'.join(line for line in synthesized[0][1].splitlines()
                                   if line.strip() != checkpoint).strip()
            presented = '\n'.join(line for line in final_lines
                                   if line.strip() != checkpoint).strip()
            checks[names[7]] = final_lines.count(checkpoint) == 1 and bool(delivered) and presented == delivered
    proof['stages'] = [
        {'step': 1, 'instruction': steps[0],
         'checklist_result_row': initial['result_row'] if initial else None,
         'how_read_result_row': how_reads[0]['result_row'] if how_reads else None,
         'explorer_launch_call_rows': [launches[task['task_id']]['call_row'] for task in explorers if task['task_id'] in launches],
         'first_wait_call_row': first_wait if first_wait >= 0 else None,
         'explorer_delivery_result_rows': [deliveries[task['task_id']]['result_row'] for task in explorers if task['task_id'] in deliveries],
         'explorer_report_read_result_rows': [event['result_row'] for event, _ in reports.values()],
         'explainer_launch_call_row': synthesis['call_row'] if synthesis else None},
        {'step': 2, 'instruction': steps[1], 'throughput': workflow['throughput'],
         'reply_result_row': reply['result_row'] if reply else None},
        {'step': 3, 'instruction': steps[2],
         'explainer_delivery_result_row': deliveries[explainer['task_id']]['result_row'] if explainer and explainer['task_id'] in deliveries else None,
         'synthesis_report_read_result_row': synthesis_read['result_row'] if synthesis_read else None,
         'findings_result_row': findings['result_row'] if findings else None},
        {'step': 4, 'instruction': steps[3],
         'unslop_read_result_row': unslop['result_row'] if unslop else None,
         'delivered_explanation_sha256': hashlib.sha256(synthesized[0][1].encode()).hexdigest() if synthesized else None,
         'verbatim_presentation_verified': checks[names[7]],
         'final_reply_call_row': reply['call_row'] if reply else None,
         'final_reply_result_row': reply['result_row'] if reply else None},
    ]
    proof['sequence_verified'] = all(checks.values())
    return [{'name': name, 'ok': bool(ok)} for name, ok in checks.items()], proof


def literal_python_argv(command):
    if not isinstance(command, str) or any(t in command for t in ('\n', ';', '|', '&', '>', '<', chr(96), '$', '\\')):
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    return argv if len(argv) > 1 and Path(argv[0]).name in {'python', 'python3'} else None


def audit_trace(events, calls, cwd, tasks, bundle, requirements, workflow):
    names = ('trace checklist precedes conversion',
             'trace conversion precedes raw inspection and queries',
             'trace ranked query supports source attribution',
             'trace captured call tree supports hot path',
             'trace paired query confirms lookup elimination',
             'trace source inspected after conversion before diagnosis',
             'trace diagnosis and reply follow supported observations')
    checks = dict.fromkeys(names, False)
    steps = workflow_steps(workflow, bundle, 'trace-forensics', 6)
    proof = {'type': 'trace-forensics', 'stages': [], 'sequence_verified': False,
             'scope': 'Bounded controller-local capture inspection; delegated inspection is unsupported.'}
    if not steps:
        return [{'name': name, 'ok': False} for name in names], proof
    expected_sql = {
        'hot_sql': "SELECT file,line,function,calls,self_seconds,cumulative_seconds FROM profile_samples WHERE capture='before' ORDER BY self_seconds DESC LIMIT 10",
        'pair_sql': "SELECT capture,SUM(CASE WHEN function='lookup_reference' THEN calls ELSE 0 END) AS lookup_calls FROM profile_samples GROUP BY capture ORDER BY capture",
        'edge_sql': "SELECT caller_file,caller_line,caller_function,callee_file,callee_line,callee_function,calls FROM profile_edges WHERE capture='before' AND callee_function='lookup_reference' ORDER BY caller_file,caller_line,caller_function",
    }
    source, tool = Path(workflow['source']).resolve(), Path(workflow['profile_tool']).resolve()
    imports, queries = [], {key: [] for key in expected_sql}
    for event in events:
        if event['name'] != 'bash':
            continue
        argv = literal_python_argv(event['args'].get('command', ''))
        if not argv or (cwd / argv[1]).resolve() != tool:
            continue
        for requirement in requirements:
            if not invocation_result(event['args']['command'], event['output'], cwd, requirement):
                continue
            if requirement.get('oracle') == 'json_equals' and argv[2:3] == ['import']:
                imports.append(event)
            elif requirement.get('oracle') == 'sqlite_query' and argv[2:3] == ['query']:
                for key, sql in expected_sql.items():
                    if workflow.get(key) == sql and argv[-1] == sql:
                        queries[key].append(event)
    imported = imports[0] if imports else None
    first_import_call = min((call['call_row'] for call in calls if call['name'] == 'bash'
                             and (argv := literal_python_argv(call['args'].get('command', '')))
                             and (cwd / argv[1]).resolve() == tool and argv[2:3] == ['import']), default=-1)
    initial = next((event for event in workflow_writes(
        events, cwd, workflow['checklist'], before=first_import_call)
        if all(step in event['args']['content'] for step in steps)), None)
    checks[names[0]] = initial is not None and imported is not None
    protected = [source, Path(workflow['database']).resolve(),
                 *[Path(path).resolve() for path in workflow['captures']]]
    accesses = []
    for call in calls:
        target = read_target(call['name'], call['args'], cwd)
        raw = target in protected
        if call['name'] == 'bash':
            command = call['args'].get('command', '')
            argv = literal_python_argv(command)
            is_import = bool(argv and (cwd / argv[1]).resolve() == tool and argv[2:3] == ['import'])
            is_query = bool(argv and (cwd / argv[1]).resolve() == tool and argv[2:3] == ['query'])
            try:
                shell = shlex.split(command)
            except ValueError:
                shell = []
            metadata = bool(shell and shell[0] in {'ls', 'stat', 'file'})
            mentions_raw = any(str(path) in command or path.name in command for path in protected)
            raw = raw or is_query or (mentions_raw and not is_import and not metadata)
        elif call['name'] == 'grep':
            argument_text = json.dumps(call['args'])
            raw = raw or any(str(path) in argument_text or str(path.parent) in argument_text for path in protected)
        if raw:
            accesses.append(call)
    checks[names[1]] = bool(imported and not tasks and all(
        call['call_row'] > imported['result_row'] for call in accesses))
    hot, edge, paired = (next(iter(queries[key]), None) for key in ('hot_sql', 'edge_sql', 'pair_sql'))
    if hot:
        output = json.loads(hot['output'].strip())
        rows = output.get('rows', [])
        checks[names[2]] = bool(
            output.get('columns') == ['file', 'line', 'function', 'calls', 'self_seconds', 'cumulative_seconds']
            and rows and len(rows[0]) == 6 and Path(rows[0][0]).resolve() == source
            and rows[0][1:4] == [1, 'lookup_reference', 6000]
            and all(type(value) in {int, float} and value > 0 for value in rows[0][4:])
            and rows[0][5] >= rows[0][4])
    if edge:
        output = json.loads(edge['output'].strip())
        checks[names[3]] = bool(
            output.get('columns') == ['caller_file', 'caller_line', 'caller_function',
                                      'callee_file', 'callee_line', 'callee_function', 'calls']
            and any(len(row) == 7 and Path(row[0]).resolve() == source and row[2] == '<genexpr>'
                    and Path(row[3]).resolve() == source and row[4:] == [1, 'lookup_reference', 6000]
                    for row in output.get('rows', [])))
    if paired:
        output = json.loads(paired['output'].strip())
        checks[names[4]] = (output.get('columns') == ['capture', 'lookup_calls']
                            and output.get('rows') == [['after', 0], ['before', 6000]])
    source_read = None
    if imported and hot and edge and paired:
        after = max(imported['result_row'], hot['result_row'], edge['result_row'])
        source_read = next(iter(workflow_reads(events, cwd, source, after=after,
                                               before=paired['call_row'])), None)
    checks[names[5]] = source_read is not None
    diagnosis, reply = None, None
    if imported and hot and edge and paired and source_read:
        after = max(event['result_row'] for event in (imported, hot, edge, paired, source_read))
        diagnosis = next(iter(workflow_writes(events, cwd, workflow['diagnosis'], after=after, final=True)), None)
        reply = next(iter(workflow_writes(events, cwd, workflow['reply'], after=after, final=True)), None)
        checks[names[6]] = bool(diagnosis and reply
                                and workflow['throughput'] in reply['args']['content'].splitlines())
    proof['stages'] = [
        {'step': 1, 'instruction': steps[0], 'checklist_result_row': initial['result_row'] if initial else None,
         'import_call_row': imported['call_row'] if imported else None},
        {'step': 2, 'instruction': steps[1], 'import_result_row': imported['result_row'] if imported else None},
        {'step': 3, 'instruction': steps[2], 'ranked_query_result_row': hot['result_row'] if hot else None,
         'call_tree_query_result_row': edge['result_row'] if edge else None},
        {'step': 4, 'instruction': steps[3], 'source_read_result_row': source_read['result_row'] if source_read else None},
        {'step': 5, 'instruction': steps[4], 'paired_query_call_row': paired['call_row'] if paired else None,
         'paired_query_result_row': paired['result_row'] if paired else None,
         'lookup_calls': {'before': 6000, 'after': 0} if checks[names[4]] else None},
        {'step': 6, 'instruction': steps[5], 'throughput': workflow['throughput'],
         'diagnosis_call_row': diagnosis['call_row'] if diagnosis else None,
         'diagnosis_result_row': diagnosis['result_row'] if diagnosis else None,
         'reply_call_row': reply['call_row'] if reply else None,
         'reply_result_row': reply['result_row'] if reply else None},
    ]
    proof['sequence_verified'] = all(checks.values())
    return [{'name': name, 'ok': bool(ok)} for name, ok in checks.items()], proof


def audit_pi(path, session, cwd, started, spec, required_reads, required_commands, tasks, bundle,
             required_invocations=(), required_order=(), workflow=None, implementation_workers=(), configured_roles=None,
             allowed_artifact_copies=(), allowed_artifact_hashes=()):
    """Trust native successful calls/results, never a controller's self-report."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or rows[0].get('type') != 'session' or rows[0].get('version') != 3:
        raise Failure('native_transcript_unsupported')
    header = rows[0]
    if (Path(header.get('cwd', '')).resolve() != cwd or not started <= stamp(header['timestamp']) <= time.time()
            or not header.get('id')):
        raise Failure('native_session_binding_failed')
    value = session.get('value')
    if session.get('agent') != 'pi' or not value:
        raise Failure('native_session_identity_missing')
    if session.get('kind') == 'path':
        if Path(value).expanduser().resolve() != path.resolve():
            raise Failure('native_session_identity_mismatch')
    elif value != header['id']:
        raise Failure('native_session_identity_mismatch')
    pending, successful, read_paths = {}, [], set()
    calls, events = [], []
    delivered, artifact_reads = set(), set()
    known_tasks = {task['task_id']: task for task in tasks}
    horch_script = (bundle / 'skills/herdr-orchestrator/scripts/horch.py').resolve()
    copy_pairs = {(str(source), str(destination)) for source, destination in allowed_artifact_copies}
    hash_sources = {}
    delivered_closed = set()
    for source in allowed_artifact_hashes:
        target = Path(source)
        owners = [task for task in tasks if target.parent == Path(task['task_dir']).resolve()]
        if (not target.is_absolute() or target.resolve() != target or not target.is_file()
                or len(owners) != 1 or target.name in {'brief.md', 'task.json', 'state.json', 'result.json'}):
            raise Failure('native_artifact_hash_source_invalid')
        owner = owners[0]
        if Path(owner['result_path']).resolve() != target.parent / 'result.json':
            raise Failure('native_artifact_hash_source_invalid')
        result = read_json(Path(owner['result_path']))
        state = read_json(target.parent / 'state.json')
        if (horch.validate_result(result, owner) != 'valid' or result.get('status') != 'completed'
                or target.name not in result.get('files', [])
                or state.get('state') != 'done' or state.get('closed') is not True):
            raise Failure('native_artifact_hash_source_invalid')
        hash_sources[str(target)] = owner['task_id']
    def artifact_hash_target(name, args):
        if name != 'bash' or not isinstance(args.get('command'), str):
            return None
        command = args['command']
        if any(token in command for token in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
            return None
        try:
            words = shlex.split(command)
        except ValueError:
            return None
        if len(words) == 2 and words[0] == 'sha256sum' and words[1] in hash_sources:
            return Path(words[1])
        return None
    last = None
    ids = set()
    models = set()
    thinking = set()
    for row_index, row in enumerate(rows[1:], 1):
        identity = row.get('id')
        if identity in ids or not identity or row.get('parentId') != last:
            raise Failure('native_transcript_branch_or_identity_ambiguous')
        ids.add(identity)
        last = identity
        if row.get('type') == 'model_change':
            models.add((row.get('provider'), row.get('modelId')))
        if row.get('type') == 'thinking_level_change':
            thinking.add(row.get('thinkingLevel'))
        message = row.get('message', {})
        if message.get('role') == 'assistant':
            if message.get('model'):
                models.add((message.get('provider'), message['model']))
            for block in message.get('content', []):
                if block.get('type') != 'toolCall':
                    continue
                name = block.get('name', '')
                if name not in {'read', 'bash', 'write', 'edit', 'grep', 'find', 'ls'}:
                    raise Failure('native_delegation_or_unsupported_tool')
                args = block.get('arguments')
                if not isinstance(args, dict) or block.get('id') in pending:
                    raise Failure('native_tool_arguments_invalid')
                command = args.get('command', '')
                if name == 'bash' and re.search(r'(?:^|[;&|\n]\s*)(?:codex|claude|pi)\b|\bherdr\s+agent\s+start\b', command):
                    raise Failure('native_delegation_forbidden')
                hash_target = artifact_hash_target(name, args)
                if hash_target is not None and hash_sources[str(hash_target)] not in delivered_closed:
                    raise Failure('artifact_hash_before_proven_closed_delivery')
                pending[block['id']] = (name, args, row_index)
                calls.append({'name': name, 'args': args, 'call_row': row_index})
        elif message.get('role') == 'toolResult':
            pair = pending.pop(message.get('toolCallId'), None)
            if pair is None or message.get('toolName') != pair[0]:
                raise Failure('native_tool_result_unbound')
            if message.get('isError') is not False:
                continue
            name, args, call_row = pair
            output = text_content(message)
            successful.append((name, args, output))
            events.append({'name': name, 'args': args, 'output': output,
                           'call_row': call_row, 'result_row': row_index})
            target = read_target(name, args, cwd)
            is_artifact_copy = False
            hash_target = artifact_hash_target(name, args)
            is_artifact_hash = hash_target is not None
            if is_artifact_hash:
                target = hash_target
                if output.strip() != sha(target) + '  ' + str(target):
                    raise Failure('native_artifact_hash_result_mismatch')
            if name == 'bash':
                command = args.get('command', '')
                if not any(token in command for token in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
                    try:
                        copy_words = shlex.split(command)
                    except ValueError:
                        copy_words = []
                    if (len(copy_words) == 3 and copy_words[0] == 'cp'
                            and tuple(copy_words[1:]) in copy_pairs):
                        target = Path(copy_words[1]).resolve()
                        is_artifact_copy = True
            # Other literal artifact-access forms must not disappear from an
            # ordering audit merely because their shell grammar is unsupported.
            argument_text = json.dumps(args, ensure_ascii=False)
            if name in {'bash', 'grep', 'find', 'ls'} and target is None:
                if name == 'bash':
                    from controller_loop import without_literal_file_writes
                    argument_text = without_literal_file_writes(args.get('command', ''))
                mentions_task = any(task['task_dir'] in argument_text or task['task_id'] in argument_text
                                    for task in tasks)
                is_horch_operation = False
                if name == 'bash' and not any(t in argument_text for t in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
                    try:
                        argv = shlex.split(argument_text)
                        is_horch_operation = (len(argv) >= 3 and Path(argv[0]).name in {'python', 'python3'}
                                              and (cwd / argv[1]).resolve() == horch_script
                                              and argv[2] in {'run', 'wait', 'list', 'close', 'stats'})
                    except ValueError:
                        pass
                if mentions_task and not is_horch_operation:
                    raise Failure('native_artifact_access_unsupported')
            if name == 'bash':
                command = args.get('command', '')
                words = []
                if not any(token in command for token in ('\n', ';', '|', '&', '>', '<', '`', '$', '\\')):
                    try:
                        words = shlex.split(command)
                    except ValueError:
                        pass
                # Delivery must come from the actual literal horch wait command,
                # not echo, prose or reading a fabricated status file.
                if (len(words) >= 3 and Path(words[0]).name in ('python', 'python3')
                        and (cwd / words[1]).resolve() == horch_script and words[2] == 'wait'):
                    for line in output.splitlines():
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        task = known_tasks.get(event.get('task_id'))
                        if task and event.get('state') == 'done':
                            if (event.get('result_path') != task['result_path']
                                    or stamp(row['timestamp']) < Path(task['result_path']).stat().st_mtime):
                                raise Failure('native_delivery_binding_failed')
                            delivered.add(task['task_id'])
                            if event.get('closed') is True:
                                delivered_closed.add(task['task_id'])
            if target:
                for task in tasks:
                    directory = Path(task['task_dir']).resolve()
                    if (directory in target.parents and target.is_file()
                            and target.name not in {'brief.md', 'task.json', 'state.json'}):
                        if task['task_id'] not in delivered:
                            raise Failure('artifact_read_before_proven_delivery')
                        content = target.read_text().strip()
                        if not is_artifact_copy and not is_artifact_hash and content and content in output:
                            artifact_reads.add(task['task_id'])
            if target in required_reads and not is_artifact_copy and not is_artifact_hash:
                # Native read offsets/truncation and partial sed ranges count only
                # if the actual result contains the complete required document.
                content = target.read_text().strip()
                if content and content in output:
                    read_paths.add(target)
    if pending:
        raise Failure('native_tool_result_missing')
    if not models or any(model != spec['model'] or (spec.get('provider') and provider != spec['provider'])
                         for provider, model in models):
        raise Failure('native_model_changed_or_unproven')
    if spec.get('effort') and thinking != {spec['effort']}:
        raise Failure('native_effort_changed_or_unproven')
    checks = [{'name': 'read ' + str(p.relative_to(bundle)), 'ok': p in read_paths}
              for p in required_reads]
    checks.extend([{'name': 'tasks observed delivered through horch wait',
                    'ok': delivered == set(known_tasks)},
                   {'name': 'task artifacts read after delivery',
                    'ok': artifact_reads == set(known_tasks)}])
    for requirement in required_commands:
        pattern = re.compile(requirement['pattern'])
        checks.append({'name': 'command text hint: ' + requirement['name'], 'ok': any(
            name == 'bash' and pattern.search(args.get('command', '')) and bool(output.strip())
            for name, args, output in successful)})
    positions = {}
    for requirement in required_invocations:
        for index, (name, args, output) in enumerate(successful):
            if name == 'bash' and invocation_result(args.get('command', ''), output, cwd, requirement):
                positions.setdefault(requirement['name'], index)
        checks.append({'name': requirement['name'], 'ok': requirement['name'] in positions})
    if required_order:
        checks.append({'name': 'native required invocation order', 'ok': all(
            left in positions and right in positions and positions[left] < positions[right]
            for left, right in zip(required_order, required_order[1:]))})
    ordered_workflow = None
    if workflow:
        if workflow.get('type') == 'prototype':
            workflow_checks, ordered_workflow = audit_prototype(
                events, calls, cwd, tasks, bundle, required_invocations, workflow, implementation_workers)
        elif workflow.get('type') == 'investigation':
            workflow_checks, ordered_workflow = audit_investigation(
                events, calls, cwd, tasks, bundle, workflow, configured_roles or {})
        elif workflow.get('type') == 'trace-forensics':
            workflow_checks, ordered_workflow = audit_trace(
                events, calls, cwd, tasks, bundle, required_invocations, workflow)
        else:
            raise Failure('native_workflow_unsupported')
        checks.extend(workflow_checks)
    return {'checks': checks, 'tool_calls': len(successful),
            **({'ordered_workflow': ordered_workflow} if ordered_workflow is not None else {}),
            'session_id_sha256': hashlib.sha256(header['id'].encode()).hexdigest(),
            'sha256': sha(path), 'format': 'pi-session-v3',
            'harness': 'pi', 'model': spec['model'], 'effort': spec.get('effort')}


class Run:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.wall_started = time.time()
        self.deadline = self.started + max(1, args.max_seconds)
        self.directory = args.output / ('playbook-' + str(time.time_ns()))
        self.directory.mkdir(parents=True, mode=0o700)
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.directory / 'config'),
                        XDG_STATE_HOME=str(self.directory / 'state'))
        # Isolate horch state without hiding the user's existing forge login.
        self.env['GH_CONFIG_DIR'] = os.environ.get('GH_CONFIG_DIR') or str(
            Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'gh')
        # Isolate horch without changing the shell's existing Mise trust roots.
        for variable, xdg, default in (
                ('MISE_CONFIG_DIR', 'XDG_CONFIG_HOME', Path.home() / '.config'),
                ('MISE_STATE_DIR', 'XDG_STATE_HOME', Path.home() / '.local/state')):
            self.env.setdefault(variable, str(Path(os.environ.get(xdg, default)) / 'mise'))
        # Keep Git's original global config order despite the isolated XDG root.
        # Includes retain relative paths and conditional includes in those files.
        if 'GIT_CONFIG_GLOBAL' not in self.env:
            git_global = self.directory / 'git-global.config'
            originals = (Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'git/config',
                         Path.home() / '.gitconfig')
            includes = []
            for original in originals:
                if original.is_file():
                    quoted = str(original.absolute()).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    includes.append('[include]\n\tpath = "' + quoted + '"\n')
            git_global.write_text(''.join(includes))
            self.env['GIT_CONFIG_GLOBAL'] = str(git_global)
        self.task_root = self.directory / 'state/herdr-orchestrator/tasks'
        self.worktree = args.repo / 'handoff' / self.directory.name / 'worktree'
        self.bundle = self.directory / 'bundle'
        self.artifacts = self.directory / 'artifacts'
        self.pane = None
        self.agent = 'playbook-e2e-' + format(time.time_ns(), 'x')
        self.session = {}
        self.tasks = {}
        self.checks, self.stage_checks, self.categories = [], [], []
        self.hashes = {}
        self.config_hash = None
        self.spec = {}
        self.config = {}
        self.native = {}
        self.behavior = {}
        self.prepared = {}
        self.revision = None
        self.case = cases.CASES.get(args.scenario, {})
        self.command_number = 0
        self.tracked_baseline = None
        self.untracked_baseline = set()
        self.inventory_names = sorted(p.stem for p in (ROOT / 'skills/poteto-mode/playbooks').glob('*.md'))
        self.phase = 'preflight'

    def call(self, argv, *, cleanup=False):
        timeout = 30 if cleanup else min(150, self.deadline - time.monotonic())
        if timeout <= 0:
            raise Failure('overall_timeout')
        self.command_number += 1
        try:
            proc = subprocess.run([str(a) for a in argv], env=self.env, text=True,
                                  capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failure('subprocess_timeout') from None
        # Commands, stdout, stderr and failures stay private.
        (self.directory / f'command-{self.command_number}.json').write_text(json.dumps(
            {'argv': [str(a) for a in argv], 'returncode': proc.returncode,
             'stdout': proc.stdout, 'stderr': proc.stderr}, indent=2))
        if proc.returncode:
            raise Failure('subprocess_failed')
        return proc.stdout

    def herdr(self, *args, cleanup=False):
        return json.loads(self.call(['herdr', *args], cleanup=cleanup))['result']

    def check(self, name, ok):
        self.checks.append({'name': name, 'ok': bool(ok)})
        if not ok:
            raise Failure('assertion_failed')

    def preflight(self):
        self.check('inventory_matches_declared_playbooks',
                   set(self.inventory_names) == set(INVENTORY))
        if self.args.max_seconds <= 0 or not self.case:
            raise Failure('scenario_or_duration_invalid')
        repo = Path(self.call(['git', '-C', self.args.repo, 'rev-parse', '--show-toplevel']).strip()).resolve()
        self.check('repository_root', repo == self.args.repo)
        self.revision = self.call(['git', '-C', repo, 'rev-parse', 'HEAD']).strip()
        self.hashes = source_hashes()
        self.config_path = horch.config_path()
        self.config_hash = sha(self.config_path)
        # horch's CLI error details may contain configuration or caller paths.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane,
                                                       getattr(self.args, 'caller_text', None))
        self.spec = self.config['workers'].get(self.args.controller, {})
        if self.spec.get('harness') != 'pi':
            raise Failure('controller_harness_unsupported')
        roles = self.case.get('expected_roles', [])
        for role in roles:
            selection = self.config.get('roles', {}).get(role)
            names = selection if isinstance(selection, list) else [selection]
            if not names or any(name not in self.config['workers'] for name in names):
                raise Failure('configured_role_missing')

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.call(['git', '-C', self.args.repo, 'worktree', 'add', '--detach', self.worktree, 'HEAD'])
        self.prepared = cases.prepare(self.args.scenario, self.worktree, self.artifacts, self.bundle)
        (self.directory / 'prepared.json').write_text(json.dumps(self.prepared, indent=2) + '\n')
        self.tracked_baseline = self.call(['git', '-C', self.worktree, 'diff', '--binary', 'HEAD'])
        self.untracked_baseline = set(self.call(['git', '-C', self.worktree, 'ls-files',
                                                '--others', '--exclude-standard']).splitlines())
        for role in self.prepared.get('expected_roles', []):
            value = self.config.get('roles', {}).get(role)
            names = value if isinstance(value, list) else [value]
            if not names or any(name not in self.config['workers'] for name in names):
                raise Failure('configured_role_missing')
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'],
                         '--cwd', self.worktree, '--label', 'playbook-e2e', '--no-focus',
                         '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                         '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'],
                         '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                         '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'],
                         '--env', 'GIT_CONFIG_GLOBAL=' + self.env['GIT_CONFIG_GLOBAL'])
        self.pane = tab['root_pane']['pane_id']
        workflow_type = self.prepared.get('workflow', {}).get('type')
        workflow_instructions = {
            'prototype': '''Use separate native write calls for the stage checklist, decision.json and
reply.md. Include any valid fixed-direction reference skip in the initial
checklist before delegation. Inspect every delegated script with a separate
full-file native read before the comparison observations. The decision and
final report must follow those observations.''',
            'investigation': '''Use separate native write calls for the exact original four-step checklist,
findings.json and reply.md. Write the checklist and fully read the how skill
before delegation. Launch both scoped explorers before the first wait. Read
their complete delivered Markdown reports before launching the explainer;
include the actual full report bodies and both angle keys in its brief.
Write EVERY complete worker brief with the native write tool. Do not read,
copy, concatenate or write task artifacts using bash, inline Python or another
script, even after delivery. This auditor cannot bind those program semantics.
Ask explorers to keep their scoped reports concise, preferably under 8 KB,
while retaining all six original explorer sections and their concrete evidence.
Require each explorer and explainer to write its complete report as report.md
in its task directory and list that report in result.json files, then read it.
After reading the delivered explainer report, write findings.json, fully read
the unslop skill again, then present the report unchanged with only the exact
throughput line added. Tell the explainer to apply unslop before delivering.
This fixture's witness protocol is stricter than How's allowance for light
edits. If the synthesis needs substantive correction, report the unresolved
stage instead of rewriting it yourself.''',
            'trace-forensics': '''Use separate native write calls for the exact original six-step checklist,
diagnosis.json and reply.md. Write the checklist before importing captures.
Do not read source or raw capture contents or query the database before the
import result. Observe ranked and captured-edge queries, fully read the source,
then observe the paired query. Write diagnosis and final reply only after all
those successful results, with the exact throughput line in the final reply.''',
        }.get(workflow_type, '')
        delegation_instructions = 'Keep this bounded trace inspection in the controller.'
        if workflow_type != 'trace-forensics':
            delegation_instructions = f'''Use {self.bundle / 'skills/herdr-orchestrator/scripts/horch.py'} for delegation,
with --caller-pane {self.pane} when dispatching; never native subagents.
For delivery use a standalone native bash call of python3 followed by the exact
absolute horch.py path, wait, and task IDs. Read each delivered task's report or
result with a separate native read call, after wait has reported state done.'''
        if workflow_type == 'prototype':
            delegation_instructions += f'''
Verify your own controller pane with herdr pane process-info --pane {self.pane}
and herdr pane read {self.pane} --source visible just before dispatch. Choose text
of at least 16 characters uniquely visible in this evaluation conversation.
Include it verbatim as --caller-text with --caller-pane on each horch run.
If the caller cannot be verified, report the unresolved stage.'''
        prompt = f'''This is a real playbook evaluation. Read {self.bundle / 'skills/poteto-mode/SKILL.md'}
in full first, then select and execute the applicable original playbook and its
Herdr mapping. Follow the playbook's required stages and use configured roles.
The source bundle is {self.bundle}; work only in {self.worktree}.
This evaluator supports only the native read, bash, write, edit, grep, find and
ls tools. Do not use codemode or another tool wrapper: its nested calls are not
visible to this auditor. Use separate native calls for report reads and brief
writes, even when combining the data would be convenient.
For each required source document use a separate native read call without an
offset/limit, or a literal cat of that single file, so its full contents appear
in the native tool result. If truncated, report the unsupported evidence stage.
{delegation_instructions}
Write your final answer to {self.artifacts / 'reply.md'}.
Put all checklists and control notes under {self.artifacts}; the worktree is read-only.
{workflow_instructions}
Do not create or edit evidence.json or an evaluator/checker. No external forge
writes, merges, configuration edits, trust changes, or model substitutions are
authorized. Report any blocked required stage explicitly.
\n{self.prepared['prompt']}\n'''
        brief = self.directory / 'controller-brief.md'
        brief.write_text(prompt)
        session_dir = self.directory / 'native-sessions'
        session_dir.mkdir()
        flags = horch.launch_args(self.spec, self.directory)
        flags += ['--session-dir', str(session_dir)]
        started = self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
                             '--timeout', '90000', '--', *flags)
        self.check('controller_started', started.get('type') == 'agent_started')
        ready_deadline = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < ready_deadline:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi'
                    and session.get('value') and entry.get('agent_status') in ('idle', 'done')):
                self.session = session
                break
            if entry.get('agent_status') == 'blocked':
                raise Failure('controller_start_blocked')
            time.sleep(min(1, max(0, ready_deadline - time.monotonic())))
        else:
            raise Failure('controller_session_not_ready')
        prompted = self.herdr('agent', 'prompt', self.agent,
                              f'Read {brief} in full and execute it.', '--wait',
                              '--until', 'working', '--timeout', '30000')
        self.check('controller_prompted', prompted.get('type') == 'agent_prompted')

    def scan(self):
        rows = []
        for path in sorted(self.task_root.glob('t-*/task.json')):
            task = read_json(path)
            if (not horch.TASK_ID_RE.fullmatch(path.parent.name)
                    or task.get('task_id') != path.parent.name
                    or Path(task.get('task_dir', '')).resolve() != path.parent.resolve()
                    or task.get('agent') != 'horch-' + path.parent.name[2:]):
                raise Failure('task_identity_invalid')
            if self.args.scenario == 'prototype' and task.get('backend', {}).get('kind') != 'legacy':
                raise Failure('prototype_worker_backend_unsupported')
            # Only these independently discovered isolated tasks are cleanup-owned.
            self.tasks[task['task_id']] = task
            state = read_json(path.parent / 'state.json')
            rows.append((task, state))
        return rows

    def monitor(self):
        idle_since = None
        while time.monotonic() < self.deadline:
            rows = self.scan()
            if any(s.get('state') in horch.SETTLED_STATES - {'done'} for _, s in rows):
                raise Failure('worker_failed_or_blocked')
            entry = self.herdr('agent', 'get', self.agent)['agent']
            self.session = entry.get('agent_session') or self.session
            status = entry.get('agent_status')
            if status == 'blocked':
                raise Failure('controller_blocked')
            if status in ('idle', 'done'):
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= 8:
                    return
            else:
                idle_since = None
            time.sleep(min(1, max(0, self.deadline - time.monotonic())))
        raise Failure('overall_timeout')

    def verify(self):
        rows = self.scan()
        if self.prepared.get('read_only'):
            self.check('tracked_worktree_unchanged', self.call(
                ['git', '-C', self.worktree, 'diff', '--binary', 'HEAD']) == self.tracked_baseline)
            untracked = set(self.call(['git', '-C', self.worktree, 'ls-files',
                                      '--others', '--exclude-standard']).splitlines())
            unexpected = {p for p in untracked - self.untracked_baseline
                          if not (p.startswith('.audit/') or p in {'todo.md', '.todo.md'}
                                  or '__pycache__' in Path(p).parts)}
            self.check('only_controller_notes_added_to_worktree', not unexpected)
        self.check('reply_exists', (self.artifacts / 'reply.md').is_file())
        self.check('tasks_delivered_and_closed', all(
            state.get('state') == 'done' and state.get('closed') is True for _, state in rows))
        for task, _ in rows:
            worker = self.config['workers'].get(task.get('worker'), {})
            if self.args.scenario == 'prototype':
                caller = task.get('controller_verification') or {}
                self.check('prototype_worker_caller_verified', caller.get('method') == 'conversation_text'
                           and caller.get('pane_id') == self.pane
                           and caller.get('workspace_id') == self.caller['workspace_id']
                           and caller.get('cwd') == str(self.worktree))
            self.check('task_configuration_and_scope',
                       task.get('cwd') == str(self.worktree)
                       and task.get('model') == worker.get('model')
                       and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir']))
                       and Path(task.get('result_path', '')).resolve() == Path(task['task_dir']) / 'result.json')
            result = read_json(Path(task['result_path']))
            self.check('task_result_identity', horch.validate_result(result, task) == 'valid'
                       and result.get('status') == 'completed')
        for role in self.prepared.get('expected_roles', []):
            value = self.config['roles'].get(role)
            names = value if isinstance(value, list) else [value]
            used = []
            for task, _ in rows:
                brief = Path(task['brief_path']).read_text()
                # Role and worker must occur in the actual submitted brief,
                # together with an explicit selection reason, not just the reply.
                if role in brief and task.get('worker') in brief and re.search(r'\b(?:reason|because)\b', brief, re.I):
                    used.append(task['worker'])
            self.check('configured_role_' + role, all(used.count(name) >= names.count(name) for name in names))
        candidates = []
        for path in (self.directory / 'native-sessions').glob('*.jsonl'):
            with path.open() as stream:
                header = json.loads(stream.readline())
            if header.get('type') == 'session' and Path(header.get('cwd', '')).resolve() == self.worktree:
                candidates.append(path)
        self.check('native_transcript_unique', len(candidates) == 1)
        required = [(self.bundle / p).resolve() for p in self.prepared['required_reads']]
        self.native = {'sha256': sha(candidates[0]), 'format': 'pi-session-v3',
                       'session_identity_sha256': hashlib.sha256(str(self.session.get('value', '')).encode()).hexdigest()}
        self.native.update(audit_pi(candidates[0], self.session, self.worktree, self.wall_started,
                               self.spec, required, self.prepared.get('required_commands', []),
                               [task for task, _ in rows], self.bundle,
                               self.prepared.get('required_invocations', []),
                               self.prepared.get('required_order', []),
                               self.prepared.get('workflow'),
                               [self.config.get('roles', {}).get('feature, refactoring')]
                               if isinstance(self.config.get('roles', {}).get('feature, refactoring'), str)
                               else self.config.get('roles', {}).get('feature, refactoring', []),
                               self.config.get('roles', {})))
        self.stage_checks = self.native['checks']
        self.behavior = cases.verify(self.args.scenario, self.worktree, self.artifacts,
                                     self.prepared.get('context', {}))
        self.checks.extend(self.behavior.get('checks', []))
        observed = {c['name']: c.get('ok') is True for c in
                    self.stage_checks + self.behavior.get('checks', [])}
        declared = self.case.get('required_stages', [])
        self.stage_checks.extend({'name': 'stage_' + name, 'ok': observed.get(name, False)}
                                 for name in declared)
        self.check('declared_stages_present', bool(declared))
        self.check('native_required_stages', all(c['ok'] for c in self.stage_checks))

    def finish(self):
        cleanup_ok = True
        if not self.native:
            try:
                paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
                if len(paths) == 1:
                    self.native = {'sha256': sha(paths[0]), 'audit_completed': False,
                                   'session_identity_sha256': hashlib.sha256(str(
                                       self.session.get('value', '')).encode()).hexdigest()}
            except Exception:
                self.categories.append('native_snapshot_failed')
        # Inspect every owned pane before closure. Stop controller first, preventing
        # new tasks, then scan once more for tasks created during the last poll.
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
            cleanup_ok = False
            self.categories.append('task_snapshot_failed')
        task_facts = []
        for task in self.tasks.values():
            try:
                state = read_json(Path(task['task_dir']) / 'state.json')
                task_facts.append({'task_id': task['task_id'], 'worker': task['worker'],
                                   'harness': task.get('harness'), 'model': task.get('model'),
                                   'effort': self.config.get('workers', {}).get(task.get('worker'), {}).get('effort'),
                                   'state': state.get('state') if state.get('state') in horch.SETTLED_STATES | {'running', 'long_running'} else 'invalid',
                                   'closed_before_cleanup': state.get('closed') is True})
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task.get('pane_id'):
                        raise Failure('cleanup_ownership_unproven')
                    screen = self.call(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'], cleanup=True)
                    (self.directory / (task['task_id'] + '-pane.json')).write_text(screen)
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py',
                               'close', task['task_id']], cleanup=True)
            except Exception:
                cleanup_ok = False
        for pane in ([self.pane] if self.pane else []) + [t['pane_id'] for t in self.tasks.values()]:
            try:
                proc = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env,
                                      text=True, capture_output=True, timeout=15)
                reply = json.loads(proc.stdout or proc.stderr)
                error = reply.get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if proc.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        integrity = False
        after_hashes = {}
        try:
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            after_hashes = source_hashes()
            integrity = (bool(self.hashes) and after_hashes == self.hashes
                         and sha(self.config_path) == self.config_hash
                         and (not copied.exists() or sha(copied) == self.config_hash)
                         and self.call(['git', '-C', self.args.repo, 'rev-parse', 'HEAD'], cleanup=True).strip() == self.revision)
            if self.bundle.exists() and (self.bundle / 'skills').exists():
                integrity = integrity and all(sha(self.bundle / p) == digest for p, digest in self.hashes.items() if p.startswith('skills/'))
        except Exception:
            pass
        self.checks += [{'name': 'source_and_config_integrity', 'ok': integrity},
                        {'name': 'owned_panes_absent', 'ok': cleanup_ok}]
        passed = not self.categories and all(c.get('ok') is True for c in self.checks)
        behavior_ok = bool(self.behavior.get('checks')) and all(c.get('ok') is True for c in self.behavior['checks'])
        stage_ok = bool(self.stage_checks) and all(c.get('ok') is True for c in self.stage_checks)
        prerequisite_block = self.phase in ('preflight', 'setup') or any(
            c in ('controller_blocked', 'controller_session_not_ready', 'controller_start_blocked') for c in self.categories)
        workflow = 'pass' if passed and self.case.get('workflow_complete', False) else (
            'blocked' if passed or prerequisite_block else 'fail')
        playbook = self.case.get('playbook', self.args.scenario)
        inventory = {name: 'not_run' for name in sorted(set(self.inventory_names) | set(INVENTORY))}
        if playbook in inventory:
            inventory[playbook] = workflow
        receipt = {'schema': 'horch/playbook-e2e/v1', 'scenario': self.args.scenario,
                   'verdict': 'pass' if passed else 'fail',
                   'stage_coverage': {'verdict': 'pass' if stage_ok else 'fail', 'checks': self.stage_checks,
                                      'declared_stages': self.case.get('required_stages', [])},
                   'behavior_verdict': 'pass' if behavior_ok else 'fail',
                   'workflow_verdict': workflow, 'full_inventory_verdict': 'not_run',
                   'inventory': inventory, 'inventory_discovered': self.inventory_names, 'source_revision': self.revision,
                   'source_sha256_before': self.hashes, 'source_sha256_after': after_hashes, 'config_sha256_before': self.config_hash,
                   'config_sha256_after': None, 'controller': {k: self.spec.get(k) for k in ('harness', 'model', 'effort', 'provider')},
                   'native_transcript': self.native, 'tasks': task_facts, 'checks': self.checks,
                   'observations': self.behavior.get('observations', {}),
                   'failure_categories': self.categories, 'last_phase': self.phase,
                   'claims': self.prepared.get('claims', []) if passed else [],
                   'limitations': self.behavior.get('limitations', []) + [
                       'Arbitrary inter-task dependency graphs are not inferred; only declared workflow sequences and delivery before artifact reads are audited.'],
                   'seconds': round(time.monotonic() - self.started, 3)}
        try:
            receipt['config_sha256_after'] = sha(self.config_path)
        except Exception:
            pass
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='existing configured Pi worker used as evaluation controller')
    parser.add_argument('--scenario', required=True, help='scenario key in playbook_cases.CASES')
    parser.add_argument('--repo', type=Path, default=Path('.'), help='existing trusted repository root')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside repository')
    parser.add_argument('--caller-pane', required=True, help='explicit actual caller pane; independently verified')
    parser.add_argument('--caller-text', help='unique visible conversation text (at least 16 characters) for agent controllers')
    parser.add_argument('--max-seconds', type=int, default=1800, help='overall run deadline')
    args = parser.parse_args()
    args.repo = args.repo.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.output == args.repo or args.repo in args.output.parents:
        parser.error('--output must be outside repository')
    if args.scenario == 'prototype':
        try:
            core_executable = horch.core.executable()
        except horch.core.CoreError:
            parser.error('Prototype requires a verified legacy Herdr backend. Core detection failed.')
        if core_executable is not None:
            parser.error('Prototype uses the legacy Herdr pane oracle. This environment selects herdr-core.')
    elif args.scenario != 'trace-forensics':
        require_historical_fixture_source(parser)
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
