#!/usr/bin/env python3
"""Verify real missing-integration preflight and installed-worker delivery.

Uses Herdr's supported PI_CODING_AGENT_DIR override for an empty, isolated Pi
directory. Never uninstalls or changes the user's integration. Requires two
configured Pi workers, one non-Pi worker, and two free worker slots. Keep other
dispatchers stopped; configuration/task isolation does not reserve global slots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from review_loop import HORCH, json_file


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi', action='append', required=True, help='configured Pi worker; supply twice')
    parser.add_argument('--other', required=True, help='configured non-Pi worker')
    parser.add_argument('--cwd', type=Path, default=Path.cwd(), help='existing trusted checkout')
    parser.add_argument('--output', type=Path, required=True, help='artifact parent outside repository')
    args = parser.parse_args()
    sys.path.insert(0, str(HORCH.parent))
    import horch
    config = horch.load_config()
    if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_WORKSPACE_ID'):
        parser.error('run inside Herdr')
    if (len(args.pi) != 2 or len(set(args.pi)) != 2
            or any(config['workers'].get(n, {}).get('harness') != 'pi' for n in args.pi)
            or args.other not in config['workers'] or config['workers'][args.other]['harness'] == 'pi'):
        parser.error('select two distinct configured Pi workers and one non-Pi worker')
    if horch.active_task_count() + 2 > config['max_active_workers']:
        parser.error('two free worker slots are required')
    args.cwd = args.cwd.expanduser().resolve()
    output = args.output.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if output == repo or repo in output.parents:
        parser.error('--output must be outside repository')
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='horch-pi-preflight-', dir=output))
    print(f'Run directory: {root}', flush=True)
    cfg = root / 'config/herdr-orchestrator/workers.toml'
    cfg.parent.mkdir(parents=True)
    shutil.copyfile(horch.config_path(), cfg)
    config_hash = sha(cfg)
    env = dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'))
    isolated_pi = root / 'empty-pi'
    isolated_pi.mkdir()
    missing_env = dict(env, PI_CODING_AGENT_DIR=str(isolated_pi))
    task_root = root / 'state/herdr-orchestrator/tasks'
    integration = Path(os.environ.get('PI_CODING_AGENT_DIR', str(Path.home() / '.pi/agent'))) / 'extensions/herdr-agent-state.ts'
    before = sha(integration) if integration.is_file() else None
    hashes = {p.name: sha(p) for p in (HORCH, Path(__file__))}
    assertions, observations, tasks = [], {}, []
    started = time.monotonic()
    problem = None

    def check(name, ok):
        assertions.append({'name': name, 'ok': bool(ok)})
        print(f'{"PASS" if ok else "FAIL"}: {name}', flush=True)
        if not ok:
            raise RuntimeError(name)

    def invoke(label, argv, call_env=env, timeout=360):
        began = time.monotonic()
        proc = subprocess.run([str(a) for a in argv], env=call_env, text=True,
                              capture_output=True, timeout=timeout)
        (root / (label + '.stdout')).write_text(proc.stdout)
        (root / (label + '.stderr')).write_text(proc.stderr)
        return proc, time.monotonic() - began

    def command(*argv):
        return [sys.executable, HORCH, *argv]

    def agents():
        p, _ = invoke('agents', ['herdr', 'agent', 'list'], timeout=30)
        if p.returncode:
            raise RuntimeError('agent_list_failed')
        return {a['pane_id'] for a in json.loads(p.stdout)['result']['agents']}

    try:
        p, _ = invoke('installed-detect', command('detect'))
        current = json.loads(p.stdout)['pi_integration']
        observations['installed_integration'] = current
        check('detect reports the installed Pi integration', p.returncode == 0 and current['status'] == 'current' and before is not None)
        p, _ = invoke('missing-status', ['herdr', 'integration', 'status'], missing_env, 30)
        check('real Herdr observes the isolated missing integration', p.returncode == 0 and 'pi: not installed (' in p.stdout)
        p, _ = invoke('missing-detect', command('detect'), missing_env)
        absent = json.loads(p.stdout)['pi_integration']
        observations['missing_integration'] = absent
        check('detect reports not_installed', p.returncode == 0 and absent['status'] == 'not_installed')
        brief = root / 'brief.md'
        brief.write_text('Write a completed setup-check result. Do not change the checkout.\n')
        previous = agents()
        for label, argv in [
            ('missing-check', command('check', args.other, *args.pi, args.pi[0], '--cwd', args.cwd)),
            ('missing-run', command('run', args.pi[0], '--brief', brief, '--cwd', args.cwd)),
        ]:
            p, seconds = invoke(label, argv, missing_env, 30)
            error = json.loads(p.stdout)
            observations[label] = {'error': error.get('error'), 'seconds': round(seconds, 3)}
            check(label + ' rejects promptly with install guidance', p.returncode != 0
                  and error.get('error') == 'pi_integration_missing'
                  and 'herdr integration install pi' in error.get('message', '') and seconds < 10)
        check('missing integration allocated no task or agent',
              not list(task_root.glob('t-*/task.json')) and agents() <= previous)
        p, _ = invoke('non-pi-check', command('check', args.other, '--cwd', args.cwd), missing_env)
        rows = [json.loads(line) for line in p.stdout.splitlines()]
        check('non-Pi check works while Pi integration is absent', p.returncode == 0 and len(rows) == 1 and rows[0]['ok'])
        p, _ = invoke('pi-check', command('check', *args.pi, '--cwd', args.cwd))
        rows = [json.loads(line) for line in p.stdout.splitlines()]
        check('installed Pi workers deliver and close', p.returncode == 0 and len(rows) == 2 and all(r['ok'] for r in rows))
        for path in sorted(task_root.glob('t-*/task.json')):
            task = json_file(path)
            state = json_file(path.with_name('state.json'))
            result = json_file(path.with_name('result.json'))
            check('real result identity and completion', state['state'] == 'done' and state['closed']
                  and horch.validate_result(result, task) == 'valid' and result['status'] == 'completed')
        check('exactly three real worker tasks', len(list(task_root.glob('t-*/task.json'))) == 3)
    except (Exception, KeyboardInterrupt) as exc:
        problem = type(exc).__name__
        (root / 'failure.txt').write_text(str(exc))
    finally:
        cleanup = True
        for path in sorted(task_root.glob('t-*/task.json')):
            try:
                task = json_file(path)
                state = json_file(path.with_name('state.json'))
                tasks.append({'task_id': task['task_id'], 'worker': task['worker'], 'state': state['state'], 'closed_before_cleanup': state['closed']})
                if not state['closed']:
                    invoke(task['task_id'] + '-pane', ['herdr', 'pane', 'read', task['pane_id'], '--source', 'recent', '--lines', '40'], timeout=30)
                    invoke(task['task_id'] + '-close', command('close', task['task_id']), timeout=30)
                p, _ = invoke(task['task_id'] + '-absent', ['herdr', 'pane', 'get', task['pane_id']], timeout=30)
                cleanup &= p.returncode != 0 and json.loads(p.stdout or p.stderr).get('error', {}).get('code') in horch.MISSING_PANE_CODES
            except Exception:
                cleanup = False
        assertions += [
            {'name': 'owned panes confirmed absent', 'ok': cleanup},
            {'name': 'installed integration unchanged', 'ok': before is not None and integration.is_file() and sha(integration) == before},
            {'name': 'source and configuration unchanged', 'ok': all(sha(p) == hashes[p.name] for p in (HORCH, Path(__file__))) and sha(cfg) == sha(horch.config_path()) == config_hash},
        ]
        evidence = {'schema': 'horch/pi-preflight-e2e/v1', 'verdict': 'pass' if not problem and all(a['ok'] for a in assertions) else 'fail',
                    'seconds': round(time.monotonic() - started, 3), 'source_hashes': hashes,
                    'observations': observations, 'tasks': tasks, 'assertions': assertions, 'problem_category': problem}
        (root / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'Evidence: {root / "evidence.json"}\nVerdict: {evidence["verdict"]}', flush=True)
    return 0 if evidence['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
