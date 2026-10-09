#!/usr/bin/env python3
"""Verify that a real Pi trust dialog never receives a horch task prompt.

Run inside Herdr with Pi 1.1.0+, its Herdr integration, and an authenticated
Pi worker. The output parent must not already be trusted by Pi. This uses real
model calls for a second worker that explicitly declines project resources.
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

from review_loop import HORCH, command, json_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True, help='configured Pi worker')
    parser.add_argument('--output', required=True, type=Path, help='untrusted local artifact parent outside the repo')
    args = parser.parse_args()
    if os.environ.get('HERDR_ENV') != '1':
        parser.error('run inside Herdr')
    sys.path.insert(0, str(HORCH.parent))
    import horch
    config = horch.load_config()
    worker = config['workers'].get(args.worker)
    if not worker or worker['harness'] != 'pi':
        parser.error('--worker must select a configured Pi worker')
    if any(a in ('-a', '--approve', '-na', '--no-approve') for a in worker['args']):
        parser.error('the selected worker must not override project trust')
    if horch.active_task_count() >= config['max_active_workers']:
        parser.error('one free worker slot is required')
    repo = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    if output == repo or repo in output.parents:
        parser.error('--output must be outside the repo')
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='horch-pi-startup-', dir=output))
    cwd = root / 'project'
    (cwd / '.agents/skills').mkdir(parents=True)
    cfg = root / 'config/herdr-orchestrator'
    cfg.mkdir(parents=True)
    env = {**os.environ, 'XDG_CONFIG_HOME': str(cfg.parent), 'XDG_STATE_HOME': str(root / 'state')}
    brief = root / 'brief.md'
    brief.write_text('Compute 7 * 137 - (7 * 137 * 250 // 10000). Verify with Python. '
                     'Write the integer to answer.txt in your task directory. Do not change the project. '
                     'Do not delegate. Write result.json last and finish.\n')
    assertions, tasks, observations = [], [], []
    began = time.monotonic()
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HORCH, Path(__file__))}
    trust = Path(os.environ.get('PI_CODING_AGENT_DIR', str(Path.home() / '.pi/agent'))) / 'trust.json'
    trust_before = trust.read_bytes() if trust.exists() else None
    problem = None

    def check(name, ok):
        assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def run(*argv, timeout=200):
        proc = subprocess.run([sys.executable, str(HORCH), *argv], env=env,
                              text=True, capture_output=True, timeout=timeout)
        if proc.returncode:
            raise RuntimeError('horch_command_failed')
        return [json.loads(line) for line in proc.stdout.splitlines()]

    def configure(decline):
        selected = {k: v for k, v in worker.items() if v is not None}
        selected['args'] = [*worker['args'], *(['--no-approve'] if decline else [])]
        text = 'max_active_workers = 1\n[workers.probe]\n'
        for key, value in selected.items():
            text += f'{key} = {json.dumps(value)}\n'
        (cfg / 'workers.toml').write_text(text)

    def start():
        row = run('run', 'probe', '--cwd', str(cwd), '--brief', str(brief))[0]
        tasks.append(row)
        state = json_file(Path(row['task_dir']) / 'state.json')
        (root / f'{row["task_id"]}-before-cleanup.json').write_text(json.dumps(state, indent=2))
        observations.append({'task_id': row['task_id'], 'state': state['state']})
        return row, state

    try:
        configure(False)
        first, state = start()
        screen = command(['herdr', 'pane', 'read', first['pane_id'], '--source', 'recent', '--lines', '60']).stdout
        (root / 'trust-screen.txt').write_text(screen)
        check('untrusted project remains at the Pi trust dialog', 'Trust project folder?' in screen)
        check('startup fails before a prompt baseline is recorded',
              state['state'] == 'start_failed' and state['baseline_seq'] is None and not state['closed'])
        check('untrusted worker produced no result', not (Path(first['task_dir']) / 'result.json').exists())
        check('Pi trust decisions stayed unchanged',
              (trust.read_bytes() if trust.exists() else None) == trust_before)
        run('close', first['task_id'])
        configure(True)
        second, state = start()
        check('fresh worker starts after explicitly declining project resources', second['state'] == 'running')
        row = run('wait', second['task_id'], '--max-seconds', '300', timeout=330)[0]
        check('fresh worker delivers and closes normally', row['state'] == 'done' and row['closed'])
        task = json_file(Path(second['task_dir']) / 'task.json')
        result = json_file(Path(second['task_dir']) / 'result.json')
        check('delivered result has matching identity and successful outcome',
              horch.validate_result(result, task) == 'valid' and result['status'] == 'completed')
        check('real worker produced the verified arithmetic answer',
              (Path(second['task_dir']) / 'answer.txt').read_text().strip() == '936')
        check('declining project resources did not grant trust',
              (trust.read_bytes() if trust.exists() else None) == trust_before)
    except (Exception, KeyboardInterrupt) as exc:
        problem = type(exc).__name__
        # Private diagnostics retain the detail; public evidence is allowlisted.
        (root / 'failure.txt').write_text(str(exc))
    finally:
        cleanup = True
        for task in tasks:
            try:
                state = json_file(Path(task['task_dir']) / 'state.json')
                if not state['closed']:
                    command(['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '40'])
                    run('close', task['task_id'])
                cleanup &= json_file(Path(task['task_dir']) / 'state.json')['closed'] is True
                proc = command(['herdr', 'pane', 'get', task['pane_id']])
                doc = json.loads(proc.stdout or proc.stderr)
                cleanup &= doc.get('error', {}).get('code') in horch.MISSING_PANE_CODES
            except Exception:
                cleanup = False
        assertions.append({'name': 'owned panes confirmed absent', 'ok': cleanup})
        assertions.append({'name': 'source stayed unchanged', 'ok': all(
            hashes[p.name] == hashlib.sha256(p.read_bytes()).hexdigest() for p in (HORCH, Path(__file__)))})
        evidence = {'schema': 'horch/pi-startup-e2e/v1',
                    'verdict': 'pass' if not problem and all(a['ok'] for a in assertions) else 'fail',
                    'seconds': round(time.monotonic() - began), 'source_hashes': hashes,
                    'worker': {k: worker[k] for k in ('harness', 'provider', 'model', 'effort')},
                    'tasks': observations, 'assertions': assertions, 'problem_category': problem}
        path = root / 'evidence.json'
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'Evidence: {path}\nVerdict: {evidence["verdict"]}', flush=True)
    return 0 if evidence['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
