#!/usr/bin/env python3
"""Real writable Feature/Refactoring playbooks with Architect and private PRs.

Requires an existing clean private invoice fixture, exact base branch and open
parent PR. Prepare a portable baseline with forge_loop.py --prepare-fixture;
create its private repository and ready baseline PR yourself. This driver never
seeds, merges, answers trust, retries failures, or substitutes configured workers.
Private artifacts/worktrees and the ready child PR are retained for inspection.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import uuid

import forge_loop as support
import playbook_loop as core

ROOT = Path(__file__).resolve().parents[1]
horch = core.horch
Failure = core.Failure
SOURCE_FILES = ('money.py', 'storage.py', 'cli.py', 'e2e_import.py')
THROUGHPUT = ('Blocking first steps', 'Independent workstreams',
              'Shared mutable state', 'Smallest safe decomposition')
READS = (
    'poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
    'pstack-herdr/references/herdr-tools.md', 'agent-workers/SKILL.md',
    'how/SKILL.md', 'how/references/explorer-prompt.md', 'how/references/explainer-prompt.md',
    'architect/SKILL.md', 'architect/references/runner-prompt.md',
    'architect/references/rationale-template.md', 'architect/references/design-red-flags.md',
    'arena/SKILL.md', 'control-cli/SKILL.md', 'poteto-mode/playbooks/opening-a-pr.md',
    'deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md', 'unslop/SKILL.md',
    'principle-model-the-domain/SKILL.md', 'principle-foundational-thinking/SKILL.md',
    'principle-redesign-from-first-principles/SKILL.md',
    'principle-subtract-before-you-add/SKILL.md', 'principle-minimize-reader-load/SKILL.md',
    'principle-prove-it-works/SKILL.md', 'principle-migrate-callers-then-delete-legacy-apis/SKILL.md',
    'principle-separate-before-serializing-shared-state/SKILL.md',
    'principle-sequence-verifiable-units/SKILL.md', 'principle-exhaust-the-design-space/SKILL.md',
    'pstack-herdr/references/agents/comment-sicko.md',
)

# An external immutable oracle witnesses real application failures as JSON data,
# so successful native tool results can bind both before and after observations.
ORACLE = r'''#!/usr/bin/env python3
import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--mode', choices=['characterize', 'feature'], required=True)
a = p.parse_args()
r, d = a.repo.resolve(), a.output.resolve()
d.mkdir(parents=True, exist_ok=False, mode=0o700)
checks, record, raw = [], [], []
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def row(identity, quantity, price, discount=0):
    return {'id': identity, 'quantity': quantity, 'unit_price_cents': price, 'discount_bp': discount}
def charged(value):
    total = Decimal(value['quantity']) * Decimal(value['unit_price_cents']) * (Decimal(1) - Decimal(value['discount_bp']) / Decimal(10000))
    return dict(value, total_cents=int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
def check(name, ok):
    checks.append({'name': name, 'ok': bool(ok)})
def invoke(label, command, store, groups=(), dry=False):
    files = []
    for index, group in enumerate(groups):
        path = d / (label + '-' + str(index) + '.json')
        path.write_text(json.dumps(group, sort_keys=True) + '\n')
        files.append(path)
    before = store.read_bytes() if store.exists() else None
    pending = store.with_suffix('.pending')
    pending_before = pending.read_bytes() if pending.exists() else None
    argv = [sys.executable, '-B', str(r / 'cli.py'), command]
    if dry:
        argv.append('--dry-run')
    argv += [str(store), *map(str, files)]
    x = subprocess.run(argv, cwd=r, capture_output=True, text=True, timeout=30)
    after = store.read_bytes() if store.exists() else None
    raw.append({'label': label, 'argv': argv, 'exit_code': x.returncode, 'stdout': x.stdout, 'stderr': x.stderr})
    error = x.stderr.replace(str(r), '<repo>').replace(str(d), '<artifacts>')
    if error.startswith('Traceback (most recent call last):'):
        error = error.rstrip().splitlines()[-1] + '\n'
    observed = {'label': label, 'exit_code': x.returncode, 'stdout': x.stdout, 'stderr': error,
                'store_before_hex': before.hex() if before is not None else None,
                'store_after_hex': after.hex() if after is not None else None,
                'pending_exists': pending.exists(),
                'pending_before_hex': pending_before.hex() if pending_before is not None else None,
                'pending_after_hex': pending.read_bytes().hex() if pending.exists() else None}
    record.append(observed)
    try:
        value = json.loads(x.stdout)
    except ValueError:
        value = None
    return observed, value
sources = {name: digest(r / name) for name in ['money.py', 'storage.py', 'cli.py', 'e2e_import.py']}
failure = None
try:
    store = d / 'ledger.json'
    old = row('persisted', 2, 49)
    x, value = invoke('seed', 'import', store, [[old]])
    check('seed through CLI', x['exit_code'] == 0 and value == {'count': 1, 'total_cents': 98})
    first = [row('txn-z', 1, 101, 5000), row('txn-a', 2, 333, 3333)]
    second = [row('txn-m', 3, 137, 250), row('txn-0', 0, 999), row('free', 7, 101, 10000)]
    expected = sorted(map(charged, [old, *first, *second]), key=lambda item: item['id'])
    summary = {'count': len(expected), 'total_cents': sum(item['total_cents'] for item in expected)}
    if a.mode == 'feature':
        x, value = invoke('dry-two-files', 'import', store, [first, second], True)
        check('dry run has exact independent Decimal totals', x['exit_code'] == 0 and value == summary)
        check('successful dry run preserves persisted bytes', x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
        pending_store = d / 'pending-ledger.json'
        pending_store.write_bytes(store.read_bytes())
        pending_store.with_suffix('.pending').write_bytes(b'preexisting pending evidence\n')
        x, value = invoke('dry-preexisting-pending', 'import', pending_store, [first, second], True)
        check('dry run preserves preexisting pending state', x['exit_code'] == 0 and value == summary
              and x['store_before_hex'] == x['store_after_hex']
              and x['pending_before_hex'] == x['pending_after_hex'] and x['pending_exists'])
        fresh = d / 'absent.json'
        x, value = invoke('dry-absent-store', 'import', fresh, [first, second], True)
        check('dry run does not create absent ledger', x['exit_code'] == 0 and value == {
            'count': len(first) + len(second), 'total_cents': sum(charged(item)['total_cents'] for item in [*first, *second])}
            and x['store_before_hex'] is None and x['store_after_hex'] is None and not x['pending_exists'])
    x, value = invoke('normal-two-files', 'import', store, [first, second])
    check('normal imports retain exact totals', x['exit_code'] == 0 and value == summary)
    x, value = invoke('export-after-import', 'export', store)
    check('normal export remains sorted and complete', x['exit_code'] == 0 and value == expected)
    rejected = [
        ('persisted-duplicate', [[row('candidate', 1, 200), old]], 'duplicate transaction'),
        ('within-file-duplicate', [[row('new-dup', 1, 200), row('new-dup', 2, 300)]], 'duplicate transaction'),
        ('across-file-duplicate', [[row('cross-dup', 1, 200)], [row('cross-dup', 2, 300)]], 'duplicate transaction'),
        ('late-invalid-discount', [[row('valid-first', 1, 101, 5000)], [row('invalid-last', 1, 200, 10001)]], 'invalid discount'),
    ]
    for label, groups, error in rejected:
        normal_store = d / (label + '-normal.json')
        normal_store.write_bytes(store.read_bytes())
        normal, normal_value = invoke(label + '-normal', 'import', normal_store, groups)
        check(label + ' normal rejection', normal['exit_code'] == 2 and isinstance(normal_value, dict)
              and error in normal_value.get('error', '') and normal['store_before_hex'] == normal['store_after_hex'] and not normal['pending_exists'])
        if a.mode == 'feature':
            x, value = invoke(label + '-dry', 'import', store, groups, True)
            check(label + ' dry rejection matches normal', (x['exit_code'], value, x['stderr']) == (normal['exit_code'], normal_value, normal['stderr'])
                  and x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
    missing_groups = [[row('before-missing', 1, 101, 5000)], [{'id': 'missing-last', 'quantity': 1, 'unit_price_cents': 200}]]
    missing_store = d / 'missing-normal.json'
    missing_store.write_bytes(store.read_bytes())
    normal, normal_value = invoke('late-missing-normal', 'import', missing_store, missing_groups)
    missing_fixed = normal['exit_code'] == 2 and isinstance(normal_value, dict) and bool(normal_value.get('error'))
    check('missing field retains bytes', normal['store_before_hex'] == normal['store_after_hex'] and not normal['pending_exists'])
    if a.mode == 'feature':
        x, value = invoke('late-missing-dry', 'import', store, missing_groups, True)
        check('dry missing field matches real normal contract', (x['exit_code'], value, x['stderr']) == (normal['exit_code'], normal_value, normal['stderr'])
              and x['store_before_hex'] == x['store_after_hex'] and not x['pending_exists'])
    x, value = invoke('final-export', 'export', store)
    check('all rejected imports leave full export intact', x['exit_code'] == 0 and value == expected)
    legacy = row('persisted-missing-total', 2, 49)
    summary_groups = [[row('new-z', 1, 101, 5000), row('new-a', 2, 333, 3333)],
                      [row('new-m', 3, 137, 250)]]
    initial_bytes = (json.dumps([legacy], sort_keys=True) + '\n').encode()
    sentinel = b'preexisting pending evidence\n'
    replacement = [legacy, *(charged(item) for group in summary_groups for item in group)]
    replacement_bytes = json.dumps(replacement, sort_keys=True).encode()
    summary_store = d / 'post-replace-summary.json'
    summary_store.write_bytes(initial_bytes)
    summary_store.with_suffix('.pending').write_bytes(sentinel)
    normal, value = invoke('post-replace-summary-normal', 'import', summary_store, summary_groups)
    check('normal late summary fault follows exact replacement', normal['exit_code'] == 1 and normal['stdout'] == ''
          and normal['stderr'] == "KeyError: 'total_cents'\n"
          and normal['store_before_hex'] == initial_bytes.hex() and normal['pending_before_hex'] == sentinel.hex()
          and normal['store_after_hex'] == replacement_bytes.hex()
          and not normal['pending_exists'] and normal['pending_after_hex'] is None)
    x, value = invoke('post-replace-summary-export', 'export', summary_store)
    check('late summary fault retains complete sorted export', x['exit_code'] == 0 and x['stderr'] == ''
          and value == sorted(replacement, key=lambda item: item['id'])
          and x['store_before_hex'] == x['store_after_hex'] == replacement_bytes.hex()
          and not x['pending_exists'] and x['pending_before_hex'] is None and x['pending_after_hex'] is None)
    if a.mode == 'feature':
        dry_store = d / 'post-replace-summary-dry.json'
        dry_store.write_bytes(initial_bytes)
        dry_store.with_suffix('.pending').write_bytes(sentinel)
        x, value = invoke('post-replace-summary-dry', 'import', dry_store, summary_groups, True)
        check('dry late summary fault preserves exact initial ledger and sentinel',
              (x['exit_code'], x['stdout'], x['stderr']) == (normal['exit_code'], normal['stdout'], normal['stderr'])
              and x['store_before_hex'] == x['store_after_hex'] == initial_bytes.hex()
              and x['pending_exists'] and x['pending_before_hex'] == x['pending_after_hex'] == sentinel.hex())
    suite = subprocess.run([sys.executable, '-B', str(r / 'e2e_import.py'), '--output', str(d / 'original-suite')], cwd=r,
                           capture_output=True, text=True, timeout=90)
    raw.append({'label': 'original-suite', 'exit_code': suite.returncode, 'stdout': suite.stdout, 'stderr': suite.stderr})
    suite_receipt = json.loads((d / 'original-suite/evidence.json').read_text())
    check('original seven or eight flows pass', suite.returncode == 0 and suite_receipt.get('verdict') == 'pass'
          and len(suite_receipt.get('flows', [])) in (7, 8) and all(item.get('ok') is True for item in suite_receipt.get('checks', [])))
except Exception as error:
    failure = type(error).__name__
    missing_fixed = False
check('source unchanged during behavior observations', sources == {name: digest(r / name) for name in sources})
result = {'mode': a.mode, 'verdict': 'pass' if failure is None and all(item['ok'] for item in checks) else 'fail',
          'failure_category': failure, 'source_sha256': sources, 'checks': checks, 'record': record,
          'missing_field_fixed': missing_fixed}
(d / 'raw.json').write_text(json.dumps(raw, indent=2) + '\n')
(d / 'observation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
'''


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def role_header(task):
    match = re.match(r'\A\s*Role: ([^\r\n]+)\r?\nPhase: ([^\r\n]+)\r?\nSlot: ([^\r\n]+)(?:\r?\n|\Z)',
                     Path(task['brief_path']).read_text())
    return match.groups() if match else (None, None, None)


def authored_assignment(task):
    """Strip only horch's exact task/nonce/result-bound appended suffix."""
    text = Path(task['brief_path']).read_text()
    suffix = '\n\n' + horch.WORKER_RULES.format(result_path=Path(task['result_path']),
                                               task_id=task['task_id'], nonce=task['nonce'])
    if not text.endswith(suffix):
        raise Failure('worker_rules_suffix_not_bound')
    return text[:-len(suffix)]


def design_readonly_git(argv, cwd, refs):
    """Reuse bounded Git grammar, distinguishing query values from paths."""
    if not argv or argv[0] != 'git':
        return None
    words = argv[1:]
    if words[:1] == ['-C']:
        if len(words) < 3 or words[1] != str(cwd):
            return None
        words = words[2:]
    if not words:
        return None
    paths, value = False, False
    for token in words[1:]:
        if value:
            value = False
            continue
        if not paths and token in ('-L', '-n', '--max-count', '--format', '--pretty', '-S', '-G', '--since', '--until'):
            value = True
        elif token == '--':
            paths = True
        elif paths or not token.startswith('-'):
            if not paths and (token in refs or re.fullmatch(r'HEAD(?:[~^]\d*)*|[a-fA-F0-9]{7,64}', token)):
                continue
            if ('~' in token or '\\' in token or '..' in token.split('/')
                    or any(ord(char) < 32 or ord(char) == 127 for char in token)):
                return None
    if words in (['branch', '--show-current'], ['status', '--short', '--branch']):
        return words[0]
    # These fixed diff flags select the index, stable headers, or whitespace
    # checks; they never introduce a path, external process, or output file.
    extra = {'--cached', '--staged', '--check', '--src-prefix=a/', '--dst-prefix=b/'}
    if words[0] == 'diff':
        cleaned, value, paths = [words[0]], False, False
        for token in words[1:]:
            if value:
                cleaned.append(token); value = False; continue
            if token == '--':
                paths = True
            if not paths and token in extra:
                continue
            cleaned.append(token)
            if not paths and token in ('-L', '-n', '--max-count', '--format', '--pretty', '-S', '-G', '--since', '--until'):
                value = True
        words = cleaned
    return support.local_git(['git', *words], cwd, refs)


def replay_worker_artifacts(calls, cwd, targets, result_path):
    """Replay actual declared-output mutations; retain original native events."""
    def require(value):
        if not value:
            raise Failure('worker_artifact_replay_rejected')
    targets=set(targets)
    require(result_path in targets and all(path.is_absolute() and path.resolve()==path and path.is_file()
                                          for path in targets))
    provenance={path:{'first':None,'last':None,'mutations':[],'changes':[]} for path in targets}
    state={};last_result={}
    ordered=sorted(calls,key=lambda event:(event['call_row'],event['result_row']))
    for event in ordered:
        if event['name'] not in ('write','edit'):
            continue
        args=event['args'];raw=args.get('path')
        require(isinstance(raw,str) and bool(raw) and '~' not in raw and '\\' not in raw
                and '..' not in raw.split('/') and not any(ord(char)<32 or ord(char)==127 for char in raw))
        target=(cwd/raw).resolve()
        if target not in targets:
            continue  # Source mutations have their existing independent scope checks.
        require(last_result.get(target,-1)<event['call_row'])
        last_result[target]=event['result_row']
        before=state.get(target)
        if event['name']=='write':
            require(set(args)=={'path','content'} and isinstance(args.get('content'),str))
            candidate=args['content']
        else:
            require(before is not None)
            edits=args.get('edits',[args])
            require(set(args)==({'path','edits'} if 'edits' in args else {'path','oldText','newText'})
                    and isinstance(edits,list) and bool(edits))
            candidate=before
            for edit in edits:
                require(isinstance(edit,dict) and set(edit)==({'oldText','newText'} if 'edits' in args
                        else {'path','oldText','newText'}) and isinstance(edit.get('oldText'),str)
                        and bool(edit['oldText']) and isinstance(edit.get('newText'),str)
                        and candidate.count(edit['oldText'])==1)
                candidate=candidate.replace(edit['oldText'],edit['newText'],1)
        # An error cannot establish whether a partial filesystem write occurred.
        # Never advance successful state or release an uncertain artifact.
        require(event.get('successful') is True)
        state[target]=candidate
        proof=provenance[target]
        if proof['first'] is None:
            require(event['name']=='write')
            proof['first']=event
        proof['last']=event;proof['mutations'].append(event)
        proof['changes'].append({'event':event,'before':before,'after':candidate})
    require(all(provenance[path]['first'] is not None and bool(state[path].strip())
                and state[path].encode('utf-8')==path.read_bytes()
                for path in targets))
    first_result=provenance[result_path]['first']['call_row']
    for event in ordered:
        args=event['args']
        result_mutation=(event['name'] in ('write','edit') and isinstance(args.get('path'),str)
                         and (cwd/args['path']).resolve()==result_path)
        require(result_mutation or event['result_row']<first_result)
    return provenance


def how_summary_refinement(artifacts, calls, cwd, report_path, inputs):
    """Require a real additive evidence paragraph; semantic correctness remains reviewed."""
    def require(value):
        if not value:
            raise Failure('how_summary_refinement_unresolved')
    proof=artifacts[report_path];draft=proof['first']['args']['content']
    texts={name:(cwd/name).read_text() for name in SOURCE_FILES}
    successful=[event for event in calls if event['successful']]
    start=proof['first']['call_row']
    require(bool(draft.strip()) and all(core.workflow_reads(successful,cwd,path,before=start)
            for path in [*(cwd/name for name in SOURCE_FILES),*inputs]))
    def grounded(text):
        for name,line in re.findall(r'\b(money\.py|storage\.py|cli\.py|e2e_import\.py):(\d+)\b',text):
            lines=texts[name].splitlines();number=int(line)
            if 0<number<=len(lines) and lines[number-1].strip() and lines[number-1] in text:
                return True
        return False
    require(grounded(draft))
    for index,change in enumerate(proof['changes']):
        event=change['event']
        if event['name']!='edit':
            continue
        for edit in event['args'].get('edits',[event['args']]):
            old,new=edit['oldText'],edit['newText']
            if new.count(old)!=1:
                continue
            addition=new.replace(old,'',1)
            if not re.search(r'\n[ \t]*\n',addition):
                continue
            for paragraph in re.split(r'\n[ \t]*\n',addition):
                paragraph=paragraph.strip()
                if (paragraph and grounded(paragraph) and paragraph not in draft and paragraph not in change['before']
                        and all(paragraph in later['after'] for later in proof['changes'][index:])):
                    return {'edit_call_row':event['call_row'],'edit_result_row':event['result_row'],
                            'draft_call_row':proof['first']['call_row'],'retained_evidence_paragraph':True}
    raise Failure('how_summary_refinement_unresolved')


def comment_gate_contract(native, task, cwd, bundle, base, scenario, source_hashes):
    """Apply original agent bootstrap and actual review witnesses before release."""
    def require(value):
        if not value:
            raise Failure('comment_native_contract_rejected')
    directory = Path(task['task_dir']).resolve()
    scope = ('cli.py', 'storage.py') if scenario == 'feature' else ('storage.py',)
    guides = [bundle / 'skills' / name for name in ('no-comments/SKILL.md',
              'pstack-herdr/references/agents/comment-sicko.md',
              'pstack-herdr/references/agents/poteto-agent.md', 'poteto-mode/SKILL.md')]
    rows = [json.loads(line) for line in native.read_text().splitlines() if line.strip()]
    texts = [(index, block['text']) for index, row in enumerate(rows)
             if row.get('message', {}).get('role') == 'assistant'
             for block in row['message'].get('content', []) if block.get('type') == 'text'
             and isinstance(block.get('text'), str) and block['text'].strip()]
    require(bool(texts) and texts[0][1].strip() == 'Yes... Ha ha ha... Yes!')
    calls = support.Run.native_events(None, native, include_errors=True)
    successful = [event for event in calls if event['successful']]
    for guide in guides[:2]:
        require(bool(core.workflow_reads(successful, cwd, guide, before=texts[0][0])))
    readable = {*guides, *(cwd / name for name in scope),
                *(directory / name for name in ('brief.md', 'task.json', 'report.md', 'review.json', 'result.json'))}
    diff_argv = ['git', '-C', str(cwd), 'diff', '--src-prefix=a/', '--dst-prefix=b/', base, '--', *scope]
    sha_argv = ['sha256sum', *(str(cwd / name) for name in SOURCE_FILES)]
    diff = subprocess.run(diff_argv, capture_output=True, text=True, timeout=20, check=True).stdout
    hashes = '\n'.join(source_hashes[name] + '  ' + str(cwd / name) for name in SOURCE_FILES)
    observed_diff, observed_hash = [], []
    for event in calls:
        name, args = event['name'], event['args']
        if name in ('read', 'grep', 'find', 'ls'):
            path = (cwd / args['path']).resolve()
            require(path in readable or path == directory or directory in path.parents)
        if name == 'bash':
            argv = support.literal(args.get('command', ''))
            require(argv in (diff_argv, sha_argv)
                    or len(argv) == 2 and argv[0] == 'cat' and (cwd / argv[1]).resolve() in readable)
            if event['successful'] and argv == diff_argv:
                require(event['output'].rstrip('\n') == diff.rstrip('\n')); observed_diff.append(event)
            if event['successful'] and argv == sha_argv:
                require(event['output'].rstrip('\n') == hashes); observed_hash.append(event)
    require(bool(observed_diff) and bool(observed_hash))
    artifacts = replay_worker_artifacts(calls, cwd,
        {directory / name for name in ('report.md', 'review.json', 'result.json')}, directory / 'result.json')
    start = min(artifacts[directory / name]['first']['call_row'] for name in ('report.md', 'review.json'))
    require(max(observed_diff[0]['result_row'], observed_hash[0]['result_row']) < start)
    for path in [*guides, *(cwd / name for name in scope)]:
        require(bool(core.workflow_reads(successful, cwd, path, before=start)))
    # Genuine findings/open work remain intact for lead assessment after release.
    return {'diff_sha256': digest_text(diff), 'source_sha256': source_hashes,
            'bootstrap_before_first_text': True, 'actual_scope_and_observations_verified': True}


def how_native_identity(native, session, cwd, started, captured, spec, guides):
    """Bind actual How native rows without altering a transcript for core's tools."""
    def require(value):
        if not value:
            raise Failure('how_native_identity_or_chain_rejected')
    rows = [json.loads(line) for line in native.read_text().splitlines() if line.strip()]
    header = rows[0] if rows else {}
    require(header.get('type') == 'session' and header.get('version') == 3 and header.get('id')
            and Path(header.get('cwd', '')).resolve() == cwd
            and started <= core.stamp(header['timestamp']) <= captured <= time.time()
            and session.get('agent') == 'pi' and session.get('source') == 'herdr:pi')
    require(Path(session['value']).expanduser().resolve() == native.resolve() if session.get('kind') == 'path'
            else session.get('value') == header['id'])
    seen, call_ids, pending, last, models, efforts = {header['id']}, set(), {}, None, set(), set()
    for row in rows[1:]:
        require(row.get('id') and row['id'] not in seen and row.get('parentId') == last)
        seen.add(row['id']); last = row['id']
        if row.get('type') == 'model_change':
            models.add((row.get('provider'), row.get('modelId')))
        if row.get('type') == 'thinking_level_change':
            efforts.add(row.get('thinkingLevel'))
        message = row.get('message', {})
        if message.get('role') == 'assistant':
            if message.get('model'):
                models.add((message.get('provider'), message['model']))
            for block in message.get('content', []):
                if block.get('type') != 'toolCall':
                    continue
                name, args, identity = block.get('name'), block.get('arguments'), block.get('id')
                require(name in ('read', 'bash', 'write', 'edit', 'grep', 'find', 'ls', 'fffind', 'ffgrep')
                        and isinstance(args, dict) and identity and identity not in call_ids)
                call_ids.add(identity); pending[identity] = name
        elif message.get('role') == 'toolResult':
            identity = message.get('toolCallId')
            require(identity in pending and pending.pop(identity) == message.get('toolName')
                    and type(message.get('isError')) is bool)
    require(not pending and bool(models) and all(model == spec['model']
            and (not spec.get('provider') or provider == spec['provider']) for provider, model in models))
    require(not spec.get('effort') or efforts == {spec['effort']})
    events = support.Run.native_events(None, native)
    for guide in guides:
        require(bool(core.workflow_reads(events, cwd, guide)))


def structure(path):
    """Compare sketch structure, ignoring renames and placeholder bodies."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [item for item in node.body if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str))]
            if any(not isinstance(item, (ast.Pass, ast.Raise)) and not (
                isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and item.value.value is Ellipsis) for item in body):
                raise Failure('design_sketch_contains_implementation')
            node.name, node.body = 'function', [ast.Pass()]
        if isinstance(node, ast.ClassDef):
            node.name = 'type'
        if isinstance(node, ast.arg):
            node.arg = 'argument'
        if isinstance(node, ast.Name) and node.id not in ('str', 'int', 'bool', 'list', 'dict', 'tuple', 'Path', 'None'):
            node.id = 'symbol'
    return ast.dump(tree, include_attributes=False)


def design_worker_protocol(slot, definition, bundle, probe, base, scenario):
    cwd = Path(definition['cwd'])
    writer = definition['phase'] == 'implementation'
    source = ('cli.py', 'storage.py') if scenario == 'feature' else ('storage.py',)
    how = definition['phase'] in ('how-explore', 'how-explain')
    how_forms = (f'''How-only exception for THIS phase: native fffind(pattern: string,
path?: string, exclude?: string|string[], limit?: positive integer); ffgrep has
the same fields plus caseSensitive?: boolean and context?: nonnegative integer.
No cursor, extra fields or null numeric values. pattern is query text, including
empty strings; exclude filters are not roots. path defaults to own cwd, or an
owned absolute/relative path/glob such as **/*.py. No surrounding whitespace,
BOM, home/tilde, .. components, backslash, control characters, braces, commas,
!, or leading -. Resolve only within EXACT_OWN_CWD. No auxiliary/sibling roots.
Use these actually available FFF tools or Git ls-files for discovery, rather
than assuming optional native grep/find/ls exist. Bash grep/find stay forbidden.
The ONLY Bash ls forms are: ls; ls -la; ls {cwd}; ls -la {cwd}.
No other flags/operands/globs/recursion/wrappers. Own session cwd is fixed.
Reader-tree descriptors must equal the immutable pre-dispatch snapshot after
delivery and contain no symlinks; external concurrent mutation is assumed absent.
This is a bounded evidence grammar, not universal FFF support or containment.'''
                 if how else 'No FFF or Bash ls/grep/find exception applies to this phase.')
    refinement = (f'''Feature how-summary refinement witness: FULL-read all four actual owned
source files ({', '.join(SOURCE_FILES)}) and both delivered explorer report inputs
before writing a correct, source-grounded complete report.md draft with native
write. The draft must cite an actual FILE:LINE and quote that exact nonempty
source line. Then use at least one successful native edit to ADD a substantive
source/evidence-boundary or reconciliation paragraph before result.json. Choose
an actual unique existing anchor; newText retains oldText EXACTLY ONCE and adds the new
paragraph separated by a blank line. The new paragraph must cite actual FILE:LINE
and quote its exact nonempty source line, be absent from the draft, and remain
in every later report state through delivery. Do not use placeholders, filler,
a deliberately incorrect draft, prescribed semantic claims or add/remove/re-add
round trips. If no legitimate refinement is justified, stop unresolved rather
than manufacture one. The gate checks actual reads, bytes and edit provenance;
final report correctness and substantive reconciliation require manual review.'''
                  if scenario == 'feature' and slot == 'how-summary' else '')
    return f'''BEGIN DESIGN WORKER EVIDENCE GRAMMAR
Slot {slot}; exact owned cwd {cwd}; source writes {json.dumps(source if writer else [])}.
Only native read/write/edit/bash/grep/find/ls, except the How phase forms below;
no codemode or wrappers. Do not assume optional native grep/find/ls are enabled.
Read the complete actual own brief before other tool calls. Read/search only own
cwd, own canonical task directory, individually declared Guide: FILE under
{bundle / 'skills'} (plus required poteto-mode/poteto-agent), and
individually declared approved Input artifact/Controller input/Integration input
FILES. No task-store parent/sibling listing or traversal, home/global/config roots.
Native ls/find/grep require an explicit owned directory/file; no ../, tilde,
backslash, control-character or symlink paths. offset/limit may be omitted/null
for read; otherwise positive integers, context nonnegative, booleans typed.
Writes/edits only declared canonical flat task outputs plus the source files
above; never brief.md/task.json/state.json. Establish each complete artifact by
native write; later native full writes or exact native edits are allowed. Edits
use nonempty unique oldText and string newText, either one replacement or an
ordered nonempty edits array. Serialize mutations per file after the preceding
result; independent files may batch. Failed mutations do not advance replayed
state and uncertain partial failure is unresolved. Every final artifact must
contain non-whitespace content; final UTF-8 bytes must equal the actual delivered
file. The FIRST result.json mutation is in a separate tool
call after ALL prior tool results; thereafter ONLY serialized result.json
mutations, no other calls. Complete real nonce, question null. All outputs must
be unique flat names declared by Output: NAME, include report.md.
Bash is ONE literal command; no newline ; | & > < backtick dollar or backslash,
even quoted; no shell wrappers/expansion, network/forge/config/delegation or Git
writes. Allowed: pwd; cat or sha256sum ONE allowed FILE; literal readonly Git in
own cwd (optional -C EXACT_OWN_CWD), operations log/blame/show/diff/status/rev-parse/
ls-files/rev-list/diff-tree, flags ONLY --oneline --follow -p --patch --stat
--name-only --name-status --short --porcelain --porcelain=v1 --no-patch --all
--reverse --abbrev-commit --no-renames --no-color --color=never --show-toplevel
--show-prefix --no-commit-id -r --stage -s --no-ext-diff --no-textconv --decorate
--graph; values -L numeric range, -n/--max-count integer, --format/--pretty/-S/-G/
--since/--until one value; equals --max-count= --format= --pretty= --since= --until=
--unified= --grep=; -N numeric, local HEAD ancestry/base {base}/hex refs, owned
paths after optional --. No rev:path, @, absolute outside paths or other flags.
CommentSicko additionally permits ONLY its explicitly supplied exact diff/hash
commands. Implementation writers ONLY additionally may run python3 {probe}
--repo {cwd} --output OWN_TASK_SUBDIRECTORY --mode {scenario if scenario == 'feature' else 'characterize'};
no other worker CLI/helpers/interpreters. This frozen oracle executes real CLI
and writes only that owned scratch directory, never protected task metadata.
Do not delegate, use native subagents, or run a whole playbook. All attempts,
including errors, are audited; violations quarantine before forwarding. This is
post-execution evidence checking, not sandbox or credential containment.
{how_forms}
{refinement}
END DESIGN WORKER EVIDENCE GRAMMAR'''


def design_scope_audit(policy_path, task_id):
    """Narrow all-attempt gate; callers expose only safe metadata on exceptions."""
    policy = core.read_json(policy_path)
    home = policy_path.parent
    def require(value):
        if not value:
            raise Failure('design_worker_scope_rejected')
    def inside(path, root):
        return path == root or root in path.parents
    for filename, digest in policy['integrity'].items():
        require(core.sha(Path(filename)) == digest)
    require(re.fullmatch(r't-[0-9a-f]{6}', task_id))
    directory = Path(policy['task_root']) / task_id
    task = core.read_json(directory / 'task.json')
    state = core.read_json(directory / 'state.json')
    binding = core.read_json(home / 'bindings' / (task_id + '.json'))
    require(Path(task['task_dir']).resolve() == directory and task['task_id'] == task_id
            and Path(task['result_path']).resolve() == directory / 'result.json'
            and Path(task['brief_path']).resolve() == directory / 'brief.md'
            and core.sha(directory / 'task.json') == binding['task_sha256']
            and core.sha(directory / 'brief.md') == binding['brief_sha256']
            and state.get('state') == 'done' and state.get('closed') is True)
    role, phase, slot = role_header(task)
    definition = policy['slots'].get(slot, {})
    require(definition.get('role') == role and definition.get('phase') == phase
            and definition.get('cwd') == task['cwd'] and task['worker'] in policy['roles'].get(role, []))
    spec = policy['workers'][task['worker']]
    require(task['argv'] == horch.launch_args(spec, directory) and task['harness'] == 'pi'
            and task['model'] == spec['model'] and task['workspace_id'] == policy['workspace'])
    cwd, bundle = Path(task['cwd']).resolve(), Path(policy['bundle'])
    assignment = authored_assignment(task)
    protocol = policy['protocols'][slot]
    require(Path(protocol['path']).read_text() == design_worker_protocol(
        slot, definition, bundle, Path(policy['probe']), policy['base'], policy['scenario'])
        and core.sha(Path(protocol['path'])) == protocol['sha256'])
    require(design_worker_protocol(slot, definition, bundle, Path(policy['probe']), policy['base'], policy['scenario']) in assignment)
    names = re.findall(r'^Output: ([A-Za-z0-9_.-]+)$', assignment, re.M)
    expected = ['report.md']
    if phase == 'architect':
        expected += ['sketch.py', 'design.json']
    elif phase.endswith('-judge'):
        expected += ['judgment.json']
    elif phase == 'reader-load':
        expected += ['reader_load.json']
    elif phase == 'no-comments':
        expected += ['review.json']
    require(len(names) == len(set(names)) and set(names) == set(expected))
    inputs = {}
    for item in binding['inputs']:
        target = Path(item['path'])
        require(target.is_file() and target.resolve() == target and core.sha(target) == item['sha256'])
        if item['kind'] == 'worker':
            gate = core.read_json(home / 'gates' / (item['task_id'] + '.json'))
            require(gate.get('verdict') == 'pass' and core.sha(home / 'gates' / (item['task_id'] + '.json')) == item['gate_sha256']
                    and gate['outputs'].get(str(target)) == item['sha256'])
        else:
            require(item['kind'] in ('controller', 'integration') and item.get('native_result_row') is not None)
            if target.name == 'architect-rubric.json':
                require(slot == 'design-judge')
            if target.name == 'implementation-rubric.json':
                require(slot == 'implementation-judge')
        inputs[target] = item['sha256']
    encoded = '--' + re.sub(r'[/\\:]', '-', str(cwd).lstrip('/\\')) + '--'
    session = binding['session']
    value = session.get('value', '')
    if session.get('kind') == 'path':
        candidate = Path(value).expanduser().resolve()
        require(candidate.parent == Path(policy['agent_dir']) / 'sessions' / encoded)
        identity = candidate.stem.rsplit('_', 1)[-1]
    else:
        identity = value
    require(str(uuid.UUID(identity)) == identity)
    paths = list((Path(policy['agent_dir']) / 'sessions' / encoded).glob('*_' + identity + '.jsonl'))
    require(len(paths) == 1 and (session.get('kind') != 'path' or paths[0].resolve() == Path(value).resolve()))
    native = paths[0]
    guides = [bundle / 'skills/poteto-mode/SKILL.md', bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md']
    declared_guides = set(guides)
    for raw in re.findall(r'^Guide: (.+)$', assignment, re.M):
        guide = Path(raw)
        require(guide.is_absolute() and guide.resolve() == guide and guide.is_file()
                and bundle / 'skills' in guide.parents)
        declared_guides.add(guide)
    how = phase in ('how-explore', 'how-explain')
    if how:
        how_native_identity(native, session, cwd, core.stamp(task['created_at']), binding['captured_at'], spec, guides)
    else:
        audit = core.audit_pi(native, session, cwd, core.stamp(task['created_at']), spec, guides, [], [], bundle)
        require(all(item['ok'] for item in audit['checks']))
    header = json.loads(native.read_text().splitlines()[0])
    require(header.get('id') == identity and core.stamp(header['timestamp']) <= binding['captured_at'])
    calls = support.Run.native_events(None, native, include_errors=True)
    successful = [event for event in calls if event['successful']]
    protected = {directory / name for name in ('brief.md', 'task.json', 'state.json')}
    output_paths = {directory / name for name in [*expected, 'result.json']}
    writer = phase == 'implementation'
    source_names = ('cli.py', 'storage.py') if policy['scenario'] == 'feature' else ('storage.py',)
    source_paths = {cwd / name for name in source_names} if writer else set()
    def canonical(raw):
        require(isinstance(raw, str) and bool(raw) and '~' not in raw and '\\' not in raw
                and not any(ord(char) < 32 or ord(char) == 127 for char in raw)
                and '..' not in raw.split('/'))
        lexical = Path(raw) if Path(raw).is_absolute() else cwd / raw
        target = lexical.resolve()
        require(not lexical.is_symlink())
        return target
    def readable(raw, search=False):
        target = canonical(raw)
        require(inside(target, cwd) or inside(target, directory) or target in declared_guides
                or target in inputs and target.is_file())
        return target
    before = binding['source_sha256']
    # Reader source is independently frozen; attempted writes are rejected below.
    if not writer:
        require({name: core.sha(cwd / name) for name in SOURCE_FILES} == before)
    tree_after = support.reader_tree(cwd)
    require(tree_after['symlink_count'] == 0 and binding['reader_tree']['symlink_count'] == 0)
    if how:
        require(policy['how_reader_trees'][slot] == binding['reader_tree'] == tree_after
                and policy['how_trees_captured_at'] <= core.stamp(task['created_at']))
    fields = {'read': {'path', 'offset', 'limit'}, 'write': {'path', 'content'},
              'edit': {'path', 'oldText', 'newText', 'edits'}, 'bash': {'command', 'timeout'},
              'grep': {'pattern', 'path', 'glob', 'ignoreCase', 'literal', 'context', 'limit'},
              'find': {'pattern', 'path', 'limit'}, 'ls': {'path', 'limit'}}
    if how:
        fields.update({'fffind': {'pattern', 'path', 'exclude', 'limit'},
                       'ffgrep': {'pattern', 'path', 'exclude', 'limit', 'caseSensitive', 'context'}})
    for event in calls:
        name, args = event['name'], event['args']
        require(name in fields and set(args) <= fields[name])
        for key, minimum in (('offset', 1), ('limit', 1), ('context', 0)):
            if key in args:
                require(name == 'read' and args[key] is None or type(args[key]) is int and args[key] >= minimum)
        for key in ('ignoreCase', 'literal'):
            if key in args:
                require(type(args[key]) is bool)
        for key in ('pattern', 'glob'):
            if key in args:
                require(isinstance(args[key], str))
        if name in ('fffind', 'ffgrep'):
            raw = args.get('path', '.')
            require(isinstance(args.get('pattern'), str) and isinstance(raw, str) and bool(raw)
                    and raw == raw.strip() and '\ufeff' not in raw
                    and not any(char in raw for char in ('{', '}', ',', '!')) and not raw.startswith('-'))
            target = canonical(raw)
            require(inside(target, cwd))
            require('exclude' not in args or isinstance(args['exclude'], str)
                    or isinstance(args['exclude'], list) and all(isinstance(item, str) for item in args['exclude']))
            require('caseSensitive' not in args or type(args['caseSensitive']) is bool)
        elif name in ('read', 'grep', 'find', 'ls'):
            require('path' in args)
            readable(args['path'], name != 'read')
        elif name in ('write', 'edit'):
            target = canonical(args.get('path'))
            require(target not in protected and target in output_paths | source_paths)
            if name == 'write':
                require(isinstance(args.get('content'), str))
            else:
                edits = args.get('edits')
                if edits is not None:
                    require(set(args) == {'path', 'edits'} and isinstance(edits, list) and bool(edits))
                else:
                    require(set(args) == {'path', 'oldText', 'newText'})
                    edits = [{key: args[key] for key in ('oldText', 'newText')}]
                require(all(isinstance(item, dict) and set(item) == {'oldText', 'newText'}
                            and all(isinstance(item[key], str) for key in item) for item in edits))
        else:
            argv = support.literal(args.get('command', ''))
            require(bool(argv))
            require(args.get('timeout') is None or type(args['timeout']) in (int, float)
                    and math.isfinite(args['timeout']) and args['timeout'] > 0)
            allowed = argv == ['pwd'] or how and argv in (['ls'], ['ls', '-la'], ['ls', str(cwd)], ['ls', '-la', str(cwd)])
            if len(argv) == 2 and argv[0] in ('cat', 'sha256sum'):
                readable(argv[1]); allowed = True
            if argv[0] == 'git':
                allowed = design_readonly_git(argv, cwd, {policy['base']}) is not None
            if phase == 'no-comments':
                scope = ('cli.py', 'storage.py') if policy['scenario'] == 'feature' else ('storage.py',)
                allowed |= argv == ['git', '-C', str(cwd), 'diff', '--src-prefix=a/', '--dst-prefix=b/', policy['base'], '--', *scope]
                allowed |= argv == ['sha256sum', *(str(cwd / name) for name in SOURCE_FILES)]
            if writer and len(argv) == 8 and argv[:2] == ['python3', policy['probe']]:
                output = canonical(argv[5])
                allowed = (argv[2:4] == ['--repo', str(cwd)] and argv[4] == '--output'
                           and argv[6:] == ['--mode', 'feature' if policy['scenario'] == 'feature' else 'characterize']
                           and directory in output.parents and not any(inside(path, output) or inside(output, path) for path in protected | output_paths))
            require(allowed)
    result = core.read_json(directory / 'result.json')
    require(horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed'
            and result.get('question') is None and isinstance(result.get('files'), list)
            and len(result['files']) == len(expected) and all(isinstance(name, str) for name in result['files'])
            and set(result['files']) == set(expected))
    artifacts = replay_worker_artifacts(calls, cwd, output_paths, directory / 'result.json')
    refinement = (how_summary_refinement(artifacts, calls, cwd, directory / 'report.md', inputs)
                  if policy['scenario'] == 'feature' and slot == 'how-summary' else None)
    brief_reads = core.workflow_reads(successful, cwd, directory / 'brief.md')
    require(bool(brief_reads) and all(event in brief_reads or event['call_row'] > brief_reads[0]['result_row'] for event in calls))
    comment_native = (comment_gate_contract(native, task, cwd, bundle, policy['base'], policy['scenario'], before)
                      if phase == 'no-comments' else None)
    return {'schema': 'design/worker-gate/v1', 'verdict': 'pass', 'task_id': task_id, 'slot': slot,
            'calls_audited': len(calls), 'native_sha256': core.sha(native), 'task_sha256': core.sha(directory / 'task.json'),
            'brief_sha256': core.sha(directory / 'brief.md'), 'binding_sha256': core.sha(home / 'bindings' / (task_id + '.json')),
            'outputs': {**{str(directory / name): core.sha(directory / name) for name in [*expected, 'result.json']},
                        **({str(cwd / name): core.sha(cwd / name) for name in source_names} if writer else {})},
            'source_sha256': {name: core.sha(cwd / name) for name in SOURCE_FILES},
            'how_reader_tree_before': policy['how_reader_trees'][slot] if how else None,
            'how_reader_tree_after': tree_after if how else None,
            'comment_native_contract': comment_native, 'how_summary_refinement': refinement,
            'artifact_mutations': {path.name: {'first_call_row': proof['first']['call_row'],
                'last_result_row': proof['last']['result_row'], 'count': len(proof['mutations'])}
                for path, proof in artifacts.items()}}


def design_wait_audit(policy_path, task_id, seconds):
    """Retain raw wait privately; never return model-authored payload on any path."""
    home = policy_path.parent
    try:
        policy = core.read_json(policy_path)
        if not re.fullmatch(r't-[0-9a-f]{6}', task_id) or not 1 <= seconds <= 120:
            raise Failure('invalid_gate_request')
        if any(core.sha(Path(filename)) != digest for filename, digest in policy['integrity'].items()):
            raise Failure('gate_integrity_changed')
        argv = [sys.executable, str(Path(policy['bundle']) / 'skills/agent-workers/scripts/agent-workers.py'),
                'wait', task_id, '--max-seconds', str(seconds)]
        began = time.time()
        try:
            raw = subprocess.run(argv, capture_output=True, text=True, timeout=seconds + 20)
            receipt = {'argv': argv, 'returncode': raw.returncode, 'stdout': raw.stdout, 'stderr': raw.stderr,
                       'started_at': began, 'completed_at': time.time()}
        except subprocess.TimeoutExpired as error:
            decode = lambda value: value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            receipt = {'argv': argv, 'returncode': None, 'stdout': decode(error.stdout), 'stderr': decode(error.stderr),
                       'started_at': began, 'completed_at': time.time()}
        destination = home / 'waits' / task_id
        destination.mkdir(parents=True, exist_ok=True)
        (destination / (str(time.time_ns()) + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        lines = [json.loads(line) for line in receipt['stdout'].splitlines() if line.strip()]
        if receipt['returncode'] != 0 or len(lines) != 1 or lines[0].get('task_id') != task_id:
            raise Failure('invalid_wait')
        event = lines[0]
        if event.get('state') in ('running', 'starting', 'long_running') and event.get('closed') is not True:
            return {'schema': 'design/safe-delivery/v1', 'task_id': task_id, 'verdict': 'pending', 'state': 'pending', 'closed': False}
        if event.get('state') != 'done' or event.get('closed') is not True:
            raise Failure('not_done')
        facts = design_scope_audit(policy_path, task_id)
        target = home / 'gates' / (task_id + '.json')
        if target.exists() and core.read_json(target) != facts:
            raise Failure('gate_changed')
        if not target.exists():
            target.write_text(json.dumps(facts, indent=2) + '\n'); target.chmod(0o444)
        return {'schema': 'design/safe-delivery/v1', 'task_id': task_id, 'verdict': 'pass',
                'state': 'done', 'closed': True, 'gate_sha256': core.sha(target),
                'outputs': list(facts['outputs']), 'native_sha256': facts['native_sha256']}
    except Exception:
        value = {'schema': 'design/safe-delivery/v1', 'task_id': task_id if re.fullmatch(r't-[0-9a-f]{6}', task_id) else None,
                 'verdict': 'fail', 'state': 'quarantined', 'closed': None, 'category': 'worker_scope_or_lifecycle_rejected'}
        if value['task_id']:
            try:
                target = home / 'gates' / (task_id + '.json')
                if not target.exists():
                    target.write_text(json.dumps(value, indent=2) + '\n'); target.chmod(0o444)
            except Exception:
                pass
        return value


class Run(core.Run):
    """Shared process lifecycle, with independent design-specific evaluation."""

    git = support.Run.git
    forge = support.Run.forge
    native_events = support.Run.native_events
    stage = support.Run.stage

    def __init__(self, args):
        super().__init__(args)
        self.branch = 'e2e/' + args.scenario + '-' + format(time.time_ns(), 'x')
        self.probe = self.directory / 'design-oracle.py'
        self.stage_proof, self.task_facts, self.slots = {}, [], {}
        self.base = self.pr = self.config_path = self.original_fixture = None
        self.baseline, self.snapshots = {}, {}
        self.role_workers = {}
        self.worker_sessions = {}
        self.comment_native = {}
        self.agent_dir = Path(self.env.get('PI_CODING_AGENT_DIR') or Path.home() / '.pi/agent').expanduser().resolve()
        self.comment_settings = {}
        self.gate_home = self.directory / 'design-gate'
        self.gate_policy = self.gate_home / 'policy.json'
        self.gate_hash = None
        self.worker_gates = {}
        self.protocols = {}
        self.comment_template = self.directory / 'protocols/comment-assignment.md'
        self.comment_template_hash = None

    def preflight(self):
        self.check('positive_duration', self.args.max_seconds > 0)
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.repo)).resolve() == ROOT)
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
        self.check('controller_is_pi', self.spec.get('harness') == 'pi')
        roles = ['how explorer', 'how explainer', 'architect runners', 'arena cross-judge pool',
                 'feature, refactoring', 'interrogate reviewers', 'judgment and prose']
        if self.args.scenario == 'feature':
            roles.append('arena runners')
        for role in roles:
            value = self.config.get('roles', {}).get(role)
            names = value if isinstance(value, list) else [value]
            self.check('role_' + role.replace(' ', '_'), bool(names) and all(name in self.config['workers']
                       and self.config['workers'][name].get('harness') == 'pi' for name in names))
            self.role_workers[role] = names
        self.check('single_explorer_explainer_implementer_comment', all(len(self.role_workers[r]) == 1 for r in (
            'how explorer', 'how explainer', 'feature, refactoring', 'judgment and prose')))
        overrides = ('--session', '--session-dir', '--session-id', '--no-session', '--continue', '--resume', '-c', '-r')
        self.check('all_worker_default_scoped_sessions', not any(arg == flag or arg.startswith(flag + '=')
                   for name in {name for names in self.role_workers.values() for name in names}
                   for arg in self.config['workers'][name].get('args', []) for flag in overrides))
        self.check('comment_session_environment_supported', not self.env.get('PI_CODING_AGENT_SESSION_DIR')
                   and (not self.env.get('PI_CODING_AGENT_DIR')
                        or Path(self.env['PI_CODING_AGENT_DIR']).expanduser().is_absolute()))
        for path in (self.agent_dir / 'settings.json', self.args.fixture_repo / '.pi/settings.json'):
            self.comment_settings[path] = core.sha(path) if path.is_file() else None
            self.check('comment_default_session_setting_' + str(len(self.comment_settings)),
                       not path.is_file() or not core.read_json(path).get('sessionDir'))
        self.check('architect_panel_and_independent_judge', len(self.role_workers['architect runners']) >= 2
                   and bool(set(self.role_workers['arena cross-judge pool']) - set(self.role_workers['architect runners'])))
        if self.args.scenario == 'feature':
            self.check('arena_panel_and_independent_judge', len(self.role_workers['arena runners']) >= 2
                       and bool(set(self.role_workers['arena cross-judge pool']) - set(self.role_workers['arena runners'])))
        self.check('fixture_root', Path(self.git('rev-parse', '--show-toplevel', repo=self.args.fixture_repo)).resolve() == self.args.fixture_repo)
        self.original_fixture = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo),
                                 self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo))
        self.check('clean_fixture', not self.original_fixture[1])
        origin = self.git('remote', 'get-url', 'origin', repo=self.args.fixture_repo)
        match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', origin)
        self.check('fixture_origin', bool(match) and match[1].lower() == self.args.forge_repo.lower())
        remote = self.forge('repo', 'view', self.args.forge_repo, '--json', 'nameWithOwner,isPrivate')
        self.check('private_forge', remote.get('isPrivate') is True and remote.get('nameWithOwner', '').lower() == self.args.forge_repo.lower())
        remote_base = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.args.base_ref, repo=self.args.fixture_repo).splitlines()
        self.check('one_remote_base', len(remote_base) == 1)
        self.base = remote_base[0].split()[0]
        self.check('exact_existing_baseline', self.original_fixture[0] == self.base
                   and self.git('rev-parse', self.args.base_ref, repo=self.args.fixture_repo) == self.base)
        self.parent_pr = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                                    'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('explicit_open_parent', self.parent_pr.get('state') == 'OPEN' and self.parent_pr.get('headRefName') == self.args.base_ref
                   and self.parent_pr.get('headRefOid') == self.base and self.parent_pr.get('isDraft') is False)
        self.baseline = {name: core.sha(self.args.fixture_repo / name) for name in SOURCE_FILES}
        self.remote_heads = self.git('ls-remote', '--heads', 'origin', repo=self.args.fixture_repo).splitlines()
        self.prs_before = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                                    'number,state,headRefName,baseRefName,isDraft')

    def observe(self, repo, label, mode):
        return json.loads(self.call([sys.executable, self.probe, '--repo', repo, '--output', self.directory / label, '--mode', mode]))

    def setup(self):
        destination = self.directory / 'config/herdr-orchestrator/workers.toml'
        destination.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, destination)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.bundle.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.probe.write_text(ORACLE)
        self.probe.chmod(0o444)
        self.probe_hash = core.sha(self.probe)
        self.before = self.observe(self.args.fixture_repo, 'independent-before', 'characterize')
        self.check('baseline_real_cli_pin', self.before.get('verdict') == 'pass' and self.before.get('source_sha256') == self.baseline)
        self.git('worktree', 'add', '-b', self.branch, self.worktree, self.base, repo=self.args.fixture_repo)
        definitions = [('how-a', 'how explorer', 'how-explore'), ('how-b', 'how explorer', 'how-explore'),
                       ('how-summary', 'how explainer', 'how-explain')]
        definitions += [(f'design-{i}', 'architect runners', 'architect') for i in range(len(self.role_workers['architect runners']))]
        definitions += [('design-judge', 'arena cross-judge pool', 'architect-judge')]
        if self.args.scenario == 'feature':
            definitions += [(f'implementation-{i}', 'arena runners', 'implementation') for i in range(len(self.role_workers['arena runners']))]
            definitions += [('implementation-judge', 'arena cross-judge pool', 'implementation-judge')]
        else:
            definitions += [('implementation', 'feature, refactoring', 'implementation'), ('reader-load', 'how explainer', 'reader-load')]
        definitions += [(f'review-{i}', 'interrogate reviewers', 'interrogate') for i in range(len(self.role_workers['interrogate reviewers']))]
        definitions += [('comment-review', 'judgment and prose', 'no-comments')]
        for slot, role, phase in definitions:
            cwd = self.worktree if slot in ('implementation', 'comment-review') else self.worktree.parent / slot
            if cwd != self.worktree:
                self.git('worktree', 'add', '--detach', cwd, self.base, repo=self.args.fixture_repo)
            self.slots[slot] = {'role': role, 'phase': phase, 'cwd': str(cwd)}
        (self.directory / 'slots.json').write_text(json.dumps(self.slots, indent=2) + '\n')
        self.prepare_protocols()
        self.gate_home.mkdir()
        for name in ('bindings', 'gates', 'waits'):
            (self.gate_home / name).mkdir()
        policy = {'task_root': str(self.task_root.resolve()), 'slots': self.slots, 'roles': self.role_workers,
                  'workers': self.config['workers'], 'bundle': str(self.bundle), 'probe': str(self.probe),
                  'base': self.base, 'scenario': self.args.scenario, 'agent_dir': str(self.agent_dir),
                  'protocols': self.protocols,
                  'comment_template': {'path': str(self.comment_template), 'sha256': self.comment_template_hash},
                  'how_reader_trees': {slot: support.reader_tree(Path(definition['cwd'])) for slot, definition in self.slots.items()
                                       if definition['phase'] in ('how-explore', 'how-explain')},
                  'how_trees_captured_at': time.time(),
                  'workspace': self.caller['workspace_id'],
                  'integrity': {str(ROOT / name): digest for name, digest in self.hashes.items()}}
        policy['integrity'].update({str(self.probe): self.probe_hash,
                                   str(destination): self.config_hash, str(self.config_path): self.config_hash})
        policy['integrity'].update({str(self.bundle / name): digest for name, digest in self.hashes.items() if name.startswith('skills/')})
        policy['integrity'].update({item['path']: item['sha256'] for item in self.protocols.values()})
        policy['integrity'][str(self.comment_template)] = self.comment_template_hash
        self.gate_policy.write_text(json.dumps(policy, indent=2) + '\n')
        self.gate_policy.chmod(0o444)
        self.gate_hash = core.sha(self.gate_policy)
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'design-e2e', '--no-focus', *sum((['--env', key + '=' + self.env[key]] for key in
                         ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL', 'GH_CONFIG_DIR')), []),
                         *(['--env', 'PI_CODING_AGENT_DIR=' + self.env['PI_CODING_AGENT_DIR']]
                           if self.env.get('PI_CODING_AGENT_DIR') else []))
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        sessions = self.directory / 'native-sessions'
        sessions.mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(sessions)]
        self.check('native_controller_started', self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
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

    def prepare_protocols(self):
        """Retain exact generated instruction data outside the bounded lead brief."""
        self.comment_template.parent.mkdir()
        for slot, definition in self.slots.items():
            path = self.comment_template.parent / (slot + '.md')
            path.write_text(design_worker_protocol(slot, definition, self.bundle, self.probe, self.base, self.args.scenario))
            path.chmod(0o444)
            self.protocols[slot] = {'path': str(path), 'sha256': core.sha(path)}
        self.comment_template.write_text(self.comment_brief())
        self.comment_template.chmod(0o444)
        self.comment_template_hash = core.sha(self.comment_template)

    def protocol_before_brief(self, events, task, launch):
        """Bind real complete protocol reads to the complete native brief write."""
        argv = core.literal_horch_command(launch['name'], launch['args'], self.worktree, self.bundle)
        self.check('protocol_brief_operand_unique', bool(argv) and argv.count('--brief') == 1
                   and argv.index('--brief') + 1 < len(argv))
        source = Path(argv[argv.index('--brief') + 1])
        self.check('protocol_brief_source_canonical', source.is_absolute() and source.resolve() == source
                   and source.parent == self.artifacts and source.suffix == '.md')
        writes = core.workflow_writes(events, self.worktree, source, before=launch['call_row'], final=True)
        self.check('protocol_complete_brief_native_write', len(writes) == 1)
        slot = role_header(task)[2]
        items = [self.protocols[slot]]
        if slot == 'comment-review':
            items.append({'path': str(self.comment_template), 'sha256': self.comment_template_hash})
        for item in items:
            path = Path(item['path'])
            self.check('immutable_instruction_data_hash', path.resolve() == path and core.sha(path) == item['sha256'])
            self.check('full_native_instruction_data_read_before_brief_' + path.stem, bool(core.workflow_reads(
                [event for event in events if event['name'] == 'read'], self.worktree, path,
                before=writes[0]['call_row'])))

    def scan(self):
        rows = super().scan()
        if self.gate_hash:
            if core.sha(self.gate_policy) != self.gate_hash:
                raise Failure('immutable_worker_gate_policy_changed')
            if (any(core.sha(Path(item['path'])) != item['sha256'] for item in self.protocols.values())
                    or core.sha(self.comment_template) != self.comment_template_hash):
                raise Failure('immutable_instruction_data_changed')
        for task, _ in rows:
            gate_path = self.gate_home / 'gates' / (task['task_id'] + '.json')
            if gate_path.is_file() and core.read_json(gate_path).get('verdict') != 'pass':
                raise Failure('worker_gate_quarantined_stop')
            if task['task_id'] not in self.worker_sessions:
                try:
                    entry = self.herdr('agent', 'get', task['agent'])['agent']
                    session = entry.get('agent_session') or {}
                    if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and session.get('value')
                            and entry.get('agent_status') == 'working' and entry.get('pane_id') == task.get('pane_id')):
                        inputs = self.capture_worker_inputs(task)
                        binding = {'session': session, 'captured_at': time.time(), 'inputs': inputs,
                                   'task_sha256': core.sha(Path(task['task_dir']) / 'task.json'),
                                   'brief_sha256': core.sha(Path(task['task_dir']) / 'brief.md'),
                                   'source_sha256': {name: core.sha(Path(task['cwd']) / name) for name in SOURCE_FILES},
                                   'reader_tree': support.reader_tree(Path(task['cwd']))}
                        target = self.gate_home / 'bindings' / (task['task_id'] + '.json')
                        target.write_text(json.dumps(binding, indent=2) + '\n'); target.chmod(0o444)
                        self.worker_sessions[task['task_id']] = session
                        (self.directory / 'worker-sessions.json').write_text(json.dumps(self.worker_sessions, indent=2) + '\n')
                except Failure:
                    pass
        return rows

    def capture_worker_inputs(self, task):
        """Bind declared files to prior gates or fixed native-produced stage facts."""
        brief = authored_assignment(task)
        native_paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('input_provenance_one_lead_session', len(native_paths) == 1)
        events = self.native_events(native_paths[0])
        # Run output must already exist in the real lead transcript; never guess
        # a stage from wall time or a self-reported worker identity.
        starts = [event for event in events if event['name'] == 'bash'
                  and (core.literal_horch_command('bash', event['args'], self.worktree, self.bundle) or [])[:2] == ['run', task['worker']]
                  and task['task_id'] in event['output']]
        if len(starts) != 1:
            # A live run command can still be awaiting its native tool result;
            # defer capture, never record an IDLE or guessed-session fallback.
            raise Failure('working_launch_receipt_not_yet_available')
        launch = starts[0]
        self.protocol_before_brief(events, task, launch)
        result = []
        fixed = {'grounding.md', 'architect-task.md', 'architect-rubric.json', 'rationale.md',
                 'implementation-task.md', 'implementation-rubric.json', 'interrogate-task.md'}
        for kind, raw in re.findall(r'^(Input artifact|Controller input|Integration input): (.+)$', brief, re.M):
            path = Path(raw)
            self.check('declared_input_canonical_file', path.is_absolute() and path.resolve() == path and path.is_file())
            digest = core.sha(path)
            if kind == 'Input artifact':
                gates = [(filename, core.read_json(filename)) for filename in (self.gate_home / 'gates').glob('*.json')]
                owners = [(filename, gate) for filename, gate in gates if gate.get('verdict') == 'pass'
                          and gate.get('outputs', {}).get(str(path)) == digest]
                self.check('declared_input_prior_pass_gate', len(owners) == 1)
                filename, gate = owners[0]
                result.append({'kind': 'worker', 'path': str(path), 'sha256': digest,
                               'task_id': gate['task_id'], 'gate_sha256': core.sha(filename)})
            elif kind == 'Controller input':
                self.check('fixed_controller_stage_input', path.parent == self.artifacts and path.name in fixed)
                slot = role_header(task)[2]
                self.check('rubric_only_matching_judge', (path.name != 'architect-rubric.json' or slot == 'design-judge')
                           and (path.name != 'implementation-rubric.json' or slot == 'implementation-judge'))
                writes = core.workflow_writes(events, self.worktree, path, before=launch['call_row'], final=True)
                self.check('actual_controller_stage_input_write', len(writes) == 1)
                result.append({'kind': 'controller', 'path': str(path), 'sha256': digest,
                               'native_result_row': writes[0]['result_row']})
            else:
                slot = role_header(task)[2]
                self.check('bounded_integration_reader_input', slot == 'reader-load' or slot.startswith('review-'))
                self.check('exact_integration_source_input', path.parent == self.worktree and path.name in SOURCE_FILES)
                gates = [core.read_json(filename) for filename in (self.gate_home / 'gates').glob('*.json')]
                self.check('integration_implementation_previously_gated', any(gate.get('verdict') == 'pass'
                           and gate.get('slot', '').startswith('implementation') and not gate['slot'].endswith('judge') for gate in gates))
                reads = core.workflow_reads(events, self.worktree, path, before=launch['call_row'])
                self.check('integration_source_lead_native_read', bool(reads))
                result.append({'kind': 'integration', 'path': str(path), 'sha256': digest,
                               'native_result_row': reads[-1]['result_row']})
        return result

    def prompt(self):
        goal = ('''Add import --dry-run. The option is immediately after import and before the
store path. It validates and calculates exactly like normal import across all
input files, with the same count/totals and errors, but never changes ledger bytes
or creates an absent ledger. It never creates, changes or removes a pending file;
preexisting pending bytes stay unchanged. Keep all normal CLI behavior.
Implement this with the REAL implementation Arena: each configured arena runner
owns its entire independent candidate in its allocated source worktree. Do not
replace Arena with a single writer and a claimed comparison.''' if self.args.scenario == 'feature' else '''Separate pure row staging/validation from persistence inside storage.py.
Keep apply_batch's public signature, CLI results, error codes and exact ledger
bytes unchanged. Name the target data shape and show the call graph. Do not add
wrapper layers or a second validation policy. Delegate the mechanical move to
the configured feature, refactoring worker in the integration worktree. Review
reduced reader load concretely, with baseline and final source citations.''')
        return f'''Read {self.bundle / 'skills/poteto-mode/SKILL.md'} in full first. You are the
native lead for original {self.args.scenario} and Opening a PR. Source bundle:
{self.bundle}. Full-read every applied source separately with native read (no
offset/limit) or literal cat of one file. Required relative skills: {json.dumps(list(READS))}
plus poteto-mode/playbooks/{self.args.scenario}.md. Write its exact eight original
numbered checklist items to {self.artifacts / 'checklist.md'} before delegation.
Also write {self.artifacts / 'phases.json'} with architect [Ground, Sketch, Agree,
Implement, Scrap] and arena [Frame, Fan out, Cross-judge, Pick, Graft, Verify],
with each value a JSON string. Do not skip a mandatory phase or claim an absent
capability. Default Architect Agree has no human checkpoint.

Evaluation tool protocol: direct native read/bash/write/edit and any actually
available optional native grep/find/ls; no codemode, wrappers or native subagents.
Do not assume optional grep/find/ls are enabled by the unchanged Pi startup.
Only phases how-explore/how-explain gain the exact fffind/ffgrep and own-cwd
Bash ls forms in their generated protocol. The lead, reader-load, writers,
judges and CommentSicko do NOT gain those exceptions. Bash grep/find stay banned.
Nested tool results cannot be bound by this evaluator. Preserve configured
models, effort, permission flags, Git hooks/signatures and original Mise roots.
No trust answers, config/auth changes, model substitutions or failure retries.
Controller Bash uses ONE literal command per call: no newline, ; | & > <,
backtick, dollar sign or backslash anywhere, even quoted. No pipelines, shell
expansion, printf/test/ls wrappers or inline interpreters. Use native read/ls/
grep/find for inspection. Actual unchanged isolated worker config is
{self.directory / 'config/herdr-orchestrator/workers.toml'}; do not expand XDG.
Accepted controller forms: python/python3 PROBE --repo PATH --output PATH --mode
MODE; python/python3 BUNDLED_HORCH run|wait|list|close|stats|detect ARGS (no -B);
git (optional -C EXACT_INTEGRATION_CWD) status/diff/show/log/blame/rev-parse/
rev-list/diff-tree/ls-files with the bounded LOCAL GIT flags in worker blocks
(diff additionally --cached/--staged/--check/--src-prefix=a/--dst-prefix=b/);
ls-remote --heads origin optionally one exact refs/heads/BASE_OR_OWN_BRANCH;
no --no-index, external/expanded path operands or output files. Query flag
values remain data, including literal ~; home syntax in filesystem paths is
forbidden. git add [--] cli.py and/or storage.py; git commit -m ONE_LITERAL_TITLE
without -n or hook/signature bypass; git push [-u or
--set-upstream] origin {self.branch}; git branch --show-current; git remote get-url
origin; gh/origin repo view, pr list/view/create (create exact base/head/repo,
ready); cat ONE_FILE without flags; pwd; command -v origin; which origin;
exactly sha256sum ABSOLUTE_COMMENT_TASK_DIR/report.md for the actual slot
comment-review's canonical report only, after its native agent-workers wait proves done
and closed. No flags, extra operands, other task reports/results or review.json
hashes. Hash output never replaces the required complete report/result reads.
No other command is accepted. Use native-written --body-file for multiline PRs.
Controller oracle calls have exactly --repo {self.worktree} --output one NEW
direct child of {self.directory} named native-* --mode characterize|feature.
Each implementation slot owns its cwd from launch through PASS delivery. During
that period do not read/write/search/list its files/directories, run content Git
(diff/show/blame/log/rev-list/diff-tree) there, or execute the oracle against it,
even failed attempts. This includes all Arena candidates and Refactor integration.
Raw gate policy/bindings/waits and task-store parents are NEVER lead-readable by
any tool or Git option. Only exact safe-delivery execution may use the gate path.
Use only bundled {self.bundle / 'skills/agent-workers/scripts/agent-workers.py'} run
for delegation; run includes --caller-pane {self.pane}. NEVER use direct horch
wait/list/stats/close/detect: wait payloads themselves contain untrusted reports.
For EACH task use ONLY this standalone delivery command (repeat pending waits,
never retry failure): python3 {Path(__file__).resolve()} --wait-audit {self.gate_policy} TASK_ID 120
It runs real bounded agent-workers wait privately and returns ONLY safe metadata. Pending
means keep waiting, no payload reads; pass/done/closed allows full-read result.json
and its listed files. Fail/quarantined/blocked/canceled means STOP immediately,
without consuming any output, launching a dependent task, coding or opening a PR.
The full all-attempt native audit is post-execution/pre-forwarding evidence
checking, NOT a sandbox or credential containment. Missing working UUID fails.
Workers must return a Markdown report, list every output in result.json, and
close on successful delivery. Never edit agent-workers task/state/result files.
Every brief's first three nonblank lines are exactly:
Role: <exact configured role>
Phase: <exact phase from slot map>
Slot: <exact slot key>
Then worker, concrete selection reason, scope, absolute mode and poteto-agent
references, and: Do not delegate, use native subagents, or run a whole playbook.
Complete this assignment yourself. Workers cannot commit or write forge state.
Immutable generated protocol FILES (slot, exact path and SHA-256):
{json.dumps(self.protocols, indent=2)}
Before native-writing each full worker brief, FULL-read its own slot's protocol
FILE with native read (no offset/limit). EVERY brief
MUST contain that exact complete generated block verbatim, not just its title.
These data files are lead-only immutable inputs: never write/edit them or grant
workers access to them. Workers receive the complete copied block in their own
brief; they must not read these external protocol files. Explicitly
declare each needed bundled guide FILE as Guide: ABSOLUTE_PATH; no blanket bundle
directory search permission. Required poteto-mode/poteto-agent remain explicit.
Explicitly
declare each output as Output: NAME on a separate line. All slots output report.md;
architect runners also sketch.py/design.json; judges also judgment.json;
reader-load also reader_load.json; CommentSicko also review.json. No other outputs.
Every full brief must be native-written to its OWN unique .md directly under
{self.artifacts}; its last prelaunch mutation is a complete native write. Pass
that exact path as --brief, freeze it at launch, never reuse/edit it or use a
task report/external file directly as --brief. All run flags remain explicit.
Declare each prior worker input FILE with Input artifact: ABSOLUTE_PATH; it must
come from a prior PASSED gate and be fully read after that safe delivery before
launching dependents. No sibling directories, config, unpassed reports or raw waits.
Controller private stage artifacts keep their complete-native-write witnesses:
after any native edit, write the final complete artifact with native write before
consumption/dispatch, and do not edit it after that final witness. This excludes
the separately specified source import/graft protocol.
Fixed lead stage FILES use Controller input: ABSOLUTE_PATH, only native-written
grounding.md/architect-task.md/architect-rubric.json/rationale.md/implementation-task.md/
implementation-rubric.json/interrogate-task.md already completed before launch.
reader-load/formal reviewers may use Integration input: ABSOLUTE_PATH for exact
integration source files, after implementation gate and lead full source reads.
Each input's actual hash and native stage/gate provenance is frozen; arbitrary
lead-listed paths never authorize reads. Reads of hidden rubric remain prohibited
for candidates. No task-store parent/sibling reads or listings, even failed calls.
Configured roles: {json.dumps(self.role_workers)}.
Allocated independent worktrees: {json.dumps(self.slots)}. Use each slot once;
no replacements/retries. All non-implementation worktrees remain source-frozen.
The mandatory comment-review slot is the one exception to baseline reader cwds:
it reads the stable actual integration worktree, with NO source writes.
Only cli.py/storage.py may change for Feature; only storage.py for Refactoring.
Never change money.py, e2e_import.py or other tracked files. No generated files
or private artifacts in Git. Keep notes under {self.artifacts} and worker outputs
inside actual task directories. All source coding is delegated except the
explicit Feature base-import/graft protocol below.

Goal: {goal}
Integration branch {self.branch} at {self.worktree}, exact baseline {self.base}.
Explicit parent PR {self.args.parent_pr} remains ready/open/unmerged; its head
{self.args.base_ref} is the ONLY authorized base. You may push ONLY {self.branch}
and create ONE ready child PR on {self.args.forge_repo}, targeting {self.args.base_ref}.
No merges, auto-merge, babysit, branch deletes or other forge writes. No mutation
of original fixture clone or public source checkout. Resolve one forge from
actual command -v origin and repository resolution; record forge + reason in
{self.artifacts / 'forge.json'} before first PR operation. If absent/unresolvable,
record gh fallback; do not substitute fake commands. Use the same forge for all
PR commands. Read deslop/no-comments/technical-writing/unslop and sequence principle
before commits and diff review. Use conventional titles and original PR sections.
After create, actual PR view JSON includes headRefOid,headRefName,baseRefName,isDraft.
Use literal standalone git, forge, agent-workers run, safe delivery and external-oracle commands. Git add
names files explicitly. No inline interpreters, shell chaining or source scripts.
Native reads/searches handle inspection. No Git signing/hook bypass flags.

After winner integration and the successful final behavior oracle (and any
reader-load/formal review), BEFORE final diff review, ANY commit or PR, run the
mandatory no-comments child review. Read original no-comments and CommentSicko
guides yourself. The supplied bootstrap is required execution-boundary disclosure,
not copied agent content. FULL-read the immutable exact Comment assignment FILE
{self.comment_template} (SHA-256 {self.comment_template_hash}) with native read,
as well as comment-review's protocol FILE above, BEFORE native-writing exactly
the complete assignment body to {self.artifacts / 'comment-brief.md'}.
then launch slot comment-review once on its integration cwd, configured worker
{self.role_workers['judgment and prose'][0]}. No other replacement or retry.
The template is lead-only data, never a worker-readable guide/input and never
passed directly as --brief; preserve the unique complete native-write witness.
Wait for actual done/closed, then full-read result.json, report.md and review.json.
Run literal sha256sum on ONLY this task's absolute canonical report.md path to
obtain report_sha256; no hash before its actual native done/closed delivery.
Write {self.artifacts / 'comment-disposition.json'} with actual task_id,
report_sha256, decision ('accept' or 'unresolved'), summary, findings_assessment,
deletion_count, restored_comments, reruns, architect_sketch, fixes, encoding_offers,
encodings, unenforced_constraints, skips, open_work. All are arrays except the
first four strings and deletion_count integer. Assess real findings against the
original rules, not invented zero findings. A source revision, rejected report,
rerun, deeper How/Why/Architect, encoding approval or unresolved constraint means
STOP unresolved BEFORE commit/PR; retain evidence, no retries or source changes.
The bounded pass path requires no findings needing revision, flags or open work;
then findings_assessment/reruns/architect_sketch/fixes/encodings are empty arrays.
Freeze the inspected source through commit. Preserve complete disposition JSON
verbatim under a No-comments heading in final reply, including all summary fields.

Behavior oracle is immutable {self.probe}; invoke it with standalone python3
--repo PATH --output NEW_EXTERNAL_DIRECTORY --mode characterize|feature. It
runs only the real CLI, derives independent Decimal totals, saves actual output,
exit codes, complete ledger bytes/pending state and original suite. It returns
zero with JSON even when app assertions fail. Do not modify/copy it or write an
evidence.json. After full How delivery, before Architect design/code fan-out, run mode characterize in integration,
output {self.directory / 'native-before'} and full-read observation.json; this is
the frozen behavior pin. Original seven/eight flows must pass. Retain it unchanged.
Final output is {self.directory / 'native-after'} with mode {self.args.scenario if self.args.scenario == 'feature' else 'characterize'}.

HOW: full complex route, two fresh how explorer tasks in how-a/how-b before
first wait, angles cli-contract and staging-persistence. Read all delivered
findings before how-summary. Its brief includes BOTH complete explorer report
bodies and angle keys. Feature how-summary additionally must perform the actual
correct-draft plus substantive retained native-edit refinement required by its
generated protocol; do not substitute another write or invent a refinement. Read the delivered full explanation; include its COMPLETE
EXACT TEXT verbatim in {self.artifacts / 'grounding.md'}. Treat the report body as
opaque text: preserve all backslashes, quotes, Unicode, spacing and line breaks,
including inside Mermaid diagrams. Do not unescape, normalize, reformat, abridge
or edit it. You may add Architect grounding context before or after that exact
body. Original How permits light edits, but this narrower E2E witness requires
literal full-body inclusion. This is Architect Ground. Do not redefine
ownership/layering; persistence remains storage-owned.
If evidence shows a change to ownership is needed, report the required why
investigation as unresolved rather than quietly skipping it.

ARCHITECT: before runners write {self.artifacts / 'architect-task.md'} with common
task + grounding, {self.artifacts / 'architect-rubric.json'} as {{"criteria": [{{"id":
"unique-key", "description": "concrete gradeable criterion"}}]}} (3–6 criteria),
and a todo for all Arena phases. Rubric stays HIDDEN from candidates: do not put
its path/body into candidate briefs. Every candidate gets the exact whole common
task body in its brief and the same grounding path, then only its own output/cwd.
Use ALL architect runners concurrently, before the first wait. Each produces
sketch.py with placeholder bodies (pass/raise NotImplementedError/ellipsis),
usage-first report.md per original rationale template and design.json describing
boundaries, data shape and call graph. Require >=2 structurally distinct whole
sketches, not renamed variations, and screen red flags/interface depth.
After ALL candidate deliveries choose one cross-judge from configured pool,
whose worker is NOT any runner for this round, in design-judge. Give it the
hidden rubric and every actual candidate artifact by anonymous slot label. It
returns judgment.json with scores {{task_id: {{criterion_id: 0..5}}}}, recommendation
(actual candidate task_id) and reason. In parallel read EVERY candidate artifact
end to end; freeze YOUR independent score table in
{self.artifacts / 'architect-scores.json'} (same scores schema) BEFORE reading
judge artifacts. After reading the actual judgment write
{self.artifacts / 'architect-decision.json'} with base_task, scores, judge_task,
comparison, grafts (list), rejected (one per loser), interface_depth, red_flags,
contested (boolean), reason and model_the_domain. Use task IDs for identities.
Compare criterion by criterion, choose a base, assess EACH loser for graft/reject,
explain disagreement rather than copying judge scores. Write the synthesized
usage/signature/module/call-graph package + rationale to
{self.artifacts / 'rationale.md'}. Proceed directly through Agree by default.

BEFORE CODE fan-out write exactly four todo items in
{self.artifacts / 'throughput.md'}, titled {json.dumps(THROUGHPUT)} with concrete
routing and shared-state boundaries. Keep nonapplicable items with n/a + reason.
Refactoring must state target shape and subtraction assessment in its rationale.
Feature repeats a REAL Arena for implementation-0..N and implementation-judge:
use implementation-task.md, implementation-rubric.json, implementation-scores.json,
implementation-decision.json with the SAME schemas and phase rules. Candidates
get exact shared implementation task and synthesized design, never the rubric.
The common implementation task and EVERY candidate brief must include both the
absolute rationale.md path and its complete exact bytes. Read rationale.md back
in full after its write and before framing that task; freeze it through final
verification. Candidates implement and verify independently in disjoint worktrees,
no integration writes, and report actual changes and rejected alternatives. This
conservative driver requires every implementation candidate to pass the real
Feature CLI oracle AND preserve all eleven frozen-before normal observations and
missing-field status exactly; a failed candidate leaves the run unresolved. Cross-judge
starts after all are done. Read every candidate source file in full after delivery.
Assess every loser honestly even when no graft is worthwhile.

FEATURE BASE IMPORT/GRAFT protocol: after implementation-decision.json ONLY,
controller native write imports cli.py/storage.py with content EXACTLY equal to
chosen delivered candidate file. No other source writes. Optional grafts must be
listed in that decision as objects: source_task (loser task_id), path (cli.py or
storage.py), old_text (unique existing fragment), new_text (exact fragment from
read loser file), reason (coherent adaptation rationale). Apply each once with
native edit oldText/newText, in manifest order. No invented implementation code,
no general rewrite; if a necessary coherent adaptation cannot fit this protocol,
report synthesis unresolved. Refactoring has NO controller source-write permission.

Run final oracle yourself on same CLI after implementation. Both scenarios must
preserve every frozen-before normal CLI observation exactly by its original
record label: normalized exit/stdout/stderr, full ledger bytes and pending state,
including malformed/rejected inputs, the actual late missing-field outcome, and
the observed post-replace total_cents summary fault with its replaced ledger.
The matching dry fault case starts from a separate identical initial ledger and
preexisting pending sentinel and must preserve both byte-for-byte.
Feature's new dry-run observations are additional; all eleven original non-dry
observations must still equal frozen before. Feature has no reader-load slot.
Refactoring additionally compares its complete record and missing-field status.
For Refactoring ONLY, then run the reader-load slot using configured how explainer
read-only to compare actual baseline/final source; it returns reader_load.json
with worth_keeping boolean, improvements (concrete list), regressions (list),
citations [{{side: before|after, path: storage.py, line: integer, text: exact source
line}}]. It must explain reader load at named boundaries, not count files.
Refactoring must revert/report unresolved if this assessment shows no gain.

Write {self.artifacts / 'scrap.json'} after implementation with required boolean,
observations list and reason. If repeated architecture friction requires Scrap,
stop unresolved: this bounded run does not silently accept it or auto-retry.
Write {self.artifacts / 'review.json'} with scope, decision and actual diff findings
after the Refactoring-only reader-load assessment (none for Feature) and any
formal review, before committing.
If design remains contested, run FULL configured interrogate reviewers in all
review slots, read the actual interrogate skill/rubric/lenses, use one common
intent/revision/rubric (interrogate-task.md, including exact baseline SHA and
full actual diff text) and all delivered findings; write interrogate.json with
resolved boolean and rationale. Unresolved findings block shipping. Do not
relable a partial review. If not contested record the concrete assessment.
Review actual full git diff. Each small ordered commit must already have a
successful native final oracle run; keep commit count <=3. Final source and pin
stay frozen after verification. Ready child PR must use exact owned head/base.
Write {self.artifacts / 'reply.md'} only after actual ready PR readback, with
original reply fields, alternative table, full throughput items, verification,
retained artifacts and real PR URL. No broader inventory/Interrogate/Scrap claim
beyond what actually ran. Preserve failures; never report a missing stage passed.
'''

    def comment_scope(self):
        return ('cli.py', 'storage.py') if self.args.scenario == 'feature' else ('storage.py',)

    def comment_diff_argv(self):
        return ['git', '-C', str(self.worktree), 'diff', '--src-prefix=a/', '--dst-prefix=b/',
                self.base, '--', *self.comment_scope()]

    def comment_brief(self):
        return f'''Role: judgment and prose
Phase: no-comments
Slot: comment-review
Worker: {self.role_workers['judgment and prose'][0]}
Reason: configured judgment and prose role fits this bounded CommentSicko audit.
{design_worker_protocol('comment-review', self.slots['comment-review'], self.bundle, self.probe, self.base, self.args.scenario)}
Output: report.md
Output: review.json
Guide: {self.bundle / 'skills/no-comments/SKILL.md'}
Guide: {self.bundle / 'skills/pstack-herdr/references/agents/comment-sicko.md'}
Use only direct native read/bash/write/edit/grep/find/ls, no codemode or wrappers.
Do not delegate, use native subagents, or run a whole playbook. Complete this
assignment yourself. No config/model/trust changes, retries, commits or forge.
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
Full-read original bundled guides:
{self.bundle / 'skills/no-comments/SKILL.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/comment-sicko.md'}
{self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'}
{self.bundle / 'skills/poteto-mode/SKILL.md'}
Scope: actual integration files {json.dumps(self.comment_scope())}, cwd
{self.worktree}, base {self.base}; NOT a detached baseline. Full-read each scoped
file and inspect the complete real diff with exactly this standalone command:
{' '.join(self.comment_diff_argv())}
Bind actual source with exactly this standalone command:
sha256sum {' '.join(str(self.worktree / name) for name in SOURCE_FILES)}
Bash accepts ONLY those two exact commands or literal cat ONE_DECLARED_FILE.
No newline, ; | & > < backtick, dollar sign or backslash anywhere, even quoted;
no shell expansion, pipelines, wrappers, extra flags, CLI execution or Git writes.
Native read/grep/find/ls may inspect only scoped files, the four declared guides
or your own task directory. All source is read-only; write/edit ONLY report.md,
review.json and result.json in your actual own agent-workers task directory. Never edit
brief.md, task.json, state.json, application/source/skill or evaluator artifacts.
Return normal actual nonce, question null; result.files lists exactly report.md
and review.json, in either order. Report actual findings, no invented zero flags.
report.md contains scoped touched files, deletion count, MUST KILL flags and skips.
review.json contains inspections (one object per scoped relative path, with path,
excerpt verbatim at least 20 characters and conclusion grounded in that file),
source_sha256 (all four actual source digests), findings (actual path/excerpt/
reason/action objects), deletion_count (nonnegative integer), restored_comments,
must_kill, skips, encoding_offers, unenforced_constraints, open_work (arrays).
This is report-only: recommended changes, rejected/ambiguous findings or any need
for a deeper How/Why/Architect/encoding/approval go into open_work, never edits or
nested delegation. Follow the original CommentSicko scope and report honestly.
'''

    def comment_session(self, task):
        session = self.worker_sessions.get(task['task_id'], {})
        cwd = Path(task['cwd']).resolve()
        encoded = '--' + re.sub(r'[/\\:]', '-', str(cwd).lstrip('/\\')) + '--'
        directory = self.agent_dir / 'sessions' / encoded
        value = session.get('value', '')
        if session.get('kind') == 'path':
            path = Path(value).expanduser().resolve()
            self.check('comment_session_exact_owned_directory', path.parent == directory)
            identity = path.stem.rsplit('_', 1)[-1]
        else:
            identity = value
        try:
            canonical = str(uuid.UUID(identity))
        except (ValueError, AttributeError):
            raise Failure('comment_native_uuid_unavailable') from None
        self.check('comment_canonical_session_uuid', canonical == identity)
        # Only this captured UUID in this exact cwd; no unrelated session scan.
        paths = list(directory.glob('*_' + canonical + '.jsonl'))
        self.check('comment_one_owned_native_session', len(paths) == 1 and (
            session.get('kind') != 'path' or paths[0].resolve() == Path(value).resolve()))
        return paths[0]

    def verify_comment(self, record, events, all_events, final_sources):
        task, launch = record['task'], record['launch']
        self.check('comment_after_stable_verified_implementation', launch['call_row'] > self.review_complete_row)
        for resource in ('no-comments/SKILL.md', 'pstack-herdr/references/agents/comment-sicko.md'):
            self.check('comment_lead_guidance_' + resource, bool(core.workflow_reads(events, self.worktree,
                       self.bundle / 'skills' / resource, before=launch['call_row'])))
        worker = self.config['workers'][task['worker']]
        source = self.comment_session(task)
        saved = self.directory / 'comment-native.jsonl'
        shutil.copy2(source, saved)
        guides = [self.bundle / 'skills' / name for name in ('no-comments/SKILL.md',
                  'pstack-herdr/references/agents/comment-sicko.md',
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
        self.check('comment_original_exact_first_output', bool(texts) and texts[0][1].strip() == 'Yes... Ha ha ha... Yes!')
        calls = self.native_events(saved, include_errors=True)
        successful = [event for event in calls if event['successful']]
        for guide in guides[:2]:
            self.check('comment_original_bootstrap_before_text_' + guide.name, bool(core.workflow_reads(
                successful, self.worktree, guide, before=texts[0][0])))
        directory = record['directory'].resolve()
        scoped = {self.worktree / name for name in self.comment_scope()}
        outputs = {directory / name for name in ('report.md', 'review.json', 'result.json')}
        readable = {*guides, *scoped, *outputs, directory / 'brief.md', directory / 'task.json'}
        sha_argv = ['sha256sum', *(str(self.worktree / name) for name in SOURCE_FILES)]
        diff_output = self.call(['git', '-C', self.worktree, 'diff', '--src-prefix=a/', '--dst-prefix=b/',
                                 self.base, 'HEAD', '--', *self.comment_scope()])
        diffs, hashes = [], []
        for event in calls:
            args = event['args']
            if event['name'] in ('write', 'edit'):
                self.check('comment_all_attempt_writes_owned_reports', isinstance(args.get('path'), str)
                           and (self.worktree / args['path']).resolve() in outputs)
            elif event['name'] in ('read', 'grep', 'find', 'ls'):
                raw = args.get('path', '.')
                self.check('comment_read_argument_known', isinstance(raw, str))
                target = (self.worktree / raw).resolve()
                self.check('comment_all_attempt_reads_scoped', target in readable or target == directory or directory in target.parents)
            elif event['name'] == 'bash':
                argv = support.literal(args.get('command', ''))
                self.check('comment_all_attempt_literal_commands', argv in (self.comment_diff_argv(), sha_argv)
                           or len(argv) == 2 and argv[0] == 'cat' and (self.worktree / argv[1]).resolve() in readable)
                if event['successful'] and argv == self.comment_diff_argv():
                    self.check('comment_full_diff_bound_to_final_commit', event['output'].rstrip('\n') == diff_output.rstrip('\n'))
                    diffs.append(event)
                if event['successful'] and argv == sha_argv:
                    expected = '\n'.join(final_sources[name] + '  ' + str(self.worktree / name) for name in SOURCE_FILES)
                    self.check('comment_source_hashes_bound_to_final_commit', event['output'].rstrip('\n') == expected)
                    hashes.append(event)
        self.check('comment_actual_diff_and_hash_observations', bool(diffs) and bool(hashes))
        artifacts = replay_worker_artifacts(calls, self.worktree, outputs, directory / 'result.json')
        self.check('comment_native_artifacts_exact_replay', all(proof['first'] is not None for proof in artifacts.values()))
        start = min(artifacts[directory / name]['first']['call_row'] for name in ('report.md', 'review.json'))
        for path in [*guides, *scoped]:
            self.check('comment_complete_native_scope_read_' + path.name, bool(core.workflow_reads(
                successful, self.worktree, path, before=start)))
        self.check('comment_observations_before_report', max(diffs[0]['result_row'], hashes[0]['result_row']) < start)
        facts = core.read_json(directory / 'review.json')
        inspections = facts.get('inspections', [])
        self.check('comment_real_scope_evidence', isinstance(inspections, list) and len(inspections) == len(scoped)
                   and {item.get('path') for item in inspections if isinstance(item, dict)} == set(self.comment_scope())
                   and all(isinstance(item.get('excerpt'), str) and len(item['excerpt']) >= 20
                           and item['excerpt'] in (self.worktree / item['path']).read_text()
                           and isinstance(item.get('conclusion'), str) and bool(item['conclusion'].strip()) for item in inspections)
                   and facts.get('source_sha256') == final_sources)
        self.check('comment_typed_actual_findings', type(facts.get('deletion_count')) is int
                   and facts['deletion_count'] >= 0 and all(isinstance(facts.get(key), list) for key in (
                       'findings', 'restored_comments', 'must_kill', 'skips', 'encoding_offers', 'unenforced_constraints', 'open_work')))
        self.check('comment_no_revision_or_unresolved_work', facts['deletion_count'] == 0
                   and all(not facts[key] for key in ('findings', 'restored_comments', 'must_kill',
                                                     'encoding_offers', 'unenforced_constraints', 'open_work')))
        report = (directory / 'report.md').read_text()
        self.check('comment_original_report_fields', all(name in report for name in self.comment_scope())
                   and all(word in report.lower() for word in ('deletion', 'must kill', 'skip')))
        disposition = self.written(events, 'comment-disposition.json', after=self.read_before(record))
        resolved = json.loads(disposition['args']['content'])
        self.check('comment_evidence_bound_lead_disposition', resolved.get('task_id') == task['task_id']
                   and resolved.get('report_sha256') == core.sha(directory / 'report.md') and resolved.get('decision') == 'accept'
                   and isinstance(resolved.get('summary'), str) and bool(resolved['summary'].strip())
                   and all(resolved.get(key) == facts[key] for key in ('deletion_count', 'restored_comments', 'skips',
                       'encoding_offers', 'unenforced_constraints', 'open_work'))
                   and all(resolved.get(key) == [] for key in ('findings_assessment', 'reruns', 'architect_sketch', 'fixes', 'encodings')))
        source_targets = {self.worktree / name for name in SOURCE_FILES}
        self.check('comment_source_frozen_after_launch', not any(event['name'] in ('write', 'edit')
                   and isinstance(event['args'].get('path'), str) and (self.worktree / event['args']['path']).resolve() in source_targets
                   and event['call_row'] > launch['call_row'] for event in all_events))
        self.comment_native = dict(audit, source_sha256=final_sources, diff_sha256=digest_text(diff_output),
                                   report_sha256=core.sha(directory / 'report.md'), audit_completed=True)
        self.comment_disposition = disposition['args']['content']
        self.review_complete_row = max(self.review_complete_row, disposition['result_row'])
        self.stage('no_comments_fresh_review', [launch, record['delivery'], *record['reads'], disposition])

    def gated_deliveries(self, tasks, events, all_events):
        native_path = next((self.directory / 'native-sessions').glob('*.jsonl'))
        native_rows = [json.loads(line) for line in native_path.read_text().splitlines() if line.strip()]
        launches, direct = core.workflow_launches(events, tasks, self.worktree, self.bundle)
        self.check('no_direct_worker_wait_payload', not direct)
        deliveries = {}
        used_briefs = set()
        for task in tasks:
            task_id = task['task_id']
            facts = design_scope_audit(self.gate_policy, task_id)
            gate_path = self.gate_home / 'gates' / (task_id + '.json')
            self.check('independent_all_worker_gate_replay', gate_path.is_file() and core.read_json(gate_path) == facts)
            self.worker_gates[role_header(task)[2]] = {**{key: value for key, value in facts.items() if key not in ('outputs', 'task_id')},
                                                       'task_id_sha256': digest_text(task_id)}
            launch = launches.get(task_id)
            self.check('one_actual_owned_launch', launch is not None)
            self.protocol_before_brief(events, task, launch)
            argv = core.literal_horch_command(launch['name'], launch['args'], self.worktree, self.bundle)
            self.check('unique_owned_brief_operand', argv.count('--brief') == 1 and argv.index('--brief') + 1 < len(argv))
            source = Path(argv[argv.index('--brief') + 1])
            self.check('native_brief_source_owned_unique', source.is_absolute() and source.resolve() == source
                       and source.parent == self.artifacts and source.suffix == '.md' and source not in used_briefs)
            used_briefs.add(source)
            writes = core.workflow_writes(events, self.worktree, source, before=launch['call_row'], final=True)
            expected = source.read_text().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
                result_path=Path(task['result_path']), task_id=task_id, nonce=task['nonce'])
            self.check('full_native_brief_before_launch', len(writes) == 1 and Path(task['brief_path']).read_text() == expected
                       and not any(event['name'] in ('write', 'edit') and isinstance(event['args'].get('path'), str)
                                   and (self.worktree / event['args']['path']).resolve() == source
                                   and event['call_row'] > launch['call_row'] for event in all_events))
            for event in events:
                argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
                if len(argv) != 6 or argv[:4] != ['python3', str(Path(__file__).resolve()), '--wait-audit', str(self.gate_policy)] or argv[4] != task_id:
                    continue
                self.check('native_gate_wait_integer_bound', argv[5].isdigit() and 1 <= int(argv[5]) <= 120)
                value = json.loads(event['output'])
                receipts = [core.read_json(path) for path in (self.gate_home / 'waits' / task_id).glob('*.json')]
                matching = [raw for raw in receipts if event['call_row'] > launch['result_row']
                            and core.stamp(native_rows[event['call_row']]['timestamp']) <= raw['started_at']
                            and raw['completed_at'] <= core.stamp(native_rows[event['result_row']]['timestamp'])
                            and raw['argv'][2:] == ['wait', task_id, '--max-seconds', argv[5]]
                            and raw['argv'][1] == str(self.bundle / 'skills/agent-workers/scripts/agent-workers.py')
                            and raw['returncode'] == 0]
                self.check('native_wrapper_real_private_wait', bool(matching))
                if value.get('verdict') == 'pending':
                    self.check('safe_pending_metadata_only', set(value) == {'schema', 'task_id', 'verdict', 'state', 'closed'}
                               and value.get('task_id') == task_id and value.get('state') == 'pending' and value.get('closed') is False)
                    continue
                expected_safe = {'schema': 'design/safe-delivery/v1', 'task_id': task_id, 'verdict': 'pass',
                                 'state': 'done', 'closed': True, 'gate_sha256': core.sha(gate_path),
                                 'outputs': list(facts['outputs']), 'native_sha256': facts['native_sha256']}
                self.check('safe_delivered_metadata_exact', value == expected_safe)
                witnessed = []
                for raw in matching:
                    lines = [json.loads(line) for line in raw['stdout'].splitlines() if line.strip()]
                    if (len(lines) == 1 and lines[0].get('task_id') == task_id and lines[0].get('state') == 'done'
                            and lines[0].get('closed') is True and lines[0].get('result_path') == task['result_path']):
                        witnessed.append(raw)
                self.check('private_actual_done_closed_bound', bool(witnessed))
                self.check('gate_receipt_before_safe_delivery', gate_path.stat().st_mtime <= core.stamp(native_rows[event['result_row']]['timestamp'])
                           and any(raw['completed_at'] <= gate_path.stat().st_mtime for raw in witnessed))
                deliveries.setdefault(task_id, event)
            self.check('one_safe_worker_delivery', task_id in deliveries)
        self.check('gate_all_launches_delivered', set(deliveries) == set(launches) == {task['task_id'] for task in tasks})
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
        for event in all_events:
            name, args = event['name'], event['args']
            target = None
            if name in ('read', 'grep', 'find', 'ls', 'write', 'edit'):
                raw_path = args.get('path', '.' if name in ('grep', 'find', 'ls') else None)
                self.check('lead_native_path_shape_known', isinstance(raw_path, str))
                self.check('lead_native_path_literal_owned_syntax', bool(raw_path) and '~' not in raw_path
                           and '\\' not in raw_path and '..' not in raw_path.split('/')
                           and not any(ord(char) < 32 or ord(char) == 127 for char in raw_path))
                target = (self.worktree / raw_path).resolve()
            elif name == 'bash':
                argv = support.literal(args.get('command', ''))
                if argv and argv[0] in ('cat', 'sha256sum') and len(argv) == 2:
                    self.check('lead_shell_file_literal_owned_syntax', bool(argv[1]) and '~' not in argv[1]
                               and '\\' not in argv[1] and '..' not in argv[1].split('/')
                               and not any(ord(char) < 32 or ord(char) == 127 for char in argv[1]))
                    target = (self.worktree / argv[1]).resolve()
            active = [task for task in tasks if role_header(task)[1] == 'implementation'
                      and launches[task['task_id']]['call_row'] < event['call_row'] <= deliveries[task['task_id']]['result_row']]
            for task in active:
                owned = Path(task['cwd']).resolve()
                if target is not None:
                    self.check('no_implementation_inspection_during_owned_period', not (
                        target == owned or owned in target.parents or target in owned.parents))
                if name == 'bash':
                    argv = support.literal(args.get('command', ''))
                    if argv[:1] == ['git']:
                        git_cwd, words = self.worktree, argv[1:]
                        if words[:1] == ['-C'] and len(words) >= 3:
                            git_cwd, words = (self.worktree / words[1]).resolve(), words[2:]
                        if words and words[0] in ('diff', 'show', 'blame', 'log', 'rev-list', 'diff-tree'):
                            self.check('no_implementation_content_git_before_gate', not (
                                git_cwd == owned or owned in git_cwd.parents or git_cwd in owned.parents))
                    if len(argv) >= 4 and argv[1:3] == [str(self.probe), '--repo']:
                        repo = (self.worktree / argv[3]).resolve()
                        self.check('no_implementation_execution_before_gate', not (
                            repo == owned or owned in repo.parents or repo in owned.parents))
            if name == 'bash':
                argv = support.literal(args.get('command', ''))
                safe_gate = len(argv) == 6 and argv[:4] == ['python3', str(Path(__file__).resolve()), '--wait-audit', str(self.gate_policy)]
                self.check('raw_gate_access_never_forwarded', safe_gate or str(self.gate_home) not in args.get('command', ''))
            if target:
                self.check('lead_no_raw_gate_or_task_parent_reads', not (target == self.task_root.resolve()
                           or target == self.gate_home or self.gate_home in target.parents))
                roots = {self.worktree, self.bundle, self.artifacts, self.args.fixture_repo,
                         *(Path(definition['cwd']) for definition in self.slots.values()),
                         self.directory / 'native-before', self.directory / 'native-after'}
                exact = {self.probe, self.directory / 'controller-brief.md',
                         self.directory / 'config/herdr-orchestrator/workers.toml', self.comment_template,
                         *(Path(item['path']) for item in self.protocols.values())}
                task_output = any(str(target) in core.read_json(self.gate_home / 'gates' / (task['task_id'] + '.json'))['outputs'] for task in tasks)
                self.check('lead_inspection_owned_roots_only', target in exact or task_output
                           or any(target == root or root in target.parents for root in roots))
                for task in tasks:
                    directory = Path(task['task_dir']).resolve()
                    if target == directory or directory in target.parents:
                        self.check('every_task_access_after_pass_gate', event['call_row'] > deliveries[task['task_id']]['result_row']
                                   and str(target) in core.read_json(self.gate_home / 'gates' / (task['task_id'] + '.json'))['outputs'])
            elif name == 'bash':
                argv = support.literal(args.get('command', ''))
                horch_argv = core.literal_horch_command('bash', args, self.worktree, self.bundle)
                gate_call = len(argv) == 6 and argv[:4] == ['python3', str(Path(__file__).resolve()), '--wait-audit', str(self.gate_policy)]
                if not gate_call and not (horch_argv and horch_argv[0] == 'run'):
                    self.check('no_unparsed_task_artifact_access', not any(task['task_id'] in args.get('command', '')
                               or task['task_dir'] in args.get('command', '') for task in tasks))
            if name in ('write', 'edit'):
                for task in tasks:
                    for filename in core.read_json(Path(task['result_path']))['files']:
                        content = (Path(task['task_dir']) / filename).read_text()
                        if content.strip() and any(content in value for value in strings(args)):
                            self.check('pasted_worker_output_after_pass_gate', event['call_row'] > deliveries[task['task_id']]['result_row'])
        for task in tasks:
            binding = core.read_json(self.gate_home / 'bindings' / (task['task_id'] + '.json'))
            for item in binding['inputs']:
                if item['kind'] == 'worker':
                    self.check('dependent_launch_after_input_pass_gate', launches[task['task_id']]['call_row'] > deliveries[item['task_id']]['result_row'])
        return launches, deliveries

    def task_records(self, tasks, events, all_events):
        launches, deliveries = self.gated_deliveries(tasks, events, all_events)
        self.check('native_launch_and_delivery_binding', set(launches) == set(deliveries) == {t['task_id'] for t in tasks})
        records = {}
        for task in tasks:
            role, phase, slot = role_header(task)
            definition = self.slots.get(slot, {})
            self.check('exact_own_role_phase_slot', definition.get('role') == role and definition.get('phase') == phase
                       and task['worker'] in self.role_workers.get(role, []) and task.get('cwd') == definition.get('cwd') and slot not in records)
            worker = self.config['workers'][task['worker']]
            self.check('worker_config_argv', task.get('model') == worker.get('model') and task.get('harness') == worker.get('harness')
                       and task.get('argv') == horch.launch_args(worker, Path(task['task_dir'])))
            result_path = Path(task['result_path'])
            self.check('worker_result_path', result_path.resolve() == Path(task['task_dir']) / 'result.json')
            result = core.read_json(result_path)
            self.check('worker_result_nonce_identity', horch.validate_result(result, task) == 'valid' and result.get('status') == 'completed')
            session = self.worker_sessions.get(task['task_id'], {})
            self.check('worker_live_session_identity', session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and bool(session.get('value')))
            brief = Path(task['brief_path']).read_text()
            self.check('worker_bounded_protocol', all(word in brief for word in ('Do not delegate', 'codemode', task['worker'],
                       str(self.bundle / 'skills/poteto-mode/SKILL.md'),
                       str(self.bundle / 'skills/pstack-herdr/references/agents/poteto-agent.md'))) and bool(re.search(r'reason|because', brief, re.I)))
            if slot == 'comment-review':
                expected = self.comment_brief().rstrip('\n') + '\n\n' + horch.WORKER_RULES.format(
                    result_path=Path(task['result_path']), task_id=task['task_id'], nonce=task['nonce'])
                self.check('comment_exact_bounded_brief', brief == expected)
                self.check('comment_exact_unique_report_files', isinstance(result.get('files'), list)
                           and len(result['files']) == 2 and all(isinstance(name, str) for name in result['files'])
                           and set(result['files']) == {'report.md', 'review.json'} and result.get('question') is None)
            reads = []
            for path in [result_path, *(Path(task['task_dir']) / name for name in result.get('files', []))]:
                self.check('result_artifact_scope', path.resolve() == result_path.resolve() or Path(task['task_dir']).resolve() in path.resolve().parents)
                proof = core.workflow_reads(events, self.worktree, path, after=deliveries[task['task_id']]['result_row'])
                self.check('all_delivered_artifacts_fully_read', bool(proof))
                reads.append(proof[0])
            reports = core.workflow_report_reads(events, task, self.worktree, deliveries[task['task_id']])
            self.check('worker_report_delivered_read', bool(reports))
            records[slot] = {'task': task, 'launch': launches[task['task_id']], 'delivery': deliveries[task['task_id']],
                             'reads': reads, 'reports': reports, 'directory': Path(task['task_dir']), 'brief': brief}
            self.task_facts.append({'task_id_sha256': digest_text(task['task_id']), 'slot': slot,
                                    'role': role, 'model': worker.get('model'), 'effort': worker.get('effort'),
                                    'session_sha256': digest_text(session['value']), 'argv_sha256': digest_text(json.dumps(task['argv'])),
                                    'result_sha256': core.sha(result_path), 'nonce_validated': True})
        return records

    def written(self, events, filename, before=float('inf'), after=-1):
        matches = core.workflow_writes(events, self.worktree, self.artifacts / filename, after=after, before=before, final=True)
        self.check('native_artifact_' + filename, len(matches) == 1)
        return matches[0]

    def read_before(self, record):
        return max(event['result_row'] for event in record['reads'])

    def panel(self, records, prefix, role):
        selected = [records[f'{prefix}-{i}'] for i in range(len(self.role_workers[role])) if f'{prefix}-{i}' in records]
        self.check('complete_panel_' + prefix, len(selected) == len(self.role_workers[role])
                   and [r['task']['worker'] for r in selected] == self.role_workers[role])
        self.check('parallel_panel_' + prefix, max(r['launch']['result_row'] for r in selected) < min(r['delivery']['call_row'] for r in selected))
        return selected

    def competition(self, events, records, kind, candidates, judge_slot, lower):
        first = min(r['launch']['call_row'] for r in candidates)
        resources = ['arena/SKILL.md']
        if kind == 'architect':
            resources += ['architect/SKILL.md', 'architect/references/runner-prompt.md',
                          'architect/references/rationale-template.md', 'architect/references/design-red-flags.md']
        for resource in resources:
            self.check('guidance_before_' + kind + '_' + resource.replace('/', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=first)))
        common = self.written(events, kind + '-task.md', before=first, after=lower)
        rubric_event = self.written(events, kind + '-rubric.json', before=first, after=lower)
        common_text = common['args']['content']
        rubric_path = self.artifacts / (kind + '-rubric.json')
        rubric = core.read_json(rubric_path)
        criteria = rubric.get('criteria', [])
        keys = {item.get('id') for item in criteria}
        self.check('hidden_gradeable_rubric_' + kind, 3 <= len(criteria) <= 6 and len(keys) == len(criteria)
                   and all(isinstance(key, str) and key for key in keys) and all(item.get('description') for item in criteria))
        self.check('common_task_and_hidden_rubric_' + kind, all(common_text in r['brief']
                   and str(self.artifacts / 'grounding.md') in r['brief']
                   and str(rubric_path) not in r['brief'] and rubric_event['args']['content'] not in r['brief'] for r in candidates))
        if kind == 'implementation':
            package = self.design_package
            package_path = self.artifacts / 'rationale.md'
            package_text = package['args']['content']
            self.check('implementation_uses_frozen_architect_package',
                       str(package_path) in common_text and package_text in common_text
                       and all(str(package_path) in r['brief'] and package_text in r['brief'] for r in candidates)
                       and core.sha(package_path) == self.design_package_hash
                       and bool(core.workflow_reads(events, self.worktree, package_path,
                                after=package['result_row'], before=common['call_row'])))
        judge = records.get(judge_slot)
        self.check('fresh_independent_crossjudge_' + kind, judge is not None and judge['task']['worker'] not in {r['task']['worker'] for r in candidates}
                   and judge['launch']['call_row'] > max(r['delivery']['result_row'] for r in candidates)
                   and str(rubric_path) in judge['brief'] and all(str(r['directory']) in judge['brief'] for r in candidates))
        own = self.written(events, kind + '-scores.json', before=min(e['call_row'] for e in judge['reads']),
                           after=max(self.read_before(r) for r in candidates))
        own_scores = json.loads(own['args']['content']).get('scores', {})
        judgment = core.read_json(judge['directory'] / 'judgment.json')
        identities = {r['task']['task_id'] for r in candidates}
        for label, table in (('parent', own_scores), ('judge', judgment.get('scores', {}))):
            self.check(label + '_criterion_scores_' + kind, set(table) == identities and all(
                set(scores) == keys and all(type(score) is int and 0 <= score <= 5 for score in scores.values()) for scores in table.values()))
        self.check('judge_actual_recommendation_' + kind, judgment.get('recommendation') in identities and bool(judgment.get('reason')))
        decision_event = self.written(events, kind + '-decision.json', after=max(self.read_before(judge), *(self.read_before(r) for r in candidates)))
        decision = json.loads(decision_event['args']['content'])
        base = decision.get('base_task')
        losers = identities - {base}
        self.check('parent_selection_' + kind, base in identities and decision.get('scores') == own_scores
                   and decision.get('judge_task') == judge['task']['task_id'] and decision.get('comparison') and decision.get('reason')
                   and type(decision.get('contested')) is bool and isinstance(decision.get('grafts'), list)
                   and {item.get('source_task') for item in decision.get('rejected', [])} == losers
                   and all(item.get('reason') for item in decision.get('rejected', [])))
        if kind == 'architect':
            self.check('architect_interface_screen', decision.get('model_the_domain')
                       and {item.get('task') for item in decision.get('interface_depth', [])} == identities
                       and {item.get('task') for item in decision.get('red_flags', [])} == identities)
            shapes = []
            for candidate in candidates:
                sketch = candidate['directory'] / 'sketch.py'
                self.check('full_sketch_and_design_read', sketch.is_file() and (candidate['directory'] / 'design.json').is_file()
                           and bool(core.workflow_reads(events, self.worktree, sketch, after=candidate['delivery']['result_row'], before=decision_event['call_row'])))
                shapes.append(structure(sketch))
            self.check('distinct_structural_designs', len(set(shapes)) >= 2)
        self.stage(kind + '_arena', [common, rubric_event, own, decision_event, judge['launch'], judge['delivery']]
                   + [event for candidate in candidates for event in (candidate['launch'], candidate['delivery'])])
        return decision, decision_event

    def native_probe(self, events, directory, mode, expected_sources):
        matches = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if (len(argv) != 8 or Path(argv[0]).name not in ('python', 'python3')
                    or (self.worktree / argv[1]).resolve() != self.probe
                    or argv[2:4] != ['--repo', str(self.worktree)]
                    or argv[4:6] != ['--output', str(directory)] or argv[6:] != ['--mode', mode]):
                continue
            try:
                value = json.loads(event['output'])
                saved = core.read_json(directory / 'observation.json')
            except (OSError, ValueError):
                continue
            if value == saved and value.get('verdict') == 'pass' and value.get('source_sha256') == expected_sources:
                matches.append(event)
        self.check('native_real_cli_' + directory.name, len(matches) == 1)
        return matches[0]

    def authorized_sources(self, all_events, records, decision, selection):
        allowed = {'cli.py', 'storage.py'} if self.args.scenario == 'feature' else {'storage.py'}
        roots = {self.worktree, self.args.fixture_repo, *(Path(slot['cwd']) for slot in self.slots.values())}
        protected = {root / name for root in roots for name in SOURCE_FILES}
        source_events = []
        for event in all_events:
            if event['name'] not in ('write', 'edit'):
                continue
            value = event['args'].get('path')
            self.check('native_write_path_known', isinstance(value, str))
            target = (self.worktree / value).resolve()
            if target in protected:
                self.check('source_write_is_authorized_arena_import', self.args.scenario == 'feature'
                           and target.parent == self.worktree and target.name in allowed
                           and event['call_row'] > selection['result_row'] and event['successful'])
                source_events.append((event, target.name))
            else:
                self.check('controller_notes_outside_source', self.artifacts in target.parents)
        if self.args.scenario == 'refactoring':
            self.check('all_refactoring_source_delegated', not source_events)
            return
        selected = next(r for r in records.values() if r['task']['task_id'] == decision['base_task'])
        chosen = {name: (Path(selected['task']['cwd']) / name).read_text() for name in allowed}
        state = {name: self.git('show', self.base + ':' + name) + '\n' for name in allowed}
        imported, applied = set(), []
        grafts = decision['grafts']
        for event, name in source_events:
            if event['name'] == 'write':
                self.check('chosen_candidate_exact_import', name not in imported and event['args'].get('content') == chosen[name])
                imported.add(name)
                state[name] = event['args']['content']
            else:
                index = len(applied)
                self.check('graft_listed_once', index < len(grafts))
                graft = grafts[index]
                source = next((r for r in records.values() if r['task']['task_id'] == graft.get('source_task')), None)
                old, new = event['args'].get('oldText'), event['args'].get('newText')
                self.check('graft_exact_provenance', source is not None and source['task']['task_id'] != decision['base_task']
                           and source['task']['task_id'] in {r['task']['task_id'] for slot, r in records.items() if slot.startswith('implementation-') and slot != 'implementation-judge'}
                           and name in imported and graft.get('path') == name and graft.get('reason')
                           and isinstance(old, str) and old and isinstance(new, str) and new
                           and graft.get('old_text') == old and graft.get('new_text') == new
                           and state[name].count(old) == 1 and new in (Path(source['task']['cwd']) / name).read_text())
                state[name] = state[name].replace(old, new, 1)
                applied.append(graft)
        self.check('complete_selected_import_and_grafts', imported == allowed and len(applied) == len(grafts)
                   and all((self.worktree / name).read_text() == text for name, text in state.items()))

    def command_allowed(self, command, *, comment_report=None):
        argv = support.literal(command)
        if not argv or any(word in ('--no-verify', '--no-gpg-sign') for word in argv):
            return False
        if comment_report is not None and argv == ['sha256sum', str(comment_report)]:
            return True
        binary = Path(argv[0]).name
        if len(argv) == 6 and argv[:4] == ['python3', str(Path(__file__).resolve()), '--wait-audit', str(self.gate_policy)]:
            return bool(re.fullmatch(r't-[0-9a-f]{6}', argv[4])) and argv[5].isdigit() and 1 <= int(argv[5]) <= 120
        if binary in ('python', 'python3'):
            if len(argv) == 8 and argv[1] == str(self.probe):
                output = Path(argv[5])
                return (argv[2:4] == ['--repo', str(self.worktree)] and argv[4] == '--output'
                        and output.is_absolute() and output.resolve() == output and output.parent == self.directory
                        and output.name.startswith('native-') and argv[6] == '--mode'
                        and argv[7] in ('feature', 'characterize'))
            return (len(argv) >= 3 and argv[1] == str(self.bundle / 'skills/agent-workers/scripts/agent-workers.py')
                    and argv[2] == 'run')
        if binary == 'git':
            rest = argv[1:]
            if rest[:1] == ['-C'] and len(rest) > 2:
                if rest[1] != str(self.worktree):
                    return False
                rest = rest[2:]
            if not rest:
                return False
            if rest[0] in ('status', 'diff', 'show', 'log', 'blame', 'rev-parse', 'rev-list', 'diff-tree', 'ls-files', 'ls-remote'):
                if rest[0] == 'ls-remote':
                    return rest[1:] in (['--heads', 'origin'], ['--heads', 'origin', 'refs/heads/' + self.branch],
                                        ['--heads', 'origin', 'refs/heads/' + self.args.base_ref])
                return design_readonly_git(['git', *rest], self.worktree, {self.base, self.branch, self.args.base_ref}) is not None
            if rest[0] == 'add':
                return bool(rest[1:]) and all(word in ('--', 'cli.py', 'storage.py') for word in rest[1:])
            if rest[0] == 'push':
                return [word for word in rest[1:] if word not in ('-u', '--set-upstream')] == ['origin', self.branch]
            if rest[0] == 'commit':
                return len(rest) == 3 and rest[1] == '-m' and bool(rest[2].strip())
            return rest == ['branch', '--show-current'] or rest == ['remote', 'get-url', 'origin']
        if binary in ('gh', 'origin'):
            if argv[1:3] == ['pr', 'create']:
                return ('--base' in argv and argv.index('--base') + 1 < len(argv)
                        and argv[argv.index('--base') + 1] == self.args.base_ref and '--draft' not in argv
                        and ('--head' not in argv or argv.index('--head') + 1 < len(argv)
                             and argv[argv.index('--head') + 1] == self.branch)
                        and ('--repo' not in argv or argv.index('--repo') + 1 < len(argv)
                             and argv[argv.index('--repo') + 1] == self.args.forge_repo))
            return argv[1:3] in (['repo', 'view'], ['pr', 'view'], ['pr', 'list'])
        return argv in (['command', '-v', 'origin'], ['which', 'origin'], ['pwd']) or binary == 'cat' and len(argv) == 2 and not argv[1].startswith('-')

    def source_snapshot(self, revision, label):
        directory = self.directory / ('snapshot-' + label)
        directory.mkdir()
        for name in SOURCE_FILES:
            data = subprocess.run(['git', '-C', str(self.worktree), 'show', revision + ':' + name],
                                  capture_output=True, timeout=20, check=True).stdout
            (directory / name).write_bytes(data)
        self.snapshots[label] = {name: core.sha(directory / name) for name in SOURCE_FILES}
        return directory

    def verify(self):
        rows = self.scan()
        self.check('all_actual_tasks_done_closed', bool(rows) and all(s.get('state') == 'done' and s.get('closed') is True for _, s in rows))
        tasks = [task for task, _ in rows]
        paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_native_controller_session', len(paths) == 1)
        native_path = paths[0]
        required = [self.bundle / 'skills' / path for path in (*READS, f'poteto-mode/playbooks/{self.args.scenario}.md')]
        events, all_events = self.native_events(native_path), self.native_events(native_path, include_errors=True)
        records = self.task_records(tasks, events, all_events)
        self.check('unique_comment_hash_owner', 'comment-review' in records)
        comment_report = Path(records['comment-review']['task']['task_dir']).resolve() / 'report.md'
        self.native = core.audit_pi(native_path, self.session, self.worktree, self.wall_started, self.spec,
                                    required, [], [], self.bundle)
        self.check('native_model_effort_reads_delivery', all(c.get('ok') is True for c in self.native['checks']))
        self.check('controller_shell_authorization', all(self.command_allowed(e['args'].get('command', ''),
                   comment_report=comment_report) for e in all_events if e['name'] == 'bash'))
        required_slots = set(self.slots) - {slot for slot in self.slots if slot.startswith('review-')}
        self.check('all_mandatory_slots_used_once', required_slots <= set(records))
        first_launch = min(r['launch']['call_row'] for r in records.values())
        checklist = self.written(events, 'checklist.md', before=first_launch)
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / f'skills/poteto-mode/playbooks/{self.args.scenario}.md').read_text(), re.M)
        self.check('exact_original_eight_step_checklist', len(steps) == 8 and re.findall(r'^\d+\. (.+)$', checklist['args']['content'], re.M) == steps)
        for resource in ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
                         'pstack-herdr/references/herdr-tools.md', 'agent-workers/SKILL.md',
                         f'poteto-mode/playbooks/{self.args.scenario}.md'):
            self.check('initial_full_read_' + resource.replace('/', '_'), bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=checklist['call_row'])))
        phases = self.written(events, 'phases.json', before=first_launch)
        self.check('architect_and_arena_phase_todos', json.loads(phases['args']['content']) == {
            'architect': ['Ground', 'Sketch', 'Agree', 'Implement', 'Scrap'],
            'arena': ['Frame', 'Fan out', 'Cross-judge', 'Pick', 'Graft', 'Verify']})
        before = self.native_probe(events, self.directory / 'native-before', 'characterize', self.baseline)
        explorers = [records['how-a'], records['how-b']]
        explanation = records['how-summary']
        self.check('how_loaded_before_exploration', bool(core.workflow_reads(events, self.worktree,
                   self.bundle / 'skills/how/SKILL.md', before=min(r['launch']['call_row'] for r in explorers))))
        self.check('full_how_parallel_exploration', max(r['launch']['result_row'] for r in explorers) < min(r['delivery']['call_row'] for r in explorers)
                   and all(self.read_before(r) < explanation['launch']['call_row'] for r in explorers)
                   and all(body in explanation['brief'] for r in explorers for _, body in r['reports'])
                   and all(key in explanation['brief'] for key in ('cli-contract', 'staging-persistence')))
        grounding = self.written(events, 'grounding.md', after=self.read_before(explanation))
        self.check('full_how_explanation_preserved', all(body in grounding['args']['content'] for _, body in explanation['reports']))
        self.stage('how_ground', [before, checklist, phases, grounding, explanation['launch'], explanation['delivery']])
        designs = self.panel(records, 'design', 'architect runners')
        self.check('characterization_after_how_before_architect', before['call_row'] > self.read_before(explanation)
                   and before['result_row'] < min(r['launch']['call_row'] for r in designs))
        design, selection = self.competition(events, records, 'architect', designs, 'design-judge', max(grounding['result_row'], before['result_row']))
        rationale = self.written(events, 'rationale.md', after=selection['result_row'])
        self.design_package = rationale
        self.design_package_hash = digest_text(rationale['args']['content'])
        package_path = self.artifacts / 'rationale.md'
        self.check('architect_package_frozen_after_selection', core.sha(package_path) == self.design_package_hash
                   and not any(e['name'] in ('write', 'edit') and isinstance(e['args'].get('path'), str)
                               and (self.worktree / e['args']['path']).resolve() == package_path
                               and e['call_row'] > rationale['result_row'] for e in all_events))
        self.check('usage_first_synthesized_rationale', all(heading in rationale['args']['content'] for heading in (
            '## Problem', '## Usage', '## Shape', '## Synthesis decision', '## Alternatives considered')))
        if self.args.scenario == 'feature':
            implementations = self.panel(records, 'implementation', 'arena runners')
        else:
            implementations = [records['implementation']]
        first_code = min(r['launch']['call_row'] for r in implementations)
        throughput = self.written(events, 'throughput.md', before=first_code, after=rationale['result_row'])
        self.check('four_actual_throughput_dimensions', all(re.search(
            r'^[-*] (?:\[ \] )?(?:\*\*)?' + re.escape(label) + r'\.?(?:\*\*)?:?\s+\S.+$',
            throughput['args']['content'], re.M) for label in THROUGHPUT)
            and len(re.findall(r'^[-*] ', throughput['args']['content'], re.M)) == 4)
        if self.args.scenario == 'feature':
            implementation, imported_at = self.competition(events, records, 'implementation', implementations,
                                                          'implementation-judge', throughput['result_row'])
            implementation_scores = self.written(events, 'implementation-scores.json')
            for record in implementations:
                for name in ('cli.py', 'storage.py'):
                    self.check('delivered_candidate_source_read', bool(core.workflow_reads(events, self.worktree, Path(record['task']['cwd']) / name,
                               after=record['delivery']['result_row'], before=implementation_scores['call_row'])))
        else:
            implementation, imported_at = design, selection
            self.check('refactor_follows_target_shape', first_code > throughput['result_row']
                       and str(self.artifacts / 'rationale.md') in implementations[0]['brief'])
        self.authorized_sources(all_events, records, implementation, imported_at)
        self.verify_worktrees(records)
        self.check('integration_clean_and_owned_branch', not self.git('status', '--porcelain=v1', '--untracked-files=all')
                   and self.git('branch', '--show-current') == self.branch)
        commits = self.git('rev-list', '--reverse', self.base + '..HEAD').splitlines()
        self.check('bounded_ordered_commits', 1 <= len(commits) <= 3 and all(
            self.git('rev-parse', commit + '^') == (self.base if index == 0 else commits[index - 1]) for index, commit in enumerate(commits)))
        self.commits = commits
        final_sources = {name: core.sha(self.worktree / name) for name in SOURCE_FILES}
        self.check('original_oracle_and_money_frozen', all(final_sources[name] == self.baseline[name] for name in ('money.py', 'e2e_import.py')))
        mode = 'feature' if self.args.scenario == 'feature' else 'characterize'
        after = self.native_probe(events, self.directory / 'native-after', mode, final_sources)
        self.check('native_final_after_implementation', after['call_row'] > max(self.read_before(r) for r in implementations)
                   and (self.args.scenario != 'feature' or after['call_row'] > imported_at['result_row']))
        final = core.read_json(self.directory / 'native-after/observation.json')
        self.check('frozen_before_receipt', core.read_json(self.directory / 'native-before/observation.json') == self.before)
        if self.args.scenario == 'refactoring':
            self.check('native_exact_cli_equivalence', final['record'] == self.before['record'] and final['missing_field_fixed'] == self.before['missing_field_fixed'])
            self.verify_reader_load(records['reader-load'], events, after)
            self.verify_staging_shape()
        else:
            self.verify_feature_normal_observations(final, 'final')
        self.stage('implementation_verify', [throughput, after] + [r['launch'] for r in implementations])
        scrap = self.written(events, 'scrap.json', after=after['result_row'])
        scrap_data = json.loads(scrap['args']['content'])
        self.check('actual_scrap_assessment', type(scrap_data.get('required')) is bool and isinstance(scrap_data.get('observations'), list) and scrap_data.get('reason'))
        if scrap_data['required']:
            raise Failure('architecture_scrap_required_unresolved')
        self.stage('architect_agree_implement_scrap', [selection, rationale, throughput, after, scrap])
        self.verify_interrogate(records, events, bool(design['contested'] or implementation['contested']), after)
        self.verify_comment(records['comment-review'], events, all_events, final_sources)
        self.verify_commits(events, commits, final_sources, after, mode)
        self.verify_opening(events, all_events, commits[-1], after)
        self.check('oracle_and_baseline_integrity', core.sha(self.probe) == self.probe_hash)

    def verify_feature_normal_observations(self, observation, scope):
        normal_before = self.before['record']
        labels = [row['label'] for row in normal_before]
        self.check('feature_' + scope + '_pinned_eleven_normal_cli_observations', len(normal_before) == 11
                   and len(set(labels)) == len(labels))
        for original in normal_before:
            observed = [row for row in observation['record'] if row.get('label') == original['label']]
            self.check('feature_' + scope + '_normal_cli_equivalence_' + original['label'],
                       len(observed) == 1 and observed[0] == original)
        self.check('feature_' + scope + '_normal_missing_field_status_preserved',
                   observation['missing_field_fixed'] == self.before['missing_field_fixed'])

    def verify_worktrees(self, records):
        for slot, record in records.items():
            cwd = Path(record['task']['cwd'])
            if cwd == self.worktree:
                self.check('integration_slot_scope_' + slot, slot in ('implementation', 'comment-review'))
                continue
            mutable = self.args.scenario == 'feature' and slot.startswith('implementation-') and slot != 'implementation-judge'
            changed = set(self.git('diff', '--name-only', self.base, repo=cwd).splitlines())
            self.check('isolated_source_scope_' + slot, self.git('rev-parse', 'HEAD', repo=cwd) == self.base
                       and (bool(changed) and changed <= {'cli.py', 'storage.py'} if mutable else not changed)
                       and not self.git('ls-files', '--others', '--exclude-standard', repo=cwd))
            if mutable:
                self.snapshots[slot] = {name: core.sha(cwd / name) for name in SOURCE_FILES}
                observation = self.observe(cwd, 'independent-' + slot, 'feature')
                matches_source = observation.get('source_sha256') == self.snapshots[slot]
                if not hasattr(self, 'candidate_outcomes'):
                    self.candidate_outcomes = {}
                self.candidate_outcomes[slot] = {
                    'verdict': 'fail',
                    'source_sha256': observation.get('source_sha256'),
                    'observation_sha256': core.sha(self.directory / ('independent-' + slot) / 'observation.json'),
                }
                self.check('candidate_real_cli_pass_' + slot, observation.get('mode') == 'feature'
                           and observation.get('verdict') == 'pass' and matches_source)
                self.verify_feature_normal_observations(observation, 'candidate_' + slot)
                self.candidate_outcomes[slot]['verdict'] = 'pass'

    def verify_reader_load(self, record, events, after):
        self.check('reader_load_reviews_actual_final', record['launch']['call_row'] > after['result_row']
                   and str(self.worktree / 'storage.py') in record['brief'])
        report = core.read_json(record['directory'] / 'reader_load.json')
        self.check('concrete_reader_load_gain', report.get('worth_keeping') is True and bool(report.get('improvements'))
                   and isinstance(report.get('regressions'), list))
        citations = report.get('citations', [])
        self.check('before_and_after_reader_load_citations', {item.get('side') for item in citations} == {'before', 'after'})
        before = self.git('show', self.base + ':storage.py').splitlines()
        final = (self.worktree / 'storage.py').read_text().splitlines()
        for cite in citations:
            lines = before if cite['side'] == 'before' else final
            number = cite.get('line')
            self.check('reader_load_citation_resolves', cite.get('path') == 'storage.py' and type(number) is int
                       and 1 <= number <= len(lines) and bool(cite.get('text')) and cite['text'].strip() == lines[number - 1].strip())
        self.reader_load_end = self.read_before(record)
        self.stage('reader_load_gain', [record['launch'], record['delivery'], *record['reads']])

    def verify_staging_shape(self):
        original = ast.parse(self.git('show', self.base + ':storage.py'))
        changed = ast.parse((self.worktree / 'storage.py').read_text())
        before = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch')
        after = next(node for node in changed.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_batch')
        self.check('public_signature_preserved', ast.dump(before.args) == ast.dump(after.args))
        old_names = {node.name for node in ast.walk(original) if isinstance(node, ast.FunctionDef)}
        helpers = [node for node in ast.walk(changed) if isinstance(node, ast.FunctionDef) and node.name not in old_names]
        called = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(after)
                  if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
        pure_staging = []
        for helper in helpers:
            calls = [node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(helper)
                     if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))]
            if (helper.name in called and any(isinstance(node, ast.For) for node in ast.walk(helper))
                    and any(isinstance(node, ast.Return) for node in ast.walk(helper))
                    and not set(calls) & {'Path', 'open', 'read_text', 'read_bytes', 'write_text', 'write_bytes', 'replace', 'unlink'}):
                pure_staging.append(helper)
        self.check('staging_separate_from_persistence', bool(pure_staging))

    def verify_interrogate(self, records, events, contested, after):
        reviews = [r for slot, r in records.items() if slot.startswith('review-')]
        self.interrogate_used = bool(reviews)
        self.review_complete_row = max(after['result_row'], getattr(self, 'reader_load_end', -1))
        if contested or reviews:
            panel = self.panel(records, 'review', 'interrogate reviewers')
            self.check('formal_review_after_stable_implementation', all(r['launch']['call_row'] > after['result_row'] for r in panel))
            for resource in ('interrogate/SKILL.md', 'interrogate/references/reviewer-prompt.md',
                             'interrogate/references/rubric.md', 'interrogate/references/code-quality-review.md',
                             'interrogate/references/lead-judgment.md'):
                self.check('formal_review_guidance_' + resource.replace('/', '_'), bool(core.workflow_reads(
                    events, self.worktree, self.bundle / 'skills' / resource, before=min(r['launch']['call_row'] for r in panel))))
            common = self.written(events, 'interrogate-task.md', before=min(r['launch']['call_row'] for r in panel), after=after['result_row'])
            self.check('formal_review_common_target', self.base in common['args']['content']
                       and self.git('diff', self.base, 'HEAD') in common['args']['content']
                       and all(common['args']['content'] in r['brief'] for r in panel))
            verdict = self.written(events, 'interrogate.json', after=max(self.read_before(r) for r in panel))
            data = json.loads(verdict['args']['content'])
            self.check('formal_review_findings_resolved', data.get('resolved') is True and data.get('rationale'))
            self.review_complete_row = max(self.review_complete_row, verdict['result_row'])
            self.stage('formal_interrogate', [common, verdict, *[r['delivery'] for r in panel]])

    def verify_commits(self, events, commits, final_sources, after, mode):
        allowed = {'cli.py', 'storage.py'} if self.args.scenario == 'feature' else {'storage.py'}
        commit_events = []
        for event in events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if argv and argv[0] == 'git' and 'commit' in argv:
                commit_events.append(event)
        self.check('all_actual_commits_witnessed', len(commit_events) == len(commits))
        for index, (commit, event) in enumerate(zip(commits, commit_events)):
            changed = set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines())
            self.check('commit_scope_and_output', bool(changed) and changed <= allowed and commit[:7] in event['output'])
            snapshot = self.source_snapshot(commit, 'commit-' + str(index))
            replay = self.observe(snapshot, 'replay-commit-' + str(index), mode)
            self.check('every_committed_unit_cli_passes', replay.get('verdict') == 'pass')
            if self.args.scenario == 'refactoring':
                self.check('every_committed_unit_equivalent', replay.get('record') == self.before['record'])
            matches = []
            for observation in events:
                argv = support.literal(observation['args'].get('command', '')) if observation['name'] == 'bash' else []
                if len(argv) != 8 or (self.worktree / argv[1]).resolve() != self.probe or argv[6:] != ['--mode', mode]:
                    continue
                try:
                    value = json.loads(observation['output'])
                except ValueError:
                    continue
                if value.get('verdict') == 'pass' and value.get('source_sha256') == self.snapshots['commit-' + str(index)] and observation['result_row'] < event['call_row']:
                    matches.append(observation)
            self.check('native_verification_before_each_commit', bool(matches))
        self.check('final_source_matches_committed_snapshot', self.snapshots['commit-' + str(len(commits) - 1)] == final_sources)
        review = self.written(events, 'review.json', before=commit_events[0]['call_row'], after=self.review_complete_row)
        self.check('actual_diff_review', bool(json.loads(review['args']['content']).get('decision')))
        expected = self.git('diff', self.base, 'HEAD')
        diffs = []
        for event in events:
            if event['name'] != 'bash':
                continue
            argv = support.literal(event['args'].get('command', ''))
            if len(argv) > 3 and argv[:2] == ['git', '-C'] and argv[2] == str(self.worktree):
                argv = ['git', *argv[3:]]
            if (argv[:2] == ['git', 'diff'] and event['output'].strip() == expected.strip()
                    and event['result_row'] < review['call_row']):
                diffs.append(event)
        self.check('native_full_diff_reviewed', bool(diffs))
        for resource in ('deslop/SKILL.md', 'no-comments/SKILL.md', 'technical-writing/SKILL.md',
                         'unslop/SKILL.md', 'principle-sequence-verifiable-units/SKILL.md'):
            self.check('guidance_before_first_commit_' + resource.split('/')[0], bool(core.workflow_reads(
                events, self.worktree, self.bundle / 'skills' / resource, before=min(review['call_row'], commit_events[0]['call_row']))))
        self.stage('ordered_verified_commits', [review, *commit_events])

    def verify_opening(self, events, all_events, head, after):
        creates, views, pushes, discoveries = [], [], [], []
        for event in all_events:
            argv = support.literal(event['args'].get('command', '')) if event['name'] == 'bash' else []
            if not argv:
                continue
            if argv in (['command', '-v', 'origin'], ['which', 'origin']):
                discoveries.append(event)
            if event['successful']:
                if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'create']:
                    creates.append(event)
                if argv[0] in ('gh', 'origin') and argv[1:3] == ['pr', 'view']:
                    views.append(event)
                if argv[0] == 'git' and 'push' in argv:
                    pushes.append(event)
        self.check('one_real_ready_child_creation', len(creates) == len(pushes) == 1 and bool(discoveries))
        create, push = creates[0], pushes[0]
        choice = self.written(events, 'forge.json', before=min(e['call_row'] for e in creates + views))
        selected = json.loads(choice['args']['content'])
        chosen = selected.get('forge')
        self.check('forge_resolution', chosen in ('gh', 'origin') and selected.get('reason')
                   and discoveries[0]['result_row'] < choice['call_row']
                   and all(support.literal(e['args']['command'])[0] == chosen for e in creates + views))
        if chosen == 'origin':
            self.check('origin_available_before_selection', discoveries[0]['successful'] and bool(discoveries[0]['output'].strip()))
        if chosen == 'gh' and discoveries[0]['successful'] and discoveries[0]['output'].strip():
            self.check('actual_origin_fallback_failure', any(e['name'] == 'bash' and support.literal(e['args'].get('command', ''))[:1] == ['origin']
                       and not e['successful'] and e['result_row'] < choice['call_row'] for e in all_events))
        argv = support.literal(create['args']['command'])
        self.check('explicit_ready_base', '--base' in argv and argv[argv.index('--base') + 1] == self.args.base_ref
                   and '--draft' not in argv and (chosen != 'origin' or ['--status', 'open'] == argv[-2:]))
        pushed = support.literal(push['args']['command'])
        self.check('only_owned_branch_pushed', 'origin' in pushed and self.branch in pushed
                   and not any(word in ('--all', '--mirror', '--delete', '--tags', '-f') or word.startswith('--force') for word in pushed)
                   and max(after['result_row'], self.review_complete_row) < push['call_row'] < create['call_row'])
        readback = [e for e in views if e['call_row'] > create['result_row'] and head in e['output']
                    and self.branch in e['output'] and self.args.base_ref in e['output']]
        self.check('native_real_head_base_readback', bool(readback))
        remote = self.git('ls-remote', '--heads', 'origin').splitlines()
        self.check('remote_scope_unchanged', sorted(remote) == sorted([*self.remote_heads, head + '\trefs/heads/' + self.branch]))
        current = self.forge('pr', 'list', '--repo', self.args.forge_repo, '--state', 'all', '--limit', '1000', '--json',
                             'number,state,headRefName,baseRefName,isDraft')
        added = [p for p in current if p['number'] not in {p['number'] for p in self.prs_before}]
        self.check('one_child_pr_only', len(added) == 1 and all(p in current for p in self.prs_before))
        self.pr = self.forge('pr', 'view', str(added[0]['number']), '--repo', self.args.forge_repo, '--json',
                             'url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,autoMergeRequest')
        (self.directory / 'pr-readback.json').write_text(json.dumps(self.pr, indent=2) + '\n')
        self.check('independent_real_ready_stacked_pr', self.pr.get('state') == 'OPEN' and self.pr.get('isDraft') is False
                   and self.pr.get('headRefName') == self.branch and self.pr.get('headRefOid') == head
                   and self.pr.get('baseRefName') == self.args.base_ref and self.pr.get('baseRefOid') == self.base
                   and self.pr.get('autoMergeRequest') is None)
        parent = self.forge('pr', 'view', str(self.args.parent_pr), '--repo', self.args.forge_repo, '--json',
                            'state,isDraft,headRefOid,headRefName,baseRefName')
        self.check('original_parent_pr_unchanged', parent == self.parent_pr)
        reply = self.written(events, 'reply.md', after=readback[-1]['result_row'])
        self.check('reply_bound_to_real_pr', self.pr['url'] in reply['args']['content']
                   and all(label in reply['args']['content'] for label in THROUGHPUT))
        self.check('reply_preserves_no_comments_disposition', 'No-comments' in reply['args']['content']
                   and self.comment_disposition in reply['args']['content'])
        self.stage('opening_a_pr', [choice, push, create, *readback, reply])

    def finish(self):
        cleanup_ok = True
        if self.pane:
            try:
                screen = self.call(['herdr', 'pane', 'read', self.pane, '--source', 'recent', '--lines', '80'], cleanup=True)
                (self.directory / 'controller-pane.json').write_text(screen)
                self.herdr('pane', 'close', self.pane, cleanup=True)
            except Exception:
                cleanup_ok = False
        try:
            # The core scan is sufficient here; do not discover unrelated agents.
            core.Run.scan(self)
        except Exception:
            self.categories.append('task_snapshot_failed')
        discovered = []
        for task in self.tasks.values():
            try:
                state = core.read_json(Path(task['task_dir']) / 'state.json')
                slot = role_header(task)[2]
                gate_path = self.gate_home / 'gates' / (task['task_id'] + '.json')
                gate = core.read_json(gate_path) if gate_path.is_file() else {}
                discovered.append({'task_id_sha256': digest_text(task['task_id']),
                                   'slot': slot if slot in self.slots else 'unrecognized',
                                   'model': task.get('model'), 'state': state.get('state') if state.get('state') in horch.SETTLED_STATES | {'running', 'long_running'} else 'unrecognized',
                                   'closed_before_cleanup': state.get('closed') is True,
                                   'live_working_binding_captured': task['task_id'] in self.worker_sessions,
                                   'gate_verdict': gate.get('verdict') if gate.get('verdict') in ('pass', 'fail') else 'not_run',
                                   'gate_sha256': core.sha(gate_path) if gate_path.is_file() else None})
            except Exception:
                self.categories.append('owned_task_lifecycle_metadata_unavailable')
        for task in self.tasks.values():
            if role_header(task)[2] == 'comment-review' and task['task_id'] in self.worker_sessions:
                try:
                    shutil.copy2(self.comment_session(task), self.directory / 'retained-comment-native.jsonl')
                except Exception:
                    self.categories.append('comment_native_snapshot_failed')
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
                value = subprocess.run(['herdr', 'pane', 'get', pane], env=self.env, capture_output=True, text=True, timeout=15)
                error = json.loads(value.stdout or value.stderr).get('error', {})
                code = error.get('code') if isinstance(error, dict) else error
                if value.returncode == 0 or code not in horch.MISSING_PANE_CODES:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
        after, config_after, integrity, fixture_integrity = {}, None, False, False
        try:
            after = support.identity()
            config_after = core.sha(self.config_path)
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            integrity = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                         and self.git('rev-parse', 'HEAD', repo=ROOT, cleanup=True) == self.revision
                         and self.git('status', '--porcelain=v1', '--untracked-files=all', repo=ROOT, cleanup=True) == self.source_status
                         and (not copied.exists() or core.sha(copied) == self.config_hash))
            if self.bundle.exists():
                integrity = integrity and all(core.sha(self.bundle / path) == digest for path, digest in self.hashes.items() if path.startswith('skills/'))
            if self.probe.exists():
                integrity = integrity and core.sha(self.probe) == self.probe_hash
            if self.gate_hash:
                integrity = integrity and core.sha(self.gate_policy) == self.gate_hash
                integrity = integrity and all(core.sha(Path(item['path'])) == item['sha256'] for item in self.protocols.values())
                integrity = integrity and core.sha(self.comment_template) == self.comment_template_hash
            integrity = integrity and all((core.sha(path) if path.is_file() else None) == digest
                                          for path, digest in self.comment_settings.items())
            if self.original_fixture is not None:
                fixture_integrity = (self.git('rev-parse', 'HEAD', repo=self.args.fixture_repo, cleanup=True),
                                     self.git('status', '--porcelain=v1', '--untracked-files=all', repo=self.args.fixture_repo, cleanup=True)) == self.original_fixture
        except Exception:
            pass
        self.checks += [{'name': 'public_source_config_bundle_oracle_integrity', 'ok': integrity},
                        {'name': 'original_fixture_unchanged', 'ok': fixture_integrity},
                        {'name': 'owned_panes_absent', 'ok': cleanup_ok}]
        passed = bool(self.checks) and not self.categories and all(check.get('ok') is True for check in self.checks)
        verdict = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory = {name: 'not_run' for name in core.INVENTORY}
        inventory[self.args.scenario] = verdict
        if 'opening_a_pr' in self.stage_proof:
            inventory['opening-a-pr'] = verdict
        if not self.native:
            paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(paths) == 1:
                self.native = {'sha256': core.sha(paths[0]), 'audit_completed': False}
        receipt = {'schema': 'horch/design-playbook-e2e/v1', 'scenario': self.args.scenario,
                   'verdict': 'pass' if passed else 'fail', 'workflow_verdict': verdict,
                   'full_inventory_verdict': 'not_run', 'inventory': inventory,
                   'source_revision': self.revision, 'source_sha256_before': self.hashes, 'source_sha256_after': after,
                   'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
                   'fixture_baseline_sha256': self.baseline, 'source_snapshots': self.snapshots,
                   'architect_package_sha256': getattr(self, 'design_package_hash', None),
                   'candidate_outcomes': getattr(self, 'candidate_outcomes', {}),
                   'native_transcript': self.native, 'native_stages': self.stage_proof, 'tasks': self.task_facts,
                   'discovered_task_lifecycles': discovered, 'all_worker_gate_audits': self.worker_gates,
                   'comment_native': self.comment_native,
                   'mandatory_comment_review_verified': 'no_comments_fresh_review' in self.stage_proof,
                   'controller': {key: self.spec.get(key) for key in ('harness', 'provider', 'model', 'effort')},
                   'checks': self.checks, 'failure_categories': self.categories, 'last_phase': self.phase,
                   'commit_count': len(getattr(self, 'commits', [])), 'interrogate_used': getattr(self, 'interrogate_used', False),
                   'forge': {'ready_pr_verified': passed and self.pr is not None, 'retained': True if self.pr else 'unconfirmed'},
                   'seconds': round(time.monotonic() - self.started, 3),
                   'limitations': [
                       'Only the selected Feature or Refactoring route is run; other inventory entries remain not_run.',
                       'Full complex How and Architect are required; Feature additionally requires real implementation Arena.',
                       'Controller imports must exactly match a delivered base; each graft replacement must be a read loser fragment with coherent rationale.',
                       'A necessary synthesis edit outside that conservative provenance protocol remains unresolved.',
                       'Architecture requiring Scrap/reframing remains unresolved; this bounded driver never invents a replacement design round.',
                       'Formal Interrogate runs the entire configured panel only when contested or explicitly used; unresolved review blocks shipping.',
                       'A fresh configured judgment and prose worker performs the mandatory CommentSicko review on the stable integration diff; any required revision, rejected report, rerun or deeper follow-up leaves this bounded run unresolved.',
                       'Only how-explore/how-explain admit the declared typed own-cwd fffind/ffgrep subset and four literal own-cwd ls forms, on trees identical to pre-dispatch symlink-free snapshots; all other roles retain their tool grammar. Safe wait gates are post-execution pre-forwarding checks, not containment, and assume no external concurrent tree mutation.',
                       'CLI equivalence normalizes traceback locations to their final exception line; raw complete stderr remains private.',
                       'Worktrees, owned branch, private artifacts and ready PR are retained; no merge or auto-merge is authorized.',
                   ]}
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    if sys.argv[1:2] == ['--wait-audit']:
        # Never let parser exceptions or raw wait/model payload escape this lane.
        try:
            if len(sys.argv) != 5:
                raise ValueError('invalid_gate_arguments')
            value = design_wait_audit(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
        except Exception:
            value = {'schema': 'design/safe-delivery/v1', 'verdict': 'fail', 'state': 'quarantined',
                     'category': 'worker_scope_or_lifecycle_rejected'}
        print(json.dumps(value, sort_keys=True))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', required=True, choices=('feature', 'refactoring'))
    parser.add_argument('--controller', required=True, help='existing configured Pi worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='trusted orchestrator source root')
    parser.add_argument('--fixture-repo', type=Path, required=True, help='existing clean private fixture clone')
    parser.add_argument('--forge-repo', required=True, help='private fixture owner/name')
    parser.add_argument('--base-ref', required=True, help='existing exact remote parent branch; never trunk')
    parser.add_argument('--parent-pr', type=int, required=True, help='existing ready open parent PR whose head is base-ref')
    parser.add_argument('--output', type=Path, required=True, help='private external artifact parent')
    parser.add_argument('--caller-pane', required=True, help='independently verified actual caller pane')
    parser.add_argument('--max-seconds', type=int, default=5400, help='overall deadline; no automatic retries')
    args = parser.parse_args()
    for key in ('repo', 'fixture_repo', 'output'):
        setattr(args, key, getattr(args, key).expanduser().resolve())
    if args.repo != ROOT:
        parser.error('--repo must identify this driver source checkout')
    if any(args.output == root or root in args.output.parents for root in (ROOT, args.fixture_repo)):
        parser.error('--output must be outside source and fixture checkouts')
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
