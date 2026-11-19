#!/usr/bin/env python3
"""Verify horch check deduplication, one-slot batching, skips, exits and cleanup.

Uses existing authenticated workers without changing their flags or trust.
Creates one owned workspace and private isolated config/state outside the repo.
Only evidence.json is a sanitized receipt; retained config/state are private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
HORCH = REPO / 'skills/agent-workers/scripts/agent-workers.py'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Run:
    def __init__(self, args, workers):
        self.args, self.workers = args, workers
        self.root = Path(tempfile.mkdtemp(prefix='horch-check-', dir=args.output))
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_STATE_HOME=str(self.root / 'state'))
        self.config = self.root / 'config/herdr-orchestrator/workers.toml'
        self.store = self.root / 'state/herdr-orchestrator/tasks'
        self.workspace = None
        self.process = None
        self.assertions, self.observations = [], {}
        self.versions = {'python': sys.version.split()[0]}
        self.hashes = {'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))}
        self.started = time.monotonic()
        self.wall_started = time.time()
        self.complete = False
        self.selected = []
        self.sequence = 0
        self.diagnostics = self.root / 'diagnostics'
        self.diagnostics.mkdir(mode=0o700)

    def sanitize(self, value):
        text = json.dumps(value, ensure_ascii=False)
        paths = {str(Path.home()): '<home>', str(REPO): '<repo>',
                 str(self.args.cwd): '<cwd>', str(self.args.output): '<output>',
                 str(self.root): '<run>', str(self.args.source_config): '<workers-config>'}
        for path in sorted(paths, key=len, reverse=True):
            text = text.replace(json.dumps(path, ensure_ascii=False)[1:-1], paths[path])
        return json.loads(text)

    def check(self, name, ok):
        self.assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def streams(self, stdout, stderr):
        self.sequence += 1
        for suffix, value in (('stdout', stdout), ('stderr', stderr)):
            if isinstance(value, bytes):
                value = value.decode('utf-8', errors='replace')
            (self.diagnostics / f'{self.sequence:03d}.{suffix}').write_text(value or '', encoding='utf-8')

    def failure(self, exc):
        with (self.diagnostics / 'failure.txt').open('a', encoding='utf-8') as stream:
            stream.write(f'{type(exc).__name__}: {exc}\n')

    def command(self, argv, timeout=30):
        try:
            proc = subprocess.run([str(a) for a in argv], env=self.env, cwd=self.args.cwd,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.streams(exc.stdout, exc.stderr)
            raise
        self.streams(proc.stdout, proc.stderr)
        return proc

    @staticmethod
    def version(value):
        # Publish only a version number, never arbitrary CLI diagnostics.
        match = re.search(r'\b\d+\.\d+\.\d+\b', str(value))
        return match.group(0) if match else None

    def herdr(self, *argv):
        proc = self.command(['herdr', *argv])
        if proc.returncode:
            raise RuntimeError('herdr_command_failed')
        return json.loads(proc.stdout)['result']

    def cli(self, *argv, timeout=60):
        return self.command([sys.executable, HORCH, *argv], timeout)

    def rows(self, label, proc):
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.observations[label] = {'exit_code': proc.returncode, 'rows': [
            {k: (v[:400] if isinstance(v, str) else v) for k, v in row.items()
             if k in ('worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds')}
            for row in rows]}
        return rows

    def records(self):
        # Invalid records are errors, never silently omitted from quota evidence.
        return {p.parent.name: read(p) for p in self.store.glob('t-*/task.json')}

    def panes(self):
        return {p['pane_id'] for p in self.herdr(
            'pane', 'list', '--workspace', self.workspace['workspace_id'])['panes']}

    def allocation(self):
        return set(self.records()), self.panes()

    def configure(self, limit):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        text = f'max_active_workers = {limit}\n'
        for name, spec in self.workers.items():
            def encode(value):
                # TOML accepts Unicode scalars, not JSON surrogate pairs or raw DEL.
                return json.dumps(value, ensure_ascii=False).replace('\x7f', '\\u007f')
            text += '\n[workers.' + encode(name) + ']\n'
            # The supported worker fields are strings and arrays of strings.
            text += ''.join(f'{encode(k)} = {encode(v)}\n' for k, v in spec.items())
        if not self.workers:
            text += '\n[workers]\n'
        self.config.write_text(text, encoding='utf-8')
        parsed = tomllib.loads(self.config.read_text())
        if parsed != {'max_active_workers': limit, 'workers': self.workers}:
            raise RuntimeError('isolated_config_roundtrip_failed')

    def close_tasks(self):
        for task_id in self.records():
            if not read(self.store / task_id / 'state.json').get('closed'):
                proc = self.cli('close', task_id)
                if proc.returncode:
                    raise RuntimeError('owned_task_close_failed')

    def scenario(self):
        for tool in dict.fromkeys(['herdr', *(w['harness'] for w in self.workers.values())]):
            proc = self.command([tool, '--version'])
            self.versions['herdr_cli' if tool == 'herdr' else tool] = {
                'exit_code': proc.returncode, 'version': self.version(proc.stdout or proc.stderr)}
        # `herdr status server --json` prints the status object itself, without a "result" envelope.
        proc = self.command(['herdr', 'status', 'server', '--json'])
        if proc.returncode:
            raise RuntimeError('herdr_command_failed')
        server = json.loads(proc.stdout)
        version = self.version(server.get('version')) if isinstance(server, dict) else None
        self.versions['herdr_server'] = {'version': version}
        if self.versions['herdr_server']['version'] is None:
            raise RuntimeError('herdr_server_version_unavailable')
        caller = self.herdr('pane', 'current', '--current')['pane']
        if any(not isinstance(caller.get(k), str) or not caller[k].strip()
               for k in ('workspace_id', 'tab_id', 'pane_id')):
            raise RuntimeError('invalid_live_caller_context')
        self.configure(1)
        result = self.herdr('workspace', 'create', '--cwd', str(self.args.cwd),
                            '--label', 'check-workers-e2e', '--no-focus',
                            '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                            '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'])
        self.workspace = result['workspace']
        self.env.update(HERDR_WORKSPACE_ID=self.workspace['workspace_id'],
                        HERDR_TAB_ID=result['tab']['tab_id'], HERDR_PANE_ID=result['root_pane']['pane_id'])
        baseline = self.panes()
        names = list(self.workers)
        self.selected = [names[0], *names]  # repeat first worker; unique count exceeds one-slot limit
        proc = self.cli('check', *self.selected, '--cwd', self.args.cwd,
                        '--max-seconds', self.args.max_seconds, timeout=self.args.max_seconds + 180)
        rows = self.rows('batch', proc)
        self.check('C001 check exits successfully', proc.returncode == 0)
        self.check('C002 selected workers deduplicated in order', self.selected == [names[0], *names]
                   and [r.get('worker') for r in rows] == list(dict.fromkeys(self.selected)))
        self.check('C003 all workers deliver done and ok', all(r.get('ok') is True and r.get('state') == 'done' for r in rows))
        records = self.records()
        self.check('C004 exactly one real task per unique selection', len(records) == len(names)
                   and {r.get('task_id') for r in rows} == set(records)
                   and all(records[r['task_id']]['worker'] == r['worker'] for r in rows))
        states = [read(self.store / t / 'state.json') for t in records]
        self.check('C005 every batch task closed and done', all(s.get('closed') is True and s.get('state') == 'done' for s in states))
        self.check('C006 check leaves exactly baseline panes', self.panes() == baseline)
        results = {t: read(self.store / t / 'result.json') for t in records}
        self.check('C007 matching completion identities', all(v.get('task_id') == t
                   and v.get('nonce') == records[t]['nonce'] and v.get('status') == 'completed'
                   for t, v in results.items()))
        self.check('C008 isolated tasks retain selected models and workspace', all(
            r.get('workspace_id') == self.workspace['workspace_id']
            and r.get('harness') == self.workers[r['worker']]['harness']
            and r.get('model') == self.workers[r['worker']]['model'] for r in records.values()))

        # Independent filesystem observations, before any driver cleanup.
        # Strict ordering fails closed on coarse timestamps instead of hiding overlap.
        lifecycle = [{'task_id': row['task_id'],
                      'published_ns': (self.store / row['task_id'] / 'task.json').stat().st_mtime_ns,
                      'closed_ns': (self.store / row['task_id'] / 'state.json').stat().st_mtime_ns}
                     for row in rows]
        self.observations['batch_lifecycle'] = lifecycle
        self.check('C009 each reservation begins after previous slot release', all(
            later['published_ns'] > earlier['closed_ns']
            for earlier, later in zip(lifecycle, lifecycle[1:])))

        self.configure(0)
        before = self.allocation()
        proc = self.cli('check', *names, '--cwd', self.args.cwd)
        rows = self.rows('zero_slots', proc)
        fields = {'worker', 'task_id', 'state', 'ok', 'pane_id', 'seconds', 'message'}
        self.check('C010 zero slots report complete skip fields', proc.returncode == 0
                   and [r.get('worker') for r in rows] == names and all(fields <= set(r)
                   and r['state'] == 'not_checked' and r['ok'] is False and r['task_id'] is None
                   and r['pane_id'] is None and r['seconds'] is None for r in rows))
        self.check('C011 zero slots allocate nothing', self.allocation() == before)

        self.configure(1)
        argv = [sys.executable, str(HORCH), 'check', names[0], '--cwd', str(self.args.cwd),
                '--max-seconds', str(self.args.max_seconds)]
        self.process = subprocess.Popen(argv, env=self.env, cwd=self.args.cwd,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        victim = None
        deadline = time.monotonic() + min(90, self.args.max_seconds)
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                for task_id, record in self.records().items():
                    if task_id in before[0]:
                        continue
                    state = read(self.store / task_id / 'state.json')
                    if state.get('state') == 'running' and state.get('saw_working') and not state.get('closed'):
                        victim = record
                        break
            except (FileNotFoundError, json.JSONDecodeError):
                pass  # publication race only; final reads remain strict
            if victim:
                break
            time.sleep(0.1)
        self.check('C020 exit probe reaches acknowledged worker', victim is not None)
        self.herdr('pane', 'close', victim['pane_id'])
        stdout, stderr = self.process.communicate(timeout=self.args.max_seconds + 180)
        self.streams(stdout, stderr)
        proc = subprocess.CompletedProcess(argv, self.process.returncode, stdout, stderr)
        self.process = None
        rows = self.rows('injected_exit', proc)
        self.check('C021 worker exit has concrete diagnostic', proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('task_id') == victim['task_id'] and rows[0].get('state') == 'exited'
                   and rows[0].get('ok') is False and 'gone' in str(rows[0].get('message')))
        self.check('C022 exit probe creates exactly one task', set(self.records()) - before[0] == {victim['task_id']})

        self.close_tasks()
        before = self.allocation()
        proc = self.cli('check', names[0], '--cwd', self.args.cwd, '--max-seconds', '0')
        rows = self.rows('exhausted_budget', proc)
        self.check('C030 exhausted budget skips with wait-limit reason', proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('worker') == names[0] and rows[0].get('state') == 'not_checked'
                   and rows[0].get('ok') is False and 'wait limit' in str(rows[0].get('message')))
        self.check('C031 exhausted budget allocates nothing', self.allocation() == before)
        self.stats_phase(names)
        self.complete = True

    def stats_phase(self, names):
        real = self.records()
        wall_end = time.time()
        unused = next(f'stats-unused{i}' for i in range(len(self.workers) + 1)
                      if f'stats-unused{i}' not in self.workers)
        self.workers[unused] = {'harness': 'pi', 'model': 'stats-model',
                                'effort': 'high', 'provider': 'stats-provider'}
        self.configure(1)
        unknown = next(f'stats-removed{i}' for i in range(len(self.workers) + 1)
                       if f'stats-removed{i}' not in self.workers)
        # Select unused IDs without relying on the randomly allocated task IDs.
        ids = [f't-{n:06x}' for n in range(1, len(real) + 3) if f't-{n:06x}' not in real]
        invalid_id, removed_id = ids[:2]
        created = datetime.fromtimestamp(wall_end - 3600, timezone.utc).isoformat()
        fixture = {'task_id': removed_id, 'nonce': 'stats-fixture', 'worker': unknown,
                   'agent': 'stats-fixture', 'pane_id': 'stats-fixture-no-pane',
                   'created_at': created, 'workspace_id': 'stats-other-workspace'}
        for task_id in (invalid_id, removed_id):
            directory = self.store / task_id
            directory.mkdir()
            task = dict(fixture, task_id=task_id, result_path=str(directory / 'result.json'))
            if task_id == invalid_id:
                task['nonce'] = None
            (directory / 'task.json').write_text(json.dumps(task))
            (directory / 'state.json').write_text(json.dumps({
                'state': 'done', 'closed': True, 'long_notified': task_id == removed_id}))
            (directory / 'result.json').write_text(json.dumps({
                'task_id': task_id, 'nonce': 'stats-fixture', 'status': 'blocked',
                'summary': 'fixture', 'files': [], 'question': 'Fixture specification question?'}))
            os.utime(directory / 'result.json', (wall_end - 900, wall_end - 900))
        # Top-level threshold and a dangling role, without changing worker definitions.
        self.config.write_text('notify_after_minutes = 20\n' + self.config.read_text()
                               + f'\n[roles]\nreview = ["{unknown}"]\n')
        before = {str(p.relative_to(self.root)): sha(p) for p in self.root.rglob('*')
                  if p.is_file() and self.diagnostics not in p.parents}
        proc = self.cli('stats')
        scoped_proc = self.cli('stats', '--workspace', self.workspace['workspace_id'])
        self.check('C040 stats commands return single JSON objects', proc.returncode == scoped_proc.returncode == 0
                   and len(proc.stdout.splitlines()) == len(scoped_proc.stdout.splitlines()) == 1)
        whole, scoped = json.loads(proc.stdout), json.loads(scoped_proc.stdout)
        self.observations['stats'] = whole
        self.observations['stats_workspace'] = scoped
        self.check('C041 stats task counts match real dispatches and fixture',
                   whole['task_count'] == len(real) + 1 and scoped['task_count'] == len(real)
                   and all(obj['workers'][n]['task_count'] == sum(r['worker'] == n for r in real.values())
                           for n in names for obj in (whole, scoped)))
        self.check('C042 stats states and problem rates match scenario', all(
            obj['workers'][n]['states'] == ({'done': 1, 'exited': 1} if n == names[0] else {'done': 1})
            and obj['workers'][n]['problem_count'] == (1 if n == names[0] else 0)
            and obj['workers'][n]['problem_rate'] == (0.5 if n == names[0] else 0)
            for n in names for obj in (whole, scoped)))
        self.check('C043 stats delivered result statuses exclude exited probe', all(
            obj['workers'][n]['result_statuses'] == {'completed': 1} for n in names for obj in (whole, scoped))
            and whole['workers'][unknown]['result_statuses'] == {'blocked': 1})
        self.check('C044 stats invalid record listed globally and excluded from other workspace',
                   whole['invalid_task_ids'] == [invalid_id] and scoped['invalid_task_ids'] == [])
        self.check('C045 stats removed worker is unconfigured and workspace filtered',
                   whole['workers'][unknown]['configured'] is False
                   and whole['workers'][unknown]['task_count'] == 1 and unknown not in scoped['workers']
                   and whole['workers'][unknown]['workspaces'] == {'stats-other-workspace': 1})
        self.check('C046 stats configured unused worker retained in both scopes', all(
            obj['configured_unused_workers'] == [unused]
            and obj['workers'][unused]['configured'] is True
            and obj['workers'][unused]['duration_minutes']['sample_size'] == 0
            and obj['workers'][unused]['task_count'] == 0 for obj in (whole, scoped)))
        states = {t: read(self.store / t / 'state.json') for t in real}
        self.check('C047 new records retain observed first settlement timestamps', all(
            self.wall_started - 1 <= datetime.fromisoformat(s['settled_at'].replace('Z', '+00:00')).timestamp() <= wall_end
            for s in states.values()) and all(
                self.wall_started - 1 <= datetime.fromisoformat(s['first_done_at'].replace('Z', '+00:00')).timestamp() <= wall_end
                for s in states.values() if s['state'] == 'done'))
        bounds = {}
        for task_id, record in real.items():
            if states[task_id]['state'] != 'done':
                continue
            directory = self.store / task_id
            created_at = datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).timestamp()
            bounds[record['worker']] = (
                max(0, (directory.joinpath('result.json').stat().st_mtime - created_at - 1) / 60),
                (directory.joinpath('state.json').stat().st_mtime - created_at + 1) / 60)
        self.observations['stats_duration_bounds_minutes'] = bounds
        self.check('C048 stats durations fit independently observed filesystem bounds', all(
            obj['workers'][n]['duration_minutes']['sample_size'] == 1
            and obj['workers'][n]['duration_minutes']['sources'] == {'first_done_at': 1}
            and obj['workers'][n]['duration_minutes']['max'] <= (wall_end - self.wall_started + 1) / 60
            and all(bounds[n][0] <= obj['workers'][n]['duration_minutes'][key] <= bounds[n][1]
                    for key in ('median', 'p90', 'max')) for n in names for obj in (whole, scoped))
            and whole['workers'][unknown]['duration_minutes'] == {
                'sample_size': 1, 'median': 45.0, 'p90': 45.0, 'max': 45.0, 'sources': {'result_mtime': 1}})
        def contains_args(value):
            if isinstance(value, dict):
                return 'args' in value or any(contains_args(v) for v in value.values())
            return isinstance(value, list) and any(contains_args(v) for v in value)
        self.check('C049 stats never exposes worker args', not contains_args([whole, scoped]))
        self.check('C050 stats workspace counts and reminder denominator match deliveries',
                   all(scoped['workers'][n]['workspaces'] == {
                       self.workspace['workspace_id']: 2 if n == names[0] else 1} for n in names)
                   and whole['delivered_duration_estimate']['timed_task_count'] == len(names) + 1
                   and scoped['delivered_duration_estimate']['timed_task_count'] == len(names))
        after = {str(p.relative_to(self.root)): sha(p) for p in self.root.rglob('*')
                 if p.is_file() and self.diagnostics not in p.parents}
        self.check('C051 stats leaves isolated config and task store unchanged', before == after)

        # Real cancellation, after the original checks so their coverage stays intact.
        brief = self.root / 'cancel-brief.md'
        brief.write_text('This is a cancellation probe. Run sleep 120 before writing any result. '
                         'Do not edit the checkout. The controller will close your pane.\n')
        proc = self.cli('run', names[0], '--brief', brief, '--cwd', self.args.cwd, timeout=180)
        rows = self.rows('cancel_run', proc)
        self.check('C052 cancellation probe starts one real running worker',
                   proc.returncode == 0 and len(rows) == 1
                   and set(self.records()) - set(real) - {invalid_id, removed_id} == {rows[0]['task_id']})
        task_id = rows[0]['task_id']
        directory = self.store / task_id
        state = read(directory / 'state.json')
        self.check('C053 cancellation probe is open and running before close',
                   state['state'] == 'running' and not state['closed']
                   and not (directory / 'result.json').exists()
                   and self.records()[task_id]['pane_id'] in self.panes())
        inflight = json.loads(self.cli('stats').stdout)['workers'][names[0]]
        self.check('C062 running work is in flight, not a settled problem',
                   inflight['unclosed_running'] == 1 and inflight['states']['running'] == 1
                   and inflight['problem_count'] == 1 and inflight['problem_rate'] == 0.5)
        proc = self.cli('close', task_id)
        self.rows('cancel_close', proc)
        state = read(directory / 'state.json')
        self.check('C054 close cancels running probe without settling it',
                   proc.returncode == 0 and state['closed'] is True and state['state'] == 'running'
                   and state.get('settled_at') is None and state.get('first_done_at') is None
                   and self.records()[task_id]['pane_id'] not in self.panes())
        for check_id, label, previous, argv in (
                ('C055', 'stats_after_cancel', whole, ()),
                ('C056', 'stats_workspace_after_cancel', scoped, ('--workspace', self.workspace['workspace_id']))):
            proc = self.cli('stats', *argv)
            current = json.loads(proc.stdout)
            self.observations[label] = current
            # Compare the entire output: only the cancellation count, task totals,
            # workspace count and last-use change; settled problem rate is unchanged.
            expected = json.loads(json.dumps(previous))
            expected['task_count'] += 1
            row = expected['workers'][names[0]]
            row['task_count'] += 1
            row['states']['closed_before_done'] = 1
            row['workspaces'][self.workspace['workspace_id']] += 1
            row['last_use'] = self.records()[task_id]['created_at']
            self.check(f'{check_id} {label} counts cancellation, not running or problems',
                       proc.returncode == 0 and current == expected)

        self.check('C057 fixed thresholds use strict greater-than and nondefault current', all(
            obj['delivered_duration_estimate'] == {
                'timed_task_count': len(names) + extra,
                'current': {'minutes': 20, 'count': extra, 'share': extra / (len(names) + extra)},
                'thresholds': [{'minutes': t, 'count': extra if t < 45 else 0,
                                'share': (extra if t < 45 else 0) / (len(names) + extra)}
                               for t in (15, 30, 45, 60, 90)]}
            for obj, extra in ((whole, 1), (scoped, 0))))
        self.check('C058 worker facts and dangling roles match configuration', all(
            whole['workers'][n][key] == self.workers[n].get(key)
            for n in self.workers for key in ('harness', 'model', 'effort', 'provider'))
            and whole['roles_with_unconfigured_workers'] == {'review': [unknown]})

        # Extend the existing fixture worker with recovered and old deliveries.
        # Fixed 10, 45, 85 minute samples distinguish median from mean, p90
        # from median, first-done from first-problem, and days from whole-store.
        extra_ids = [f't-{n:06x}' for n in range(1, len(self.records()) + 5)
                     if f't-{n:06x}' not in self.records()][:2]
        for task_id, minutes, age in zip(extra_ids, (10, 85), (7200, 3 * 86400)):
            directory = self.store / task_id
            directory.mkdir()
            start = wall_end - age
            stamp = lambda seconds: datetime.fromtimestamp(seconds, timezone.utc).isoformat()
            task = dict(fixture, task_id=task_id, created_at=stamp(start),
                        result_path=str(directory / 'result.json'))
            (directory / 'task.json').write_text(json.dumps(task))
            (directory / 'state.json').write_text(json.dumps({
                'state': 'done', 'closed': True, 'settled_at': stamp(start + 60),
                'first_done_at': stamp(start + minutes * 60)}))
            (directory / 'result.json').write_text(json.dumps({
                'task_id': task_id, 'nonce': 'stats-fixture', 'status': 'completed',
                'summary': 'fixture', 'files': [], 'question': None}))
        extended = json.loads(self.cli('stats').stdout)
        recent = json.loads(self.cli('stats', '--days', '1').stdout)
        self.observations['stats_extended'] = extended
        self.observations['stats_recent'] = recent
        self.check('C059 multi-sample median and nearest-rank p90 use first-done endpoints',
                   extended['workers'][unknown]['duration_minutes'] == {
                       'sample_size': 3, 'median': 45.0, 'p90': 85.0, 'max': 85.0,
                       'sources': {'first_done_at': 2, 'result_mtime': 1}}
                   and extended['workers'][unknown]['duration_samples'] == sorted([
                       {'task_id': removed_id, 'minutes': 45.0, 'endpoint_source': 'result_mtime'},
                       *[{'task_id': t, 'minutes': m, 'endpoint_source': 'first_done_at'}
                         for t, m in zip(extra_ids, (10.0, 85.0))]], key=lambda s: s['task_id']))
        self.check('C060 days scope excludes old delivery and recomputes percentiles',
                   recent['task_count'] == extended['task_count'] - 1
                   and recent['scope']['days'] == 1 and recent['scope']['created_since'] is not None
                   and recent['workers'][unknown]['duration_minutes'] == {
                       'sample_size': 2, 'median': 27.5, 'p90': 45.0, 'max': 45.0,
                       'sources': {'first_done_at': 1, 'result_mtime': 1}})
        fired = {n: sum(s.get('long_notified') is True for t, s in states.items()
                        if real[t]['worker'] == n) for n in names}
        self.check('C063 stored reminder firings count flags per worker and in scope',
                   all(obj['workers'][n]['reminder_fired'] == fired[n]
                       for obj in (whole, scoped, extended, recent) for n in names)
                   and all(obj['workers'][unknown]['reminder_fired'] == 1
                           and obj['reminder_fired'] == sum(fired.values()) + 1
                           for obj in (whole, extended, recent))
                   and scoped['reminder_fired'] == sum(fired.values())
                   and all(obj['workers'][unused]['reminder_fired'] == 0
                           for obj in (whole, scoped, extended, recent)))
        # A current threshold equal to a standard bucket must appear exactly once.
        self.config.write_text(self.config.read_text().replace('notify_after_minutes = 20',
                                                             'notify_after_minutes = 45'))
        dedup = json.loads(self.cli('stats').stdout)['delivered_duration_estimate']
        self.check('C061 current threshold is not duplicated and shares use fixed samples',
                   dedup['current'] == {'minutes': 45, 'count': 1, 'share': 1 / (len(names) + 3)}
                   and dedup['thresholds'] == [
                       {'minutes': t, 'count': 2 if t < 45 else (1 if t < 85 else 0),
                        'share': (2 if t < 45 else (1 if t < 85 else 0)) / (len(names) + 3)}
                       for t in (15, 30, 60, 90)])

    def cleanup(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                stdout, stderr = self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                stdout, stderr = self.process.communicate()
            self.streams(stdout, stderr)
        ok = True
        if self.workspace is not None:
            try:
                self.close_tasks()
                live = self.panes()
                self.check('C100 all owned worker panes removed',
                           all(r['pane_id'] not in live for r in self.records().values()))
            except Exception as exc:
                self.failure(exc)
                ok = False
            try:
                self.herdr('workspace', 'close', self.workspace['workspace_id'])
                live = self.herdr('workspace', 'list')['workspaces']
                ok &= self.workspace['workspace_id'] not in {w['workspace_id'] for w in live}
            except Exception as exc:
                self.failure(exc)
                ok = False
        self.assertions.append({'name': 'owned workspace cleanup confirmed', 'ok': ok})


class HotSwapRun(Run):
    """Two real in-flight tasks, one alias changed and removed without retuning."""

    def __init__(self, args, workers):
        super().__init__(args, workers)
        self.env.setdefault('MISE_CONFIG_DIR', str(Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mise'))
        self.env.setdefault('MISE_STATE_DIR', str(Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'mise'))
        self.skipped = False
        self.checkout_before = None
        self.source_before = self.skill_hashes()
        self.alias_specs = []
        self.owned_tasks = []
        self.hot_limit = self.started + args.max_seconds
        self.root_pane = None
        self.selected_specs = {}
        self.limitations = []

    @staticmethod
    def skill_hashes():
        return {str(p.relative_to(REPO)): sha(p) for p in (REPO / 'skills').rglob('*')
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}

    def checkout_signature(self):
        proc = self.command(['git', 'ls-files', '-z'])
        head = self.command(['git', 'rev-parse', 'HEAD'])
        if proc.returncode or head.returncode:
            raise RuntimeError('hot_swap_checkout_identity_unavailable')
        paths = proc.stdout.split('\0')
        manifest = {name: sha(self.args.cwd / name) if (self.args.cwd / name).is_file() else None
                    for name in paths if name}
        return {'sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                'tracked_files': len(manifest), 'revision': head.stdout.strip()}

    def remaining(self):
        remaining = self.hot_limit - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('hot_swap_deadline_exceeded')
        return remaining

    def wait_shell_ready(self):
        deadline = min(self.hot_limit, time.monotonic() + 30)
        stable = None
        while time.monotonic() < deadline:
            pane = self.herdr('pane', 'get', self.root_pane)['pane']
            info = self.herdr('pane', 'process-info', '--pane', self.root_pane)['process_info']
            shell = info.get('shell_pid')
            foreground = info.get('foreground_processes') or []
            revision = pane.get('revision')
            ready = (isinstance(shell, int) and shell > 0
                     and info.get('foreground_process_group_id') == shell
                     and any(process.get('pid') == shell for process in foreground)
                     and isinstance(revision, int) and revision > 0
                     and not pane.get('agent'))
            identity = (shell, revision) if ready else None
            if identity and stable and stable[0] == identity:
                if time.monotonic() - stable[1] >= .5:
                    self.observations['owned_shell_readiness'] = {
                        'shell_owns_foreground': True, 'rendered_revision_positive': True,
                        'rendered_revision_stable': True}
                    return
            else:
                stable = (identity, time.monotonic()) if identity else None
            time.sleep(min(.2, max(0, deadline - time.monotonic())))
        raise RuntimeError('owned_shell_not_ready')

    def hot_cli(self, *argv):
        """Use the owned shell's real ancestry rather than forge caller context."""
        self.wait_shell_ready()
        self.sequence += 1
        stem = self.diagnostics / f'hot-command-{self.sequence:03d}'
        out, err, status = (Path(str(stem) + suffix) for suffix in ('.stdout', '.stderr', '.exit'))
        command = shlex.join([sys.executable, str(HORCH), *[str(a) for a in argv]])
        # All substituted paths/arguments are shell-quoted; only this fixed wrapper
        # captures the real process exit code. It does not bypass caller proof.
        command += (' > ' + shlex.quote(str(out)) + ' 2> ' + shlex.quote(str(err))
                    + '; hot_swap_status=$?; printf "%s" "$hot_swap_status" > '
                    + shlex.quote(str(status) + '.tmp') + ' && mv '
                    + shlex.quote(str(status) + '.tmp') + ' ' + shlex.quote(str(status)))
        proc = self.command(['herdr', 'pane', 'run', self.root_pane, command])
        if proc.returncode:
            raise RuntimeError('owned_pane_run_failed')
        deadline = min(self.hot_limit, time.monotonic() + 180)
        while time.monotonic() < deadline:
            if status.is_file():
                return subprocess.CompletedProcess(argv, int(status.read_text()),
                                                   out.read_text(), err.read_text())
            time.sleep(min(.2, max(0, deadline - time.monotonic())))
        raise RuntimeError('owned_horch_command_timeout')

    def configure_alias(self, spec, phase):
        self.workers = {'swap': dict(spec)} if spec is not None else {}
        self.configure(2)
        snapshot = self.root / ('workers-' + phase + '.toml')
        snapshot.write_bytes(self.config.read_bytes())
        self.alias_specs.append({'phase': phase, 'sha256': sha(snapshot)})
        actual = tomllib.loads(snapshot.read_text()).get('workers', {})
        self.check('hot swap isolated alias snapshot ' + phase,
                   actual == ({'swap': spec} if spec is not None else {}))

    def gate_brief(self, label):
        from decimal import Decimal, ROUND_HALF_UP
        directory = self.root / ('calculation-' + label)
        directory.mkdir()
        marker = secrets.token_hex(16)
        events = []
        seed = 11 if label == 'a' else 29
        for index in range(720):
            events.append({'id': f'event-{index:04d}', 'account': f'account-{(index * seed) % 37:02d}',
                           'kind': 'refund' if index % 7 == 0 else 'sale',
                           'quantity': (index * 13 + seed) % 9,
                           'unit_price_cents': (index * 127 + seed * 19) % 15001,
                           'discount_bp': (index * 271 + seed) % 10001})
        batches = []
        for batch in range(9):
            chunk = events[batch * 80:(batch + 1) * 80]
            retries = events[max(0, batch * 80 - 17):batch * 80]
            batches.append(chunk + retries)
        (directory / 'input.json').write_text(json.dumps({'batches': batches}))
        balances = {}
        for event in events:
            amount = int((Decimal(event['quantity']) * event['unit_price_cents']
                          * (10000 - event['discount_bp']) / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            if event['kind'] == 'refund':
                amount = -amount
            balances[event['account']] = balances.get(event['account'], 0) + amount
        expected = {'unique_events': len(events),
                    'duplicate_events': sum(map(len, batches)) - len(events),
                    'net_total_cents': sum(balances.values()),
                    'balances': balances,
                    'top_accounts': [account for account in sorted(balances, key=lambda a: (-balances[a], a))[:5]],
                    'checksum': sum((index + 1) * balances[account]
                                    for index, account in enumerate(sorted(balances)))}
        brief = directory / 'brief.md'
        brief.write_text(f"""Implement and execute a real reconciliation calculation, without editing the checkout.
Read input batches from {directory / 'input.json'}. Each event has a global id;
ignore exact duplicate retries across all batches. For each unique event compute
quantity * unit_price_cents * (10000-discount_bp) / 10000, rounded half-up to a
whole cent PER EVENT. A refund negates this rounded amount; a sale adds it.
Aggregate signed cents by account, including accounts whose balance is zero.
Write solution.py and answer.json beside your result.json. Answer must have exactly
unique_events, duplicate_events, net_total_cents, balances (account to integer),
top_accounts (five account strings, descending balance, ties ascending name),
and checksum (sum of sorted-account 1-based index times signed account balance).
The independently rerunnable solution.py must perform the calculation itself
when invoked with Python with no command-line arguments.
IMPORTANT: first have the running solution.py write the exact text {marker}
to {directory / 'ready'}, then block inside that SAME process waiting for
{directory / 'release'} to exist (poll every 0.2 seconds, bounded to
{self.args.max_seconds} seconds). Do not produce answer.json or result.json before
release. Keep the native bash invocation running while blocked, with a timeout
long enough for this gate. After release compute, write answer.json, and exit.
Then publish the standard nonce-bound completed result. No subagents, Herdr,
horch, configuration changes, model changes or trust/approval answers.
""")
        return directory, marker, brief, expected

    def start_gated(self, label):
        directory, marker, brief, expected = self.gate_brief(label)
        before = set(self.records())
        proc = self.hot_cli('run', 'swap', '--brief', brief, '--cwd', self.args.cwd,
                            '--caller-pane', self.root_pane)
        rows = self.rows('hot_start_' + label, proc)
        self.check('hot swap task starts ' + label, proc.returncode == 0 and len(rows) == 1
                   and rows[0].get('state') == 'running')
        task_id = rows[0]['task_id']
        self.check('hot swap one allocation ' + label, set(self.records()) - before == {task_id})
        task = self.records()[task_id]
        self.owned_tasks.append(task)
        while self.remaining() > 0:
            entry = self.herdr('agent', 'get', task['agent'])['agent']
            status = entry.get('agent_status')
            if status == 'blocked':
                raise RuntimeError('hot_swap_worker_blocked')
            ready = (directory / 'ready').read_text() if (directory / 'ready').is_file() else ''
            if ready:
                self.check('hot swap readiness identity ' + label, ready == marker)
                self.check('hot swap acknowledged working gate ' + label,
                           status == 'working' and not (Path(task['task_dir']) / 'result.json').exists())
                break
            if status in ('idle', 'done'):
                raise RuntimeError('hot_swap_worker_settled_before_gate')
            time.sleep(min(.5, self.remaining()))
        self.check('hot swap native session capture owns task pane ' + label,
                   entry.get('pane_id') == task['pane_id'])
        native_capture = {'task_id': task_id, 'agent': task['agent'],
                          'pane_id': task['pane_id'], 'observed_at': time.time(),
                          'session': entry.get('agent_session') or {}}
        (directory / 'native-session.json').write_text(json.dumps(native_capture, indent=2) + '\n')
        return {'task': task, 'directory': directory, 'expected': expected,
                'native_capture': native_capture,
                'record_sha256': sha(Path(task['task_dir']) / 'task.json')}

    def check_gates(self, gates, phase):
        for gate in gates:
            task = gate['task']
            entry = self.herdr('agent', 'get', task['agent'])['agent']
            self.check('hot swap running task preserved ' + phase + ' ' + task['task_id'],
                       entry.get('agent_status') == 'working'
                       and sha(Path(task['task_dir']) / 'task.json') == gate['record_sha256']
                       and not (Path(task['task_dir']) / 'result.json').exists())

    @staticmethod
    def normalized(spec):
        return dict({'provider': None, 'effort': None, 'args': [], 'description': None}, **spec)

    def audit_native(self, task, spec, capture):
        if spec['harness'] != 'pi':
            return {'available': False, 'limitation': 'native model audit implemented for Pi only'}
        # horch wait may already have closed the delivered task's pane. Bind
        # the transcript to its independently captured working-session identity.
        session = capture.get('session') or {}
        value = session.get('value')
        paths = []
        if value and session.get('kind') == 'path':
            path = Path(value).expanduser()
            paths = [path] if path.is_file() else []
        elif value:
            paths = list((Path.home() / '.pi/agent/sessions').rglob('*' + value + '*.jsonl'))
        if len(paths) != 1:
            return {'available': False, 'limitation': 'native Pi transcript unavailable or ambiguous'}
        path = paths[0]
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        header = rows[0] if rows else {}
        session_started = datetime.fromisoformat(header['timestamp'].replace('Z', '+00:00')).timestamp()
        task_started = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00')).timestamp()
        identity_ok = (header.get('type') == 'session' and header.get('version') == 3
                       and bool(header.get('id')) and header.get('cwd') == task['cwd'] == str(self.args.cwd)
                       and task_started <= session_started <= capture.get('observed_at', 0)
                       and capture.get('task_id') == task['task_id']
                       and capture.get('agent') == task['agent']
                       and capture.get('pane_id') == task['pane_id']
                       and session.get('agent') == 'pi' and session.get('source') == 'herdr:pi'
                       and (session.get('kind') == 'path' or header.get('id') == value))
        models = {(row.get('provider'), row.get('modelId')) for row in rows if row.get('type') == 'model_change'}
        models.update((row['message'].get('provider'), row['message']['model']) for row in rows
                      if row.get('message', {}).get('role') == 'assistant' and row['message'].get('model'))
        self.check('hot swap native model identity ' + task['task_id'], identity_ok and bool(models)
                   and all(model == spec['model'] and (not spec.get('provider') or provider == spec['provider'])
                           for provider, model in models))
        return {'available': True, 'sha256': sha(path), 'model': spec['model'],
                'session_id_sha256': hashlib.sha256(str(header.get('id')).encode()).hexdigest()}

    def scenario(self):
        self.selected = list(self.workers)
        if len(self.selected) != 2:
            raise RuntimeError('hot_swap_requires_exactly_two_workers')
        self.selected_specs = {name: dict(spec) for name, spec in self.workers.items()}
        first, second = (self.selected_specs[name] for name in self.selected)
        # Descriptions alone do not make two execution definitions different.
        execution = lambda spec: {k: self.normalized(spec).get(k) for k in ('harness', 'model', 'provider', 'effort', 'args')}
        if execution(first) == execution(second):
            self.skipped = True
            self.limitations.append('selected worker execution definitions are indistinguishable; no hot swap was run')
            return
        for tool in dict.fromkeys(['herdr', first['harness'], second['harness']]):
            proc = self.command([tool, '--version'])
            self.versions['herdr_cli' if tool == 'herdr' else tool] = {
                'exit_code': proc.returncode, 'version': self.version(proc.stdout or proc.stderr)}
        proc = self.command(['herdr', 'status', 'server', '--json'])
        if proc.returncode:
            raise RuntimeError('herdr_command_failed')
        server = json.loads(proc.stdout)
        version = self.version(server.get('version')) if isinstance(server, dict) else None
        self.versions['herdr_server'] = {'version': version}
        if version is None:
            raise RuntimeError('herdr_server_version_unavailable')
        self.checkout_before = self.checkout_signature()
        self.configure_alias(first, 'initial')
        result = self.herdr('workspace', 'create', '--cwd', self.args.cwd,
                            '--label', 'hot-swap-e2e', '--no-focus',
                            '--env', 'MISE_CONFIG_DIR=' + self.env['MISE_CONFIG_DIR'],
                            '--env', 'MISE_STATE_DIR=' + self.env['MISE_STATE_DIR'],
                            '--env', 'XDG_CONFIG_HOME=' + self.env['XDG_CONFIG_HOME'],
                            '--env', 'XDG_STATE_HOME=' + self.env['XDG_STATE_HOME'])
        self.workspace = result['workspace']
        self.root_pane = result['root_pane']['pane_id']
        baseline = self.panes()
        a = self.start_gated('a')
        self.check_gates([a], 'before-update')
        self.configure_alias(second, 'replaced')
        self.check_gates([a], 'after-update')
        b = self.start_gated('b')
        self.check_gates([a, b], 'before-removal')
        self.configure_alias(None, 'removed')
        self.check_gates([a, b], 'after-removal')
        before = self.allocation()
        proc = self.hot_cli('run', 'swap', '--brief', self.root / 'calculation-a/brief.md',
                            '--cwd', self.args.cwd, '--caller-pane', self.root_pane)
        error = json.loads(proc.stdout)
        self.check('hot swap removed alias refuses dispatch', proc.returncode != 0 and error.get('error') == 'unknown_worker')
        self.check('hot swap removed alias allocates nothing', self.allocation() == before)
        self.check_gates([a, b], 'after-refusal')
        # Compare immutable records against independently loaded saved config phases.
        sys.path.insert(0, str(HORCH.parent))
        import horch
        self.observations['hot_swap_tasks'] = []
        for gate, spec, phase in ((a, first, 'initial'), (b, second, 'replaced')):
            task = gate['task']
            self.check('hot swap exact launch snapshot ' + phase,
                       task['worker'] == 'swap' and task['argv'] == horch.launch_args(self.normalized(spec), Path(task['task_dir']))
                       and task['harness'] == spec['harness'] and task['model'] == spec['model'])
            self.observations['hot_swap_tasks'].append({
                'task_id': task['task_id'], 'phase': phase, 'harness': spec['harness'],
                'model': spec['model'], 'effort': spec.get('effort'),
                'task_record_sha256': gate['record_sha256']})
        for gate in (a, b):
            (gate['directory'] / 'release').write_text('released\n')
        waiting = {a['task']['task_id'], b['task']['task_id']}
        while waiting:
            proc = self.hot_cli('wait', *sorted(waiting), '--max-seconds', str(max(1, min(20, int(self.remaining())))))
            rows = self.rows('hot_wait', proc)
            self.check('hot swap wait succeeds', proc.returncode == 0)
            for row in rows:
                if row.get('state') == 'done':
                    waiting.discard(row['task_id'])
                elif row.get('state') not in ('running', 'long_running'):
                    raise RuntimeError('hot_swap_worker_did_not_deliver')
        for gate, spec in ((a, first), (b, second)):
            task = gate['task']
            directory = Path(task['task_dir'])
            result = read(directory / 'result.json')
            self.check('hot swap valid delivered identity ' + task['task_id'],
                       horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed'
                       and read(directory / 'state.json').get('state') == 'done')
            self.check('hot swap independent reconciliation ' + task['task_id'],
                       read(directory / 'answer.json') == gate['expected'])
            # Preserve the delivered answer, then require the actual retained
            # script to regenerate it. This produces a rerunnable E2E artifact.
            (directory / 'answer-delivered.json').write_bytes((directory / 'answer.json').read_bytes())
            (directory / 'answer.json').unlink()
            proc = subprocess.run([sys.executable, str(directory / 'solution.py')],
                                  cwd=directory, env=self.env, text=True, capture_output=True,
                                  timeout=min(30, self.remaining()))
            self.streams(proc.stdout, proc.stderr)
            self.check('hot swap solution independently reruns ' + task['task_id'],
                       proc.returncode == 0 and read(directory / 'answer.json') == gate['expected'])
            native = self.audit_native(task, spec, gate['native_capture'])
            self.observations['hot_swap_tasks'][0 if gate is a else 1]['native'] = native
            if not native['available']:
                self.limitations.append(native['limitation'])
        self.observations['alias_snapshots'] = self.alias_specs
        self.observations['baseline_pane_count'] = len(baseline)
        self.complete = True

    def cleanup(self):
        # Inspect failure panes before parent cleanup, retaining private diagnostics.
        for task in self.records().values():
            try:
                state = read(Path(task['task_dir']) / 'state.json')
                if not state.get('closed'):
                    proc = self.command(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '80'])
                    if proc.returncode:
                        raise RuntimeError('owned_task_pane_inspection_failed')
            except Exception as exc:
                self.failure(exc)
        if self.root_pane:
            try:
                proc = self.command(['herdr', 'pane', 'read', self.root_pane, '--source', 'recent', '--lines', '80'])
                if proc.returncode:
                    raise RuntimeError('owned_root_pane_inspection_failed')
            except Exception as exc:
                self.failure(exc)
        super().cleanup()
        self.assertions.append({'name': 'hot swap skill sources unchanged',
                                'ok': self.skill_hashes() == self.source_before})
        self.observations['skill_source_hashes_before'] = self.source_before
        self.observations['skill_source_hashes_after'] = self.skill_hashes()
        if self.checkout_before is not None:
            after = self.checkout_signature()
            self.observations['checkout_before'] = self.checkout_before
            self.observations['checkout_after'] = after
            self.assertions.append({'name': 'hot swap tracked checkout and revision unchanged',
                                    'ok': after == self.checkout_before})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='append', required=True,
                        help='existing authenticated worker; repeat for at least two distinct names')
    parser.add_argument('--cwd', type=Path, default=Path.cwd(), help='existing trusted checkout, read only')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside checkout')
    parser.add_argument('--hot-swap-only', action='store_true',
                        help='exercise an isolated live worker alias replacement/removal only (exactly two workers)')
    parser.add_argument('--max-seconds', type=int, default=300, help='normal per-check wait cap; hot-swap overall deadline (positive)')
    args = parser.parse_args()
    if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_PANE_ID', '').strip():
        parser.error('run inside Herdr with a verified live caller pane ID')
    args.cwd = args.cwd.expanduser().resolve(strict=True)
    args.output = args.output.expanduser().resolve()
    names = list(dict.fromkeys(args.worker))
    if len(names) < 2 or args.max_seconds < 1 or not args.cwd.is_dir():
        parser.error('require two distinct workers, an existing cwd and a positive cap')
    if args.output == REPO or REPO in args.output.parents:
        parser.error('--output must be outside checkout')
    cfg = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'herdr-orchestrator/workers.toml'
    args.source_config = cfg.expanduser().resolve()
    config_hash = None
    workers = {}
    args.output.mkdir(parents=True, exist_ok=True)
    run = (HotSwapRun if args.hot_swap_only else Run)(args, workers)
    print(f'Run directory: {run.root}', flush=True)
    problem = None
    try:
        config_hash = sha(cfg)
        configured = tomllib.loads(cfg.read_text(encoding='utf-8')).get('workers', {})
        if not isinstance(configured, dict) or any(
                not isinstance(configured.get(name), dict) for name in names):
            raise RuntimeError('selected_worker_not_configured')
        workers.update({name: configured[name] for name in names})
        run.scenario()
    except (Exception, KeyboardInterrupt) as exc:
        run.failure(exc)
        problem = type(exc).__name__  # no exception text or transcripts in receipt
    finally:
        try:
            run.cleanup()
        except (Exception, KeyboardInterrupt) as exc:
            run.failure(exc)
            problem = type(exc).__name__
        for name, condition in (
            ('real configuration unchanged', lambda: config_hash is not None and sha(cfg) == config_hash),
            ('verified sources unchanged', lambda: run.hashes == {
                'horch_sha256': sha(HORCH), 'driver_sha256': sha(Path(__file__))})):
            try:
                ok = condition()
            except OSError:
                ok = False
            run.assertions.append({'name': name, 'ok': ok})
        real_config_after = None
        if args.hot_swap_only:
            try:
                real_config_after = sha(cfg)
            except OSError:
                pass
        evidence = run.sanitize({
            'schema': 'horch/hot-swap-e2e/v1' if args.hot_swap_only else 'horch/check-workers-e2e/v1',
            'verdict': ('skip' if args.hot_swap_only and run.skipped and problem is None and all(a['ok'] for a in run.assertions)
                        else 'pass' if run.complete and problem is None and all(a['ok'] for a in run.assertions) else 'fail'),
            'scenario_complete': run.complete,
            'diagnostics': str(run.diagnostics),
            'source_hashes': run.hashes, 'versions': run.versions,
            'workers': {n: {k: s.get(k) for k in ('harness', 'model', 'provider', 'effort')}
                        for n, s in workers.items()},
            'batch_limit': 2 if args.hot_swap_only else 1, 'selections': run.selected,
            **({'mode': 'hot-swap-only', 'limitations': run.limitations,
                'real_config_sha256_before': config_hash,
                'real_config_sha256_after': real_config_after} if args.hot_swap_only else {}),
            'rerun': ['python3', 'e2e/check_workers.py', *(['--hot-swap-only'] if args.hot_swap_only else []), *sum((['--worker', n] for n in names), []),
                      '--cwd', str(args.cwd), '--output', str(args.output), '--max-seconds', str(args.max_seconds)],
            'seconds': round(time.monotonic() - run.started, 3),
            'observations': run.observations, 'assertions': run.assertions, 'problem_category': problem})
        receipt = run.root / 'evidence.json'
        receipt.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        print(f'Evidence: {receipt}\nVerdict: {evidence["verdict"]}', flush=True)
    return 0 if evidence['verdict'] in ('pass', 'skip') else 1


if __name__ == '__main__':
    raise SystemExit(main())
