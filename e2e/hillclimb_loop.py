#!/usr/bin/env python3
"""Attended original Hillclimb E2E with real measured attempts and a ready child PR.

Uses the pristine portable perf_loop fixture. All model/forge actions occur only
in explicit live mode; configuration, permissions and harness flags are copied.
There is no unattended wake, retry, merge, or automatic trust response.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import traceback
import uuid

import playbook_loop as core
import forge_loop as forge_helpers
import perf_loop as perf

ROOT, Failure, horch = perf.ROOT, core.Failure, core.horch
READS = tuple(dict.fromkeys((*perf.READS,
    'poteto-mode/playbooks/hillclimb.md', 'show-me-your-work/SKILL.md',
    'show-me-your-work/scripts/log.sh', 'show-me-your-work/references/decision-log-template.tsv',
    'principle-build-the-lever/SKILL.md', 'principle-prove-it-works/SKILL.md',
    'principle-guard-the-context-window/SKILL.md', 'principle-separate-before-serializing-shared-state/SKILL.md',
    'principle-laziness-protocol/SKILL.md')))
COMMENT_BOOTSTRAP = ('Bootstrap: Before ANY assistant natural text, use native read tools only to load '
                     'the full original no-comments skill and CommentSicko agent instructions. '
                     'After both reads complete, follow the original first-output rule: the ENTIRE first '
                     'nonempty assistant natural-text block must contain ONLY the greeting required by the original '
                     'agent, with no prefix, suffix or explanation. Make the next action a separate native '
                     'read tool call of an assigned required source/input; wait for that tool result before '
                     'any further assistant prose. This bootstrap declares a native serialization boundary, '
                     'not replacement agent rules.')
FILES = ('reconcile.py', 'cli.py', 'e2e_reconcile.py', 'workload.json', 'contract.json')
LEDGER = ('id', 'hypothesis', 'change', 'before', 'after', 'delta', 'tests', 'verdict', 'note')
TRAIL = ('ts', 'phase', 'decision', 'why', 'evidence', 'result')

# The engine is the frozen real-CLI measurement helper, with one explicit
# contrast-workload mode for sensitivity only. Per-attempt sides remain identical.
_ENGINE_GUARD = "if snapshots['before']['workload.json'] != snapshots['after']['workload.json']:"
if _ENGINE_GUARD not in perf.PROBE:
    raise RuntimeError('measurement_helper_contract_changed')
ENGINE = perf.PROBE.replace("p.add_argument('--nonce', required=True)",
    "p.add_argument('--nonce', required=True)\np.add_argument('--contrast-workload', action='store_true')")
ENGINE = ENGINE.replace(_ENGINE_GUARD,
    "if not a.contrast_workload and snapshots['before']['workload.json'] != snapshots['after']['workload.json']:")

# Perf's one-fix prose assumes specific before/after counters. Hillclimb uses
# only its measured data; its own report below describes every real attempt.
_report_start = ENGINE.index("    report = ['# Reconciliation measurement', '',")
_report_end_marker = "    result['portable_report'] = '\\n'.join(report) + '\\n'\n"
_report_end = ENGINE.index(_report_end_marker, _report_start) + len(_report_end_marker)
ENGINE = ENGINE[:_report_start] + ENGINE[_report_end:]

PROBE = r'''#!/usr/bin/env python3
"""Owned-state snapshot/measurement lever; never edits the application."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--mode', choices=['sensitivity', 'baseline', 'begin', 'evaluate', 'record', 'review-ready', 'final'], required=True)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--state', type=Path, required=True)
p.add_argument('--nonce', required=True)
p.add_argument('--id', type=int)
p.add_argument('--target-reduction', type=float, required=True)
p.add_argument('--attempt-floor', type=int, required=True)
a = p.parse_args()
root, state = a.root.resolve(), a.state.resolve()
files = ('reconcile.py', 'cli.py', 'e2e_reconcile.py', 'workload.json', 'contract.json')
ledger_header = ('id','hypothesis','change','before','after','delta','tests','verdict','note')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
def load(path):
    return json.loads(path.read_text())
def hashes(directory):
    return {name: sha(directory / name) for name in files}
def snapshot(path):
    path.mkdir(parents=True, exist_ok=False)
    for name in files:
        shutil.copy2(root / name, path / name)
    return hashes(path)
def observe(label, before, after, contrast=False):
    destination = state / label
    argv = [sys.executable, '-B', str(state / 'engine.py'), '--mode', 'compare',
            '--before', str(before), '--after', str(after), '--output', str(destination), '--nonce', a.nonce]
    if contrast:
        argv += ['--contrast-workload']
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=120)
    (state / (label + '.stdout')).write_text(proc.stdout)
    (state / (label + '.stderr')).write_text(proc.stderr)
    if proc.returncode:
        return {'valid': False, 'exit_code': proc.returncode}
    value = json.loads(proc.stdout)
    if value != load(destination / 'observation.json') or value['nonce'] != a.nonce:
        raise ValueError('measurement identity mismatch')
    return {'valid': True, 'measurement': value, 'sha256': sha(destination / 'observation.json')}
def suite(directory, label):
    destination = state / label
    proc = subprocess.run([sys.executable, '-B', str(directory / 'e2e_reconcile.py'),
                           '--output', str(destination)], text=True, capture_output=True, timeout=120)
    (state / (label + '.stdout')).write_text(proc.stdout)
    (state / (label + '.stderr')).write_text(proc.stderr)
    evidence = destination / 'evidence.json'
    value = load(evidence) if evidence.is_file() else {}
    return {'valid': proc.returncode == 0 and value.get('verdict') == 'pass'
                    and len(value.get('flows', [])) == 6 and all(r.get('ok') is True for r in value['flows']),
            'sha256': sha(evidence) if evidence.is_file() else None, 'exit_code': proc.returncode}
def function_ast(path):
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_linear']
    if len(nodes) != 1:
        raise ValueError('function missing')
    return ast.dump(nodes[0], include_attributes=False)
def outside(path):
    text = path.read_text()
    target = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_linear')
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:target.body[0].lineno-1]) + '    pass\n' + ''.join(lines[target.end_lineno:])
def contract(before, after):
    return (all(sha(before / name) == sha(after / name) for name in files if name != 'reconcile.py')
            and outside(before / 'reconcile.py') == outside(after / 'reconcile.py')
            and function_ast(before / 'reconcile.py') != function_ast(after / 'reconcile.py'))
def classify(observed, tests, before, after, simplification):
    if not observed['valid'] or not tests['valid'] or not contract(before, after):
        return 'reverted', 'invalid measurement, regression gate, or function scope'
    metric = observed['measurement']['timings']
    if metric['after']['maximum_ms'] < metric['before']['minimum_ms']:
        return 'kept', 'improvement exceeds the complete observed range'
    # Concrete simplification is narrower than line count: strict AST node
    # reduction, same public function, explicit mechanism, and <=2% median loss
    # within overlapping ranges. It never establishes an improvement.
    count = lambda path: sum(1 for _ in ast.walk(ast.parse(path.read_text())))
    overlap = (metric['after']['minimum_ms'] <= metric['before']['maximum_ms']
               and metric['before']['minimum_ms'] <= metric['after']['maximum_ms'])
    if (simplification and count(after / 'reconcile.py') < count(before / 'reconcile.py')
            and overlap and metric['after']['median_ms'] <= metric['before']['median_ms'] * 1.02):
        return 'kept', 'strict AST simplification holds the metric within overlapping noise'
    return 'reverted', 'no improvement beyond noise and no qualifying simplification'
result = {'schema':'hillclimb/lever/v1','mode':a.mode,'nonce':a.nonce}
artifacts = state / 'artifacts'
hill = artifacts / 'hillclimb'
if a.mode == 'sensitivity':
    small, target = state / 'sensitivity-small', state / 'sensitivity-target'
    snapshot(small)
    snapshot(target)
    data = {'references': [['account-' + str(i), i % 31 + 1] for i in range(20)],
            'payments': [['account-' + str(i % 20), i % 19 + 1] for i in range(60)]}
    (small / 'workload.json').write_text(json.dumps(data, sort_keys=True) + '\n')
    result['observation'] = observe('sensitivity-measurement', small, target, True)
elif a.mode == 'baseline':
    baseline = state / 'baseline'
    result['source_sha256'] = snapshot(baseline)
    result['observation'] = observe('baseline-measurement', baseline, baseline)
    result['tests'] = suite(baseline, 'baseline-regression')
    hill.mkdir(parents=True, exist_ok=True)
    with (hill / 'decision.tsv').open('x') as f:
        csv.writer(f, delimiter='\t', lineterminator='\n').writerow(ledger_header)
elif a.mode == 'begin':
    attempt = state / ('attempt-' + str(a.id))
    attempt.mkdir(exist_ok=False)
    result.update(id=a.id, before_sha256=snapshot(attempt / 'before'))
    write(attempt / 'begin.json', result)
elif a.mode == 'evaluate':
    attempt = state / ('attempt-' + str(a.id))
    hypothesis = load(hill / ('hypothesis-' + str(a.id) + '.json'))
    result.update(id=a.id, before_sha256=hashes(attempt / 'before'),
                  after_sha256=snapshot(attempt / 'after'))
    result['observation'] = observe('attempt-' + str(a.id) + '-measurement', attempt / 'before', attempt / 'after')
    result['tests'] = suite(attempt / 'after', 'attempt-' + str(a.id) + '-regression')
    verdict, why = classify(result['observation'], result['tests'], attempt / 'before', attempt / 'after',
                            hypothesis.get('simplification') is True)
    measured = result['observation'].get('measurement')
    result.update(verdict=verdict, reason=why, scope_changed=contract(attempt / 'before', attempt / 'after'),
                  expected_delta=(measured['timings']['after']['median_ms']-measured['timings']['before']['median_ms'])
                                 if measured else None)
    write(attempt / 'evaluation.json', result)
elif a.mode == 'record':
    attempt = state / ('attempt-' + str(a.id))
    evaluation = load(attempt / 'evaluation.json')
    decision = load(hill / ('decision-' + str(a.id) + '.json'))
    hypothesis = load(hill / ('hypothesis-' + str(a.id) + '.json'))
    measurement = evaluation['observation'].get('measurement')
    before = measurement['timings']['before']['median_ms'] if measurement else None
    after = measurement['timings']['after']['median_ms'] if measurement else None
    expected = dict(id=a.id, hypothesis=hypothesis['hypothesis'], change=hypothesis['mechanism'],
        before=before, after=after, delta=(after-before) if measurement else None,
        tests='green' if evaluation['tests']['valid'] else 'failed',
        verdict=evaluation['verdict'], note=evaluation['reason'])
    if decision != expected:
        raise ValueError('decision does not match real observations')
    expected_source = evaluation['after_sha256'] if evaluation['verdict'] == 'kept' else evaluation['before_sha256']
    if hashes(root) != expected_source:
        raise ValueError('kept source or complete revert not witnessed')
    path = hill / 'decision.tsv'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open() as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        if len(rows) != a.id-1:
            raise ValueError('ledger order mismatch')
    else:
        raise ValueError('ledger was not opened at baseline')
    with path.open('a') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        writer.writerow([json.dumps(expected[key], ensure_ascii=True) for key in ledger_header])
    result.update(id=a.id, decision=expected, source_sha256=hashes(root), ledger_sha256=sha(path))
    write(attempt / 'record.json', result)
elif a.mode == 'review-ready':
    destination = state / 'review'
    destination.mkdir(exist_ok=False)
    sessions = list((state / 'native-sessions').glob('*.jsonl'))
    if len(sessions) != 1:
        raise ValueError('controller session ambiguous')
    shutil.copy2(sessions[0], destination / 'controller-transcript.jsonl')
    result['transcript_sha256'] = sha(destination / 'controller-transcript.jsonl')
    result['ledger_sha256'] = sha(hill / 'decision.tsv')
    result['trail_sha256'] = sha(artifacts / 'trail/decision.tsv')
    write(destination / 'manifest.json', result)
elif a.mode == 'final':
    final = state / 'final'
    result['source_sha256'] = snapshot(final)
    result['observation'] = observe('final-measurement', state / 'baseline', final)
    result['tests'] = suite(final, 'final-regression')
    with (hill / 'decision.tsv').open() as f:
        rows = list(csv.DictReader(f, delimiter='\t'))
    decisions = [{key:json.loads(row[key]) for key in ledger_header} for row in rows]
    measurement = result['observation'].get('measurement')
    reduction = (1-measurement['timings']['after']['median_ms']/measurement['timings']['before']['median_ms']) if measurement else None
    result.update(attempts=len(rows), kept=sum(r['verdict']=='kept' for r in decisions),
                  reverted=sum(r['verdict']=='reverted' for r in decisions), reduction=reduction,
                  predicate_met=(reduction is not None and reduction >= a.target_reduction/100
                                 and len(rows) >= a.attempt_floor and result['tests']['valid']))
    if measurement:
        t = measurement['timings']
        result['primary_number'] = '%.3f ms -> %.3f ms (%.1f%% reduction)' % (
            t['before']['median_ms'],t['after']['median_ms'],100*reduction)
        lines = ['# Reconciliation Hillclimb', '', result['primary_number'], '',
            'Five alternating unprofiled full-CLI runs per side; profiles are separate. Startup, JSON validation, complete reconciliation and output are timed.',
            '', '| Side | Median ms | Minimum ms | Maximum ms |',
            '| --- | ---: | ---: | ---: |']
        for side in ('before','after'):
            lines += ['| %s | %.3f | %.3f | %.3f |' % (side,t[side]['median_ms'],t[side]['minimum_ms'],t[side]['maximum_ms'])]
        lines += ['', 'All timed runs consumed 2,500 references and 6,000 payments, returned the independently computed result, and reported zero errors.',
            '', 'Target: %.1f%% reduction with at least %d attempts.' % (a.target_reduction,a.attempt_floor),
            'Attempts: %d kept, %d reverted.' % (result['kept'],result['reverted']),
            'Workload SHA-256: '+measurement['workload_sha256'],
            'Baseline source SHA-256: '+measurement['sources']['before']['reconcile.py'],
            'Final source SHA-256: '+measurement['sources']['after']['reconcile.py'],
            '', '## Attempts', '', '| ID | Before ms | After ms | Delta ms | Tests | Verdict |',
            '| --- | ---: | ---: | ---: | --- | --- |']
        for row in decisions:
            number = lambda x: 'invalid' if x is None else '%.3f' % x
            lines += ['| %s | %s | %s | %s | %s | %s |' % (
                row['id'],number(row['before']),number(row['after']),number(row['delta']),row['tests'],row['verdict'])]
        lines += ['', 'Each attempt used a fresh bounded implementation worker and a frozen before/after snapshot. A keep requires a green CLI gate and a gap exceeding observed ranges, or strict AST simplification with overlapping ranges and at most 2% median loss.',
            '', 'Scope: one function, this deterministic local workload and host. Warm filesystem and interpreter startup are included. No production ceiling, concurrency scaling, unattended wake, or universal speedup is claimed.']
        result['portable_report'] = '\n'.join(lines)+'\n'
if a.mode not in ('begin','evaluate','record','review-ready'):
    write(state / (a.mode + '.json'), result)
print(json.dumps(result, sort_keys=True))
'''



def document_patch_headers(value):
    """Normalize only Git's cached mnemonic headers for PERFORMANCE.md."""
    lines = value.splitlines(keepends=True)
    owned_header = False
    for index,line in enumerate(lines):
        text = line.rstrip('\r\n')
        if text.startswith('diff --git '):
            owned_header = text in ('diff --git a/PERFORMANCE.md b/PERFORMANCE.md',
                                    'diff --git c/PERFORMANCE.md i/PERFORMANCE.md')
        elif text.startswith(('@@','GIT binary patch')):
            owned_header = False
        if owned_header:
            for old,new in (('diff --git c/PERFORMANCE.md i/PERFORMANCE.md',
                             'diff --git a/PERFORMANCE.md b/PERFORMANCE.md'),
                            ('--- c/PERFORMANCE.md','--- a/PERFORMANCE.md'),
                            ('+++ i/PERFORMANCE.md','+++ b/PERFORMANCE.md')):
                if text == old:
                    lines[index] = new + line[len(old):]
    return ''.join(lines)

def identity():
    paths = [*ROOT.joinpath('skills').rglob('*'), *(ROOT / 'e2e' / name for name in
        ('hillclimb_loop.py', 'perf_loop.py', 'forge_loop.py', 'playbook_loop.py', 'playbook_cases.py'))]
    return {str(path.relative_to(ROOT)): core.sha(path) for path in paths
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def family(spec):
    model, provider = str(spec.get('model', '')).lower(), str(spec.get('provider', '')).lower()
    for pattern, name in ((r'(?:^|[/:-])gpt[-0-9]', 'gpt'), (r'claude', 'claude'),
                          (r'deepseek', 'deepseek'), (r'(?:^|[/:-])glm[-0-9]', 'glm'),
                          (r'gemini', 'gemini'), (r'grok', 'grok'), (r'qwen', 'qwen')):
        if re.search(pattern, model):
            return name
    raise Failure('model_family_unsupported_or_ambiguous')


def measured(value):
    """Validate actual work and timing arithmetic without prescribing a winner."""
    if (value.get('schema') != 'reconcile/measurement/v1' or value.get('mode') != 'compare'
            or value.get('unit') != 'ms' or value.get('errors') != 0
            or value.get('profiling_in_reported_timing') is not False):
        return False
    observations = value.get('observations', [])
    if len(observations) != 10 or [r.get('side') for r in observations] != ['before', 'after'] * 5:
        return False
    for label in ('before', 'after'):
        rows = [r for r in observations if r['side'] == label]
        samples = [r.get('elapsed_ms', 0) for r in rows]
        if min(samples) <= 0 or any(r.get('result', {}).get('errors') != 0 for r in rows):
            return False
        expected = {'runs': 5, 'samples_ms': samples, 'median_ms': statistics.median(samples),
                    'minimum_ms': min(samples), 'maximum_ms': max(samples)}
        if value.get('timings', {}).get(label) != expected:
            return False
    return value.get('speedup_fraction') == 1 - value['timings']['after']['median_ms'] / value['timings']['before']['median_ms']


def hill_scope_audit(policy_path,task_id):
    """Replay existing role audits before making any worker payload lead-readable."""
    policy=core.read_json(policy_path);home=policy_path.parent
    def require(value):
        if not value:
            raise Failure('hillclimb_worker_gate_rejected')
    require(re.fullmatch(r't-[0-9a-f]{6}',task_id))
    require(all(core.sha(Path(name))==digest for name,digest in policy['integrity'].items()))
    directory=Path(policy['task_root'])/task_id
    task=core.read_json(directory/'task.json');state=core.read_json(directory/'state.json')
    binding=core.read_json(home/'bindings'/(task_id+'.json'))
    require(task['task_id']==task_id and Path(task['task_dir']).resolve()==directory
            and Path(task['result_path']).resolve()==directory/'result.json'
            and Path(task['brief_path']).resolve()==directory/'brief.md'
            and state.get('state')=='done' and state.get('closed') is True
            and core.sha(directory/'task.json')==binding['task_sha256']
            and core.sha(directory/'brief.md')==binding['brief_sha256']
            and binding.get('working_agent',{}).get('agent_status')=='working'
            and binding['working_agent'].get('pane_id')==task['pane_id']
            and binding['working_agent'].get('agent_session')==binding['session'])
    result=core.read_json(directory/'result.json')
    require(horch.validate_result(result,task)=='valid' and result.get('status')=='completed')
    # Reuse this file's maintained role-specific audits without launching a Run.
    audit=Run.__new__(Run)
    audit.checks=[];audit.config=policy['config'];audit.role_workers=policy['roles']
    audit.args=argparse.Namespace(**policy['args']);audit.base=policy['base'];audit.nonce=policy['nonce']
    for name in ('directory','task_root','worktree','reader','bundle','agent_dir'):
        setattr(audit,name,Path(policy[name]))
    audit.gate_home=home;audit.gate_policy=policy_path
    audit.probe=audit.directory/'hillclimb-probe.py';audit.engine=audit.directory/'engine.py'
    audit.artifacts=audit.directory/'artifacts'
    audit.task_sessions={task_id:binding['session']}
    audit.how_tree_before=policy['how_tree_before'];audit.how_tree_captured_at=policy['how_tree_captured_at']
    assignment=audit.controller_assignment(task)
    match=re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)',assignment)
    role=match[1] if match else None
    require(role in policy['roles'] and task['worker'] in policy['roles'][role])
    spec=policy['config']['workers'][task['worker']]
    require(task.get('harness')=='pi' and task.get('model')==spec['model']
            and task.get('argv')==horch.launch_args(spec,directory)
            and Path(task['cwd']).resolve()==(audit.reader if role=='how explainer' else audit.worktree))
    for item in binding['dependencies']:
        path=home/'gates'/(item['task_id']+'.json')
        require(core.sha(path)==item['gate_sha256'] and core.read_json(path).get('verdict')=='pass')
    require(all(core.sha(Path(item['path']))==item['sha256'] for item in binding['inputs']))
    require(core.sha(Path(binding['source_path']))==binding['source_sha256'])
    lead=list((audit.directory/'native-sessions').glob('*.jsonl'))
    require(len(lead)==1)
    events,all_events=audit.native_events(lead[0]),audit.native_events(lead[0],include_errors=True)
    launches,_=core.workflow_launches(events,[task],audit.worktree,audit.bundle)
    require(task_id in launches)
    launch=launches[task_id]
    argv=core.literal_horch_command(launch['name'],launch['args'],audit.worktree,audit.bundle)
    require(argv.count('--brief')==1)
    source=Path(argv[argv.index('--brief')+1])
    expected={'how explainer':'how-brief.md','bounded trail audit':'trail-brief.md',
              'judgment and prose':'comment-brief.md'}
    require(source.parent==audit.artifacts/'hillclimb' and (source.name==expected.get(role)
            or role=='hillclimb' and re.fullmatch(r'brief-[1-9]\d*\.md',source.name)))
    audit.bind_brief(events,all_events,task,launch,source,role)
    native,native_audit=audit.audit_task_native(task)
    native_rows=[json.loads(line) for line in native.read_text().splitlines() if line.strip()]
    header=native_rows[0]
    require(not native.is_symlink() and header.get('id')==native.stem.rsplit('_',1)[-1]
            and Path(header.get('cwd','')).resolve()==Path(task['cwd']).resolve()
            and core.stamp(task['created_at'])<=core.stamp(header['timestamp'])<=binding['captured_at'])
    calls=audit.native_events(native,include_errors=True)
    cwd=Path(task['cwd']).resolve()
    inputs={Path(item['path']) for item in binding['inputs']}
    def readable(raw):
        if not isinstance(raw,str) or not raw or '~' in raw or '\x00' in raw:
            return False
        target=(cwd/raw).resolve()
        return target in inputs or any(target==root or root in target.parents for root in (cwd,directory,audit.bundle))
    brief_reads=core.workflow_reads(audit.native_events(native),cwd,directory/'brief.md')
    require(bool(brief_reads) and task['nonce'] in (directory/'brief.md').read_text()
            and all(any(read['result_row']<call['call_row'] for read in brief_reads) for call in calls
                    if call['name'] in ('bash','fffind','ffgrep','write','edit')))
    document=Path(binding['source_path']).read_bytes().decode('utf-8')
    initial=document;artifacts={};last={};mutations={}
    allowed={'report.md','result.json'}|({'review.json'} if role=='judgment and prose' else set())
    for event in calls:
        name,args=event['name'],event['args']
        if name in ('read','grep','find','ls'):
            require(readable(args.get('path','.' if name!='read' else None)))
        elif name=='bash':
            words=forge_helpers.literal(args.get('command',''))
            if words and words[0] in ('cat','sha256sum','wc'):
                operands=words[2:] if words[0]=='wc' else words[1:]
                require(bool(operands) and all(readable(raw) for raw in operands))
        if name not in ('write','edit'):
            continue
        raw=args.get('path');require(isinstance(raw,str) and '~' not in raw and '\x00' not in raw)
        target=(cwd/raw).resolve()
        writer=role=='hillclimb' and target==cwd/'reconcile.py'
        require(writer or target.parent==directory and target.name in allowed)
        require(last.get(target,-1)<event['call_row']);last[target]=event['result_row']
        candidate=document if writer else artifacts.get(target,'')
        if name=='write':
            require(set(args)=={'path','content'} and isinstance(args['content'],str));candidate=args['content']
        else:
            edits=args.get('edits',[args])
            require(set(args)==({'path','edits'} if 'edits' in args else {'path','oldText','newText'})
                    and isinstance(edits,list) and bool(edits))
            for edit in edits:
                require(isinstance(edit,dict) and set(edit)==({'oldText','newText'} if 'edits' in args else {'path','oldText','newText'})
                        and isinstance(edit.get('oldText'),str) and bool(edit['oldText'])
                        and isinstance(edit.get('newText'),str) and candidate.count(edit['oldText'])==1)
                candidate=candidate.replace(edit['oldText'],edit['newText'],1)
        if writer:
            require(perf.outside_function(candidate)==perf.outside_function(initial))
        if event['successful']:
            if writer:
                document=candidate
            else:
                artifacts[target]=candidate
            mutations.setdefault(target,[]).append(event)
    files=result.get('files')
    require(isinstance(files,list) and all(isinstance(name,str) for name in files)
            and len(set(files))==len(files) and 'report.md' in files and set(files)<=allowed)
    output_names=set(files)|{'result.json'}
    require(set(path.name for path in artifacts)==output_names)
    result_calls=mutations.get(directory/'result.json',[])
    require(bool(result_calls) and all(event['result_row']<result_calls[0]['call_row'] for event in calls
            if event['name'] in ('write','edit') and (cwd/event['args']['path']).resolve()!=directory/'result.json'))
    for name in output_names:
        path=directory/name
        require(path.is_file() and path.resolve()==path and artifacts.get(path) is not None and artifacts[path].encode()==path.read_bytes())
    require(all(core.sha(cwd/name)==digest for name,digest in binding['fixture_sha256'].items()))
    snapshot=home/'sources'/(task_id+'.py')
    if role=='hillclimb':
        if snapshot.exists():
            require(snapshot.read_bytes()==document.encode())
        else:
            require((cwd/'reconcile.py').read_bytes()==document.encode())
            snapshot.write_bytes(document.encode());snapshot.chmod(0o444)
    else:
        require((cwd/'reconcile.py').read_bytes()==initial.encode())
    outputs={str(directory/name):core.sha(directory/name) for name in sorted(output_names)}
    if role=='hillclimb':
        outputs[str(cwd/'reconcile.py')]=core.sha(snapshot)
    return {'schema':'hillclimb/worker-gate/v1','verdict':'pass','task_id':task_id,'role':role,
            'task_sha256':core.sha(directory/'task.json'),'brief_sha256':core.sha(directory/'brief.md'),
            'binding_sha256':core.sha(home/'bindings'/(task_id+'.json')),'native_sha256':core.sha(native),
            'calls_audited':len(calls),'outputs':outputs,'source_sha256':hashlib.sha256(document.encode()).hexdigest()}


def hill_wait_audit(policy_path,task_id,seconds):
    """Only safe fixed metadata crosses this delivery boundary, including failure."""
    home=policy_path.parent
    try:
        policy=core.read_json(policy_path)
        if not re.fullmatch(r't-[0-9a-f]{6}',task_id) or not 1<=seconds<=120:
            raise Failure('invalid_gate_request')
        if any(core.sha(Path(name))!=digest for name,digest in policy['integrity'].items()):
            raise Failure('gate_integrity_changed')
        target=home/'gates'/(task_id+'.json')
        if target.exists() and core.read_json(target).get('verdict')!='pass':
            raise Failure('quarantine_is_final')
        argv=[sys.executable,str(Path(policy['bundle'])/'skills/herdr-orchestrator/scripts/horch.py'),
              'wait',task_id,'--max-seconds',str(seconds)]
        began=time.time()
        try:
            raw=subprocess.run(argv,capture_output=True,text=True,timeout=seconds+20)
            receipt={'argv':argv,'returncode':raw.returncode,'stdout':raw.stdout,'stderr':raw.stderr,
                     'started_at':began,'completed_at':time.time()}
        except subprocess.TimeoutExpired as error:
            decode=lambda value:value.decode(errors='replace') if isinstance(value,bytes) else value or ''
            receipt={'argv':argv,'returncode':None,'stdout':decode(error.stdout),'stderr':decode(error.stderr),
                     'started_at':began,'completed_at':time.time()}
        destination=home/'waits'/task_id;destination.mkdir(parents=True,exist_ok=True)
        (destination/(str(time.time_ns())+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
        lines=[json.loads(line) for line in receipt['stdout'].splitlines() if line.strip()]
        if receipt['returncode']!=0 or len(lines)!=1 or lines[0].get('task_id')!=task_id:
            raise Failure('invalid_wait')
        event=lines[0]
        if event.get('state') in ('running','starting','long_running') and event.get('closed') is not True:
            return {'schema':'hillclimb/safe-delivery/v1','task_id':task_id,'verdict':'pending','state':'pending','closed':False}
        if event.get('state')!='done' or event.get('closed') is not True:
            raise Failure('not_done_closed')
        facts=hill_scope_audit(policy_path,task_id)
        if target.exists() and core.read_json(target)!=facts:
            raise Failure('gate_changed')
        if not target.exists():
            target.write_text(json.dumps(facts,indent=2)+'\n');target.chmod(0o444)
        return {'schema':'hillclimb/safe-delivery/v1','task_id':task_id,'verdict':'pass','state':'done','closed':True,
                'gate_sha256':core.sha(target),'outputs':list(facts['outputs']),'native_sha256':facts['native_sha256']}
    except Exception:
        value={'schema':'hillclimb/safe-delivery/v1','task_id':task_id if re.fullmatch(r't-[0-9a-f]{6}',task_id) else None,
               'verdict':'fail','state':'quarantined','closed':None,'category':'worker_scope_or_lifecycle_rejected'}
        if value['task_id']:
            try:
                target=home/'gates'/(task_id+'.json')
                if not target.exists():
                    target.write_text(json.dumps(value,indent=2)+'\n');target.chmod(0o444)
            except Exception:
                pass
        return value


class Run(core.Run):
    git = perf.Run.git
    forge = perf.Run.forge
    native_events = forge_helpers.Run.native_events
    stage = forge_helpers.Run.stage
    artifact = perf.Run.artifact

    def __init__(self, args):
        args.scenario = 'hillclimb'
        super().__init__(args)
        self.branch = 'e2e/hillclimb-' + secrets.token_hex(8)
        self.nonce = secrets.token_hex(24)
        self.probe = self.directory / 'hillclimb-probe.py'
        self.engine = self.directory / 'engine.py'
        self.config_path = self.original_fixture = self.pr = self.base = None
        self.stage_proof, self.snapshot, self.task_sessions = {}, {}, {}
        self.iterations, self.task_facts = [], []
        self.agent_dir = Path(self.env.get('PI_CODING_AGENT_DIR') or Path.home()/'.pi/agent').expanduser().resolve()
        self.session_settings_hashes = {}
        self.how_tree_before = None
        self.how_tree_captured_at = None
        self.gate_home = self.directory/'hillclimb-gate'
        self.gate_policy = self.gate_home/'policy.json'
        self.gate_hash = None

    def preflight(self):
        self.check('positive_deadline', self.args.max_seconds > 0)
        self.check('inventory_matches_declared_playbooks',
                   set(self.inventory_names) == set(core.INVENTORY))
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == ROOT)
        self.revision = self.git('rev-parse', 'HEAD', repo=ROOT)
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT)
        self.hashes = identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('controller_is_existing_pi', self.spec.get('harness') == 'pi')
        self.role_workers = {}
        for role in ('hillclimb', 'how explainer', 'judgment and prose'):
            selection = self.config.get('roles', {}).get(role)
            names = selection if isinstance(selection, list) else [selection]
            self.check('configured_single_' + role.replace(' ', '_'), len(names) == 1
                       and names[0] in self.config['workers'] and self.config['workers'][names[0]].get('harness') == 'pi')
            self.role_workers[role] = names
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.fixture_refs = self.git('for-each-ref', '--format=%(objectname)%09%(refname)',
                                     repo=self.args.fixture_repo).splitlines()
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('fixture_clean', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('explicit_fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        repo = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('explicit_private_forge', repo.get('isPrivate') is True
                   and repo.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        rows = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('one_remote_baseline', len(rows) == 1)
        self.base = rows[0].split()[0]
        self.check('pinned_pristine_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base)
        self.check('portable_fixture_matches', all((self.args.fixture_repo / name).is_file()
                   and core.sha(self.args.fixture_repo / name) == hashlib.sha256(value.encode()).hexdigest()
                   for name, value in perf.fixture_files().items()))
        self.bootstrap = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo,
                                    '--json', 'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('explicit_parent_pr_ready_open', self.bootstrap.get('state') == 'OPEN'
                   and self.bootstrap.get('isDraft') is False and self.bootstrap.get('headRefOid') == self.base
                   and self.bootstrap.get('headRefName') == self.args.base_ref)
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000',
                                    '--json', 'number,state,headRefName,baseRefName,isDraft')

        reviewer = self.config['workers'].get(self.args.trail_reviewer, {})
        self.check('existing_pi_trail_reviewer', reviewer.get('harness') == 'pi')
        self.check('different_actual_model_family', family(reviewer) != family(self.spec))
        self.review_spec = reviewer
        self.role_workers['bounded trail audit'] = [self.args.trail_reviewer]
        overrides = ('--session', '--session-dir', '--session-id', '--no-session', '--continue', '--resume', '-c', '-r')
        for name in {worker for names in self.role_workers.values() for worker in names}:
            self.check('owned_cwd_sessions_no_worker_override', not any(
                arg == flag or arg.startswith(flag+'=') for arg in self.config['workers'][name].get('args', [])
                for flag in overrides))
        self.check('no_session_directory_env_override', not self.env.get('PI_CODING_AGENT_SESSION_DIR'))
        for label,path in (('agent',self.agent_dir/'settings.json'),
                           ('fixture',self.args.fixture_repo/'.pi/settings.json')):
            self.session_settings_hashes[label] = core.sha(path) if path.is_file() else None
            if path.is_file():
                self.check('owned_cwd_sessions_default_setting_'+label, not core.read_json(path).get('sessionDir'))
        self.check('explicit_target_and_attempt_floor', 0 < self.args.target_reduction < 100
                   and self.args.attempt_floor >= 3 and self.args.max_attempts >= self.args.attempt_floor)
    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(PROBE)
        self.probe_hash = core.sha(self.probe)
        self.probe.chmod(0o444)
        self.engine.write_text(ENGINE)
        self.engine_hash = core.sha(self.engine)
        self.engine.chmod(0o444)
        self.baseline = self.directory / 'baseline'
        (self.artifacts / 'hillclimb').mkdir()
        (self.artifacts / 'trail').mkdir()
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        self.reader = self.worktree.parent / 'how-reader'
        self.git('worktree', 'add', '--detach', self.reader, self.base, repo=self.args.fixture_repo)
        self.how_tree_before = forge_helpers.reader_tree(self.reader)
        self.how_tree_captured_at = time.time()
        (self.directory/'how-tree-before.json').write_text(json.dumps({
            'descriptor':self.how_tree_before,'captured_at':self.how_tree_captured_at},indent=2)+'\n')
        env = [item for key in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL', 'GH_CONFIG_DIR')
               for item in ('--env', key + '=' + self.env[key])]
        if self.env.get('PI_CODING_AGENT_DIR'):
            env += ['--env', 'PI_CODING_AGENT_DIR=' + str(self.agent_dir)]
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'hillclimb-e2e', '--no-focus', *env)
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
        self.gate_home.mkdir()
        for name in ('bindings','gates','waits','sources'):
            (self.gate_home/name).mkdir()
        integrity={str(ROOT/name):digest for name,digest in self.hashes.items()}
        integrity.update({str(self.bundle/name):digest for name,digest in self.hashes.items() if name.startswith('skills/')})
        integrity.update({str(self.probe):self.probe_hash,str(self.engine):self.engine_hash,
                          str(self.config_path):self.config_hash,str(destination):self.config_hash})
        policy={'directory':str(self.directory),'task_root':str(self.task_root.resolve()),'worktree':str(self.worktree),
            'reader':str(self.reader),'bundle':str(self.bundle),'agent_dir':str(self.agent_dir),'base':self.base,
            'nonce':self.nonce,'config':self.config,'roles':self.role_workers,'args':vars(self.args),
            'controller_session':self.session,'controller_spec':self.spec,'wall_started':self.wall_started,
            'how_tree_before':self.how_tree_before,'how_tree_captured_at':self.how_tree_captured_at,
            'integrity':integrity}
        policy['args']={key:str(value) if isinstance(value,Path) else value for key,value in policy['args'].items()}
        self.gate_policy.write_text(json.dumps(policy,indent=2)+'\n');self.gate_policy.chmod(0o444)
        self.gate_hash=core.sha(self.gate_policy)
        self.check('controller_prompted', self.herdr('agent', 'prompt', self.agent, f'Read {brief} in full and execute it.',
                   '--wait', '--until', 'working', '--timeout', '30000').get('type') == 'agent_prompted')


    def scan(self):
        rows=super().scan()
        self.guard_live_lead_access(rows)
        if self.gate_hash and core.sha(self.gate_policy)!=self.gate_hash:
            raise Failure('immutable_worker_gate_policy_changed')
        for task,state in rows:
            gate=self.gate_home/'gates'/(task['task_id']+'.json')
            if gate.is_file() and core.read_json(gate).get('verdict')!='pass':
                raise Failure('worker_gate_quarantined_stop')
            if task['task_id'] in self.task_sessions or state.get('closed'):
                continue
            try:
                entry=self.herdr('agent','get',task['agent'])['agent']
                session=entry.get('agent_session') or {}
                if (entry.get('pane_id')!=task['pane_id'] or entry.get('agent_status')!='working'
                        or session.get('agent')!='pi' or session.get('source')!='herdr:pi' or not session.get('value')):
                    continue
                binding=self.capture_gate_binding(task,session)
                binding['working_agent']={key:entry.get(key) for key in ('agent_status','pane_id','agent_session')}
                self.check('captured_agent_is_working',binding['working_agent']['agent_status']=='working')
            except Failure as error:
                if str(error)=='working_launch_receipt_not_yet_available':
                    continue
                raise
            target=self.gate_home/'bindings'/(task['task_id']+'.json')
            target.write_text(json.dumps(binding,indent=2)+'\n');target.chmod(0o444)
            (Path(task['task_dir'])/'native-session-capture.json').write_text(json.dumps(
                {key:binding[key] for key in ('session','captured_at','task_sha256','brief_sha256')},indent=2)+'\n')
            self.task_sessions[task['task_id']]=session
        return rows

    def guard_live_lead_access(self,rows):
        """Stop on attempted raw forwarding; never inspect tool-result payloads here."""
        paths=list((self.directory/'native-sessions').glob('*.jsonl'))
        if len(paths)!=1:
            return
        for line in paths[0].read_text().splitlines():
            row=json.loads(line);message=row.get('message',{})
            if message.get('role')!='assistant':
                continue
            for block in message.get('content',[]):
                if block.get('type')!='toolCall':
                    continue
                name,args=block.get('name'),block.get('arguments',{})
                if not isinstance(args,dict):
                    raise Failure('lead_tool_schema_rejected')
                command=args.get('command','') if name=='bash' else ''
                if name=='bash' and not self.controller_command_allowed(command):
                    raise Failure('lead_bash_command_quarantined')
                safe=self.gate_invocation(command) if name=='bash' else None
                horch_args=core.literal_horch_command(name,args,self.worktree,self.bundle)
                words=forge_helpers.literal(command) if name=='bash' else []
                if words and words[0] in ('python','python3') and str(Path(__file__).resolve()) in words and safe is None:
                    raise Failure('unparsed_delivery_gate_quarantined')
                if name=='bash' and str(self.bundle/'skills/herdr-orchestrator/scripts/horch.py') in command and not horch_args:
                    raise Failure('unparsed_horch_command_quarantined')
                if horch_args and horch_args[0]!='run':
                    raise Failure('raw_horch_poll_quarantined')
                if safe is not None or horch_args:
                    continue
                target=None
                if name in ('read','grep','find','ls','write','edit'):
                    raw=args.get('path','.' if name in ('grep','find','ls') else None)
                    if isinstance(raw,str):
                        target=(self.worktree/raw).resolve()
                words=forge_helpers.literal(command) if name=='bash' else []
                if len(words)==2 and words[0] in ('cat','sha256sum'):
                    target=(self.worktree/words[1]).resolve()
                elif name=='bash' and any(task['task_id'] in command or task['task_dir'] in command for task,_ in rows):
                    raise Failure('unparsed_task_access_quarantined')
                if str(self.gate_home) in command:
                    raise Failure('raw_gate_access_quarantined')
                if target is None:
                    continue
                if (target==self.gate_home or self.gate_home in target.parents or target in self.gate_home.parents
                        or target.suffix=='.jsonl'):
                    raise Failure('raw_audit_access_quarantined')
                if target==self.task_root.resolve() or target in self.task_root.resolve().parents:
                    raise Failure('task_parent_access_quarantined')
                if self.task_root.resolve() in target.parents:
                    owner=[task for task,_ in rows if Path(task['task_dir']).resolve() in target.parents]
                    if len(owner)!=1:
                        raise Failure('unknown_task_access_quarantined')
                    task=owner[0];gate=self.gate_home/'gates'/(task['task_id']+'.json')
                    if (not gate.is_file() or core.read_json(gate).get('verdict')!='pass'
                            or str(target) not in core.read_json(gate).get('outputs',{}) or name in ('write','edit')):
                        raise Failure('ungated_output_access_quarantined')

    def capture_gate_binding(self,task,session):
        paths=list((self.directory/'native-sessions').glob('*.jsonl'))
        self.check('one_working_lead_session',len(paths)==1)
        events=self.native_events(paths[0])
        launches,_=core.workflow_launches(events,[task],self.worktree,self.bundle)
        if task['task_id'] not in launches:
            raise Failure('working_launch_receipt_not_yet_available')
        launch=launches[task['task_id']]
        assignment=self.controller_assignment(task)
        match=re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)',assignment)
        role=match[1] if match else None
        self.check('working_bound_configured_role',role in self.role_workers and task['worker'] in self.role_workers[role])
        dependencies=[]
        for other in self.tasks.values():
            if other['task_id']==task['task_id'] or core.stamp(other['created_at'])>=core.stamp(task['created_at']):
                continue
            gate=self.gate_home/'gates'/(other['task_id']+'.json')
            self.check('dependent_work_requires_prior_pass_gate',gate.is_file() and core.read_json(gate).get('verdict')=='pass')
            safe=[e for e in events if self.gate_invocation(e['args'].get('command','')) is not None
                  and e['name']=='bash' and self.gate_invocation(e['args']['command'])[0]==other['task_id']
                  and e['result_row']<launch['call_row'] and json.loads(e['output']).get('verdict')=='pass']
            self.check('dependent_work_after_safe_delivery',bool(safe))
            for raw_path in core.read_json(gate)['outputs']:
                path=Path(raw_path)
                if path.parent==Path(other['task_dir']).resolve():
                    self.check('dependency_full_outputs_read_after_safe_delivery',bool(core.workflow_reads(
                        events,self.worktree,path,after=safe[-1]['result_row'],before=launch['call_row'])))
            dependencies.append({'task_id':other['task_id'],'gate_sha256':core.sha(gate),
                                 'delivery_result_row':safe[-1]['result_row']})
        inputs=[]
        allowed_inputs=self.role_input_paths(role)
        for raw in re.findall(r'^Input artifact: (.+)$',assignment,re.M):
            path=Path(raw)
            allowed=(path.is_absolute() and path.resolve()==path and path.is_file()
                     and path in allowed_inputs)
            self.check('working_declared_input_owned',allowed)
            digest=core.sha(path)
            # Every extra input is a completed native stage artifact, not a guessed file.
            writes=core.workflow_writes(events,self.worktree,path,before=launch['call_row'],final=True)
            reads=core.workflow_reads(events,self.worktree,path,before=launch['call_row'])
            ready=[e for e in events if e['name']=='bash' and self.lever_invocation(e['args'].get('command',''))==('review-ready',None)
                   and e['result_row']<launch['call_row']]
            manifest=core.read_json(self.directory/'review/manifest.json') if ready else {}
            staged={self.directory/'review/controller-transcript.jsonl':manifest.get('transcript_sha256'),
                    self.artifacts/'hillclimb/decision.tsv':manifest.get('ledger_sha256'),
                    self.artifacts/'trail/decision.tsv':manifest.get('trail_sha256')}
            stage_bound=bool(ready) and json.loads(ready[-1]['output'])==manifest and staged.get(path)==digest
            self.check('working_input_actual_native_stage_provenance',bool(writes or reads or stage_bound))
            inputs.append({'path':str(path),'sha256':digest})
        source=Path(task['cwd'])/'reconcile.py'
        if role=='hillclimb':
            argv=core.literal_horch_command(launch['name'],launch['args'],self.worktree,self.bundle)
            brief=Path(argv[argv.index('--brief')+1])
            number=re.fullmatch(r'brief-([1-9]\d*)\.md',brief.name)
            self.check('writer_exact_attempt_brief',number is not None)
            source=self.directory/('attempt-'+number[1])/'before/reconcile.py'
            begins=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))==
                    self.lever_argv('begin',int(number[1])) and e['result_row']<launch['call_row']]
            self.check('writer_native_begin_source_binding',len(begins)==1
                       and json.loads(begins[0]['output'])['before_sha256']['reconcile.py']==core.sha(source))
        return {'session':session,'captured_at':time.time(),'inputs':inputs,'dependencies':dependencies,
            'task_sha256':core.sha(Path(task['task_dir'])/'task.json'),'brief_sha256':core.sha(Path(task['brief_path'])),
            'source_path':str(source),'source_sha256':core.sha(source),
            'fixture_sha256':{name:core.sha(Path(task['cwd'])/name) for name in FILES if name!='reconcile.py'}}

    def role_input_paths(self,role):
        if role=='how explainer':
            return set()
        if role=='hillclimb':
            return {self.artifacts/'hillclimb/explanation.md',
                    *(self.artifacts/f'hillclimb/hypothesis-{i}.json' for i in range(1,self.args.max_attempts+1))}
        logs={self.artifacts/'hillclimb/decision.tsv',self.artifacts/'trail/decision.tsv'}
        if role=='judgment and prose':
            return logs|{self.directory/'final.json',self.artifacts/'pr-body.md',
                         *(self.artifacts/('hillclimb/'+name) for name in ('comment-scope.json','comment-diff.patch','attention.md'))}
        return logs|{self.directory/'review/controller-transcript.jsonl',self.directory/'review/manifest.json',
            *(self.artifacts/f'hillclimb/{kind}-{i}.json' for i in range(1,self.args.max_attempts+1) for kind in ('hypothesis','decision')),
            *(self.directory/f'attempt-{i}/{kind}.json' for i in range(1,self.args.max_attempts+1) for kind in ('evaluation','record'))}

    def gate_invocation(self,command):
        argv=forge_helpers.literal(command)
        if (len(argv)==6 and argv[:4]==['python3',str(Path(__file__).resolve()),'--wait-audit',str(self.gate_policy)]
                and re.fullmatch(r't-[0-9a-f]{6}',argv[4]) and argv[5].isdigit() and 1<=int(argv[5])<=120):
            return argv[4],int(argv[5])
        return None

    def lever_argv(self, mode, number=None):
        argv = ['python3', '-B', str(self.probe), '--mode', mode, '--root', str(self.worktree),
                '--state', str(self.directory), '--nonce', self.nonce,
                '--target-reduction', str(self.args.target_reduction),
                '--attempt-floor', str(self.args.attempt_floor)]
        return argv + (['--id', str(number)] if number is not None else [])

    def prompt(self):
        a, b, d = self.artifacts, self.bundle / 'skills', self.directory
        command = lambda mode, number=None: shlex.join(self.lever_argv(mode, number))
        return f"""Read {b / 'poteto-mode/SKILL.md'} and follow original Hillclimb in one ATTENDED lead turn.
Goal: sustained measured improvement of the real reconciliation CLI on the frozen 2,500-reference/6,000-payment workload. User target is at least {self.args.target_reduction}% lower end-to-end wall median and at least {self.args.attempt_floor} genuinely distinct measured attempts. Maximum {self.args.max_attempts} attempts is a resource bound, not an alternate successful predicate. If unmet, stop honestly unresolved; do not lower the floor/target. No unattended wake exists or is claimed.

Except for the explicitly declared How-only installed FFF exception below, use ONLY native read, bash, write, edit, grep, find, ls. No codemode, eval, shell pipelines/redirection/substitution, inline scripts/Python, or invented wrappers; the one declared same-file --wait-audit delivery command is the required maintained exception. Use literal direct CLI commands and absolute paths. Literal bash rejects newline, semicolon, pipe, ampersand, redirection, backtick, dollar or backslash even inside quotes; no home-expansion (~ or ~user) filesystem paths. Native ls uses path/limit fields, not shell flags. Controller bash grammar: exact lever commands below; bare uptime/nproc/pwd; command -v origin; literal bash original-log.sh assigned-trail-path plus five row fields; direct python/python3 bundled horch.py run only; cat FILE or sha256sum FILE for one absolute file; git -C exact_worktree readonly status/diff/show/log/blame/rev-parse/rev-list/diff-tree/ls-files/ls-remote, branch --show-current, remote get-url origin, add only reconcile.py or PERFORMANCE.md, commit -m normal perf/docs scoped subject, exact restore --source=HEAD -- reconcile.py, push [-u/--set-upstream] origin owned_branch; selected gh/origin repo view, pr view/list or the exact assigned ready pr create. No other controller bash forms. For every task, delivery is ONLY python3 {Path(__file__).resolve()} --wait-audit {self.gate_policy} TASK_ID 120 (1..120 seconds); repeat pending waits, never retry failure. Raw horch wait/list/stats/close/detect, raw policy/bindings/waits/gates/native-session/output copies and task-store-parent inspection are prohibited. Read exact declared outputs ONLY after verdict=pass, state=done, closed=true; a failure quarantines the run immediately, exposes no model payload and requires STOP. This is post-execution validation, not containment. Do not inspect or execute a writer's integration cwd/source before its PASS. Dispatch each later worker only after all earlier safe PASS deliveries and full required report reads. All worker briefs must repeat this tool protocol, no nested workers and no trust/approval dialog answers. Worker Bash follows the exact role-specific forms below; no generic module/script execution is authorized; source/report/result writes use native edit/write only, scoped to assigned function and owned task directory. Do not retune models/settings or retry failed model tasks.
Only fresh configured hillclimb workers may edit app source, ONLY body of reconcile_linear in {self.worktree / 'reconcile.py'}. No other app/workload/oracle/harness/config edits. You supervise/review; never author source. Only owned branch {self.branch} may be pushed. No merges/automerge/other PR mutations.
Named controller-native-write artifacts only: checklist.md; hillclimb/workload.json, hillclimb/metric.json, hillclimb/vetting.json, hillclimb/freeze.json, hillclimb/how-brief.md, hillclimb/explanation.md, hillclimb/stop.json, hillclimb/trail-brief.md, hillclimb/attention.md, hillclimb/comment-brief.md, hillclimb/comment-scope.json, hillclimb/comment-diff.patch, hillclimb/comment-decision.json; hillclimb/hypothesis-N.json, hillclimb/brief-N.md, hillclimb/review-N.json, hillclimb/decision-N.json for integer N=1..{self.args.max_attempts}; pr-body.md, forge-resolution.json, reply.md; and sanitized PERFORMANCE.md in worktree. No direct writes/edits to either decision.tsv, probe state, snapshots, measurements, results or raw transcripts. Ledger writes happen only through the immutable lever; generic trail rows only through original log.sh.

Read full required instructions: {json.dumps([str(b / resource) for resource in READS])}. Read original 8-stage Hillclimb; first native-write {a / 'checklist.md'} with exact original top-level numbered instructions before any task/work. Do How SIMPLE route first: one readonly explainer configured {self.role_workers['how explainer'][0]} on detached {self.reader}, with original explainer prompt, assignment in {a / 'hillclimb/how-brief.md'}. Literal horch run --brief that path; raw horch polling is never authorized. All task briefs first line Role: exact role (how explainer, hillclimb, bounded trail audit, or judgment and prose), selected worker and reason in the full controller-authored prefix before Horch's appended rules, 'Do not delegate', absolute {b / 'pstack-herdr/references/agents/poteto-agent.md'} and {b / 'poteto-mode/SKILL.md'}. Wait ONLY through the same-file safe gate; after actual PASS/done/closed, read result JSON and FULL listed report. Preserve How explanation verbatim in {a / 'hillclimb/explanation.md'}.
All non-How local readonly Git is recognized only by the owned-cwd local grammar: optional -C must be the exact canonical owned cwd; log/blame/show/diff/status/rev-parse/ls-files/rev-list/diff-tree, the readonly flags/value forms enumerated in the Comment grammar below, owned path operands and actual base/HEAD ancestry/hex revisions only. No --no-index, external operands (including relative/./ aliases resolving outside cwd), output/ext-diff/textconv execution, configuration overrides or generic rev:path. Additional exact readonly forms: branch --show-current, diff --check, status --short --branch. The controller additionally permits exact diff --cached and diff --staged for complete documentation review; ls-remote --heads origin optionally followed by refs/heads/{self.branch} or refs/heads/{self.args.base_ref}; remote get-url origin, and the already specified explicit add/commit/restore/push forms. These retain normal Git configuration/hooks and do not authorize arbitrary flags.
Writer-only Python Bash is python or python3, optional ONE leading -B, then exactly cli.py workload.json, -m py_compile reconcile.py, or e2e_reconcile.py --output NEW_DIR. Each named file operand is either its literal basename in owned cwd or its exact absolute owned path; no ./ aliases, flags, additional operands or alternative scripts/modules. Oracle NEW_DIR is an exact canonical absolute fresh directory strictly inside this writer's actual task directory, outside app, with no symlink components; choose a distinct directory for every invocation, never task identity/report names. No other writer Python, json.tool or output operands are admitted.
Trail-only file Bash: cat ONE_READABLE_FILE; sha256sum 1..3 readable files without flags; wc -l 1..4 explicitly declared Input artifact files; wc -c ONE_READABLE_FILE; bare pwd; the exact four ls forms stated in its brief; readonly local Git as above. Readable files are only its owned cwd, bundle, own task directory or exact declared inputs, never private gate policy/bindings/sources/waits/native copies. Trail-only Python is python or python3 with optional ONE leading -B followed by exactly -m json.tool ABSOLUTE_OWN_TASK_REPORT_MD or -m json.tool ABSOLUTE_OWN_TASK_RESULT_JSON; no other modules/scripts, flags or output operands. The authored trail brief must explicitly repeat these forms and boundaries.
The worker-visible TASK_DIR/native-session-capture.json is a declared read-only identity exception in its own task directory, containing ONLY session, captured_at, task_sha256 and brief_sha256. It may be read or counted with the admitted wc -c form. Full source/input/dependency/WORKING bindings remain exclusively in private gate storage and are never worker-readable. Do not modify either capture or any identity file. How and Comment keep their separate existing grammars; these Python/wc/variadic forms do not apply to them.
Every actual assignment must fully declare its role grammar, read its nonce-bound full brief before Bash/FFF/write/edit, and write only canonical report.md/result.json (Comment may also write review.json). result.files must uniquely list report.md and every supplementary output, in any order. Native write+edit is allowed with unique nonempty oldText; mutations are sequential per file, independent files may be batched; finish ALL source/report edits before the first result.json mutation, write result last. No task identity/config writes. For every external artifact the worker needs, add one literal Input artifact: ABSOLUTE_PATH line: writers use only explanation.md and their own hypothesis-N.json; trail uses review/controller-transcript.jsonl, review/manifest.json, both logs, each actual hypothesis/decision and attempt evaluation/record; Comment uses its scope JSON, patch, final.json, both logs, attention.md and pr-body.md. Other reads are only its owned cwd, own task directory and bundle. No other input files, raw gate metadata or other task stores. The gate binds live WORKING UUID, exact launch/brief/nonce/cwd/config, native input provenance and prior safe deliveries; missing WORKING capture is unresolved, not an identity fallback.
The actual How brief MUST explicitly declare this role-only installed-tool contract: native read/write/edit/bash plus exact fffind(pattern:string,path?:string,exclude?:string|string[],limit?:positive integer) and ffgrep with those fields plus caseSensitive?:boolean/context?:nonnegative integer. No cursor/unknown fields/null numeric FFF values; empty patterns allowed. FFF path defaults to owned cwd and accepts only owned absolute/relative paths/globs such as **; no surrounding whitespace/BOM, tilde, .. component, backslash, NUL, braces, comma, ! or leading -. exclude is only a filter. Use actual FFF native search or Git ls-files for search/enumeration, NOT unavailable native grep/find/ls. Bash grep/find are DISALLOWED. Bash allows only bare pwd, cat/sha256sum ONE readable owned file, exact {shlex.join(['ls',str(self.reader)])} or {shlex.join(['ls','-la',str(self.reader)])} (no other directories/flags/recursive forms/bare ls), and readonly LOCAL GIT with optional -C exact cwd: log/blame/show/diff/status/rev-parse/ls-files/rev-list/diff-tree; standard readonly flags as enumerated in the Comment grammar below, plus branch --show-current/diff --check/status --short --branch. Git show HEAD:OWNED_RELATIVE_PATH or HEAD~:OWNED_RELATIVE_PATH permits exactly one operand/no options; no absolute/home/traversal/empty/dot components/backslash/control characters/extra colon/leading -. No application/test/measurement/config/network commands, delegation or wrappers. Every Bash argument is literal with the same forbidden characters as above. Native reads are limited to this reader, its actual task directory and the bundle; no tilde/NUL/symlink escape. Write/edit only canonical task report.md/result.json, never reader source or task identity; full-read nonce-bound brief before Bash/FFF/write/edit. read offset/limit may be null, otherwise positive integer; bash timeout null/omitted or finite positive. Before/after symlink-free reader trees must remain identical; this is post-execution auditing under a stable-tree assumption, not containment. How grants no exceptions to other roles. The controller, implementation and Comment retain their existing grammars without FFF or Bash ls. Trail has no FFF and permits only its separately declared four-directory Bash ls exception. Repeat these declarations in the actual How assignment.
Write {a / 'hillclimb/workload.json'} with architecture_sha256 (actual explanation file sha via sha256sum), dimensions (data size/history/state/concurrency), complaint, target_case, simpler_case, relevance. Then choose metric in {a / 'hillclimb/metric.json'} with metric='full_cli_wall_median_ms', direction='lower', target_reduction={self.args.target_reduction}, attempt_floor={self.args.attempt_floor}, attended=true, workload_sha256 (actual frozen workload hash). Do not choose a source-count proxy.

Read {self.probe} AND {self.engine} in full, uptime and nproc; read benchmark-checklist before running sensitivity. Native-write {a / 'hillclimb/vetting.json'} BEFORE measurements, keys claim, timed_surface, included_work, ignored_work, cache_state, production_config, limiter_plan, bounds, correctness, errors, repetitions. State startup+JSON+validation+complete reconciliation+output; private stdlib fixture, not an inferred production ceiling, warmed filesystem. Profiles separate from reported numbers; AB five per side with work/error/result checks.
Run sensitivity exactly:
{command('sensitivity')}
Read {d / 'sensitivity.json'} fully; small20refs60payments vs target2500refs6000payments must actually separate. If not, stop unresolved; do not change source or invent a win.
Freeze the validated harness/workload/metric via native-write {a / 'hillclimb/freeze.json'}, keys probe_sha256, engine_sha256, workload_sha256, metric_sha256, sensitivity_sha256 (actual sha256sum each), verdict='sensitive', host_observations={{'uptime':actual full stripped output,'nproc':actual integer}}, sensitivity_timings=actual sensitivity observation measurement.timings, work_counts={{'small':{{'references':20,'payments':60}},'target':{{'references':2500,'payments':6000}}}}, errors=0, limiter={{'function':'lookup_reference','calls':6000,'self_seconds':actual target profile lookup_self_seconds,'profile_self_seconds':actual target profile profile_self_seconds}}, bounds stating observed ranges and unestablished production ceiling.
Run baseline+green six-flow regression exactly:
{command('baseline')}
Read {d / 'baseline.json'} fully; baseline and gate must be green BEFORE any source edits.
Use original {b / 'show-me-your-work/scripts/log.sh'} through bash to create {a / 'trail/decision.tsv'} with one initial row: phase='frame', decision='freeze measured baseline', why=actual evidence reason, evidence='{d / 'baseline.json'}', result='tests green'. The lever already created Hillclimb's 9-column {a / 'hillclimb/decision.tsv'} header. Both outside Git, canonical 6-column trail remains unchanged.

For each sequential attempt N, read BOTH entire current decision.tsv logs BEFORE hypothesis; no no-op or canned attempts. Native-write {a / 'hillclimb/hypothesis-N.json'} with id=N, hypothesis (distinct concrete idea), mechanism (distinct implementation mechanism tied to How), mantras={json.dumps(list(perf.MANTRAS))}, mantra_index (1..7), earlier_applicability, architecture_sha256, simplification boolean. Borrow mantra ORDER, not Perf issue's early stop. If stalled/rejects, explicitly pivot category with grounds instead of padding. Do not repeat AST-identical candidates or unchanged source.
Snapshot exact last accepted state:
{command('begin', 1)}
For N>1 use the SAME literal command with --id N. Then native-write actual bounded role hillclimb assignment to {a / 'hillclimb/brief-N.md'}; unchanged configured worker {self.role_workers['hillclimb'][0]}, cwd {self.worktree}. One fresh task per attempt. Only that function, one mechanism, no commits or docs/config edits. Wait done/closed, read actual result/full report, inspect literal git -C {self.worktree} diff -- reconcile.py. Write {a / 'hillclimb/review-N.json'} with id, source_sha256, scope='reconcile_linear', public_contract, mechanism, concerns (string, 'none' if none).
Then evaluate snapshots, real alternating measurements and real six-flow regression:
{command('evaluate', 1)}
Read actual attempt-N/evaluation.json fully. The immutable evaluator supplies the actual verdict, not a requested outcome. Keep only a gap exceeding observed full ranges, or a strictly smaller AST holding overlapping median within 2% and explicit simplification=true. Invalid measurements/gates are rejected.
Native-write {a / 'hillclimb/decision-N.json'} with EXACT fields id,hypothesis,change,before,after,delta,tests,verdict,note: hypothesis/changed mechanism from hypothesis; medians from evaluation.observation.measurement (null if invalid), delta copied verbatim from evaluation.expected_delta (do not reconstruct/round it), tests='green' or 'failed', verdict and note EXACT evaluator verdict/reason.
If kept: normal Git add reconcile.py, then ONE normal perf(scope): ... commit for this accepted fix, explicit file only. If reverted: ONLY git -C {self.worktree} restore --source=HEAD -- reconcile.py; no reset/clean/broad restore, no rejected commit. Verify source bytes match exact prior accepted snapshot, clean tree.
Record the actual ledger row only AFTER keep commit or full revert:
{command('record', 1)}
Read actual record JSON and log.sh append exactly one row with phase='attempt-N', decision='kept attempt N' or 'reverted attempt N', why=the actual hypothesis, evidence='{d}/attempt-N/evaluation.json', result='tests green kept', 'tests green reverted', or 'tests failed reverted' as actually observed. Read both ledgers before next attempt. Never stack untested edits.
Use up to {self.args.max_attempts} real attempts. After at least {self.args.attempt_floor}, run final baseline-vs-current comparison:
{command('final')}
Read {d / 'final.json'}. Call final ONLY once when accumulated actual measurements reasonably support the predicate, or when reporting unresolved. If final predicate is false, stop unresolved; do not resample or change the predicate.
Write {a / 'hillclimb/stop.json'} keys target_reduction, attempt_floor, attempts, kept, reverted, reduction, predicate_met, reason, remaining_ideas, next_idea; bind all numbers to final.json; explain stall/pivot and cheapest remaining worthwhile idea. Do not claim success if predicate false. Never force kept/reverted counts.

Before handoff audit both logs against this run's actual native trace:
{command('review-ready')}
This freezes current scoped controller transcript and trail manifest under {d / 'review'}. Read actual manifest. Native-write {a / 'hillclimb/trail-brief.md'} for one bounded trail audit (not formal Interrogate), configured worker {self.args.trail_reviewer}, cwd {self.worktree}, readonly/no delegation. Explain choice is an explicit existing configured worker of a different actual model family; no applicable role is invented. Its actual authored brief must repeat four lines 'Trail-only literal ls: ABSOLUTE_DIRECTORY', one for each of {d}, {self.bundle}, {b}, and TASK_DIR (a declared literal placeholder resolved only to this task's actual task directory from the appended result path). This prospectively permits only ls with that single absolute operand, no flags/bare/recursive/multioperand/other-directory forms; all path components must be symlink-free. No trail FFF exception. Full-read actual nonce-bound brief before any Bash command. Task must read full frozen controller transcript (chunk native reads if needed), both full ledgers, review manifest, all hypotheses/decisions/evaluation+record artifacts, flag weak evidence/skipped verification/risky choices/gaps. Produce listed report.md containing only a JSON object with reviewed_model, reviewed_manifest_sha256, flags(list), blocking(list), scope='bounded trail audit', checked_distinct_mechanisms=true, checked_mantra_order=true, checked_plateau_response=true, checked_log_native_consistency=true ONLY when actually supported; otherwise flag and mark false; no fabricated 'no flags'. Actual native task session/model/effort is independently audited. Wait done/closed; read actual result and full JSON report. If blockers, stop unresolved; never hide or rerun the same audit to erase flags.
Native-write {a / 'hillclimb/attention.md'} beginning 'reviewed by <actual model>' followed by each actual flag, or 'No flags'. This leaf's Attention is mandatory.

If predicate met and audit nonblocking, read OpeningPR/deslop/no-comments/technical-writing/unslop/sequence. Write {self.worktree / 'PERFORMANCE.md'} EXACT final.json portable_report (no private paths). Prepare {a / 'pr-body.md'} original headings Why/What changed/Scope/[Tradeoffs]/Blast Radius/Verification, one exact primary_number from final.json and [measurement and iterations](PERFORMANCE.md) link. Preserve accepted fixes in original order. Before the final documentation commit and final diff review, complete ONE mandatory fresh CommentSicko phase, AFTER all measured attempts and the trail audit. Never spawn one per attempt. Read original {b / 'no-comments/SKILL.md'} and {b / 'pstack-herdr/references/agents/comment-sicko.md'} fully. Capture literal git -C {self.worktree} diff {self.base} -- reconcile.py and native-write its exact full output to {a / 'hillclimb/comment-diff.patch'}. Native-write {a / 'hillclimb/comment-scope.json'} with EXACT keys base='{self.base}', source='reconcile.py', report='PERFORMANCE.md', source_sha256, performance_sha256, final_sha256, ledger_sha256, trail_sha256, diff_sha256; bind actual final source, PERFORMANCE.md, {d / 'final.json'}, both decision.tsv files and patch via actual sha256sum single-file commands. These files remain frozen through review, final commit and PR.
Native-write {a / 'hillclimb/comment-brief.md'} first line Role: judgment and prose; configured worker {self.role_workers['judgment and prose'][0]}, cwd {self.worktree}, selected worker/reason, Do not delegate and absolute poteto-agent/poteto-mode paths as above. CommentSicko is the original instruction agent, NOT a different worker/model. Assign full native reads of original no-comments and comment-sicko instructions, current reconcile.py and PERFORMANCE.md, scope JSON, exact patch, final.json, both logs, attention.md and pr-body.md; include those exact absolute input paths. Do not restate or copy the agent's greeting or rules. The supplied bootstrap is required execution-boundary disclosure, not copied agent content; repeat it verbatim in the actual assignment: {COMMENT_BOOTSTRAP} It is report-only and may not change any source, report, logs, measurements, task identity or configuration. It may native-write only its canonical report.md, result.json and optional supplementary review.json in its actual task directory; list report.md and any supplementary review.json in result.files (unique entries in any order), write result last. Result.files may include its own result.json as well; optional review.json is supplementary, the typed report.md is authoritative. No extra tasks, retries or substitutions.
The CommentSicko brief must declare this complete tool grammar: seven native read/bash/write/edit/grep/find/ls only, never FFF/codemode/wrappers/delegation/network/forge/application or test/measurement execution. Native schemas read(path,offset?,limit?), write(path,content), edit(path,oldText,newText) OR edit(path,edits:[{{oldText,newText}}]), bash(command,timeout?), grep(pattern,path?,glob?,ignoreCase?,literal?,context?,limit?), find(pattern,path?,limit?), ls(path?,limit?); no extra fields. read offset/limit and bash timeout may be null; otherwise numbers positive (context nonnegative), booleans actual booleans, text fields strings. Read/search paths are only its own integration cwd, its actual task directory, supplied bundle, or these explicitly assigned external input files. Paths contain no tilde (~ or ~user), NUL or symlink escape; do not expand home paths. Git HEAD~ / HEAD^ revisions before -- are allowed. Bash literal commands reject newline, semicolon, pipe, ampersand, redirection, backtick, dollar or backslash even inside quotes. Accepted bash is bare pwd; cat FILE or sha256sum FILE for one assigned readable file; or readonly git [-C exact_owned_cwd] log/blame/show/diff/status/rev-parse/ls-files/rev-list/diff-tree with owned paths, base or HEAD ancestry, local hashes and these read-only flags only: --oneline,--follow,-p,--patch,--stat,--name-only,--name-status,--short,--porcelain,--porcelain=v1,--no-patch,--all,--reverse,--abbrev-commit,--no-renames,--no-color,--color=never,--show-toplevel,--show-prefix,--no-commit-id,-r,--stage,-s,--no-ext-diff,--no-textconv,--decorate,--graph; -N integer shorthand; -L numeric line[,numeric-or-+numeric]; -n/--max-count integer; --format/--pretty/-S/-G/--since/--until followed by query data; --max-count=/--format=/--pretty=/--since=/--until=/--unified=/--grep= values. No output/ext-diff/textconv/no-index execution. branch --show-current, diff --check and status --short --branch also allowed. Prefer native tools for other inspection. Native ls(path?,limit?) is supported. Read full nonce-bound brief before shell/write/edit use. No shell mutations; native task-artifact edits use nonempty unique exact oldText/newText matches. Mutations of each individual artifact must be sequential; independent report.md/review.json writes may share an assistant message. Finish all report/supplement mutations before the first result.json write/edit; native write followed by native edit is allowed and final replayed bytes must match the delivered file. Repeat this grammar in the brief; it applies to this readonly role, not permission to rerun any workflow.
Require canonical report.md to contain one JSON object: scope equals exact comment-scope.json; touched_files=[], deletion_count=0, restored_comments=[]; findings is a list of unique nonempty id, path (reconcile.py or PERFORMANCE.md), positive one-based line, symbol, kind (delete/keep/reshape/suppression/constraint), reason and exact nonempty evidence_excerpt on/including cited nonempty line; must_kill contains finding IDs; skips is a list of path/reason/evidence_excerpt objects from those same files; encoding_offers and open_work are lists. Findings must be truthful, never forced empty. Wait actual done and closed, then read actual nonce-bound result and ALL listed complete artifacts. Fully reread final source, PERFORMANCE.md, patch, final.json and both logs after report delivery. Record {a / 'hillclimb/comment-decision.json'}: scope_sha256, report_sha256, report_accepted, verdict pass/unresolved, dispositions (one per actual finding: id, decision accept/reject, concrete reason, actual scoped evidence_excerpt), deletion_count=0, restored_comments=[], flags=actual must_kill, skips=actual skips, reruns=0, architect_sketch=null, fixes=[], encoding_offers=actual offers, encodings=[], unenforced_constraints=[], open_work=actual open_work. Accept keeps only with proof; reject false findings only with concrete disproof. Accepted actionable findings, rejected whole report, required rerun/How/Why/Architect, encoding offer or open work leave this bounded run unresolved. Stop without final commit/PR; never fake zero findings, fix measured source, retry or pretend correction coverage. After dispatch no source/log/PERFORMANCE/scope/patch rewrites. Then review the complete actual PERFORMANCE.md documentation patch with literal git -C {self.worktree} diff, git -C {self.worktree} diff --cached, or git -C {self.worktree} diff --staged before making one separate normal docs(scope): ... commit of ONLY PERFORMANCE.md. Since accepted source fixes are already committed and PERFORMANCE.md is new, stage PERFORMANCE.md first and use the complete cached/staged diff; empty output or --stat/--check never counts as review. Final PR remains READY only after this actual nested stage succeeds.
Discover Origin with literal 'command -v origin', if present actually origin repo view {self.args.forge_repo} before choosing; prefer if resolves, otherwise gh. Record selected/reason in {a / 'forge-resolution.json'}. Push ONLY owned {self.branch}, create exactly one READY child PR explicit --base {self.args.base_ref}, --head {self.branch}, --body-file {a / 'pr-body.md'}, repo {self.args.forge_repo}. The exact ready create grammar is gh/origin pr create followed only by unique flag/value pairs in any order: --base {self.args.base_ref}, --head {self.branch}, --body-file {a / 'pr-body.md'}, --title NONEMPTY_TEXT, and optional --repo {self.args.forge_repo}; Origin additionally requires --status open (gh does not accept it). Base/head/body-file/title are mandatory, no duplicate flags, other file inputs, unknown options, positional operands or draft flags. Native readback same resolved forge with actual head/base/ready; no merges/automerge.
Final native-write {a / 'reply.md'}: metric+target, exact primary_number, attempts kept/reverted, each accepted fix one line, private decision.tsv path, grounded next idea, actual PR URL; end with an Attention section containing exact attention.md contents. Explicitly attended-only; all other playbooks/wake/cloud remain unverified.
"""

    def lever_invocation(self, command):
        argv = forge_helpers.literal(command)
        for mode in ('sensitivity', 'baseline', 'final', 'review-ready'):
            if argv == self.lever_argv(mode):
                return mode, None
        for number in range(1, self.args.max_attempts + 1):
            for mode in ('begin', 'evaluate', 'record'):
                if argv == self.lever_argv(mode, number):
                    return mode, number
        return None

    def local_read_git(self,argv,cwd,*,controller=False):
        if not argv or argv[0]!='git':
            return False
        rest=argv[1:]
        if rest[:1]==['-C']:
            if len(rest)<3 or rest[1]!=str(cwd):
                return False
            rest=rest[2:]
        if forge_helpers.local_git(argv,cwd,{self.base}) is not None:
            return True
        exact=(['branch','--show-current'],['diff','--check'],['status','--short','--branch'])
        if rest in exact:
            return True
        return controller and rest in (['diff','--cached'],['diff','--staged'])

    def worker_python_allowed(self,argv,role,cwd,task_dir,oracle_outputs):
        if not argv or argv[0] not in ('python','python3'):
            return False
        rest=argv[1:]
        if rest[:1]==['-B']:
            rest=rest[1:]
        if role=='bounded trail audit':
            return rest in (['-m','json.tool',str(task_dir/'report.md')],
                            ['-m','json.tool',str(task_dir/'result.json')])
        if role!='hillclimb':
            return False
        own=lambda raw,name:raw in (name,str(cwd/name))
        if len(rest)==2 and own(rest[0],'cli.py') and own(rest[1],'workload.json'):
            return True
        if len(rest)==3 and rest[:2]==['-m','py_compile'] and own(rest[2],'reconcile.py'):
            return True
        if len(rest)==3 and own(rest[0],'e2e_reconcile.py') and rest[1]=='--output':
            raw=rest[2]
            if not raw or '~' in raw or '\x00' in raw:
                return False
            output=Path(raw)
            if (not output.is_absolute() or raw!=str(output) or output.resolve()!=output or task_dir not in output.parents
                    or output==task_dir or output in oracle_outputs
                    or output.relative_to(task_dir).parts[0] in ('report.md','result.json','brief.md','task.json','state.json',
                                                                 'native-session-capture.json')
                    or any(part.is_symlink() for part in (output,*output.parents))):
                return False
            oracle_outputs.add(output)
            return True
        return False

    def controller_command_allowed(self, command):
        argv = forge_helpers.literal(command)
        if not argv:
            return False
        if argv in (['uptime'], ['nproc'], ['pwd'], ['command', '-v', 'origin']):
            return True
        if self.lever_invocation(command) is not None or self.gate_invocation(command) is not None:
            return True
        if argv[0] == 'bash':
            return (len(argv) == 8 and Path(argv[1]).resolve() == self.bundle / 'skills/show-me-your-work/scripts/log.sh'
                    and Path(argv[2]).resolve() == self.artifacts / 'trail/decision.tsv'
                    and (argv[3] == 'frame' and argv[7] == 'tests green'
                         or re.fullmatch(r'attempt-[1-9]\d*', argv[3])
                         and argv[7] in ('tests green kept','tests green reverted','tests failed reverted')))
        if argv[0] in ('python', 'python3'):
            return (len(argv) >= 3 and argv[1] == str(self.bundle / 'skills/herdr-orchestrator/scripts/horch.py')
                    and argv[2] == 'run')
        if argv[0] in ('cat', 'sha256sum'):
            return len(argv) == 2 and Path(argv[1]).is_absolute()
        if argv[:3] == ['git', '-C', str(self.worktree)] and len(argv) > 3:
            rest = argv[3:]
            if self.local_read_git(argv,self.worktree,controller=True):
                return True
            if rest[0]=='ls-remote':
                return rest[1:] in (['--heads','origin'],['--heads','origin','refs/heads/'+self.branch],
                                    ['--heads','origin','refs/heads/'+self.args.base_ref])
            if rest[0] == 'remote':
                return rest[1:] == ['get-url', 'origin']
            if rest[0] == 'add':
                return [word for word in rest[1:] if word != '--'] in (['reconcile.py'], ['PERFORMANCE.md'])
            if rest[0] == 'commit':
                return len(rest) == 3 and rest[1] == '-m' and bool(re.fullmatch(r'(?:perf|docs)\([a-z0-9_-]+\): [^\n]+', rest[2]))
            if rest[0] == 'restore':
                return rest[1:] == ['--source=HEAD', '--', 'reconcile.py']
            if rest[0] == 'push':
                return rest[1:] in (['origin', self.branch], ['-u', 'origin', self.branch],
                                    ['--set-upstream', 'origin', self.branch])
            return False
        if argv[0] in ('gh', 'origin'):
            if argv[1:3] in (['pr', 'view'], ['pr', 'list'], ['repo', 'view']):
                return True
            if argv[1:3]!=['pr','create']:
                return False
            expected={'--base':self.args.base_ref,'--head':self.branch,
                      '--body-file':str(self.artifacts/'pr-body.md'),'--repo':self.args.forge_repo}
            if argv[0]=='origin':
                expected['--status']='open'
            operands=argv[3:]
            if len(operands)%2:
                return False
            observed={}
            for flag,value in zip(operands[::2],operands[1::2]):
                if flag in observed or flag not in {*expected,'--title'}:
                    return False
                if flag=='--title':
                    if not value.strip():
                        return False
                elif value!=expected[flag]:
                    return False
                observed[flag]=value
            required={'--base','--head','--body-file','--title'}
            if argv[0]=='origin':
                required.add('--status')
            return required<=set(observed)
        return False

    def lever_event(self, events, mode, number=None):
        matching = [e for e in events if e['name'] == 'bash'
                    and forge_helpers.literal(e['args'].get('command', '')) == self.lever_argv(mode, number)]
        self.check('one_real_lever_' + mode + '_' + str(number), len(matching) == 1)
        event = matching[0]
        value = json.loads(event['output'])
        path = (self.directory / ('attempt-' + str(number)) /
                {'begin':'begin.json','evaluate':'evaluation.json','record':'record.json'}[mode]
                if number is not None else self.directory / (
                    'review/manifest.json' if mode == 'review-ready' else mode + '.json'))
        self.check('native_lever_retained_identity_' + mode + '_' + str(number),
                   value == core.read_json(path) and value.get('nonce') == self.nonce and value.get('mode') == mode)
        return value, event

    def audit_measurement(self, observed, directory, roots, *, contrast=False):
        self.check('measurement_exists_' + directory.name, observed.get('valid') is True)
        value = observed['measurement']
        self.check('measurement_samples_actual_work_' + directory.name, measured(value)
                   and value.get('nonce') == self.nonce
                   and value == core.read_json(directory / 'observation.json')
                   and observed['sha256'] == core.sha(directory / 'observation.json'))
        import pstats
        for label, root in roots.items():
            data = core.read_json(root / 'workload.json')
            from decimal import Decimal
            expected = {'references':len(data['references']), 'payments':len(data['payments']), 'errors':0,
                        'total_units':int(sum((Decimal(dict(data['references'])[k])*Decimal(v)
                                              for k,v in data['payments']), Decimal(0)))}
            self.check('workload_result_and_source_' + directory.name + '_' + label,
                       value['sources'][label] == {name:core.sha(root / name) for name in FILES}
                       and all(row['result'] == expected for row in value['observations'] if row['side'] == label)
                       and value['profiles'][label]['result'] == expected)
            profile, frames = directory / (label + '.prof'), directory / (label + '-frames.json')
            stats = pstats.Stats(str(profile)).stats
            rows = [{'file':file,'line':line,'function':name,'calls':calls,
                     'self_seconds':own,'cumulative_seconds':cumulative}
                    for (file,line,name),(_,calls,own,cumulative,_) in stats.items()]
            rows.sort(key=lambda r:r['self_seconds'], reverse=True)
            summary = value['profiles'][label]
            source = str(root / 'reconcile.py')
            self.check('actual_binary_profile_' + directory.name + '_' + label,
                       core.sha(profile) == summary['profile_sha256'] and core.sha(frames) == summary['frames_sha256']
                       and core.read_json(frames) == rows
                       and summary['lookup_calls'] == sum(r['calls'] for r in rows if r['file']==source and r['function']=='lookup_reference')
                       and summary['reconcile_calls'] == sum(r['calls'] for r in rows if r['file']==source and r['function']=='reconcile_linear')
                       and summary['lookup_self_seconds'] == sum(r['self_seconds'] for r in rows if r['file']==source and r['function']=='lookup_reference')
                       and summary['profile_self_seconds'] == sum(r['self_seconds'] for r in rows)
                       and summary['reconcile_calls'] == 1)
        if not contrast:
            self.check('same_frozen_workload_' + directory.name, value['sources']['before']['workload.json']
                       == value['sources']['after']['workload.json'] == hashlib.sha256(perf.fixture_files()['workload.json'].encode()).hexdigest())
        return value

    def independent_measure(self, before, after, label):
        output = self.directory / ('independent-' + label)
        argv = [sys.executable, '-B', self.engine, '--mode', 'compare', '--before', before, '--after', after,
                '--output', output, '--nonce', self.nonce]
        try:
            value = json.loads(self.call(argv))
        except Failure:
            return {'valid':False}, output
        return {'valid':True,'measurement':value,'sha256':core.sha(output / 'observation.json')}, output

    def independent_gate(self, root, label):
        destination = self.directory / ('independent-gate-' + label)
        try:
            value = json.loads(self.call([sys.executable, '-B', root / 'e2e_reconcile.py', '--output', destination]))
        except Failure:
            return False
        receipt = core.read_json(destination / 'evidence.json')
        return value == {'verdict':'pass','flows':6} and receipt.get('verdict') == 'pass' and all(
            row.get('ok') is True for row in receipt.get('flows', [])) and len(receipt.get('flows', [])) == 6

    def classify(self, evaluation, before, after, hypothesis):
        if not evaluation['observation'].get('valid') or not evaluation['tests']['valid']:
            return 'reverted', 'invalid measurement, regression gate, or function scope'
        scope = (all(core.sha(before / name) == core.sha(after / name) for name in FILES if name != 'reconcile.py')
                 and perf.outside_function((before / 'reconcile.py').read_text()) ==
                     perf.outside_function((after / 'reconcile.py').read_text())
                 and self.function_ast(before) != self.function_ast(after))
        if not scope:
            return 'reverted', 'invalid measurement, regression gate, or function scope'
        metric = evaluation['observation']['measurement']['timings']
        if metric['after']['maximum_ms'] < metric['before']['minimum_ms']:
            return 'kept', 'improvement exceeds the complete observed range'
        count = lambda root:sum(1 for _ in ast.walk(ast.parse((root / 'reconcile.py').read_text())))
        if (hypothesis.get('simplification') is True and count(after)<count(before)
                and metric['after']['minimum_ms'] <= metric['before']['maximum_ms']
                and metric['before']['minimum_ms'] <= metric['after']['maximum_ms']
                and metric['after']['median_ms'] <= metric['before']['median_ms']*1.02):
            return 'kept', 'strict AST simplification holds the metric within overlapping noise'
        return 'reverted', 'no improvement beyond noise and no qualifying simplification'

    @staticmethod
    def function_ast(root):
        node = next(n for n in ast.parse((root / 'reconcile.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_linear')
        return ast.dump(node, include_attributes=False)

    def controller_assignment(self, task):
        """Strip only Horch's exact nonce-bound appended suffix, never a heading."""
        retained = Path(task['brief_path']).read_text()
        suffix = '\n\n' + horch.WORKER_RULES.format(
            result_path=Path(task['task_dir'])/'result.json',task_id=task['task_id'],nonce=task['nonce'])
        self.check('retained_brief_exact_horch_suffix', retained.endswith(suffix))
        return retained[:-len(suffix)]

    def bind_brief(self, events, all_events, task, launch, source, role):
        writes = core.workflow_writes(events, self.worktree, source, before=launch['call_row'], final=True)
        argv = core.literal_horch_command(launch['name'], launch['args'], self.worktree, self.bundle)
        retained = Path(task['brief_path'])
        expected = source.read_text().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
            result_path=Path(task['task_dir'])/'result.json',task_id=task['task_id'],nonce=task['nonce'])
        assignment = self.controller_assignment(task)
        self.check('bound_native_brief_' + source.name, bool(writes) and argv.count('--brief') == 1
                   and Path(argv[argv.index('--brief')+1]).resolve() == source
                   and retained.resolve() == Path(task['task_dir'])/'brief.md' and retained.read_text() == expected
                   and re.match(r'\A\s*Role: '+re.escape(role)+r'(?:\r?\n|\Z)', assignment)
                   and task['worker'] in assignment and re.search(r'reason|because', assignment, re.I)
                   and all(word in assignment for word in ('Do not delegate',
                       str(self.bundle/'skills/pstack-herdr/references/agents/poteto-agent.md'),
                       str(self.bundle/'skills/poteto-mode/SKILL.md')))
                   and all(e['result_row'] < launch['call_row'] for e in all_events
                       if e['name'] in ('write','edit') and isinstance(e['args'].get('path'),str)
                       and (self.worktree/e['args']['path']).resolve()==source))
        return writes

    def audit_task_native(self, task):
        spec = self.config['workers'][task['worker']]
        session = self.task_sessions.get(task['task_id'], {})
        self.check('task_native_session_captured', bool(session.get('value')))
        cwd = Path(task['cwd']).resolve()
        encoded = '--' + re.sub(r'[/\\\\:]', '-', str(cwd).lstrip('/\\\\')) + '--'
        directory = self.agent_dir/'sessions'/encoded
        value = session['value']
        if session.get('kind') == 'path':
            supplied = Path(value).expanduser().resolve()
            self.check('task_native_owned_cwd_location', supplied.parent == directory)
            identity = supplied.stem.rsplit('_', 1)[-1]
        else:
            identity = value
        try:
            canonical = str(uuid.UUID(identity))
        except (ValueError, AttributeError):
            raise Failure('worker_session_uuid_unavailable') from None
        self.check('task_native_canonical_uuid', canonical == identity)
        # Never enumerate another cwd or UUID, even when this lookup fails.
        candidates = list(directory.glob('*_' + canonical + '.jsonl'))
        self.check('task_native_owned_path_unambiguous', len(candidates) == 1
                   and (session.get('kind') != 'path' or candidates[0].resolve() == supplied))
        path = candidates[0]
        assignment=self.controller_assignment(task)
        role_match = re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)', assignment)
        role = role_match[1] if role_match else None
        if role == 'how explainer':
            return path,self.audit_how_native(task,path,spec,assignment)
        audit = core.audit_pi(path, session, Path(task['cwd']).resolve(), core.stamp(task['created_at']),
                              spec, [], [], [], self.bundle)
        self.check('actual_task_native_model_effort_tools', all(row['ok'] for row in audit['checks']))
        if role == 'judgment and prose':
            self.audit_comment_native(task, path)
            return path, audit
        if role=='bounded trail audit':
            self.check('trail_only_ls_contract_declared', all('Trail-only literal ls: '+str(path) in assignment
                for path in (self.directory,self.bundle,self.bundle/'skills'))
                and 'Trail-only literal ls: TASK_DIR' in assignment)
        writer=role == 'hillclimb'
        task_dir=Path(task['task_dir']).resolve()
        native_events=self.native_events(path,include_errors=True)
        self.check('bounded_worker_native_write_scope',all(
            isinstance(e['args'].get('path'),str) and (
                task_dir in (Path(task['cwd'])/e['args']['path']).resolve().parents
                or writer and (Path(task['cwd'])/e['args']['path']).resolve()==self.worktree/'reconcile.py')
            for e in native_events if e['name'] in ('write','edit')))
        extra={Path(raw) for raw in re.findall(r'^Input artifact: (.+)$',assignment,re.M)}
        def readable(raw):
            if not isinstance(raw,str) or not raw or '~' in raw or '\x00' in raw:
                return False
            target=(cwd/raw).resolve()
            return target in extra or any(target==root or root in target.parents for root in (cwd,task_dir,self.bundle))
        oracle_outputs=set()
        for event in native_events:
            if event['name']!='bash':
                continue
            argv=forge_helpers.literal(event['args'].get('command',''))
            allowed=False
            if argv:
                binary=argv[0]
                if argv==['pwd']:
                    allowed=True
                elif binary=='cat':
                    allowed=len(argv)==2 and readable(argv[1])
                elif binary=='sha256sum':
                    allowed=(1<=len(argv[1:])<=(3 if role=='bounded trail audit' else 1)
                             and all(not raw.startswith('-') and readable(raw) for raw in argv[1:]))
                elif binary=='wc' and role=='bounded trail audit':
                    allowed=(len(argv)>=3 and argv[1] in ('-l','-c')
                             and 1<=len(argv[2:])<=(4 if argv[1]=='-l' else 1)
                             and all(not raw.startswith('-') and readable(raw)
                                     and (argv[1]!='-l' or (cwd/raw).resolve() in extra) for raw in argv[2:]))
                elif binary=='ls' and role=='bounded trail audit':
                    allowed=(len(argv)==2 and argv[0]=='ls' and Path(argv[1]) in
                             {self.directory,self.bundle,self.bundle/'skills',task_dir}
                             and Path(argv[1]).is_absolute() and Path(argv[1]).resolve()==Path(argv[1])
                             and not any(part.is_symlink() for part in (Path(argv[1]),*Path(argv[1]).parents)))
                elif binary=='git':
                    allowed=self.local_read_git(argv,cwd)
                elif binary in ('python','python3'):
                    allowed=self.worker_python_allowed(argv,role,cwd,task_dir,oracle_outputs)
            self.check('bounded_worker_no_native_delegation_or_wrappers',allowed)
        return path, audit

    def audit_how_native(self, task, path, spec, assignment):
        """Post-execution How-only FFF audit; no pre-execution containment claim."""
        cwd, task_dir = Path(task['cwd']).resolve(),Path(task['task_dir']).resolve()
        self.check('how_exact_configured_reader', cwd==self.reader
                   and task['worker']==self.role_workers['how explainer'][0])
        binding=core.read_json(task_dir/'native-session-capture.json')
        saved=self.directory/'how-worker-native.jsonl'
        shutil.copy2(path,saved)
        rows=[json.loads(line) for line in saved.read_text().splitlines() if line.strip()]
        header=rows[0] if rows else {}
        self.check('how_live_native_binding', not path.is_symlink() and core.sha(path)==core.sha(saved)
                   and header.get('type')=='session' and header.get('version')==3
                   and header.get('id')==path.stem.rsplit('_',1)[-1]
                   and Path(header.get('cwd','')).resolve()==cwd
                   and binding.get('session')==self.task_sessions[task['task_id']]
                   and binding.get('task_sha256')==core.sha(task_dir/'task.json')
                   and binding.get('brief_sha256')==core.sha(Path(task['brief_path']))
                   and core.stamp(task['created_at'])<=core.stamp(header['timestamp'])<=binding['captured_at'])
        after=forge_helpers.reader_tree(cwd)
        (self.directory/'how-tree-after.json').write_text(json.dumps({
            'descriptor':after,'captured_at':time.time()},indent=2)+'\n')
        self.check('how_reader_tree_symlink_free_and_stable', self.how_tree_before is not None
                   and self.how_tree_before==after and after['symlink_count']==0
                   and self.how_tree_captured_at<=core.stamp(task['created_at']))
        self.check('how_exception_declared_in_actual_brief', all(word in assignment for word in (
            'fffind','ffgrep','cursor','exclude','caseSensitive','context',str(cwd)))
                   and shlex.join(['ls',str(cwd)]) in assignment)
        def readable(raw):
            if not isinstance(raw,str) or not raw or '~' in raw or '\x00' in raw:
                return False
            target=(cwd/raw).resolve()
            return any(target==root or root in target.parents for root in (cwd,task_dir,self.bundle))
        def git_read(argv):
            if forge_helpers.local_git(argv,cwd,{self.base}) is not None:
                return True
            prefix=['git','-C',str(cwd)] if argv[:3]==['git','-C',str(cwd)] else ['git']
            rest=argv[len(prefix):]
            if rest in (['branch','--show-current'],['diff','--check'],['status','--short','--branch']):
                return argv[:len(prefix)]==prefix
            if len(rest)==2 and rest[0]=='show':
                match=re.fullmatch(r'HEAD~?:(.+)',rest[1])
                if match:
                    raw=match[1]
                    return (not raw.startswith(('/','-')) and not any(c in raw for c in ('~','\\',':'))
                            and not any(ord(c)<32 or ord(c)==127 for c in raw)
                            and all(part not in ('','.','..') for part in raw.split('/'))
                            and (cwd/raw).resolve().is_relative_to(cwd))
            return False
        schemas={'read':{'path','offset','limit'},'write':{'path','content'},
            'edit':{'path','oldText','newText','edits'},'bash':{'command','timeout'},
            'fffind':{'pattern','path','exclude','limit'},
            'ffgrep':{'pattern','path','exclude','limit','caseSensitive','context'}}
        pending,ids,call_ids,last,models,efforts={},set(),set(),None,set(),set()
        for index,row in enumerate(rows[1:],1):
            identity=row.get('id')
            self.check('how_native_unbranched_parent_chain', bool(identity) and identity not in ids
                       and identity!=header['id'] and row.get('parentId')==last)
            ids.add(identity);last=identity
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
                    self.check('how_all_attempt_tool_schema', name in schemas and isinstance(args,dict)
                               and set(args)<=schemas[name] and bool(call_id) and call_id not in call_ids)
                    call_ids.add(call_id);pending[call_id]=name
                    for key,minimum in (('offset',1),('limit',1),('context',0)):
                        self.check('how_numeric_schema',key not in args or name=='read' and args[key] is None
                                   or type(args[key]) is int and args[key]>=minimum)
                    if name in ('fffind','ffgrep'):
                        raw=args.get('path','.')
                        self.check('how_fff_typed_owned_query', isinstance(args.get('pattern'),str)
                                   and isinstance(raw,str) and bool(raw) and raw==raw.strip() and '\ufeff' not in raw
                                   and not any(c in raw for c in ('\\','~','\x00','{','}',',','!'))
                                   and '..' not in raw.split('/') and not raw.startswith('-')
                                   and (cwd/raw).resolve().is_relative_to(cwd))
                        self.check('how_fff_filter_schema', 'exclude' not in args or isinstance(args['exclude'],str)
                                   or isinstance(args['exclude'],list) and all(isinstance(x,str) for x in args['exclude']))
                        self.check('how_fff_case_schema','caseSensitive' not in args or type(args['caseSensitive']) is bool)
                    elif name=='read':
                        self.check('how_owned_native_read',readable(args.get('path')))
                    elif name in ('write','edit'):
                        raw=args.get('path')
                        self.check('how_no_reader_tree_or_identity_write_attempt', isinstance(raw,str)
                                   and '~' not in raw and '\x00' not in raw
                                   and (cwd/raw).resolve() in {task_dir/'report.md',task_dir/'result.json'})
                        if name=='write':
                            self.check('how_native_write_schema',set(args)=={'path','content'} and isinstance(args['content'],str))
                        else:
                            edits=args.get('edits',[args])
                            self.check('how_native_edit_schema',set(args)==({'path','edits'} if 'edits' in args
                                       else {'path','oldText','newText'}) and isinstance(edits,list) and bool(edits)
                                       and all(isinstance(edit,dict) and set(edit)==({'oldText','newText'} if 'edits' in args
                                           else {'path','oldText','newText'}) and isinstance(edit.get('oldText'),str)
                                           and bool(edit['oldText']) and isinstance(edit.get('newText'),str) for edit in edits))
                    else:
                        argv=forge_helpers.literal(args.get('command',''))
                        allowed=(argv==['pwd'] or argv in (['ls',str(cwd)],['ls','-la',str(cwd)])
                                 or len(argv)==2 and argv[0] in ('cat','sha256sum') and readable(argv[1])
                                 or bool(argv) and argv[0]=='git' and git_read(argv))
                        self.check('how_no_bash_search_execution_or_wrappers',allowed)
                        timeout=args.get('timeout')
                        self.check('how_timeout_schema',timeout is None or type(timeout) in (int,float)
                                   and 0<timeout<float('inf'))
            elif message.get('role')=='toolResult':
                call_id=message.get('toolCallId')
                self.check('how_native_result_bound',call_id in pending and message.get('toolName')==pending[call_id]
                           and type(message.get('isError')) is bool)
                del pending[call_id]
        self.check('how_all_calls_resolved',not pending)
        self.check('how_actual_configured_model_effort',bool(models) and all(model==spec['model']
                   and (not spec.get('provider') or provider==spec['provider']) for provider,model in models)
                   and (not spec.get('effort') or efforts=={spec['effort']}))
        calls=self.native_events(saved,include_errors=True)
        successful=self.native_events(saved)
        brief_reads=core.workflow_reads(successful,cwd,Path(task['brief_path']))
        self.check('how_nonce_brief_read_before_active_tools',bool(brief_reads)
                   and task['nonce'] in Path(task['brief_path']).read_text()
                   and all(any(read['result_row']<call['call_row'] for read in brief_reads)
                           for call in calls if call['name'] in ('bash','fffind','ffgrep','write','edit')))
        return {'checks':[{'name':'how_scoped_native_identity_tools_tree_model','ok':True}],
                'sha256':core.sha(saved),'format':'pi-session-v3','harness':'pi','model':spec['model'],
                'effort':spec.get('effort'),'tool_calls':len(calls),
                'session_id_sha256':hashlib.sha256(header['id'].encode()).hexdigest()}

    def audit_comment_native(self, task, path):
        """Audit all attempts of the readonly nested phase; this is not a sandbox."""
        cwd, task_dir = self.worktree, Path(task['task_dir']).resolve()
        binding = core.read_json(task_dir / 'native-session-capture.json')
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        header = rows[0]
        self.check('comment_live_session_binding', binding.get('session') == self.task_sessions[task['task_id']]
                   and binding.get('task_sha256') == core.sha(task_dir / 'task.json')
                   and binding.get('brief_sha256') == core.sha(Path(task['brief_path']))
                   and core.stamp(task['created_at']) <= core.stamp(header['timestamp']) <= binding['captured_at']
                   and header.get('id') == path.stem.rsplit('_',1)[-1]
                   and Path(header.get('cwd','')).resolve() == cwd and not path.is_symlink())
        saved = self.directory / 'comment-worker-native.jsonl'
        shutil.copy2(path, saved)
        self.check('comment_native_retained_stable', core.sha(path) == core.sha(saved))
        assignment = self.controller_assignment(task)
        inputs = {self.artifacts / ('hillclimb/' + name) for name in (
            'comment-scope.json','comment-diff.patch','decision.tsv','attention.md')}
        inputs |= {self.artifacts / 'trail/decision.tsv', self.artifacts / 'pr-body.md',
                   self.directory / 'final.json'}
        self.check('comment_tool_only_bootstrap_assigned', COMMENT_BOOTSTRAP in assignment
                   and 'Yes... Ha ha ha... Yes!' not in assignment)
        self.check('comment_explicit_input_assignment', all(str(item) in assignment for item in inputs)
                   and all(str(self.bundle / 'skills' / item) in assignment for item in (
                       'no-comments/SKILL.md','pstack-herdr/references/agents/comment-sicko.md')))
        def readable(raw):
            if not isinstance(raw,str) or not raw or '~' in raw or '\x00' in raw:
                return False
            target = (cwd / raw).resolve()
            return (any(target == root or root in target.parents for root in (cwd,task_dir,self.bundle))
                    or target in inputs and str(target) in assignment)
        allowed_artifacts = {task_dir / name for name in ('report.md','result.json','review.json')}
        schemas = {'read': {'path','offset','limit'}, 'write': {'path','content'},
            'edit': {'path','oldText','newText','edits'}, 'bash': {'command','timeout'},
            'grep': {'pattern','path','glob','ignoreCase','literal','context','limit'},
            'find': {'pattern','path','limit'}, 'ls': {'path','limit'}}
        calls = self.native_events(saved,include_errors=True)
        successful = self.native_events(saved)
        artifacts, last_artifact_result, artifact_mutations = {}, {}, {}
        for event in calls:
            name, args = event['name'],event['args']
            self.check('comment_tool_schema', name in schemas and isinstance(args,dict) and set(args) <= schemas[name])
            for key, minimum in (('offset',1),('limit',1),('context',0)):
                self.check('comment_numeric_schema', key not in args or name == 'read' and args[key] is None
                           or type(args[key]) is int and args[key] >= minimum)
            for key in ('ignoreCase','literal'):
                self.check('comment_boolean_schema', key not in args or type(args[key]) is bool)
            if name in ('read','grep','find','ls'):
                self.check('comment_readonly_owned_paths', readable(args.get('path','.' if name != 'read' else None)))
                for key in ('pattern','glob'):
                    self.check('comment_search_string_schema', key not in args or isinstance(args[key],str))
                self.check('comment_search_required_pattern', name not in ('grep','find') or 'pattern' in args)
            elif name in ('write','edit'):
                raw = args.get('path')
                self.check('comment_canonical_artifact_write_only', isinstance(raw,str) and '~' not in raw
                           and '\x00' not in raw and (cwd/raw).resolve() in allowed_artifacts)
                target = (cwd/raw).resolve()
                self.check('comment_same_artifact_mutations_serial', last_artifact_result.get(target,-1) < event['call_row'])
                last_artifact_result[target] = event['result_row']
                if name == 'write':
                    self.check('comment_write_schema', set(args)=={'path','content'} and isinstance(args['content'],str))
                    candidate = args['content']
                else:
                    edits = args.get('edits',[args])
                    self.check('comment_edit_schema', set(args) == ({'path','edits'} if 'edits' in args else {'path','oldText','newText'})
                               and isinstance(edits,list) and bool(edits))
                    candidate = artifacts.get(target,'')
                    for edit in edits:
                        self.check('comment_unique_exact_replacement', isinstance(edit,dict)
                                   and set(edit)==({'oldText','newText'} if 'edits' in args else {'path','oldText','newText'})
                                   and isinstance(edit.get('oldText'),str) and bool(edit['oldText'])
                                   and isinstance(edit.get('newText'),str) and candidate.count(edit['oldText']) == 1)
                        candidate = candidate.replace(edit['oldText'],edit['newText'],1)
                if event['successful']:
                    artifacts[target] = candidate
                    artifact_mutations.setdefault(target,[]).append(event)
            elif name == 'bash':
                argv = forge_helpers.literal(args.get('command',''))
                allowed = argv == ['pwd'] or (len(argv)==2 and argv[0] in ('cat','sha256sum') and readable(argv[1]))
                if argv and argv[0] == 'git':
                    # local_git rejects output, remote, external paths and home expansion;
                    # it preserves HEAD ancestry and data-valued format/search options.
                    allowed = forge_helpers.local_git(argv,cwd,{self.base}) is not None
                    allowed = allowed or argv in ([ 'git','-C',str(cwd),'branch','--show-current'],
                        ['git','branch','--show-current'],['git','-C',str(cwd),'diff','--check'],
                        ['git','diff','--check'],['git','-C',str(cwd),'status','--short','--branch'],
                        ['git','status','--short','--branch'])
                self.check('comment_no_execution_mutation_delegation_or_wrapper', allowed)
                timeout=args.get('timeout')
                self.check('comment_timeout_schema', timeout is None or type(timeout) in (int,float)
                           and 0 < timeout < float('inf'))
        brief_reads = core.workflow_reads(successful,cwd,Path(task['brief_path']))
        self.check('comment_nonce_brief_before_active_tools', bool(brief_reads)
                   and task['nonce'] in Path(task['brief_path']).read_text()
                   and all(any(e['result_row'] < call['call_row'] for e in brief_reads)
                           for call in calls if call['name'] in ('write','edit','bash')))
        report_mutations = artifact_mutations.get(task_dir/'report.md',[])
        result_mutations = artifact_mutations.get(task_dir/'result.json',[])
        self.check('comment_native_artifacts_final_replay', bool(report_mutations and result_mutations)
                   and artifacts.get(task_dir/'report.md') == (task_dir/'report.md').read_text()
                   and artifacts.get(task_dir/'result.json') == (task_dir/'result.json').read_text()
                   and all(event['result_row'] < result_mutations[0]['call_row'] for event in calls
                           if event['name'] in ('write','edit') and (cwd/event['args']['path']).resolve()!=task_dir/'result.json'))
        self.check('comment_supplementary_artifacts_bound', all(target.is_file() and candidate == target.read_text()
                   and (target.name != 'review.json' or 'review.json' in core.read_json(task_dir/'result.json').get('files',[]))
                   for target,candidate in artifacts.items()))
        required = list(inputs) + [cwd/'reconcile.py',cwd/'PERFORMANCE.md'] + [self.bundle/'skills'/item for item in (
            'no-comments/SKILL.md','pstack-herdr/references/agents/comment-sicko.md')]
        before = min(event['call_row'] for event in report_mutations)
        self.check('comment_full_original_guides_and_final_scope', all(self.complete_native_read(
            [event for event in successful if event['result_row'] < before],cwd,item) for item in required))
        first_text_row, first_text = next(((index,block['text'].strip()) for index,row in enumerate(rows[1:],1)
            if row.get('message',{}).get('role')=='assistant'
            for block in row['message'].get('content',[]) if block.get('type')=='text'
            and isinstance(block.get('text'),str) and block['text'].strip()),(len(rows),None))
        for resource in ('no-comments/SKILL.md','pstack-herdr/references/agents/comment-sicko.md'):
            self.check('comment_original_loaded_before_any_natural_text', self.complete_native_read(
                [event for event in successful if event['name']=='read' and event['result_row']<first_text_row],
                cwd,self.bundle/'skills'/resource))
        self.check('comment_original_whole_first_text', first_text == 'Yes... Ha ha ha... Yes!')

    def verify_tasks(self, rows):
        self.check('all_actual_tasks_done_closed', bool(rows) and all(
            state.get('state')=='done' and state.get('closed') is True for _,state in rows))
        for task,_ in rows:
            spec = self.config['workers'].get(task.get('worker'),{})
            self.check('task_config_argv_nonce_identity', task.get('harness')==spec.get('harness')
                       and task.get('model')==spec.get('model')
                       and task.get('argv')==horch.launch_args(spec,Path(task['task_dir']))
                       and Path(task['result_path']).resolve()==Path(task['task_dir'])/'result.json'
                       and horch.validate_result(core.read_json(Path(task['result_path'])),task)=='valid'
                       and core.read_json(Path(task['result_path'])).get('status')=='completed')
            self.task_facts.append({'worker_sha256':hashlib.sha256(task['worker'].encode()).hexdigest(),
                'harness':spec.get('harness'),'model':spec.get('model'),'effort':spec.get('effort'),
                'task_sha256':core.sha(Path(task['task_dir'])/'task.json'),
                'result_sha256':core.sha(Path(task['result_path'])),'nonce_validated':True})

    def report(self, events, task, delivery, before=float('inf')):
        reads = core.workflow_report_reads(events,task,self.worktree,delivery,before=before)
        self.check('delivered_full_worker_report',bool(reads))
        self.check('actual_result_after_delivery',bool(core.workflow_reads(
            events,self.worktree,Path(task['result_path']),after=delivery['result_row'],before=before)))
        return reads

    def gated_deliveries(self,tasks,events,all_events):
        """Independently bind safe waits and reject all premature/raw access attempts."""
        native=next((self.directory/'native-sessions').glob('*.jsonl'))
        rows=[json.loads(line) for line in native.read_text().splitlines() if line.strip()]
        launches,direct=core.workflow_launches(events,tasks,self.worktree,self.bundle)
        self.check('no_raw_horch_wait_delivery',not direct)
        deliveries,gates={},{}
        for task in tasks:
            task_id=task['task_id'];path=self.gate_home/'gates'/(task_id+'.json')
            facts=hill_scope_audit(self.gate_policy,task_id)
            self.check('independent_worker_gate_replay',path.is_file() and core.read_json(path)==facts)
            gates[task_id]=facts
            self.check('one_owned_launch_before_gate',task_id in launches)
            for event in events:
                invocation=self.gate_invocation(event['args'].get('command','')) if event['name']=='bash' else None
                if invocation is None or invocation[0]!=task_id:
                    continue
                seconds=invocation[1];value=json.loads(event['output'])
                receipts=[core.read_json(item) for item in (self.gate_home/'waits'/task_id).glob('*.json')]
                matching=[raw for raw in receipts if raw['returncode']==0
                    and raw['argv'][1:]==[str(self.bundle/'skills/herdr-orchestrator/scripts/horch.py'),
                                         'wait',task_id,'--max-seconds',str(seconds)]
                    and core.stamp(rows[event['call_row']]['timestamp'])<=raw['started_at']
                    and raw['completed_at']<=core.stamp(rows[event['result_row']]['timestamp'])]
                self.check('safe_delivery_real_private_wait',bool(matching)
                           and launches[task_id]['result_row']<event['call_row'])
                if value.get('verdict')=='pending':
                    self.check('pending_safe_metadata_only',value=={'schema':'hillclimb/safe-delivery/v1',
                        'task_id':task_id,'verdict':'pending','state':'pending','closed':False})
                    continue
                expected={'schema':'hillclimb/safe-delivery/v1','task_id':task_id,'verdict':'pass','state':'done',
                    'closed':True,'gate_sha256':core.sha(path),'outputs':list(facts['outputs']),
                    'native_sha256':facts['native_sha256']}
                self.check('safe_pass_metadata_exact',value==expected and task_id not in deliveries)
                witnessed=[]
                for raw in matching:
                    observed=[json.loads(line) for line in raw['stdout'].splitlines() if line.strip()]
                    if (len(observed)==1 and observed[0].get('task_id')==task_id and observed[0].get('state')=='done'
                            and observed[0].get('closed') is True and observed[0].get('result_path')==task['result_path']):
                        witnessed.append(raw)
                self.check('actual_done_closed_before_pass_gate',bool(witnessed)
                    and path.stat().st_mtime<=core.stamp(rows[event['result_row']]['timestamp'])
                    and any(raw['completed_at']<=path.stat().st_mtime for raw in witnessed))
                deliveries[task_id]=event
            self.check('each_worker_has_safe_delivery',task_id in deliveries)
        self.check('all_launches_safely_delivered',set(deliveries)==set(launches)=={task['task_id'] for task in tasks})
        for task in tasks:
            binding=core.read_json(self.gate_home/'bindings'/(task['task_id']+'.json'))
            self.check('all_prior_workers_gated_before_dependent_launch',all(
                dep['task_id'] in deliveries and deliveries[dep['task_id']]['result_row']<launches[task['task_id']]['call_row']
                and core.sha(self.gate_home/'gates'/(dep['task_id']+'.json'))==dep['gate_sha256']
                for dep in binding['dependencies']))
            for dep in binding['dependencies']:
                owner=next(item for item in tasks if item['task_id']==dep['task_id'])
                for raw in gates[dep['task_id']]['outputs']:
                    path=Path(raw)
                    if path.parent==Path(owner['task_dir']).resolve():
                        self.check('independent_dependency_full_read_before_launch',bool(core.workflow_reads(
                            events,self.worktree,path,after=deliveries[dep['task_id']]['result_row'],
                            before=launches[task['task_id']]['call_row'])))
        for event in all_events:
            name,args=event['name'],event['args'];target=None
            words=forge_helpers.literal(args.get('command','')) if name=='bash' else []
            safe=self.gate_invocation(args.get('command','')) if name=='bash' else None
            horch_args=core.literal_horch_command(name,args,self.worktree,self.bundle)
            if name in ('read','grep','find','ls','write','edit'):
                raw=args.get('path','.' if name in ('grep','find','ls') else None)
                self.check('lead_literal_filesystem_path',isinstance(raw,str) and bool(raw) and '~' not in raw
                           and '\x00' not in raw and '..' not in raw.split('/'))
                target=(self.worktree/raw).resolve()
            elif words and words[0] in ('cat','sha256sum') and len(words)==2:
                target=(self.worktree/words[1]).resolve()
            if name=='bash':
                self.check('no_raw_gate_access_or_horch_poll',safe is not None or str(self.gate_home) not in args.get('command',''))
                self.check('horch_only_run_before_safe_gate',not horch_args or horch_args[0]=='run')
                if safe is None and not horch_args and target is None:
                    self.check('no_task_paths_hidden_in_other_shell_operands',not any(
                        task['task_id'] in args.get('command','') or task['task_dir'] in args.get('command','') for task in tasks))
            if target is not None:
                private={self.task_root.resolve(),self.gate_home,self.directory/'native-sessions'}
                self.check('no_raw_audit_or_task_parent_inspection',not any(target==root or root in target.parents
                    or target in root.parents for root in private)
                    or any(Path(task['task_dir']).resolve() in target.parents for task in tasks))
                stage_roots={self.directory/name for name in ('baseline','sensitivity-small','sensitivity-target',
                    'baseline-measurement','sensitivity-measurement','final','final-measurement')}
                stage_roots|={self.directory/(prefix+str(i)+suffix) for i in range(1,self.args.max_attempts+1)
                              for prefix,suffix in (('attempt-',''),('attempt-','-measurement'))}
                roots={self.worktree,self.reader,self.bundle,self.artifacts,self.args.fixture_repo,*stage_roots}
                exact={self.probe,self.engine,Path(__file__).resolve(),self.directory/'controller-brief.md',
                    self.directory/'config/herdr-orchestrator/workers.toml',self.directory/'baseline.json',
                    self.directory/'sensitivity.json',self.directory/'final.json',self.directory/'review/manifest.json'}
                output=any(str(target) in facts['outputs'] for facts in gates.values())
                self.check('lead_only_known_stage_or_gated_output_roots',target in exact or output
                           or any(target==root or root in target.parents for root in roots))
                self.check('no_native_transcript_or_snapshot_copies',target.suffix!='.jsonl'
                    and not target.name.endswith(('worker-native.jsonl','native-session-capture.json')))
                for task in tasks:
                    root=Path(task['task_dir']).resolve()
                    if target==root or root in target.parents:
                        self.check('task_output_read_only_after_accepted_gate',str(target) in gates[task['task_id']]['outputs']
                            and event['call_row']>deliveries[task['task_id']]['result_row']
                            and name not in ('write','edit'))
                        if words[:1]==['sha256sum']:
                            self.check('gated_task_hash_is_actual_single_file',event['output'].strip()==
                                       core.sha(target)+'  '+str(target))
            # The writer's live integration source is also withheld until its PASS gate.
            for task in tasks:
                role=gates[task['task_id']]['role']
                if role!='hillclimb' or not (launches[task['task_id']]['call_row']<event['call_row']
                                            <=deliveries[task['task_id']]['result_row']):
                    continue
                if target is not None:
                    self.check('no_candidate_source_inspection_before_gate',not (target==self.worktree
                        or self.worktree in target.parents or target in self.worktree.parents))
                if words and words[0]=='git':
                    self.check('no_candidate_git_content_before_gate',words[3:4] not in
                               (['diff'],['show'],['log'],['blame'],['diff-tree'],['rev-list']))
                if name=='bash':
                    self.check('no_candidate_measurement_before_gate',self.lever_invocation(args.get('command','')) is None)
        return launches,deliveries

    def verify(self):
        rows = self.scan()
        self.verify_tasks(rows)
        tasks = [t for t,_ in rows]
        sessions = list((self.directory/'native-sessions').glob('*.jsonl'))
        self.check('one_bound_controller_session',len(sessions)==1)
        events, all_events = self.native_events(sessions[0]), self.native_events(sessions[0],include_errors=True)
        names = {'checklist.md','pr-body.md','forge-resolution.json','reply.md',
                 *(f'hillclimb/{name}' for name in ('workload.json','metric.json','vetting.json','freeze.json',
                     'how-brief.md','explanation.md','stop.json','trail-brief.md','attention.md',
                     'comment-brief.md','comment-scope.json','comment-diff.patch','comment-decision.json')),
                 *(f'hillclimb/{kind}-{i}.{suffix}' for i in range(1,self.args.max_attempts+1)
                     for kind,suffix in (('hypothesis','json'),('brief','md'),('review','json'),('decision','json')))}
        writable = {self.artifacts/name for name in names}|{self.worktree/'PERFORMANCE.md'}
        self.check('all_native_writes_guarded_including_failures',all(
            isinstance(e['args'].get('path'),str) and (self.worktree/e['args']['path']).resolve() in writable
            for e in all_events if e['name'] in ('write','edit')))
        self.check('all_native_shell_operations_guarded_including_failures',all(
            self.controller_command_allowed(e['args'].get('command','')) for e in all_events if e['name']=='bash'))
        launches, deliveries = self.gated_deliveries(tasks,events,all_events)
        self.check('every_task_literal_launch_done_delivery',set(launches)==set(deliveries)=={t['task_id'] for t in tasks})
        by_brief = {}
        for task in tasks:
            argv = core.literal_horch_command(launches[task['task_id']]['name'],launches[task['task_id']]['args'],
                                              self.worktree,self.bundle)
            self.check('unique_named_brief_launch',argv.count('--brief')==1)
            source = Path(argv[argv.index('--brief')+1]).resolve()
            self.check('brief_is_authorized_unique_input',source not in by_brief and source in writable)
            by_brief[source] = task
        comment_path = self.artifacts/'hillclimb/comment-brief.md'
        self.check('one_fresh_comment_assignment', comment_path in by_brief)
        self.comment_task = by_brief[comment_path]
        self.native = core.audit_pi(sessions[0],self.session,self.worktree,self.wall_started,self.spec,
                                   [self.bundle/'skills'/name for name in READS],[],[],self.bundle)
        self.check('controller_actual_model_effort_guidance_delivery',all(r['ok'] for r in self.native['checks']))
        how_path = self.artifacts/'hillclimb/how-brief.md'
        trail_path = self.artifacts/'hillclimb/trail-brief.md'
        self.check('how_and_trail_tasks_present',how_path in by_brief and trail_path in by_brief)
        how, reviewer = by_brief[how_path], by_brief[trail_path]
        self.check('configured_how_and_trail_workers',how['worker']==self.role_workers['how explainer'][0]
                   and reviewer['worker']==self.args.trail_reviewer
                   and Path(how['cwd']).resolve()==self.reader and Path(reviewer['cwd']).resolve()==self.worktree)
        how_launch, review_launch = launches[how['task_id']],launches[reviewer['task_id']]
        how_writes = self.bind_brief(events,all_events,how,how_launch,how_path,'how explainer')
        self.bind_brief(events,all_events,reviewer,review_launch,trail_path,'bounded trail audit')
        how_reports = self.report(events,how,deliveries[how['task_id']])
        explanation, explanation_events = self.artifact(events,'hillclimb/explanation.md',
            after=max(e['result_row'] for e,_ in how_reports))
        self.check('how_explanation_preserved',all(text in explanation for _,text in how_reports))
        self.check('how_reader_detached_pristine',self.git('rev-parse','HEAD',repo=self.reader)==self.base
                   and not self.git('branch','--show-current',repo=self.reader)
                   and not self.git('status','--porcelain=v1','--untracked-files=all',repo=self.reader))
        workload, workload_events = self.artifact(events,'hillclimb/workload.json',
            after=explanation_events[-1]['result_row'],
            keys=('architecture_sha256','dimensions','complaint','target_case','simpler_case','relevance'))
        metric, metric_events = self.artifact(events,'hillclimb/metric.json',after=workload_events[-1]['result_row'],
            keys=('metric','direction','target_reduction','attempt_floor','attended','workload_sha256'))
        self.check('architecture_grounded_explicit_immutable_goal',workload['architecture_sha256']==core.sha(
            self.artifacts/'hillclimb/explanation.md') and metric=={
                'metric':'full_cli_wall_median_ms','direction':'lower','target_reduction':self.args.target_reduction,
                'attempt_floor':self.args.attempt_floor,'attended':True,
                'workload_sha256':core.sha(self.worktree/'workload.json')})
        checklist = core.workflow_writes(events,self.worktree,self.artifacts/'checklist.md',before=how_launch['call_row'])
        steps = re.findall(r'^\d+\. (.+)$',(self.bundle/'skills/poteto-mode/playbooks/hillclimb.md').read_text(),re.M)
        checklist = [e for e in checklist if re.findall(r'^\d+\. (.+)$',e['args']['content'],re.M)==steps]
        self.check('exact_original_eight_stage_checklist',len(steps)==8 and bool(checklist))
        self.stage('hillclimb_1_how_workload_metric',checklist+how_writes+[how_launch]+
                   [e for e,_ in how_reports]+explanation_events+workload_events+metric_events)

        sensitivity, sensitive_event = self.lever_event(events,'sensitivity')
        self.check('metric_before_measurement',metric_events[-1]['result_row']<sensitive_event['call_row'])
        sensitive = self.audit_measurement(sensitivity['observation'],self.directory/'sensitivity-measurement',
            {'before':self.directory/'sensitivity-small','after':self.directory/'sensitivity-target'},contrast=True)
        self.check('real_workload_sensitivity',sensitive['timings']['after']['minimum_ms']>
                   2*sensitive['timings']['before']['maximum_ms']
                   and sensitive['profiles']['before']['lookup_calls']==60
                   and sensitive['profiles']['after']['lookup_calls']==6000)
        host = [e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))
                in (['uptime'],['nproc']) and e['result_row']<sensitive_event['call_row'] and e['output'].strip()]
        self.check('actual_load_and_core_observation',{forge_helpers.literal(e['args']['command'])[0] for e in host}=={'uptime','nproc'})
        probe_reads = core.workflow_reads(events,self.worktree,self.probe,before=sensitive_event['call_row'])
        engine_reads = core.workflow_reads(events,self.worktree,self.engine,before=sensitive_event['call_row'])
        benchmark = core.workflow_reads(events,self.worktree,self.bundle/'skills/benchmark-checklist/SKILL.md',
                                         before=sensitive_event['call_row'])
        self.check('read_actual_harness_and_checklist_before_number',bool(probe_reads and engine_reads and benchmark))
        _, vetting = self.artifact(events,'hillclimb/vetting.json',after=metric_events[-1]['result_row'],
            before=sensitive_event['call_row'],keys=('claim','timed_surface','included_work','ignored_work','cache_state',
                'production_config','limiter_plan','bounds','correctness','errors','repetitions'))
        freeze, freeze_events = self.artifact(events,'hillclimb/freeze.json',after=sensitive_event['result_row'],
            keys=('probe_sha256','engine_sha256','workload_sha256','metric_sha256','sensitivity_sha256','verdict',
                  'host_observations','sensitivity_timings','work_counts','errors','limiter','bounds'))
        self.check('harness_frozen_after_proven_sensitivity',all(freeze[key]==value for key,value in {
            'probe_sha256':self.probe_hash,'engine_sha256':self.engine_hash,
            'workload_sha256':core.sha(self.worktree/'workload.json'),
            'metric_sha256':core.sha(self.artifacts/'hillclimb/metric.json'),
            'sensitivity_sha256':core.sha(self.directory/'sensitivity.json'),'verdict':'sensitive'}.items()))
        host_values={forge_helpers.literal(e['args']['command'])[0]:e['output'].strip() for e in host}
        self.check('frozen_measurement_vetting_actual_host_limiter_work',freeze['host_observations']=={
            'uptime':host_values['uptime'],'nproc':int(host_values['nproc'])}
            and freeze['sensitivity_timings']==sensitive['timings']
            and freeze['work_counts']=={'small':{'references':20,'payments':60},
                                       'target':{'references':2500,'payments':6000}}
            and freeze['errors']==0 and freeze['limiter']=={
                'function':'lookup_reference','calls':6000,
                'self_seconds':sensitive['profiles']['after']['lookup_self_seconds'],
                'profile_self_seconds':sensitive['profiles']['after']['profile_self_seconds']})
        baseline, baseline_event = self.lever_event(events,'baseline')
        self.check('freeze_before_baseline',freeze_events[-1]['result_row']<baseline_event['call_row'])
        base = self.audit_measurement(baseline['observation'],self.directory/'baseline-measurement',
                                     {'before':self.baseline,'after':self.baseline})
        self.check('pristine_complaint_and_green_baseline_gate',baseline['tests']['valid']
                   and all((self.baseline/name).read_text()==perf.fixture_files()[name] for name in FILES)
                   and base['profiles']['before']['lookup_calls']==6000
                   and base['profiles']['before']['lookup_self_seconds']/base['profiles']['before']['profile_self_seconds']>.5
                   and self.independent_gate(self.baseline,'baseline'))
        self.stage('hillclimb_2_sensitive_frozen_harness_green_baseline',
                   host+probe_reads+engine_reads+benchmark+vetting+[sensitive_event]+freeze_events+[baseline_event])

        final, final_event = self.lever_event(events,'final')
        self.final_value = final
        ledger_path, generic_path = self.artifacts/'hillclimb/decision.tsv',self.artifacts/'trail/decision.tsv'
        with ledger_path.open() as f:
            reader = csv.DictReader(f,delimiter='\t')
            self.check('original_hillclimb_ledger_columns',tuple(reader.fieldnames or ())==LEDGER)
            decisions = [{key:json.loads(row[key]) for key in LEDGER} for row in reader]
        with generic_path.open() as f:
            reader = csv.DictReader(f,delimiter='\t')
            self.check('original_show_work_columns',tuple(reader.fieldnames or ())==TRAIL)
            trail = list(reader)
        n = len(decisions)
        self.check('actual_declared_attempt_floor_and_task_count',self.args.attempt_floor<=n<=self.args.max_attempts
                   and len(tasks)==n+3 and [r['id'] for r in decisions]==list(range(1,n+1)))
        attempted_levers=[e for e in all_events if e['name']=='bash'
                          and self.lever_invocation(e['args'].get('command','')) is not None]
        self.check('no_failed_or_retried_measurement_levers',len(attempted_levers)==3*n+4
                   and all(e['successful'] for e in attempted_levers))
        logs = [e for e in events if e['name']=='bash' and
                forge_helpers.literal(e['args'].get('command',''))[:2]==
                ['bash',str(self.bundle/'skills/show-me-your-work/scripts/log.sh')]]
        self.check('original_append_only_log_helper_rows',len(logs)==len(trail)==n+1)
        for row,event in zip(trail,logs):
            argv = forge_helpers.literal(event['args']['command'])
            self.check('trail_row_bound_to_actual_helper',len(argv)==8 and list(row)[0]=='ts'
                       and [row[key] for key in TRAIL[1:]]==argv[3:]
                       and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',row['ts']))
        self.check('initial_trail_actual_green_baseline',trail[0]['phase']=='frame'
                   and trail[0]['decision']=='freeze measured baseline'
                   and trail[0]['evidence']==str(self.directory/'baseline.json')
                   and trail[0]['result']=='tests green' and baseline_event['result_row']<logs[0]['call_row'])
        self.stage('hillclimb_3_open_both_original_decision_logs',[baseline_event,logs[0]])

        ledger_lines, trail_lines = ledger_path.read_text().splitlines(),generic_path.read_text().splitlines()
        last_record = logs[0]['result_row']
        accepted_root, hypotheses, mechanisms, candidates, commits = self.baseline,set(),set(),{self.function_ast(self.baseline)},[]
        attempt_events, hypothesis_records, plateau = [],[],[]
        all_commit_events = [e for e in events if e['name']=='bash' and
            forge_helpers.literal(e['args'].get('command',''))[:4]==['git','-C',str(self.worktree),'commit']]
        for number,decision in enumerate(decisions,1):
            start, started = self.lever_event(events,'begin',number)
            evaluation,evaluated = self.lever_event(events,'evaluate',number)
            record,recorded = self.lever_event(events,'record',number)
            root = self.directory/('attempt-'+str(number))
            before,after = root/'before',root/'after'
            hypothesis,h_events = self.artifact(events,f'hillclimb/hypothesis-{number}.json',
                after=last_record,before=started['call_row'],keys=('id','hypothesis','mechanism','mantras','mantra_index',
                    'earlier_applicability','architecture_sha256','simplification'))
            self.check('distinct_grounded_hypothesis_'+str(number),hypothesis['id']==number
                       and hypothesis['hypothesis'] not in hypotheses and hypothesis['mechanism'] not in mechanisms
                       and hypothesis['mantras']==list(perf.MANTRAS) and type(hypothesis['mantra_index']) is int
                       and 1<=hypothesis['mantra_index']<=7 and type(hypothesis['simplification']) is bool
                       and hypothesis['architecture_sha256']==core.sha(self.artifacts/'hillclimb/explanation.md'))
            hypotheses.add(hypothesis['hypothesis'])
            mechanisms.add(hypothesis['mechanism'])
            for path,lines in ((ledger_path,ledger_lines[:number]),(generic_path,trail_lines[:number+1])):
                prefix='\n'.join(lines).strip()
                reads=[e for e in events if core.read_target(e['name'],e['args'],self.worktree)==path
                       and prefix in e['output'] and last_record<e['call_row']
                       and e['result_row']<h_events[0]['call_row']]
                self.check('actual_complete_log_read_before_attempt_'+str(number)+'_'+path.parent.name,bool(reads))
                hypothesis_records+=reads
            self.check('exact_last_accepted_source_before_attempt_'+str(number),
                       start['before_sha256']=={name:core.sha(accepted_root/name) for name in FILES}
                       and start['before_sha256']=={name:core.sha(before/name) for name in FILES})
            candidate=self.function_ast(after)
            self.check('actual_distinct_nonempty_function_change_'+str(number),candidate not in candidates
                       and candidate!=self.function_ast(before)
                       and perf.outside_function((before/'reconcile.py').read_text())==
                           perf.outside_function((after/'reconcile.py').read_text()))
            candidates.add(candidate)
            source=self.artifacts/f'hillclimb/brief-{number}.md'
            self.check('one_task_for_each_hypothesis',source in by_brief)
            task=by_brief[source]
            launch,delivery=launches[task['task_id']],deliveries[task['task_id']]
            self.check('fresh_configured_hillclimb_integration_worker',task['worker']==self.role_workers['hillclimb'][0]
                       and Path(task['cwd']).resolve()==self.worktree and started['result_row']<launch['call_row'])
            brief_events=self.bind_brief(events,all_events,task,launch,source,'hillclimb')
            reports=self.report(events,task,delivery,before=evaluated['call_row'])
            diffs=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))==
                   ['git','-C',str(self.worktree),'diff','--','reconcile.py']
                   and max(e['result_row'] for e,_ in reports)<e['call_row'] and e['result_row']<evaluated['call_row']
                   and 'reconcile_linear' in e['output']]
            review,review_events=self.artifact(events,f'hillclimb/review-{number}.json',
                after=max([e['result_row'] for e in diffs],default=float('inf')),before=evaluated['call_row'],
                keys=('id','source_sha256','scope','public_contract','mechanism','concerns'))
            self.check('actual_scoped_diff_review_'+str(number),bool(diffs) and review['id']==number
                       and review['scope']=='reconcile_linear' and review['source_sha256']==core.sha(after/'reconcile.py'))
            if evaluation['observation'].get('valid'):
                self.audit_measurement(evaluation['observation'],self.directory/f'attempt-{number}-measurement',
                                       {'before':before,'after':after})
            observed_verdict,why=self.classify(evaluation,before,after,hypothesis)
            self.check('independent_original_decision_recomputation_'+str(number),
                       (evaluation['verdict'],evaluation['reason'])==(observed_verdict,why))
            independent,output=self.independent_measure(before,after,'attempt-'+str(number))
            independent_tests=self.independent_gate(after,'attempt-'+str(number))
            if independent.get('valid'):
                self.audit_measurement(independent,output,{'before':before,'after':after})
            replay_verdict,_=self.classify({'observation':independent,'tests':{'valid':independent_tests}},before,after,hypothesis)
            self.check('independent_replay_same_keep_or_revert_'+str(number),replay_verdict==observed_verdict)
            chosen,chosen_events=self.artifact(events,f'hillclimb/decision-{number}.json',
                after=evaluated['result_row'],before=recorded['call_row'])
            metric_value=evaluation['observation'].get('measurement')
            medians=metric_value['timings'] if metric_value else None
            expected={'id':number,'hypothesis':hypothesis['hypothesis'],'change':hypothesis['mechanism'],
                'before':medians['before']['median_ms'] if medians else None,
                'after':medians['after']['median_ms'] if medians else None,
                'delta':medians['after']['median_ms']-medians['before']['median_ms'] if medians else None,
                'tests':'green' if evaluation['tests']['valid'] else 'failed','verdict':observed_verdict,'note':why}
            self.check('ledger_decision_exact_real_numbers_'+str(number),
                       evaluation.get('expected_delta')==expected['delta'] and chosen==decision==record['decision']==expected)
            between=[e for e in all_commit_events if chosen_events[-1]['result_row']<e['call_row']
                     and e['result_row']<recorded['call_row']]
            reverts=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))==
                     ['git','-C',str(self.worktree),'restore','--source=HEAD','--','reconcile.py']
                     and chosen_events[-1]['result_row']<e['call_row'] and e['result_row']<recorded['call_row']]
            if observed_verdict=='kept':
                self.check('one_commit_only_for_accepted_attempt_'+str(number),len(between)==1 and not reverts)
                commits+=between
                accepted_root=after
            else:
                self.check('complete_scoped_revert_no_commit_'+str(number),len(reverts)==1 and not between)
            self.check('post_decision_exact_bytes_'+str(number),record['source_sha256']=={
                name:core.sha(accepted_root/name) for name in FILES})
            log=logs[number]
            self.check('real_attempt_trail_after_commit_or_revert_'+str(number),
                       recorded['result_row']<log['call_row']
                       and trail[number]['phase']=='attempt-'+str(number)
                       and trail[number]['decision']==observed_verdict+' attempt '+str(number)
                       and trail[number]['why']==hypothesis['hypothesis']
                       and trail[number]['evidence']==str(root/'evaluation.json')
                       and trail[number]['result']==('tests green ' if evaluation['tests']['valid'] else 'tests failed ')+observed_verdict)
            last_record=log['result_row']
            records=h_events+[started]+brief_events+[launch,delivery]+[e for e,_ in reports]+diffs+review_events+[evaluated]+chosen_events+between+reverts+[recorded,log]
            attempt_events+=records
            hypothesis_records+=h_events
            self.iterations.append({'id':number,'verdict':observed_verdict,'nonce_validated':True,
                'before_sha256':evaluation['before_sha256'],'after_sha256':evaluation['after_sha256'],
                'evaluation_sha256':core.sha(root/'evaluation.json'),'record_sha256':core.sha(root/'record.json'),
                'native_rows':[{'call_row':e['call_row'],'result_row':e['result_row']} for e in records]})
            plateau+=h_events if number>1 else []
        indices=[core.read_json(self.artifacts/f'hillclimb/hypothesis-{i}.json')['mantra_index']
                 for i in range(1,n+1)]
        self.check('performance_mantra_order_not_early_stop',indices==sorted(indices))
        self.stage('hillclimb_4_grounded_distinct_ordered_hypotheses',hypothesis_records)
        self.stage('hillclimb_5_fresh_measured_keep_or_revert_iterations',attempt_events)
        self.stage('hillclimb_6_push_past_first_plateau',plateau,len(hypotheses)>=self.args.attempt_floor)
        self.verify_final(events,all_events,final,final_event,last_record,decisions,commits,accepted_root,reviewer,
                          launches,deliveries,rows)

    def complete_native_read(self, events, cwd, path):
        """Require all retained lines, including chunked native reads."""
        text=path.read_text()
        lines=text.splitlines()
        if core.workflow_reads(events,cwd,path):
            return True
        covered=set()
        for e in events:
            if e['name']!='read' or core.read_target(e['name'],e['args'],cwd)!=path:
                continue
            offset=e['args'].get('offset')
            limit=e['args'].get('limit')
            offset=1 if offset is None else offset
            limit=len(lines) if limit is None else limit
            if type(offset) is not int or type(limit) is not int or offset<1 or limit<1:
                continue
            first,last=offset-1,min(len(lines),offset-1+limit)
            content='\n'.join(lines[first:last]).strip()
            if content and content in e['output']:
                covered.update(range(first,last))
        return bool(lines) and covered==set(range(len(lines)))

    def verify_final(self,events,all_events,final,final_event,last_record,decisions,accepted_events,
                     accepted_root,reviewer,launches,deliveries,rows):
        self.check('all_attempts_settled_before_final',last_record<final_event['call_row'])
        value=self.audit_measurement(final['observation'],self.directory/'final-measurement',
                                    {'before':self.baseline,'after':self.directory/'final'})
        self.snapshot={'before':{name:core.sha(self.baseline/name) for name in FILES},
                       'after':{name:core.sha(self.directory/'final'/name) for name in FILES}}
        self.check('final_exact_last_accepted_source',final['source_sha256']=={
            name:core.sha(accepted_root/name) for name in FILES}
            =={name:core.sha(self.worktree/name) for name in FILES})
        independent,output=self.independent_measure(self.baseline,self.directory/'final','final')
        self.check('independent_final_measurement_valid',independent.get('valid'))
        replay=self.audit_measurement(independent,output,{'before':self.baseline,'after':self.directory/'final'})
        self.check('actual_and_independent_target_not_relaxed',final['predicate_met'] is True
                   and final['tests']['valid'] is True and len(decisions)>=self.args.attempt_floor
                   and final['attempts']==len(decisions)
                   and final['kept']==sum(r['verdict']=='kept' for r in decisions)
                   and final['reverted']==sum(r['verdict']=='reverted' for r in decisions)
                   and final['reduction']==value['speedup_fraction']
                   and final['reduction']>=self.args.target_reduction/100
                   and replay['speedup_fraction']>=self.args.target_reduction/100
                   and self.independent_gate(self.directory/'final','final'))
        stop,stop_events=self.artifact(events,'hillclimb/stop.json',after=final_event['result_row'],
            keys=('target_reduction','attempt_floor','attempts','kept','reverted','reduction','predicate_met',
                  'reason','remaining_ideas','next_idea'))
        self.check('honest_attended_stop_and_next_idea',all(stop[key]==expected for key,expected in {
            'target_reduction':self.args.target_reduction,'attempt_floor':self.args.attempt_floor,
            'attempts':final['attempts'],'kept':final['kept'],'reverted':final['reverted'],
            'reduction':final['reduction'],'predicate_met':True}.items()))
        self.stage('hillclimb_7_original_predicate_and_grounded_next_idea',[final_event]+stop_events)

        manifest,ready=self.lever_event(events,'review-ready')
        review_launch=launches[reviewer['task_id']]
        self.check('trail_review_after_stop_before_handoff',
                   stop_events[-1]['result_row']<ready['call_row'] and ready['result_row']<review_launch['call_row'])
        frozen=self.directory/'review/controller-transcript.jsonl'
        actual=list((self.directory/'native-sessions').glob('*.jsonl'))[0]
        self.check('actual_scoped_native_trail_snapshot',actual.read_bytes().startswith(frozen.read_bytes())
                   and manifest['transcript_sha256']==core.sha(frozen)
                   and manifest['ledger_sha256']==core.sha(self.artifacts/'hillclimb/decision.tsv')
                   and manifest['trail_sha256']==core.sha(self.artifacts/'trail/decision.tsv'))
        reports=self.report(events,reviewer,deliveries[reviewer['task_id']])
        candidates=[]
        for _,content in reports:
            try:
                report=json.loads(content)
            except ValueError:
                continue
            if isinstance(report,dict) and report.get('scope')=='bounded trail audit':
                candidates.append(report)
        self.check('one_real_structured_trail_review',len(candidates)==1)
        report=candidates[0]
        task_path,task_audit=self.audit_task_native(reviewer)
        review_events=self.native_events(task_path)
        required=[frozen,self.directory/'review/manifest.json',
                  self.artifacts/'hillclimb/decision.tsv',self.artifacts/'trail/decision.tsv']
        required += [self.artifacts/f'hillclimb/{kind}-{i}.json' for i in range(1,len(decisions)+1)
                     for kind in ('hypothesis','decision')]
        required += [self.directory/f'attempt-{i}/{kind}.json' for i in range(1,len(decisions)+1)
                     for kind in ('evaluation','record')]
        self.check('reviewer_actually_read_complete_scoped_evidence',all(
            self.complete_native_read(review_events,self.worktree,path) for path in required))
        self.check('actual_cross_family_trail_review_nonblocking',
                   family(self.review_spec)!=family(self.spec)
                   and report.get('reviewed_model')==self.review_spec['model']
                   and report.get('reviewed_manifest_sha256')==core.sha(self.directory/'review/manifest.json')
                   and isinstance(report.get('flags'),list) and report.get('blocking')==[]
                   and all(report.get(key) is True for key in (
                       'checked_distinct_mechanisms','checked_mantra_order','checked_plateau_response',
                       'checked_log_native_consistency')))
        self.trail_review={'model':self.review_spec['model'],'family':family(self.review_spec),
                           'controller_family':family(self.spec),'flags':len(report['flags']),
                           'blocking':0,'native':task_audit,'manifest_sha256':core.sha(self.directory/'review/manifest.json')}
        attention,attention_events=self.artifact(events,'hillclimb/attention.md',
            after=max(e['result_row'] for e,_ in reports))
        expected_first='reviewed by '+self.review_spec['model']
        self.check('mandatory_leaf_attention_actual_flags',attention.splitlines()[0]==expected_first
                   and (all(str(flag) in attention for flag in report['flags']) if report['flags'] else 'No flags' in attention))
        for task,_ in rows:
            if task['task_id']!=reviewer['task_id']:
                _,audit=self.audit_task_native(task)
                self.task_facts[next(i for i,t in enumerate(rows) if t[0]['task_id']==task['task_id'])]['native']=audit
        comment_path = self.artifacts/'hillclimb/comment-brief.md'
        comment = self.comment_task
        self.check('comment_configured_role_owned_cwd', comment['worker'] == self.role_workers['judgment and prose'][0]
                   and Path(comment['cwd']).resolve() == self.worktree)
        self.bind_brief(events,all_events,comment,launches[comment['task_id']],comment_path,'judgment and prose')
        self.verify_commits_and_pr(events,all_events,final,accepted_events,attention,attention_events,
                                   comment,launches[comment['task_id']],deliveries[comment['task_id']])

    def verify_comment_review(self, events, all_events, final, attention_events,
                              task, launch, delivery, commit):
        scope_path, patch_path = self.artifacts / 'hillclimb/comment-scope.json', self.artifacts / 'hillclimb/comment-diff.patch'
        scope, scope_events = self.artifact(events, 'hillclimb/comment-scope.json',
            after=max(event['result_row'] for event in attention_events), before=launch['call_row'])
        patch, patch_events = self.artifact(events, 'hillclimb/comment-diff.patch', before=scope_events[0]['call_row'])
        expected_scope = {'base': self.base, 'source': 'reconcile.py', 'report': 'PERFORMANCE.md',
                          'source_sha256': core.sha(self.directory / 'final/reconcile.py'),
                          'performance_sha256': core.sha(self.worktree / 'PERFORMANCE.md'),
                          'final_sha256': core.sha(self.directory / 'final.json'),
                          'ledger_sha256': core.sha(self.artifacts / 'hillclimb/decision.tsv'),
                          'trail_sha256': core.sha(self.artifacts / 'trail/decision.tsv'),
                          'diff_sha256': core.sha(patch_path)}
        self.check('comment_scope_binds_measured_source_and_report', scope == expected_scope
                   and scope['source_sha256'] == core.sha(self.worktree / 'reconcile.py'))
        diff_argv = ['git', '-C', str(self.worktree), 'diff', self.base, '--', 'reconcile.py']
        diffs = [event for event in events if event['name'] == 'bash'
                 and forge_helpers.literal(event['args'].get('command', '')) == diff_argv
                 and max(e['result_row'] for e in attention_events) < event['call_row']
                 and event['result_row'] < patch_events[0]['call_row'] and event['output'] == patch]
        self.check('comment_actual_current_diff_bound', len(diffs) == 1
                   and patch == self.call(diff_argv))
        report_writes = core.workflow_writes(events, self.worktree, self.worktree / 'PERFORMANCE.md',
            after=max(event['result_row'] for event in attention_events), before=launch['call_row'], final=True)
        body_writes = core.workflow_writes(events, self.worktree, self.artifacts / 'pr-body.md',
            after=max(event['result_row'] for event in attention_events), before=launch['call_row'], final=True)
        self.check('comment_review_after_report_ready', bool(report_writes and body_writes)
                   and launch['call_row'] > max(event['result_row'] for event in scope_events + report_writes + body_writes))
        frozen_inputs = {self.worktree/'PERFORMANCE.md',scope_path,patch_path,self.artifacts/'pr-body.md'}
        self.check('comment_review_freezes_final_inputs', all(event['result_row'] < launch['call_row']
            for event in all_events if event['name'] in ('write','edit')
            and isinstance(event['args'].get('path'),str)
            and (self.worktree/event['args']['path']).resolve() in frozen_inputs))
        for resource in ('no-comments/SKILL.md', 'pstack-herdr/references/agents/comment-sicko.md'):
            self.check('lead_comment_guidance_before_dispatch', bool(core.workflow_reads(events, self.worktree,
                self.bundle / 'skills' / resource, before=launch['call_row'])))
        reports = core.workflow_report_reads(events, task, self.worktree, delivery,
                                             before=commit['call_row'], report_name='report.md')
        self.check('comment_report_done_delivered_fully_read', bool(reports) and bool(core.workflow_reads(
            events, self.worktree, Path(task['result_path']), after=delivery['result_row'], before=commit['call_row'])))
        report_path = Path(task['task_dir']) / 'report.md'
        result_files = core.read_json(Path(task['result_path'])).get('files')
        self.check('comment_result_files_unique_unordered', isinstance(result_files, list)
                   and all(isinstance(name, str) for name in result_files)
                   and len(set(result_files)) == len(result_files) and 'report.md' in result_files
                   and set(result_files) <= {'report.md','review.json','result.json'})
        listed_reads = []
        for name in result_files:
            reads = core.workflow_reads(events,self.worktree,Path(task['task_dir'])/name,
                                        after=delivery['result_row'],before=commit['call_row'])
            self.check('comment_all_listed_artifacts_read_after_delivery', bool(reads))
            listed_reads += reads
        report = core.read_json(report_path)
        self.check('comment_report_typed_scope', isinstance(report, dict) and report.get('scope') == scope
                   and report.get('touched_files') == [] and type(report.get('deletion_count')) is int and report['deletion_count'] == 0
                   and report.get('restored_comments') == []
                   and all(isinstance(report.get(key), list) for key in ('findings', 'must_kill', 'skips', 'encoding_offers', 'open_work')))
        findings = report['findings']
        self.check('comment_findings_unique', all(isinstance(finding, dict) and isinstance(finding.get('id'), str)
                   and bool(finding['id']) for finding in findings)
                   and len({finding['id'] for finding in findings}) == len(findings))
        texts = {name: (self.worktree / name).read_text() for name in ('reconcile.py', 'PERFORMANCE.md')}
        for finding in findings:
            path, excerpt = finding.get('path'), finding.get('evidence_excerpt')
            self.check('comment_finding_actual_scoped_evidence', path in texts
                       and finding.get('kind') in ('delete', 'keep', 'reshape', 'suppression', 'constraint')
                       and bool(finding.get('symbol')) and bool(finding.get('reason'))
                       and type(finding.get('line')) is int and 0 < finding['line'] <= len(texts[path].splitlines())
                       and isinstance(excerpt, str) and bool(excerpt) and excerpt in texts[path]
                       and bool(texts[path].splitlines()[finding['line'] - 1].strip())
                       and (texts[path].splitlines()[finding['line'] - 1] in excerpt
                            or excerpt in texts[path].splitlines()[finding['line'] - 1]))
        self.check('comment_flags_and_skips_scoped', all(isinstance(flag, str) and flag in {finding['id'] for finding in findings}
                   for flag in report['must_kill']) and all(isinstance(skip, dict) and skip.get('path') in texts
                   and bool(skip.get('reason')) and isinstance(skip.get('evidence_excerpt'), str)
                   and bool(skip['evidence_excerpt']) and skip['evidence_excerpt'] in texts[skip['path']] for skip in report['skips']))
        decision, decision_events = self.artifact(events, 'hillclimb/comment-decision.json',
            after=max([event['result_row'] for event, _ in reports] + [event['result_row'] for event in listed_reads]),
            before=commit['call_row'])
        for path in (self.worktree / 'reconcile.py', self.worktree / 'PERFORMANCE.md', patch_path,
                     self.directory / 'final.json', self.artifacts / 'hillclimb/decision.tsv',
                     self.artifacts / 'trail/decision.tsv'):
            self.check('lead_comment_findings_checked_against_scope', bool(core.workflow_reads(events, self.worktree,
                path, after=max(event['result_row'] for event, _ in reports), before=decision_events[0]['call_row'])))
        dispositions = decision.get('dispositions')
        self.check('comment_lead_actual_report_disposition', decision.get('scope_sha256') == core.sha(scope_path)
                   and decision.get('report_sha256') == core.sha(report_path)
                   and isinstance(dispositions, list) and len(dispositions) == len(findings)
                   and all(isinstance(item, dict) and item.get('id') in {finding['id'] for finding in findings}
                           and item.get('decision') in ('accept', 'reject') and bool(item.get('reason'))
                           and isinstance(item.get('evidence_excerpt'), str) and bool(item['evidence_excerpt'])
                           and item['evidence_excerpt'] in texts[next(finding['path'] for finding in findings
                                                                    if finding['id'] == item['id'])] for item in dispositions)
                   and len({item['id'] for item in dispositions}) == len(findings))
        accepted = {item['id'] for item in dispositions if item['decision'] == 'accept'}
        self.check('comment_no_unresolved_measurement_invalidating_work', decision.get('report_accepted') is True
                   and decision.get('verdict') == 'pass'
                   and all(finding['kind'] == 'keep' for finding in findings if finding['id'] in accepted)
                   and all(flag not in accepted for flag in report['must_kill'])
                   and type(decision.get('deletion_count')) is int and decision['deletion_count'] == 0 and decision.get('restored_comments') == []
                   and decision.get('flags') == report['must_kill'] and decision.get('skips') == report['skips']
                   and type(decision.get('reruns')) is int and decision['reruns'] == 0 and decision.get('architect_sketch') is None
                   and decision.get('fixes') == [] and decision.get('encoding_offers') == report['encoding_offers'] == []
                   and decision.get('encodings') == [] and decision.get('unenforced_constraints') == []
                   and decision.get('open_work') == report['open_work'] == [])
        self.stage('opening_no_comments_comment_sicko', scope_events + patch_events + diffs + [launch, delivery]
                   + [event for event, _ in reports] + decision_events)
        return decision_events

    def verify_commits_and_pr(self,events,all_events,final,accepted_events,attention,attention_events,
                              comment,comment_launch,comment_delivery):
        self.check('owned_branch_clean',not self.git('status','--porcelain=v1','--untracked-files=all')
                   and self.git('branch','--show-current')==self.branch)
        self.commits=self.git('rev-list','--reverse',self.base+'..HEAD').splitlines()
        self.check('one_commit_per_accepted_fix_then_evidence',
                   len(self.commits)==final['kept']+1 and final['kept']>=1)
        previous=self.base
        kept=[row for row in self.iterations if row['verdict']=='kept']
        for commit,iteration,event in zip(self.commits[:-1],kept,accepted_events):
            self.check('accepted_commit_order_exact_scope',self.git('rev-parse',commit+'^')==previous
                       and self.git('diff-tree','--no-commit-id','--name-only','-r',commit).splitlines()==['reconcile.py']
                       and self.git('rev-parse',commit+':reconcile.py')==
                           self.git('hash-object',self.directory/f"attempt-{iteration['id']}/after/reconcile.py")
                       and commit[:7] in event['output'])
            previous=commit
        self.check('measurement_document_separate_last_commit',self.git('rev-parse',self.commits[-1]+'^')==previous
                   and self.git('diff-tree','--no-commit-id','--name-only','-r',self.commits[-1]).splitlines()==['PERFORMANCE.md'])
        self.check('only_allowed_function_and_document_final_diff',
                   self.git('diff','--name-only',self.base,'HEAD').splitlines()==['PERFORMANCE.md','reconcile.py']
                   and perf.outside_function(perf.APP)==perf.outside_function((self.worktree/'reconcile.py').read_text())
                   and all((self.worktree/name).read_text()==text for name,text in perf.fixture_files().items()
                           if name!='reconcile.py'))
        self.check('portable_report_exact_real_iterations',
                   (self.worktree/'PERFORMANCE.md').read_text()==final['portable_report']
                   and not any(str(path) in final['portable_report'] for path in
                               (ROOT,self.directory,self.worktree,self.args.fixture_repo)))
        commits=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))[:4]==
                 ['git','-C',str(self.worktree),'commit']]
        pushes=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))[:4]==
                ['git','-C',str(self.worktree),'push']]
        creates=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))[:3]
                 in (['gh','pr','create'],['origin','pr','create'])]
        views=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command',''))[:3]
               in (['gh','pr','view'],['origin','pr','view'])]
        self.check('actual_ordered_commit_push_ready_create_counts',len(commits)==len(self.commits)
                   and len(pushes)==len(creates)==1 and self.commits[-1][:7] in commits[-1]['output']
                   and attention_events[-1]['result_row']<commits[-1]['call_row']
                   and commits[-1]['result_row']<pushes[0]['call_row']<creates[0]['call_row']
                   and pushes[0]['result_row']<creates[0]['call_row'])
        guidance=[]
        for resource in ('poteto-mode/playbooks/opening-a-pr.md','deslop/SKILL.md','no-comments/SKILL.md',
                         'technical-writing/SKILL.md','unslop/SKILL.md','principle-sequence-verifiable-units/SKILL.md'):
            reads=core.workflow_reads(events,self.worktree,self.bundle/'skills'/resource,before=commits[0]['call_row'])
            self.check('actual_guidance_before_all_commits_'+resource.split('/')[0],bool(reads))
            guidance+=reads
        docs=core.workflow_writes(events,self.worktree,self.worktree/'PERFORMANCE.md',
            after=attention_events[-1]['result_row'],before=commits[-1]['call_row'],final=True)
        body,body_events=self.artifact(events,'pr-body.md',after=attention_events[-1]['result_row'],
                                       before=creates[0]['call_row'])
        self.check('original_pr_body_actual_primary_and_link',bool(docs) and final['primary_number'] in body
                   and bool(re.search(r'\[[^\]]+\]\((?:\./)?PERFORMANCE\.md\)',body))
                   and re.findall(r'^## (.+)$',body,re.M) in (
                       ['Why','What changed','Scope','Blast Radius','Verification'],
                       ['Why','What changed','Scope','Tradeoffs','Blast Radius','Verification'])
                   and len(body.splitlines())<40
                   and not any(str(path) in body for path in (ROOT,self.directory,self.worktree,self.args.fixture_repo)))
        comment_decision = self.verify_comment_review(events,all_events,final,attention_events,
            comment,comment_launch,comment_delivery,commits[-1])
        document_patch = document_patch_headers(self.call(
            ['git','-C',self.worktree,'diff',self.commits[-1]+'^',self.commits[-1],'--','PERFORMANCE.md']))
        full_diff=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command','')) in (
                   ['git','-C',str(self.worktree),'diff'],
                   ['git','-C',str(self.worktree),'diff','--cached'],
                   ['git','-C',str(self.worktree),'diff','--staged'])
                   and e['result_row']<commits[-1]['call_row']
                   and e['call_row']>max(e['result_row'] for e in comment_decision)
                   and document_patch_headers(e['output']) == document_patch]
        self.check('actual_complete_final_document_diff_review',bool(full_diff) and bool(document_patch.strip())
                   and document_patch.startswith('diff --git a/PERFORMANCE.md b/PERFORMANCE.md\n'))
        clean=[e for e in events if e['name']=='bash' and forge_helpers.literal(e['args'].get('command','')) in (
            ['git','-C',str(self.worktree),'status','--porcelain'],
            ['git','-C',str(self.worktree),'status','--porcelain=v1'])
            and commits[-1]['result_row']<e['call_row'] and e['result_row']<creates[0]['call_row']
            # Pi's exact successful empty-bash marker applies only to this
            # literal owned Git status witness, never other reads or probes.
            and e['output'].strip() in ('','(no output)')]
        self.check('actual_clean_state_before_forge_delivery',bool(clean))
        resolution,resolution_events=self.artifact(events,'forge-resolution.json',
            before=min(e['call_row'] for e in creates+views),keys=('selected','reason'))
        selected=resolution['selected']
        discovery=[e for e in all_events if e['name']=='bash' and
                   forge_helpers.literal(e['args'].get('command',''))==['command','-v','origin']
                   and e['result_row']<resolution_events[0]['call_row']]
        self.check('one_actual_origin_discovery',len(discovery)==1)
        self.check('one_resolved_forge',selected in ('gh','origin') and all(
            forge_helpers.literal(e['args']['command'])[0]==selected for e in creates+views))
        origin=[e for e in all_events if e['name']=='bash' and
                forge_helpers.literal(e['args'].get('command',''))[:3]==['origin','repo','view']
                and discovery[0]['result_row']<e['call_row'] and e['result_row']<resolution_events[0]['call_row']]
        exists=discovery[0]['successful'] and discovery[0]['output'].strip() not in ('','(no output)')
        if exists:
            resolved=any(e['successful'] and self.args.forge_repo.lower() in e['output'].lower() for e in origin)
            self.check('observed_origin_preference_or_resolution_failure',
                       bool(origin) and ((selected=='origin' and resolved) or
                       (selected=='gh' and not resolved and any(not e['successful'] for e in origin))))
        else:
            self.check('observed_gh_fallback_absent_origin',selected=='gh')
        argv=forge_helpers.literal(creates[0]['args']['command'])
        self.check('actual_ready_explicit_parent_base_owned_head','--draft' not in argv
                   and (selected!='origin' or '--status' in argv and argv[argv.index('--status')+1]=='open')
                   and all(flag in argv and argv[argv.index(flag)+1]==expected for flag,expected in
                       {'--base':self.args.base_ref,'--head':self.branch,
                        '--body-file':str(self.artifacts/'pr-body.md')}.items()))
        self.verify_remote(self.commits[-1])
        readback=[e for e in views if e['call_row']>creates[0]['result_row'] and self.branch in e['output']
                  and self.args.base_ref in e['output'] and self.commits[-1] in e['output']]
        self.check('native_and_independent_pr_same_identity',bool(readback) and self.pr['url'] in creates[0]['output']
                   and self.pr['body']==body and re.fullmatch(r'perf\([a-z0-9_-]+\): [^\n.]+',self.pr['title']))
        reply,reply_events=self.artifact(events,'reply.md',after=max(e['result_row'] for e in readback))
        self.check('original_reply_actual_metric_iterations_trail_next_idea_attention',
                   final['primary_number'] in reply and self.pr['url'] in reply and attention in reply
                   and str(self.artifacts/'hillclimb/decision.tsv') in reply
                   and re.search(r'(?mi)^#{1,3} Attention\s*$',reply) is not None
                   and self.artifacts.joinpath('hillclimb/stop.json').is_file()
                   and str(core.read_json(self.artifacts/'hillclimb/stop.json')['next_idea']) in reply)
        self.stage('opening_a_pr',guidance+docs+full_diff+commits+clean+body_events+resolution_events+pushes+creates+readback+reply_events)
        self.stage('hillclimb_8_ordered_accepted_commits_ready_pr',creates+readback+reply_events)

    verify_remote = perf.Run.verify_remote

    def discovered_lifecycle(self):
        """Fixed metadata only; discovering a task never claims its final audit passed."""
        facts=[]
        states=horch.SETTLED_STATES|{'starting','running','long_running','unknown'}
        for task in self.tasks.values():
            try:
                state=core.read_json(Path(task['task_dir'])/'state.json')
                retained=Path(task['brief_path']).read_text()
                suffix='\n\n'+horch.WORKER_RULES.format(result_path=Path(task['task_dir'])/'result.json',
                    task_id=task['task_id'],nonce=task['nonce'])
                assignment=retained[:-len(suffix)] if retained.endswith(suffix) else ''
                match=re.match(r'\A\s*Role: ([^\r\n]+)(?:\r?\n|\Z)',assignment)
                role=match[1] if match and match[1] in self.role_workers else 'unknown'
                spec=self.config.get('workers',{}).get(task.get('worker'),{})
                path=self.gate_home/'gates'/(task['task_id']+'.json')
                gate=core.read_json(path).get('verdict') if path.is_file() else 'not_evaluated'
                gate=gate if gate in ('pass','fail') else 'not_evaluated'
                observed=state.get('state')
                facts.append({'task_id_sha256':hashlib.sha256(task['task_id'].encode()).hexdigest(),
                    'worker_id_sha256':hashlib.sha256(task.get('worker','').encode()).hexdigest(),
                    'role':role,'configured_model':spec.get('model'),'configured_effort':spec.get('effort'),
                    'state':observed if observed in states else 'unknown',
                    'closed':state.get('closed') if type(state.get('closed')) is bool else None,
                    'gate_verdict':gate,'gate_category':{'pass':'accepted','fail':'worker_scope_or_lifecycle_rejected',
                                                       'not_evaluated':'not_evaluated'}[gate]})
            except Exception:
                facts.append({'task_id_sha256':hashlib.sha256(str(task.get('task_id','')).encode()).hexdigest(),
                              'state':'unknown','closed':None,'gate_verdict':'not_evaluated',
                              'gate_category':'lifecycle_metadata_unavailable'})
        return facts

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
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py', 'close', task['task_id']], cleanup=True)
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
            if self.engine.exists():
                integrity = integrity and core.sha(self.engine) == self.engine_hash
            if self.gate_hash:
                integrity = integrity and core.sha(self.gate_policy)==self.gate_hash
            for label,path in (('agent',self.agent_dir/'settings.json'),
                               ('fixture',self.args.fixture_repo/'.pi/settings.json')):
                integrity = integrity and label in self.session_settings_hashes and (
                    core.sha(path) if path.is_file() else None) == self.session_settings_hashes.get(label)
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
                refs = self.git('for-each-ref', '--format=%(objectname)%09%(refname)',
                                repo=self.args.fixture_repo, cleanup=True).splitlines()
                owned = {'refs/heads/' + self.branch, 'refs/remotes/origin/' + self.branch}
                fixture_integrity = fixture_integrity and sorted(
                    row for row in refs if row.split('\t', 1)[-1] not in owned) == sorted(self.fixture_refs)
        except Exception:
            pass
        self.checks.extend([{'name': 'source_head_config_bundle_probe_integrity', 'ok': integrity},
                            {'name': 'original_fixture_checkout_untouched', 'ok': fixture_integrity},
                            {'name': 'owned_panes_absent', 'ok': cleanup_ok}])
        passed = bool(self.checks) and not self.categories and all(c.get('ok') is True for c in self.checks)
        inventory = {name: 'not_run' for name in core.INVENTORY}
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory.update({'hillclimb': verdict, 'opening-a-pr': verdict})
        if not self.native:
            sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(sessions) == 1:
                self.native = {'sha256': core.sha(sessions[0]), 'audit_completed': False}
        receipt = {
            'schema': 'horch/hillclimb-playbook-e2e/v1', 'verdict': 'pass' if passed else 'fail',
            'workflow_verdict': verdict, 'stage_coverage': 'complete' if passed else 'incomplete',
            'behavior_verdict': 'pass' if passed else 'unproven', 'full_inventory_verdict': 'not_run', 'inventory': inventory,
            'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
            'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
            'controller': {k: self.spec.get(k) for k in ('harness', 'provider', 'model', 'effort')},
            'native_transcript': self.native, 'native_stages': self.stage_proof,
            'tasks': getattr(self, 'task_facts', []), 'checks': self.checks,
            'discovered_worker_lifecycle': self.discovered_lifecycle(),
            'attended': True, 'unattended_wake_verdict': 'not_run', 'cloud_execution_verdict': 'not_run',
            'attempt_floor': self.args.attempt_floor, 'target_reduction_percent': self.args.target_reduction,
            'iterations': self.iterations, 'trail_review': getattr(self, 'trail_review', {}),
            'fixture_snapshots': self.snapshot, 'commit_count': len(getattr(self, 'commits', [])),
            'forge': {'ready_pr_verified': passed and self.pr is not None,
                      'retained': True if self.pr is not None else 'unconfirmed'},
            'failure_categories': self.categories, 'last_phase': self.phase,
            'seconds': round(time.monotonic() - self.started, 3),
            'limitations': [
                'One attended lead turn only; unattended wake and cloud execution are not run.',
                'The deterministic workload, simple How route and one-function optimization boundary are fixture-specific.',
                'Five alternating full-CLI observations per side include startup and warm filesystem effects; profiles are separate.',
                'Keep/revert decisions and the final target must survive independent replay; host noise can fail a run.',
                'A simplification keep requires strict AST reduction, overlapping ranges and at most 2% median loss.',
                'Semantic mechanism/order/plateau quality additionally depends on the mandatory different-family bounded trail audit.',
                'CommentSicko is a readonly final-scope report/disposition lane; actionable changes, reruns, encoding and open work remain unresolved.',
                'Playbook coverage is limited to attended Hillclimb and Opening a PR.',
                'Owned branches, worktrees, rejected/accepted snapshots, private evidence and a ready PR remain for inspection.',
            ],
        }
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    if sys.argv[1:2]==['--wait-audit']:
        try:
            if len(sys.argv)!=5:
                raise ValueError('invalid_gate_arguments')
            value=hill_wait_audit(Path(sys.argv[2]),sys.argv[3],int(sys.argv[4]))
        except Exception:
            value={'schema':'hillclimb/safe-delivery/v1','verdict':'fail','state':'quarantined',
                   'category':'worker_scope_or_lifecycle_rejected'}
        print(json.dumps(value,sort_keys=True))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trail-reviewer', help='existing configured Pi worker of a different model family; bounded audit, no new role')
    parser.add_argument('--target-reduction', type=float, default=50.0, help='declared full-CLI reduction percentage before any measurement')
    parser.add_argument('--attempt-floor', type=int, default=3, help='declared minimum genuinely distinct attempts, at least three')
    parser.add_argument('--max-attempts', type=int, default=6, help='resource bound; not a replacement success predicate')
    parser.add_argument('--controller', help='existing configured Pi controller worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='existing trusted orchestrator checkout')
    parser.add_argument('--fixture-repo', type=Path, help='existing clean private fixture clone')
    parser.add_argument('--forge-repo', help='private fixture GitHub owner/name')
    parser.add_argument('--parent-pr', type=int, help='existing ready private baseline PR number')
    parser.add_argument('--base-ref', help='existing unmerged fixture baseline branch')
    parser.add_argument('--output', type=Path, help='private artifact parent outside both checkouts')
    parser.add_argument('--caller-pane', help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=5400, help='overall run deadline; never retries')
    args = parser.parse_args()
    required = ('controller', 'trail_reviewer', 'fixture_repo', 'forge_repo', 'base_ref', 'parent_pr', 'output', 'caller_pane')
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
    if args.parent_pr <= 0:
        parser.error('--parent-pr must be positive')
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
