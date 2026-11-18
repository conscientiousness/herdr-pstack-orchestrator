#!/usr/bin/env python3
"""Original Runtime forensics E2E on one owned live Node process.

No application fix, forge action, installation, retry, or model substitution.
Private sources, protocol records and native sessions remain in --output.

Failure boundaries considered before implementation: unavailable WebSocket or Pi;
wrong inspector/PID/nonce/source/session; target exit or restart; empty/unrelated
profile; reduction unsupported or invented; instrumentation of a nonexistent
symbol; fabricated counters; foreground/request-driven work; incomplete native
reads, failed unauthorized writes, reordered or unbound calls; changed sources,
configuration or public HEAD; ambiguous cleanup. All fail closed. Only a live
end-to-end run can establish the workflow verdict.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
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
from urllib.parse import unquote, urlsplit

import playbook_loop as core
import forge_loop as forge

ROOT = Path(__file__).resolve().parents[1]
Failure = core.Failure
horch = core.horch
READS = ('poteto-mode/SKILL.md', 'pstack-herdr/SKILL.md',
         'pstack-herdr/references/herdr-tools.md', 'herdr-orchestrator/SKILL.md',
         'poteto-mode/playbooks/runtime-forensics.md', 'control-cli/SKILL.md',
         'benchmark-checklist/SKILL.md', 'principle-guard-the-context-window/SKILL.md',
         'principle-explain-the-number/SKILL.md', 'unslop/SKILL.md')
CHECKPOINT = 'throughput checkpoint: n/a, read-only forensics'

TARGET = r'''import http from 'node:http';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
const workload = JSON.parse(readFileSync(new URL('./workload.json', import.meta.url)));
const identity = Object.freeze({pid: process.pid, nonce: process.argv[2],
  sourceSha256: createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex')});
Object.defineProperty(globalThis, '__identity', {value: identity});
globalThis.__ledger = {requests: 0, ticks: 0, lastTotal: 0};
globalThis.lookupReference = function lookupReference(references, account) {
  for (const [key, value] of references) {
    if (key === account) return value;
  }
  throw new Error('Missing account');
};
globalThis.reconcileLedger = function reconcileLedger() {
  let total = 0;
  for (const [account, amount] of workload.payments) {
    total += globalThis.lookupReference(workload.references, account) * amount;
  }
  return total;
};
globalThis.scheduledReconciliation = function scheduledReconciliation() {
  globalThis.__ledger.lastTotal = globalThis.reconcileLedger();
  globalThis.__ledger.ticks++;
};
const server = http.createServer((request, response) => {
  globalThis.__ledger.requests++;
  response.setHeader('content-type', 'application/json');
  response.end(JSON.stringify(globalThis.__ledger));
});
server.listen(0, '127.0.0.1', () => {
  const timer = setInterval(() => globalThis.scheduledReconciliation(), 65);
  console.log(JSON.stringify({identity, http: server.address(), intervalMs: 65}));
  process.once('SIGTERM', () => {clearInterval(timer); server.close(() => process.exit(0));});
});
'''

# This immutable tool accepts fixed forensic actions, never caller-supplied JS.
# Its daemon retains one WebSocket connection throughout the native workflow.
PROBE = r'''import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import net from 'node:net';
import path from 'node:path';
const sha = data => createHash('sha256').update(data).digest('hex');
const read = name => JSON.parse(readFileSync(name, 'utf8'));
const put = (name, value) => writeFileSync(name, JSON.stringify(value, null, 2) + '\n', {flag: 'wx', mode: 0o400});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function reduce(profile) {
  const nodes = new Map(profile.nodes.map(node => [node.id, node]));
  const parents = new Map();
  for (const node of profile.nodes) for (const child of node.children || []) parents.set(child, node.id);
  const counts = new Map();
  for (const id of profile.samples || []) counts.set(id, (counts.get(id) || 0) + 1);
  return [...counts].map(([id, samples]) => {
    const node = nodes.get(id), callers = [];
    let parent = parents.get(id);
    while (parent !== undefined && callers.length < 12) {
      const ancestor = nodes.get(parent);
      callers.push(ancestor.callFrame); parent = parents.get(parent);
    }
    return {id, samples, frame: node.callFrame, callers};
  }).sort((a,b) => b.samples - a.samples || a.id - b.id);
}
if (process.argv[2] === '--reduce-file') {
  if (process.argv.length !== 4) throw new Error('Expected one profile');
  console.log(JSON.stringify(reduce(read(process.argv[3]))));
} else if (process.argv[2] === '--serve') {
  const descriptor = read(process.argv[3]), root = path.dirname(process.argv[3]);
  const session = randomUUID(), pending = new Map(), parsed = new Map();
  const ws = new WebSocket(descriptor.inspector);
  let serial = 0, busy = false, stopped = false;
  const log = value => appendFileSync(path.join(root, 'protocol.jsonl'), JSON.stringify({time: Date.now(), session, ...value}) + '\n', {mode: 0o600});
  ws.addEventListener('message', event => {
    const message = JSON.parse(String(event.data)); log({direction: 'response', message});
    if (message.method === 'Debugger.scriptParsed') parsed.set(message.params.scriptId, message.params);
    if (message.id) {
      const waiter = pending.get(message.id); pending.delete(message.id);
      if (!waiter) throw new Error('Unbound inspector response');
      if (message.error) waiter.reject(new Error(JSON.stringify(message.error))); else waiter.resolve(message.result);
    }
  });
  ws.addEventListener('close', () => {if (!stopped) process.exit(2);});
  await new Promise((resolve, reject) => {ws.addEventListener('open', resolve, {once:true}); ws.addEventListener('error', reject, {once:true});});
  async function cdp(method, params = {}) {
    const id = ++serial, message = {id, method, params};
    log({direction: 'request', message});
    return await Promise.race([new Promise((resolve,reject) => {pending.set(id,{resolve,reject}); ws.send(JSON.stringify(message));}),
      new Promise((_, reject) => {const timer = setTimeout(() => reject(new Error('Inspector deadline')), 15000); timer.unref();})]);
  }
  async function evaluate(expression) {
    const response = await cdp('Runtime.evaluate', {expression, returnByValue:true});
    if (response.exceptionDetails || !response.result || response.result.type !== 'object') throw new Error('Runtime expression failed');
    return response.result.value;
  }
  const metricsExpression = '({identity:globalThis.__identity, requests:globalThis.__ledger.requests, ticks:globalThis.__ledger.ticks, lastTotal:globalThis.__ledger.lastTotal, instrumentation:globalThis.__instrumentation ? {symbol:globalThis.__instrumentation.symbol,count:globalThis.__instrumentation.count,stack:globalThis.__instrumentation.stack} : null})';
  async function metrics() {
    const value = await evaluate(metricsExpression);
    if (JSON.stringify(value.identity) !== JSON.stringify(descriptor.identity)) throw new Error('Target identity changed');
    return value;
  }
  await cdp('Runtime.enable'); await cdp('Debugger.enable');
  const initial = await metrics();
  put(path.join(root, 'probe-ready.json'), {session, inspector:descriptor.inspector, initial});
  let stage = 0;
  const server = net.createServer(socket => {
    let buffer = '';
    socket.on('data', chunk => {buffer += chunk; if (buffer.includes('\n')) {
      const line = buffer.slice(0,buffer.indexOf('\n')); buffer = '';
      handle(line).then(value => socket.end(JSON.stringify({ok:true,value}) + '\n'))
        .catch(error => socket.end(JSON.stringify({ok:false,error:String(error)}) + '\n'));
    }});
  });
  async function handle(line) {
    if (busy) throw new Error('Concurrent action'); busy = true;
    try {
      const request = JSON.parse(line), start = Date.now(), firstRequest = serial + 1;
      if (request.nonce !== descriptor.identity.nonce) throw new Error('Nonce mismatch');
      const actions = ['capture','reduce','instrument','observe','source'];
      if (request.action !== actions[stage]) throw new Error('Out of order or repeated action');
      const before = await metrics(); let detail;
      if (request.action === 'capture') {
        await cdp('Profiler.enable'); await cdp('Profiler.setSamplingInterval', {interval:1000});
        await cdp('Profiler.start'); await sleep(1800);
        const result = await cdp('Profiler.stop');
        put(path.join(root,'cpu.cpuprofile'),result.profile);
        detail = {profileSha256:sha(readFileSync(path.join(root,'cpu.cpuprofile'))), samples:result.profile.samples.length};
      } else if (request.action === 'reduce') {
        const rows = reduce(read(path.join(root,'cpu.cpuprofile')));
        put(path.join(root,'reduced-frames.json'), rows);
        detail = {profileSha256:sha(readFileSync(path.join(root,'cpu.cpuprofile'))),
          reductionSha256:sha(readFileSync(path.join(root,'reduced-frames.json'))),
          sampledFrames:rows.length, samples:rows.reduce((n,row)=>n+row.samples,0), top:rows.slice(0,12)};
      } else if (request.action === 'instrument') {
        const symbol = request.symbol;
        if (!['lookupReference','reconcileLedger','scheduledReconciliation'].includes(symbol)) throw new Error('Not an owned source function');
        // Preserve receiver, arguments, return value and thrown errors. No work is invoked here.
        const expression = `(() => { const symbol=${JSON.stringify(symbol)}; const original=globalThis[symbol]; if(typeof original!=='function'||globalThis.__instrumentation||!original.toString().startsWith('function '+symbol+'(')) throw new Error('Existing source function required'); const state={symbol,count:0,stack:null}; globalThis.__instrumentation=state; globalThis[symbol]=function forensicCounter(...args){state.count++; if(state.stack===null) state.stack=new Error('Observed invocation').stack; return Reflect.apply(original,this,args);}; return {symbol,originalSource:original.toString(),installed:true,count:state.count}; })()`;
        detail = await evaluate(expression);
      } else if (request.action === 'observe') {
        // The only work during this window is the application's existing timer.
        await sleep(1400); detail = {windowMs:1400};
      } else {
        const scripts = [...parsed.values()].filter(script => script.url === descriptor.sourceUrl);
        if (scripts.length !== 1) throw new Error('Source script ambiguous');
        const script = scripts[0], result = await cdp('Debugger.getScriptSource', {scriptId:script.scriptId});
        put(path.join(root,'runtime-source.json'), {script, ...result});
        const lines = result.scriptSource.split('\n');
        detail = {scriptId:script.scriptId,url:script.url,sourceSha256:sha(result.scriptSource),
          locations:lines.flatMap((text,index)=> /globalThis\.(lookupReference|reconcileLedger|scheduledReconciliation) = function|setInterval\(/.test(text) ? [{line:index+1,text}] : [])};
      }
      const after = await metrics();
      const value = {schema:'runtime/operation/v1',action:request.action,session,inspector:descriptor.inspector,
        identity:descriptor.identity,start,end:Date.now(),firstRequest,lastRequest:serial,before,after,detail};
      put(path.join(root,request.action+'.json'),value); stage++; return value;
    } finally {busy=false;}
  }
  server.listen(descriptor.socket);
  process.once('SIGTERM',()=>{stopped=true; ws.close();server.close(()=>process.exit(0));});
} else {
  if (process.argv[2] !== '--control') throw new Error('Expected --control descriptor action');
  const descriptor = read(process.argv[3]), action = process.argv[4];
  if (!['capture','reduce','instrument','observe','source'].includes(action)) throw new Error('Unknown action');
  if ((action === 'instrument' && (process.argv.length !== 7 || process.argv[5] !== '--symbol')) ||
      (action !== 'instrument' && process.argv.length !== 5)) throw new Error('Unsupported arguments');
  const request = {action,nonce:descriptor.identity.nonce};
  if (action === 'instrument') request.symbol = process.argv[6];
  const result = await new Promise((resolve,reject)=>{
    const socket=net.createConnection(descriptor.socket), timer=setTimeout(()=>{socket.destroy();reject(new Error('Probe deadline'));},25000);
    let buffer=''; socket.on('connect',()=>socket.write(JSON.stringify(request)+'\n'));
    socket.on('data',chunk=>buffer+=chunk); socket.on('error',reject);
    socket.on('end',()=>{clearTimeout(timer);try {resolve(JSON.parse(buffer));} catch(error){reject(error);}});
  });
  if (!result.ok) throw new Error(result.error);
  console.log(JSON.stringify(result.value));
}
'''


def identity():
    paths = [*ROOT.joinpath('skills').rglob('*'), Path(__file__).resolve(),
             ROOT / 'e2e/playbook_loop.py', ROOT / 'e2e/playbook_cases.py', ROOT / 'e2e/forge_loop.py']
    return {str(path.relative_to(ROOT)): core.sha(path) for path in paths
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def reduce_profile(profile):
    """Independent replay of actual sampled frames and their captured parents."""
    nodes = {node['id']: node for node in profile['nodes']}
    parents = {child: node['id'] for node in profile['nodes'] for child in node.get('children', [])}
    counts = {}
    for sample in profile['samples']:
        counts[sample] = counts.get(sample, 0) + 1
    rows = []
    for node_id, samples in counts.items():
        callers, parent = [], parents.get(node_id)
        while parent is not None and len(callers) < 12:
            callers.append(nodes[parent]['callFrame'])
            parent = parents.get(parent)
        rows.append({'id': node_id, 'samples': samples, 'frame': nodes[node_id]['callFrame'], 'callers': callers})
    return sorted(rows, key=lambda row: (-row['samples'], row['id']))


class Run(core.Run):
    def __init__(self, args):
        args.scenario = 'runtime-forensics'
        super().__init__(args)
        self.worktree = self.directory / 'target'
        self.probe = self.directory / 'probe.mjs'
        self.descriptor = self.directory / 'control.json'
        self.nonce = secrets.token_hex(24)
        self.target = self.broker = None
        self.stage_proof, self.immutable = {}, {}
        self.config_path = None
        self.source_status = None
        self.handles = []
        self.operations = {}

    native_events = forge.Run.native_events
    stage = forge.Run.stage

    def git(self, *args, cleanup=False):
        return self.call(['git', '-C', self.args.repo, *args], cleanup=cleanup).strip()

    def preflight(self):
        self.check('positive_deadline', self.args.max_seconds > 0)
        self.check('inventory_matches_declared_playbooks',
                   set(self.inventory_names) == set(core.INVENTORY))
        self.check('source_root', Path(self.git('rev-parse', '--show-toplevel')).resolve() == ROOT)
        self.revision = self.git('rev-parse', 'HEAD')
        self.source_status = self.git('status', '--porcelain=v1', '--untracked-files=all')
        self.hashes = identity()
        self.config_path = horch.config_path()
        self.config_hash = core.sha(self.config_path)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            horch.require_herdr_env()
            self.config = horch.load_config()
            self.caller = horch.require_caller_context(self.args.caller_pane, self.args.caller_text)
        self.spec = self.config['workers'].get(self.args.controller, {})
        self.check('existing_configured_pi', self.spec.get('harness') == 'pi')
        self.node = shutil.which('node')
        self.check('node_available', bool(self.node))
        capability = json.loads(self.call([self.node, '--input-type=module', '-e',
            'console.log(JSON.stringify({version:process.version,webSocket:typeof WebSocket}))']))
        self.check('builtin_websocket_available', capability.get('webSocket') == 'function')
        self.node_version = capability['version']

    def freeze(self, path, content):
        path.write_text(content)
        path.chmod(0o444)
        self.immutable[path] = core.sha(path)

    def spawn_owned(self, argv, label):
        stdout = (self.directory / (label + '.stdout')).open('w')
        stderr = (self.directory / (label + '.stderr')).open('w')
        self.handles.extend([stdout, stderr])
        return subprocess.Popen([str(word) for word in argv], cwd=self.worktree, env=self.env,
                                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)

    def wait_file(self, path, process, seconds=15):
        deadline = min(self.deadline, time.monotonic() + seconds)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise Failure('owned_process_exited_before_ready')
            if path.exists() and path.stat().st_size:
                try:
                    return core.read_json(path)
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        raise Failure('owned_process_readiness_timeout')

    def setup(self):
        copied = self.directory / 'config/herdr-orchestrator/workers.toml'
        copied.parent.mkdir(parents=True)
        shutil.copy2(self.config_path, copied)
        self.task_root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.worktree.mkdir()
        shutil.copytree(ROOT / 'skills', self.bundle / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.freeze(self.worktree / 'target.mjs', TARGET)
        workload = {'references': [[f'account-{i}', i % 31 + 1] for i in range(2500)],
                    'payments': [[f'account-{(i * 173) % 2500}', i % 19 + 1] for i in range(6000)]}
        self.freeze(self.worktree / 'workload.json', json.dumps(workload, sort_keys=True) + '\n')
        self.freeze(self.probe, PROBE)
        self.target = self.spawn_owned([self.node, '--inspect=127.0.0.1:0', self.worktree / 'target.mjs', self.nonce], 'target')
        hello = self.wait_file(self.directory / 'target.stdout', self.target)
        self.check('owned_target_hello', hello.get('identity') == {'pid': self.target.pid, 'nonce': self.nonce,
                   'sourceSha256': self.immutable[self.worktree / 'target.mjs']}
                   and hello.get('http', {}).get('address') == '127.0.0.1'
                   and hello.get('http', {}).get('port', 0) > 0)
        stderr = (self.directory / 'target.stderr').read_text()
        urls = re.findall(r'ws://127\.0\.0\.1:\d+/[a-f0-9-]+', stderr)
        self.check('one_owned_inspector', len(urls) == 1)
        self.socket_path = Path('/tmp') / ('runtime-e2e-' + secrets.token_hex(12) + '.sock')
        self.freeze(self.descriptor, json.dumps({'identity': hello['identity'], 'inspector': urls[0],
                    'sourceUrl': (self.worktree / 'target.mjs').as_uri(), 'socket': str(self.socket_path)}, indent=2) + '\n')
        self.broker = self.spawn_owned([self.node, self.probe, '--serve', self.descriptor], 'probe')
        self.ready = self.wait_file(self.directory / 'probe-ready.json', self.broker)
        deadline = min(self.deadline, time.monotonic() + 5)
        while not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        self.check('single_live_probe_ready', self.socket_path.exists()
                   and self.ready['initial']['identity'] == hello['identity'])
        self.write_replay()
        env = [item for key in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'MISE_CONFIG_DIR', 'MISE_STATE_DIR', 'GIT_CONFIG_GLOBAL')
               for item in ('--env', key + '=' + self.env[key])]
        tab = self.herdr('tab', 'create', '--workspace', self.caller['workspace_id'], '--cwd', self.worktree,
                         '--label', 'runtime-e2e', '--no-focus', *env)
        self.pane = tab['root_pane']['pane_id']
        brief = self.directory / 'controller-brief.md'
        brief.write_text(self.prompt())
        sessions = self.directory / 'native-sessions'
        sessions.mkdir()
        flags = horch.launch_args(self.spec, self.directory) + ['--session-dir', str(sessions)]
        self.check('controller_started', self.herdr('agent', 'start', self.agent, '--kind', 'pi', '--pane', self.pane,
                   '--timeout', '90000', '--', *flags).get('type') == 'agent_started')
        deadline = min(self.deadline, time.monotonic() + 90)
        while time.monotonic() < deadline:
            entry = self.herdr('agent', 'get', self.agent)['agent']
            session = entry.get('agent_session') or {}
            if (session.get('agent') == 'pi' and session.get('source') == 'herdr:pi' and session.get('value')
                    and entry.get('agent_status') in ('idle', 'done')):
                self.session = session
                break
            if entry.get('agent_status') == 'blocked':
                raise Failure('controller_start_blocked')
            time.sleep(1)
        else:
            raise Failure('controller_session_not_ready')
        self.check('controller_prompted', self.herdr('agent', 'prompt', self.agent,
                   f'Read {brief} in full and execute it.', '--wait', '--until', 'working',
                   '--timeout', '30000').get('type') == 'agent_prompted')

    def argv(self, action, symbol=None):
        words = [self.node, str(self.probe), '--control', str(self.descriptor), action]
        return words + (['--symbol', symbol] if symbol else [])

    def prompt(self):
        skills, notes = self.bundle / 'skills', self.artifacts
        command = lambda action: shlex.join(self.argv(action))
        return f'''Read {skills / 'poteto-mode/SKILL.md'} fully, then execute its ORIGINAL Runtime forensics playbook and Herdr mapping. Diagnose why the live invoice reconciliation service consumes CPU with no HTTP traffic. Deliver a cited diagnosis only. The already-running owned target is scoped for benign live instrumentation; no fixes, reloads, restarts, PRs, external services, configuration changes, trust answers, retries or substitutions.
Use ONLY direct native read, bash, write, edit, grep, find, ls. No codemode, tool wrappers, inline scripts, arbitrary eval, shell redirection, pipelines, compound commands, or delegation. This captured artifact is bounded: reduce it using the maintained immutable helper and keep its small reduced finding locally; if it actually requires a subagent, stop and report the unsupported stage. Never invent delegation evidence.
Bash accepts only the exact fixed probe commands below, bare uptime, nproc or pwd, and cat or sha256sum with exactly one assigned absolute file path. Use the native read/grep/find/ls tools for other inspection; do not add bash arguments, commands or wrappers outside that literal grammar.
Every required source document must have a separate full read with no offset/limit, or literal cat of that one file, whose complete contents appear in the result. Read all: {json.dumps([str(skills / name) for name in READS])}.
Before target inspection or any forensic work, use exactly one native write to {notes / 'checklist.md'} containing the full original FIVE numbered Runtime forensics instructions (including continuation text). Preserve that complete original-instruction prefix unchanged. Keep planning and completion in a separate section after that prefix. Earlier native edits to that separate tail may record planning notes, including before capture. Only use native edit calls with nonempty, uniquely matching oldText and nonempty newText; an initial separate pending section may be replaced. The final checklist edit must record completion after all five actual operations and the required full runtime-source.json and target.mjs reads. Do not rewrite checklist.md with a later native write. Read {self.probe} fully; this maintained control-cli harness accepts fixed operations and instruments only a selected existing source function. All notes may be written ONLY to checklist.md, decision.json, diagnosis.json, reply.md under {notes}; source, probe, descriptor, captures and evaluator are immutable. Failed write attempts are audited too.
1. Capture the real live CPU signal via control-cli using this exact literal command:
{command('capture')}
Read {self.directory / 'capture.json'} fully. There are zero HTTP requests; the existing target remains alive.
2. Reduce the captured profile using the exact literal command:
{command('reduce')}
Read {self.directory / 'reduce.json'} fully: it contains the top twelve actual sampled frames and their captured callers. The complete reduction and original profile stay on disk for independent replay; do not flood the context with raw artifacts. Before instrumentation, write {notes / 'decision.json'} with symbol (the actual hot global function symbol), profile_sha256 (capture detail.profileSha256), reduction_sha256 (reduce detail.reductionSha256), mechanism and caller (the captured timer caller symbol). Ground the choice in the actual sampled function/callers.
3. Instrument YOUR selected existing symbol using the exact literal command form below, replacing SYMBOL with the symbol in decision.json:
{shlex.join(self.argv('instrument', 'SYMBOL'))}
Read {self.directory / 'instrument.json'} fully. The helper injects a counting wrapper, preserves original function behavior, and records a real caller stack without invoking work itself. Then observe later callbacks on the SAME target and inspector connection:
{command('observe')}
Read {self.directory / 'observe.json'} fully. Require increasing real counter/timer ticks and HTTP requests=0. No source fix or foreground synthetic work.
4. Map actual captured frames and live script to source:
{command('source')}
Read {self.directory / 'source.json'}, {self.directory / 'runtime-source.json'} and {self.worktree / 'target.mjs'} fully. Write {notes / 'diagnosis.json'} with symbol, caller, source_line (one-based hot function definition), timer_line (one-based setInterval scheduling line), profile_sha256, source_sha256, counter_before, counter_after, requests=0, mechanism and limitations. Use exact actual evidence, not source-only theory. Source location must agree with live script/profile and unchanged file hash.
5. Write {notes / 'reply.md'} after all observations and source mapping, citing the signal, actual reduced finding, increasing instrumentation counter and caller stack, exact source file:symbol:line plus timer line, private artifact paths, and principles read that changed a decision. Include the exact observed final counter as ungrouped decimal or standard comma-grouped decimal, as a complete digit/comma token with no malformed grouping. Cite the signal through capture.json OR cpu.cpuprofile, the reduced finding through reduce.json OR reduced-frames.json, and the observation through observe.json. Use local Markdown links resolved relative to reply.md or exact absolute artifact paths. The summary JSONs remain independently bound to the original profile, complete reduction and raw CDP evidence. Include EXACTLY one line:
{CHECKPOINT}
Report uncertainty honestly. Do not claim a fix, throughput benchmark, other playbooks, full inventory, cloud, or wake/sleep coverage.
'''

    def write_replay(self):
        (self.directory / 'REPLAY.md').write_text(f'''# Private runtime forensic evidence

The target and probe sources are retained unchanged. Protocol JSONL contains actual
request/response IDs, one persistent inspector session, and runtime identity.
The target was stopped during cleanup; do not attach to a stale inspector URL.

Replay the captured reduction without a model or live target:

    {shlex.join([self.node, str(self.probe), '--reduce-file', str(self.directory / 'cpu.cpuprofile')])}

Compare that JSON with reduced-frames.json. runtime-source.json contains the actual
Debugger.getScriptSource response. Instrumentation and observation JSONs cite
the request ID ranges in protocol.jsonl; target.stdout contains its original hello.
To repeat the full E2E with a new owned process and new artifact directory:

    {shlex.join([sys.executable, '-B', str(Path(__file__).resolve()), '--controller', self.args.controller, '--repo', str(ROOT), '--output', str(self.args.output), '--caller-pane', self.args.caller_pane, '--max-seconds', str(self.args.max_seconds)])}

For an agent controller, include --caller-text with fresh unique text from its visible conversation.
Keep this directory private; do not commit native sessions or raw captures.
''')

    def full_read(self, events, path, *, after=-1, before=float('inf')):
        found = core.workflow_reads(events, self.worktree, path, after=after, before=before)
        self.check('full_read_' + path.name, bool(found))
        return found

    def artifact(self, events, name, *, after=-1, before=float('inf')):
        path = self.artifacts / name
        found = core.workflow_writes(events, self.worktree, path, after=after, before=before, final=True)
        self.check('native_artifact_' + name, len(found) == 1)
        return (core.read_json(path) if name.endswith('.json') else path.read_text()), found

    def operation(self, events, action, symbol=None):
        value = core.read_json(self.directory / (action + '.json'))
        found = [event for event in events if event['name'] == 'bash'
                 and forge.literal(event['args'].get('command', '')) == self.argv(action, symbol)]
        self.check('one_literal_operation_' + action, len(found) == 1)
        event = found[0]
        try:
            output = json.loads(event['output'])
        except ValueError:
            output = None
        self.check('actual_output_matches_capture_' + action, output == value
                   and value.get('action') == action and value.get('session') == self.ready['session']
                   and value.get('identity') == self.ready['initial']['identity']
                   and value.get('inspector') == self.ready['inspector'])
        self.full_read(events, self.directory / (action + '.json'), after=event['result_row'])
        self.operations[action] = value
        return value, event

    def verify(self):
        self.check('target_and_probe_still_live', self.target.poll() is None and self.broker.poll() is None)
        hello = core.read_json(self.directory / 'target.stdout')
        descriptor = core.read_json(self.descriptor)
        self.check('retained_hello_pid_nonce_source_inspector_binding', hello['identity'] == descriptor['identity']
                   == self.ready['initial']['identity']
                   and hello['identity']['pid'] == self.target.pid and hello['identity']['nonce'] == self.nonce
                   and hello['identity']['sourceSha256'] == self.immutable[self.worktree / 'target.mjs']
                   and descriptor['inspector'] == self.ready['inspector']
                   and descriptor['inspector'] in (self.directory / 'target.stderr').read_text())
        self.check('no_delegation_for_bounded_artifact', not self.scan())
        sessions = list((self.directory / 'native-sessions').glob('*.jsonl'))
        self.check('one_native_session', len(sessions) == 1)
        self.native = core.audit_pi(sessions[0], self.session, self.worktree, self.wall_started, self.spec,
                                   [self.bundle / 'skills' / name for name in READS], [], [], self.bundle)
        self.check('native_identity_model_effort_full_guidance', all(row['ok'] for row in self.native['checks']))
        events = self.native_events(sessions[0])
        all_events = self.native_events(sessions[0], include_errors=True)
        allowed = {self.artifacts / name for name in ('checklist.md', 'decision.json', 'diagnosis.json', 'reply.md')}
        self.check('all_write_attempts_scoped', all(isinstance(e['args'].get('path'), str)
                   and (self.worktree / e['args']['path']).resolve() in allowed
                   for e in all_events if e['name'] in ('write', 'edit')))
        decision, decision_events = self.artifact(events, 'decision.json')
        symbol = decision.get('symbol')
        self.check('selected_existing_symbol', symbol in ('lookupReference', 'reconcileLedger', 'scheduledReconciliation'))
        commands = [self.argv(action, symbol if action == 'instrument' else None)
                    for action in ('capture', 'reduce', 'instrument', 'observe', 'source')]
        self.check('all_bash_attempts_literal_read_or_fixed_probe', all(
            (argv := forge.literal(e['args'].get('command', ''))) in commands
            or (len(argv) == 2 and argv[0] in ('cat', 'sha256sum') and Path(argv[1]).is_absolute())
            or argv in (['pwd'], ['uptime'], ['nproc']) for e in all_events if e['name'] == 'bash'))
        capture, cap = self.operation(events, 'capture')
        reduction, red = self.operation(events, 'reduce')
        instrument, ins = self.operation(events, 'instrument', symbol)
        observation, obs = self.operation(events, 'observe')
        mapping, source = self.operation(events, 'source')
        ordered = [cap, red, decision_events[0], ins, obs, source]
        self.check('native_original_sequence', all(a['result_row'] < b['call_row'] for a, b in zip(ordered, ordered[1:])))
        steps = re.findall(r'^\d+\. (.+)$', (self.bundle / 'skills/poteto-mode/playbooks/runtime-forensics.md').read_text(), re.M)
        checklist_path = self.artifacts / 'checklist.md'
        checklist_events = core.workflow_writes(events, self.worktree, checklist_path, before=cap['call_row'])
        self.check('native_initial_checklist_write', len(checklist_events) == 1
                   and len(core.workflow_writes(events, self.worktree, checklist_path)) == 1)
        checklist = checklist_events[0]['args']['content']
        self.check('exact_five_stage_checklist', len(steps) == 5 and re.findall(r'^\d+\. (.+)$', checklist, re.M) == steps)
        # Step 2 has a continuation paragraph; compare the entire original stage block.
        original = (self.bundle / 'skills/poteto-mode/playbooks/runtime-forensics.md').read_text()
        block = original[original.index('1. Capture'):original.index('\n\n**Reply:**')]
        self.check('full_original_checklist_continuation', checklist.count(block) == 1)
        preserved = checklist[:checklist.index(block) + len(block)]
        completion_edits = [e for e in events if e['name'] == 'edit'
                            and isinstance(e['args'].get('path'), str)
                            and (self.worktree / e['args']['path']).resolve() == checklist_path]
        updated, previous = checklist, checklist_events[0]['result_row']
        for event in completion_edits:
            self.check('checklist_edit_order', previous < event['call_row'])
            before_final_edit = updated
            edits = event['args'].get('edits', [event['args']])
            self.check('checklist_completion_edits_supported', isinstance(edits, list) and bool(edits))
            for edit in edits:
                self.check('checklist_completion_edit_unambiguous', isinstance(edit, dict)
                           and isinstance(edit.get('oldText'), str) and bool(edit['oldText'])
                           and isinstance(edit.get('newText'), str) and updated.count(edit['oldText']) == 1)
                updated = updated.replace(edit['oldText'], edit['newText'], 1)
                self.check('checklist_original_instructions_preserved', updated.startswith(preserved)
                           and updated.count(block) == 1)
            previous = event['result_row']
        self.check('native_final_checklist_completion_bound', bool(completion_edits)
                   and updated == checklist_path.read_text()
                   and bool(updated[len(preserved):].strip())
                   and updated[len(preserved):] != before_final_edit[len(preserved):])
        early = self.full_read(events, self.probe, after=checklist_events[0]['result_row'], before=cap['call_row'])
        for name in READS:
            self.full_read(events, self.bundle / 'skills' / name, before=cap['call_row'])
        self.check('checklist_precedes_forensic_work', checklist_events[0]['result_row'] < min(e['call_row'] for e in early + [cap])
                   and all(core.read_target(e['name'], e['args'], self.worktree) not in
                           {self.worktree / 'target.mjs', self.worktree / 'workload.json'}
                           for e in events if e['call_row'] < cap['result_row']))
        self.full_read(events, self.directory / 'reduce.json', after=red['result_row'], before=decision_events[0]['call_row'])
        profile = core.read_json(self.directory / 'cpu.cpuprofile')
        replay = reduce_profile(profile)
        self.check('independent_sample_reduction', replay == core.read_json(self.directory / 'reduced-frames.json')
                   and len(profile['samples']) >= 200 and sum(row['samples'] for row in replay) == len(profile['samples'])
                   and profile['endTime'] - profile['startTime'] >= 1_000_000
                   and capture['detail']['samples'] == len(profile['samples'])
                   and capture['detail']['profileSha256'] == core.sha(self.directory / 'cpu.cpuprofile')
                   and reduction['detail']['profileSha256'] == capture['detail']['profileSha256']
                   and reduction['detail']['reductionSha256'] == core.sha(self.directory / 'reduced-frames.json')
                   and reduction['detail']['top'] == replay[:12])
        uri = (self.worktree / 'target.mjs').as_uri()
        hot = [row for row in replay if row['frame']['url'] == uri]
        self.check('sampled_linear_lookup_and_timer_caller', bool(hot) and hot[0]['frame']['functionName'] == 'lookupReference'
                   and hot[0]['samples'] >= len(profile['samples']) * .1
                   and any(frame['functionName'] == 'scheduledReconciliation' and frame['url'] == uri
                           for frame in hot[0]['callers']))
        self.check('decision_from_actual_reduction', symbol == hot[0]['frame']['functionName']
                   and decision.get('caller') == 'scheduledReconciliation'
                   and decision.get('profile_sha256') == capture['detail']['profileSha256']
                   and decision.get('reduction_sha256') == reduction['detail']['reductionSha256']
                   and bool(decision.get('mechanism')))
        before = observation['before']['instrumentation']
        after = observation['after']['instrumentation']
        expected_total = sum(((i * 173) % 2500 % 31 + 1) * (i % 19 + 1) for i in range(6000))
        self.check('real_later_invocations_without_http_input', instrument['detail'].get('installed') is True
                   and instrument['detail'].get('symbol') == symbol and instrument['detail'].get('count') == 0
                   and before['symbol'] == after['symbol'] == symbol and after['count'] > before['count'] >= 0
                   and observation['after']['ticks'] > observation['before']['ticks']
                   and observation['after']['lastTotal'] == expected_total
                   and isinstance(after['stack'], str) and 'scheduledReconciliation' in after['stack']
                   and 'Timeout.' in after['stack'] and str(self.worktree / 'target.mjs') in after['stack']
                   and all(value[side]['requests'] == 0 for value in self.operations.values() for side in ('before', 'after')))
        runtime_source = core.read_json(self.directory / 'runtime-source.json')
        live_source_reads = self.full_read(events, self.directory / 'runtime-source.json', after=source['result_row'])
        source_reads = self.full_read(events, self.worktree / 'target.mjs', after=source['result_row'])
        self.check('checklist_final_completion_after_observations', completion_edits[-1]['call_row'] > max(
            event['result_row'] for event in (cap, red, ins, obs, source))
            and all(any(read['result_row'] < completion_edits[-1]['call_row'] for read in reads)
                    for reads in (live_source_reads, source_reads)))
        self.check('exact_live_script_source', runtime_source['scriptSource'] == TARGET
                   and mapping['detail']['sourceSha256'] == self.immutable[self.worktree / 'target.mjs']
                   and runtime_source['script']['url'] == uri
                   and hot[0]['frame']['scriptId'] == mapping['detail']['scriptId'])
        lines = TARGET.splitlines()
        source_line = next(i + 1 for i, line in enumerate(lines) if line.startswith('globalThis.' + symbol + ' = function '))
        timer_line = next(i + 1 for i, line in enumerate(lines) if 'setInterval(' in line)
        self.check('sample_definition_line_matches_source', hot[0]['frame']['lineNumber'] + 1 == source_line)
        diagnosis, diagnosis_events = self.artifact(events, 'diagnosis.json', after=max(e['result_row'] for e in source_reads))
        expected = {'symbol': symbol, 'caller': 'scheduledReconciliation', 'source_line': source_line,
                    'timer_line': timer_line, 'profile_sha256': capture['detail']['profileSha256'],
                    'source_sha256': mapping['detail']['sourceSha256'], 'counter_before': before['count'],
                    'counter_after': after['count'], 'requests': 0}
        self.check('diagnosis_exact_observations', all(diagnosis.get(key) == value for key, value in expected.items())
                   and bool(diagnosis.get('mechanism')) and bool(diagnosis.get('limitations')))
        reply, reply_events = self.artifact(events, 'reply.md', after=diagnosis_events[0]['result_row'])
        reply_path = self.artifacts / 'reply.md'
        linked_targets = set()
        for match in re.finditer(r'(?<!!)\[[^\]\n]+\]\(\s*(?:<([^<>\n]+)>|([^\s)]+))(?:\s+["\'][^\n]*["\'])?\s*\)', reply):
            try:
                destination = urlsplit(match[1] or match[2])
            except ValueError:
                continue
            if not destination.scheme and not destination.netloc and not destination.query and destination.path:
                target = (reply_path.parent / unquote(destination.path)).resolve()
                if target.is_file():
                    linked_targets.add(target)
        citation_end = r'(?=$|[\s`<>()\[\],;"\']|\.(?=$|\s))'
        artifact_groups = (('capture.json', 'cpu.cpuprofile'),
                           ('reduce.json', 'reduced-frames.json'), ('observe.json',))
        artifacts_cited = all(any(path.resolve() in linked_targets or re.search(
            r'(?<![\w/.-])' + re.escape(str(path)) + citation_end, reply)
            for path in (self.directory / name for name in group)) for group in artifact_groups)
        source_cited = re.search(r'(?<![\w/.-])' + re.escape(str(self.worktree / 'target.mjs'))
                                 + r':(?:' + re.escape(symbol) + r':)?' + str(source_line) + citation_end, reply)
        counter_cited = re.search(r'(?<![\d,])(?:' + re.escape(str(after['count'])) + '|'
                                 + re.escape(format(after['count'], ',')) + r')(?!\d|,\S|\.\d)', reply)
        self.check('cited_final_diagnosis_checkpoint', reply.splitlines().count(CHECKPOINT) == 1
                   and artifacts_cited and bool(source_cited) and bool(counter_cited)
                   and all(text in reply for text in (symbol, 'scheduledReconciliation',
                                                      str(timer_line))))
        self.verify_protocol()
        self.stage('runtime_1_capture_live_signal', early + [cap])
        self.stage('runtime_2_reduce_then_select', [red] + decision_events)
        self.stage('runtime_3_instrument_then_observe', [ins, obs])
        self.stage('runtime_4_map_live_source', [source] + source_reads + diagnosis_events)
        self.stage('runtime_5_checkpoint_and_cited_reply', reply_events)

    def verify_protocol(self):
        rows = [json.loads(line) for line in (self.directory / 'protocol.jsonl').read_text().splitlines()]
        requests, responses = {}, {}
        for row in rows:
            self.check('protocol_single_persistent_session', row['session'] == self.ready['session'])
            message = row['message']
            if row['direction'] == 'request':
                self.check('unique_request_id', message['id'] not in requests)
                requests[message['id']] = row
            elif 'id' in message:
                self.check('bound_response_id', message['id'] in requests and message['id'] not in responses
                           and row['time'] >= requests[message['id']]['time'] and 'error' not in message)
                responses[message['id']] = row
        self.check('all_protocol_requests_resolved', set(requests) == set(responses))
        self.check('monotonic_request_ids', list(requests) == list(range(1, len(requests) + 1)))
        previous = 0
        for action, operation in self.operations.items():
            first, last = operation['firstRequest'], operation['lastRequest']
            self.check('operation_time_and_id_order_' + action, previous < first <= last
                       and operation['start'] <= requests[first]['time'] <= responses[last]['time'] <= operation['end'])
            previous = last
            ids = list(range(first, last + 1))
            evaluate = [index for index in ids if requests[index]['message']['method'] == 'Runtime.evaluate']
            values = [responses[index]['message']['result'].get('result', {}).get('value') for index in evaluate]
            self.check('runtime_metrics_bound_' + action, values[0] == operation['before'] and values[-1] == operation['after'])
            if action == 'capture':
                stops = [index for index in ids if requests[index]['message']['method'] == 'Profiler.stop']
                starts = [index for index in ids if requests[index]['message']['method'] == 'Profiler.start']
                self.check('raw_profiler_response_replayed', len(starts) == len(stops) == 1
                           and starts[0] < stops[0]
                           and requests[stops[0]]['time'] - responses[starts[0]]['time'] >= 1750
                           and responses[stops[0]]['message']['result']['profile'] == core.read_json(self.directory / 'cpu.cpuprofile'))
            elif action == 'instrument':
                self.check('instrument_request_real_existing_wrapper', len(evaluate) == 3 and values[1] == operation['detail']
                           and 'Reflect.apply(original,this,args)' in requests[evaluate[1]]['message']['params']['expression']
                           and 'state.count++' in requests[evaluate[1]]['message']['params']['expression'])
            elif action == 'observe':
                self.check('observe_only_reads_real_metrics', len(ids) == len(evaluate) == 2
                           and requests[evaluate[0]]['message']['params']['expression'] ==
                               requests[evaluate[1]]['message']['params']['expression']
                           and responses[evaluate[1]]['time'] - requests[evaluate[0]]['time'] >= 1350)
            elif action == 'source':
                sources = [index for index in ids if requests[index]['message']['method'] == 'Debugger.getScriptSource']
                self.check('raw_live_source_response_replayed', len(sources) == 1 and
                           responses[sources[0]]['message']['result']['scriptSource'] == TARGET)

    def finish(self):
        cleanup = True
        if self.pane:
            try:
                (self.directory / 'controller-pane.json').write_text(self.call(
                    ['herdr', 'pane', 'read', self.pane, '--source', 'recent', '--lines', '80'], cleanup=True))
                self.herdr('pane', 'close', self.pane, cleanup=True)
                proc = subprocess.run(['herdr', 'pane', 'get', self.pane], env=self.env, text=True,
                                      capture_output=True, timeout=15)
                value = json.loads(proc.stdout or proc.stderr)
                error = value.get('error', {})
                cleanup = proc.returncode != 0 and (error.get('code') if isinstance(error, dict) else error) in horch.MISSING_PANE_CODES
            except Exception:
                cleanup = False
        try:
            self.scan()
            for task in self.tasks.values():
                state = core.read_json(Path(task['task_dir']) / 'state.json')
                if not state.get('closed'):
                    entry = self.herdr('agent', 'get', task['agent'], cleanup=True)['agent']
                    if entry.get('pane_id') != task.get('pane_id'):
                        raise Failure('cleanup_ownership_unproven')
                    self.call([sys.executable, self.bundle / 'skills/herdr-orchestrator/scripts/horch.py',
                               'close', task['task_id']], cleanup=True)
                proc = subprocess.run(['herdr', 'pane', 'get', task['pane_id']], env=self.env,
                                      text=True, capture_output=True, timeout=15)
                value = json.loads(proc.stdout or proc.stderr)
                error = value.get('error', {})
                cleanup = cleanup and proc.returncode != 0 and (
                    error.get('code') if isinstance(error, dict) else error) in horch.MISSING_PANE_CODES
        except Exception:
            cleanup = False
        exited = {}
        # Closing the inspector first prevents Node waiting for a debugger at exit.
        for label, process in (('probe', self.broker), ('target', self.target)):
            if process is None:
                continue
            try:
                alive = process.poll() is None
                if alive:
                    process.terminate()
                code = process.wait(timeout=8)
                exited[label] = {'pid': process.pid, 'alive_before_cleanup': alive, 'exit_code': code,
                                 'exact_child_reaped': process.poll() is not None}
                cleanup = cleanup and alive and code == 0
            except Exception:
                cleanup = False
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass
        for handle in self.handles:
            handle.close()
        socket_path = getattr(self, 'socket_path', None)
        if socket_path is not None and socket_path.exists():
            socket_path.unlink()
        (self.directory / 'owned-process-cleanup.json').write_text(json.dumps(exited, indent=2) + '\n')
        after, config_after, intact = {}, None, False
        try:
            after = identity()
            config_after = core.sha(self.config_path)
            intact = (bool(self.hashes) and self.hashes == after and config_after == self.config_hash
                      and self.git('rev-parse', 'HEAD', cleanup=True) == self.revision
                      and self.git('status', '--porcelain=v1', '--untracked-files=all', cleanup=True) == self.source_status
                      and all(core.sha(path) == digest for path, digest in self.immutable.items()))
            copied = self.directory / 'config/herdr-orchestrator/workers.toml'
            intact = intact and (not copied.exists() or core.sha(copied) == self.config_hash)
            if self.bundle.exists():
                intact = intact and all(core.sha(self.bundle / name) == digest for name, digest in self.hashes.items()
                                        if name.startswith('skills/'))
        except Exception:
            pass
        self.checks.extend([{'name': 'source_head_config_target_probe_integrity', 'ok': intact},
                            {'name': 'owned_pane_and_exact_processes_stopped', 'ok': cleanup}])
        passed = not self.categories and bool(self.stage_proof) and all(row['ok'] for row in self.checks)
        workflow = 'pass' if passed else ('blocked' if self.phase in ('preflight', 'setup') else 'fail')
        inventory = {name: 'not_run' for name in core.INVENTORY}
        inventory['runtime-forensics'] = workflow
        if not self.native:
            paths = list((self.directory / 'native-sessions').glob('*.jsonl'))
            if len(paths) == 1:
                self.native = {'sha256': core.sha(paths[0]), 'audit_completed': False}
        # Public receipt contains structural verdicts/counts/hashes, never private paths or raw text.
        native = {key: value for key, value in self.native.items() if key != 'checks'}
        native['guidance_checks'] = len(self.native.get('checks', []))
        receipt = {'schema': 'horch/runtime-playbook-e2e/v1', 'verdict': 'pass' if passed else 'fail',
                   'workflow_verdict': workflow, 'stage_coverage': 'complete' if passed else 'incomplete',
                   'behavior_verdict': 'pass' if passed else 'unproven', 'full_inventory_verdict': 'not_run',
                   'inventory': inventory, 'source_revision': self.revision,
                   'source_sha256_before': self.hashes, 'source_sha256_after': after,
                   'config_sha256_before': self.config_hash, 'config_sha256_after': config_after,
                   'controller': {key: self.spec.get(key) for key in ('harness', 'provider', 'model', 'effort')},
                   'native_transcript': native, 'native_stages': self.stage_proof, 'checks': self.checks,
                   'failure_categories': self.categories, 'last_phase': self.phase,
                   'seconds': round(time.monotonic() - self.started, 3),
                   'owned_process_count': len(exited), 'native_operation_count': len(self.operations),
                   'artifact_sha256': {path.name: core.sha(path) for path in self.directory.iterdir()
                                       if path.is_file() and path.name in {'protocol.jsonl', 'cpu.cpuprofile',
                                           'reduced-frames.json', 'runtime-source.json', 'owned-process-cleanup.json',
                                           'target.stdout', 'probe-ready.json', 'capture.json', 'reduce.json',
                                           'instrument.json', 'observe.json', 'source.json'}},
                   'limitations': ['Only the owned synthetic 2,500-reference / 6,000-payment timer workload is covered.',
                       'No application fix, PR, production performance claim, cloud, or wake/sleep scenario is covered.',
                       'Playbook coverage is limited to Runtime forensics.',
                       'Only literal supported native tools and bounded controller-local reduction are audited.',
                       'Private retained protocol and sources permit reduction replay; a fresh live run requires Herdr and the configured Pi controller.']}
        (self.directory / 'evidence.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f"Evidence: {self.directory / 'evidence.json'}\nVerdict: {receipt['verdict']}")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, help='existing configured Pi controller worker')
    parser.add_argument('--repo', type=Path, default=ROOT, help='existing trusted source checkout')
    parser.add_argument('--output', type=Path, required=True, help='private artifact parent outside source checkout')
    parser.add_argument('--caller-pane', required=True, help='independently verified actual caller pane')
    parser.add_argument('--caller-text', help='unique visible conversation text (at least 16 characters) for agent controllers')
    parser.add_argument('--max-seconds', type=int, default=1200, help='overall deadline; no retries')
    args = parser.parse_args()
    args.repo, args.output = args.repo.expanduser().resolve(), args.output.expanduser().resolve()
    if args.repo != ROOT:
        parser.error('--repo must identify this source checkout')
    if args.output == ROOT or ROOT in args.output.parents:
        parser.error('--output must be outside the source checkout')
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
