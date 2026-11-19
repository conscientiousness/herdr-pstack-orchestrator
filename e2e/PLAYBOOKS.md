# Original playbook verification

Full playbook conformance is a later milestone. The current release scope
is [reversible setup and a practical delivery workflow](../docs/RELEASE-EVIDENCE.md).
This inventory preserves original outcomes; those failures do not become passes
when a distinct practical workflow succeeds. Missing runtime prerequisites are
marked **blocked** below.

Skill discovery, a correct application result, and execution of an original
playbook are separate claims. This inventory covers the 22 files in
[`poteto-mode/playbooks`](../skills/poteto-mode/playbooks/). pstack 0.15.43
removed Orchestrate. Historical receipts retain their source attribution. Unavailable stages
stay unresolved. A local scenario does not establish another controller
harness's compatibility.

## Workflow review for pstack 0.15.43

This source review covers every bundled playbook. Follow the selected playbook for its method and the [Herdr adapter](../skills/pstack-herdr/SKILL.md) for execution. The [0.15.43 receipt](evidence/workflow-review-0.15.43.json) records the fresh checks. The [scenario inventory](#complete-inventory) includes the earlier live runs.

| Playbook | What the controller must preserve when using Herdr |
|---|---|
| Investigation | Trace the source and give a cited answer. Use Why for motivation. A recommendation ends with the decision and tradeoffs. |
| Bug fix | Reproduce the failure, trace its cause, dispatch a scoped fix, and rerun the original repro on the changed surface. |
| Feature · Refactoring | Trace the subsystem and sketch the design. Feature verifies the new behavior. Refactoring pins the existing behavior before dispatch and compares it afterward. The controller manages shared writes and any Arena or review panel. |
| Prototype · Multi-phase plan | Prototype competing approaches in scratch space and compare observed results. Hand back the decision or the verifiable plan. The operator starts implementation separately. |
| Perf issue · Hillclimb | Establish a repeatable baseline and measure on the same surface. Hillclimb also records each keep or revert against its metric and correctness gates. Unattended continuation needs a durable wake facility. |
| Runtime forensics · Trace forensics | Runtime instruments a live process to prove a mechanism. Trace works from an existing capture and attributes the signal to source. Both deliver a diagnosis. |
| Visual parity | Keep the original visual baseline, isolate component ownership, and verify pixel differences on the actual UI. The original per-component loop requires a supported execution facility. |
| Authoring a skill · Eval | Author in the chosen harness, validate the installed artifact and follow its delivery scope. Eval isolates candidates, hides the rubric and model labels as required, and checks the observed skill reads and outputs. Disclose unavailable blinding or judging. |
| Opening a PR · Babysit | Apply the shared pre-commit and review triggers, then open the scoped PR. Start Babysit when requested. Check takes one snapshot, threads-only handles review threads, and drive follows the lowest unmerged PR to the operator's gate. |
| Shipping | Require an independent verifier on the real surface for each PR, identify the contiguous verified run, and check the landing heads. Cloud verification and actual merge authority are separate prerequisites. |
| Autonomous run · Autopilot-full · Autopilot-stack | Record the goal, stop condition and durable wake mechanism. Autopilot additionally requires cloud ownership and independent verification. Keep one live writer per PR. Stack hands verified PRs to the operator. Full requires explicit merge authority. |
| Pause safely · Session pickup | At an explicit pause, preserve owned work at a safe boundary and leave a durable resume note. Pickup reads the authorized trail and rechecks the actual branch and outstanding work. |
| Worktree cleanup | Identify the exact worktree, its changes, reachable commits, active worker and pinned chat ownership before pruning. Retain any candidate whose ownership or data loss is unresolved. |

## Run a live controller

`playbook_loop.py` starts a real evaluation controller directly in its own
Herdr tab. The controller reads the bundled `poteto-mode`, selects a playbook,
and uses configured workers through `agent-workers`. It is not a bounded `agent-workers` worker.
The initial implementation supports Pi controllers; Codex and Claude Code
controller coverage remains separate work.

Run from a trusted checkout inside Herdr. Confirm the actual caller pane using
the [caller identity procedure](../skills/agent-workers/references/setup.md#caller-context).
Use a private artifact directory outside the checkout:

```bash
python3 e2e/playbook_loop.py --controller <configured-pi-worker> \
  --scenario trace-forensics --repo "$PWD" --caller-pane <verified-pane> \
  --caller-text '<unique visible conversation text>' \
  --output /tmp/horch-playbook-proof --max-seconds 1200
```

Trace and Runtime use small, controller-local captures. Prototype can also run
on the legacy Herdr backend, where its worker pane checks apply. All three
require an authenticated Pi controller and the verified caller. Stop other
isolated dispatchers in that workspace.
The runner copies worker definitions unchanged, preserves existing permission
flags, and does not answer trust dialogs. It preserves the shell's original
Mise config and state roots when isolating agent-workers's XDG directories. Git retains
its original global configuration files and precedence through a private include
wrapper, including relative include origins; user Git settings stay unchanged.
Forge drivers and their controller tabs also retain the original GitHub CLI
configuration location through `GH_CONFIG_DIR`, including an existing explicit
override. They do not copy login credentials or require a separate test login.
This does not establish environment forwarding into Herdr-created worker panes.

Native sessions must match the fresh controller's cwd, time, session identity,
model and effort. Required documents must appear in successful native tool
results. Submitted tasks must match configured launch arguments and deliver
valid results. Artifact reads must follow delivery. Final claims that a skill
was followed do not establish execution.

The current auditor recognizes direct native `read`, `bash`, `write`, `edit`,
`grep`, `find` and `ls` calls. Pi's `codemode` is a native tool, but its nested
calls are outside this evidence grammar. The evaluation prompt states that
restriction explicitly; it does not change the configured harness or permissions.

The controller does not grade its own result:

| Scenario | Independent observations |
|---|---|
| Investigation | Exact structured facts and source citations across command, transaction storage, and integer money modules |
| Prototype | Two rounding implementations and a labeled CLI rerun on fractional-cent, ordinary, empty and zero-value inputs |
| Trace forensics | Real paired profiles, exact SQLite row preservation, source attribution and equal reconciliation results |

Prototype observations must come from direct CLI invocations with oracle-checked
JSON outputs. Profile conversion must precede analysis through the frozen CLI.
The importer preserves function rows and captured caller edges; query outputs
are checked against the retained database. Source citations resolve to the exact
supplied file, including valid fixture-relative and worktree-relative paths.
Command text mentioning a tool is only a hint.

Required child skills are part of workflow eligibility. Reading `no-comments`
does not apply it: its fresh Comment Sicko task must actually deliver and be
reviewed before final PR review. An evaluator's task-count restriction cannot silently
waive that stage; the original workflow stays unresolved.

The Investigation fixture uses a narrower presentation protocol than How's
allowance for light edits: the explainer applies `unslop` before delivery, and
the controller presents that explanation unchanged with one throughput line.
This makes explanation preservation observable without a semantic-similarity
score. A synthesis that needs substantive correction leaves the stage unresolved.
Each canonical `report.md` must be read and propagated in full. Complete briefs
must use native `write`; shell/Python task-artifact composition is outside the
auditor's grammar. A later attempt correctly stopped on an erroneous synthesis,
so successful unchanged presentation still has no positive receipt.

### Rerun a historical scenario

The historical model fixtures were authored for pstack 0.15.25 at `e5136d8`.
Investigation requires the old How prompts, the design fixtures require the old
Architect panel, and the Babysit fixture extracts nine numbered stages. The current
playbooks use different instructions. To reproduce a recorded run, select its
machine receipt from the [inventory](#complete-inventory) and check out its
**repository** `source_revision`, which includes the matching driver, bundle and
worker protocol. For example, to inspect the historical Investigation driver:

```bash
receipt=e2e/evidence/playbook-investigation-concat.json
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_revision"])' "$receipt")
replay=$(mktemp -d)
git worktree add --detach "$replay/source" "$revision"
cd "$replay/source"
python3 e2e/playbook_loop.py --help
```

Follow that checkout's prerequisites and run command. Preserve any recorded
failure. Portable fixture preparation and local CLI replay can also run from
the current checkout.

## Continuity and writable workflows

Runtime forensics can use the current checkout. For the other live fixtures
in this table, use the [recorded checkout](#rerun-a-historical-scenario).
Read the measured results and each fresh receipt before reporting coverage.

| Driver | Scope and prerequisites |
|---|---|
| `pause_pickup.py` | Two fresh Pi sessions, one local WIP commit, scoped prior trail and persisted importer verification; no remote writes |
| `forge_loop.py` | Private invoice fixture; captured repository snapshot, audited How/Why delivery, two ordered test/fix commits and a ready child PR; original live-source Why remains unresolved |
| `design_loop.py` | Feature or Refactoring, actual How/Architect/Arena stages, independent behavior/equivalence, fresh Comment Sicko delivery and a ready private child PR |
| `perf_loop.py` | Fresh profiles, separate unprofiled alternating CLI timings, one-function fix and a ready private child PR |
| `authoring_loop.py` | Actual skill-authoring guidance, existing validator, two independently traced usage cases and a ready private child PR |
| `runtime_loop.py` | Owned live Node Inspector process, CPU capture, benign instrumentation and source-attributed diagnosis; no fix or PR |
| `hillclimb_loop.py` | Attended measured attempts, both original decision-log formats, different-family trail review, fresh Comment Sicko delivery and a ready private child PR |
| `babysit_loop.py` | One read-only Check pass over an explicit real private PR chain; no drive, background wake or merge |

For continuity, from the recorded checkout:

```bash
python3 e2e/pause_pickup.py --controller <configured-pi-worker> \
  --repo "$PWD" --caller-pane <verified-pane> \
  --output /tmp/horch-continuity-proof --max-seconds 2400
```

The recorded continuity fixture establishes its originating Feature workstream
in session A. Session B recovers that context from the actual prior trail, uses
neutral verdict choices and names the numbered original resume step. Earlier
Feature grounding/design and later PR/review are outside this fixture's coverage.
The fresh receipt below verifies this refined reporting contract.

Prepare portable fixture files without Git, credentials, Herdr or model calls:

```bash
python3 e2e/forge_loop.py --prepare-fixture /tmp/invoice-baseline
python3 -B /tmp/invoice-baseline/e2e_import.py --output /tmp/invoice-baseline-proof
python3 e2e/perf_loop.py --prepare-fixture /tmp/reconciliation-baseline
python3 -B /tmp/reconciliation-baseline/e2e_reconcile.py --output /tmp/reconciliation-baseline-proof
```

Follow the generated README to create your own private fixture repository and
ready baseline PR. Keep it unmerged. Use each live driver's `--help` for explicit
clone, forge repository, base branch and parent PR arguments. These drivers
retain real child PRs and never merge or enable auto-merge. Initial portable
baselines passed their seven invoice flows and six reconciliation flows; those
bootstrap checks are not native playbook executions.

Skill authoring needs existing creator guidance and its validator's PyYAML
dependency; it never installs that dependency. Explicit forward use does not
prove automatic discovery. Runtime forensics needs Node with Inspector and
built-in WebSocket support. A fresh live run passes all five stages after four
retained checker-contract failures; the independent audits below distinguish them.
The first Feature attempt was manually stopped after explorer tool and
directory-scope violations; its lead had already consumed the reports and
launched synthesis. The first Refactoring run automatically quarantined delivery
before lead consumption; its complete workflow remains unresolved. The first Authoring run
failed its controller command check and omitted a mandatory delegated review,
as detailed below. The first Perf
attempt retains a failed native-audit receipt. A second machine pass is rejected
by independent worker-tool review; both are described below.
The first live Bug fix investigation was stopped for an actual
repository-scope violation, described below; it produced no fix or PR.

Hillclimb uses the pristine reconciliation baseline and an explicit configured
`--trail-reviewer` from a different model family. Its declared stop condition
combines the improvement target with at least three distinct measured attempts.
Every candidate is retained, and decisions are independently replayed; neither
kept nor reverted counts are predetermined. Attended iteration does not prove
durable wake or unattended execution.
A fresh Comment Sicko review follows the stable measured attempts and trail
audit, before final PR review and the documentation commit. Accepted attempt
checkpoint commits precede that final review.

Babysit requires `--stack-prs` as at least two real PR numbers in bottom-to-top
base-chain order. It executes the original watcher once and binds its actual
`STATUS` rows to separate forge snapshots. Its private copied bootstrap may
install locked Bun dependencies at execution time. Unsupported Origin selection,
unavailable checks or a changing forge snapshot remain unresolved. Even a pass
would cover bounded Check only, not the entire Babysit playbook. The first Check
attempt stopped in preparation on a checker-contract gap; its original failed
receipt and independent audit are preserved below. The first Hillclimb run was manually stopped on explicitly excluded
How shell listings before any measured attempt or PR.

## Interpret evidence

The printed `evidence.json` is authoritative. Its private parent directory also
retains configuration, commands, panes, transcripts, profiles and outputs. Only
the sanitized receipt is a candidate for publication.

- `behavior_verdict` covers independent fixture checks.
- `stage_coverage` covers declared stages and their native evidence.
- `workflow_verdict` additionally requires full workflow eligibility and ordered
  native evidence. Measured core-workflow passes cover fixed-direction Prototype
  and bounded paired-capture Trace forensics. The fresh continuity receipt records
  completed Pause and Pickup phases. Its earlier failed attempts and Investigation
  remain failed.
- `inventory` accounts for every playbook. `not_run` is not a pass.
- `full_inventory_verdict` cannot pass from one scenario.

No inter-task dependency graph is inferred from final task states. Delivery
before an individual artifact read is audited separately. Role names in a
brief alone cannot prove a multi-phase workflow.

Failed attempts stay failed, including startup failures before a model prompt.
Fixing the verifier does not retroactively promote a receipt. Recorded source
hashes identify the tested code; keep historical attribution intact.

### Measured results

The [complete Prototype receipt](evidence/playbook-prototype.json) passes the
fixed-direction core workflow with a real Pi controller and one delivered
implementation task. Its six-stage native record proves the original checklist
preceded delegation, all three scripts were inspected, both labeled alternatives
were observed on the same discriminating input, and the decision and final
handoff followed the observations. Reference gathering was explicitly skipped
because the supplied contract fixed the direction, as the playbook permits.
The decision records concrete tradeoffs, throwaway scope and a Feature handoff.

Independent replay returns 102 versus 101 cents for the separating invoice,
933 cents for the ordinary case, and zero for zero-cost and empty invoices.
Both standalone variants and the shared runner produce these results even when
the decision file is temporarily unavailable. This covers the behavioral fork
with a fixed direction; it does not cover an open visual design search or a
production Feature build. The [earlier stage receipt](evidence/playbook-prototype-stages.json)
retains its original unresolved workflow verdict.

The [fresh Trace forensics receipt](evidence/playbook-trace.json) passes all six
stages in 148.428 seconds. Independent review compared every SQLite row and edge
with the original profiles: nine function rows and five caller edges were
preserved exactly. Four native SQL observations were replayed read-only without
changing database bytes. The controller converted before analysis, queried the
hot path and captured caller, mapped it to source, compared the pair, then wrote
the diagnosis. The captures show 6,000 lookups before and zero after, with equal
reconciliation results of 958008. No workload rerun or source change occurred.
This covers bounded controller-local captures, not large-capture delegation,
runtime instrumentation, or a generalized performance improvement.

The [Investigation attempt](evidence/playbook-investigation-codemode.json)
remains failed. The native audit could not inspect a `codemode` wrapper.
Independent review confirmed both full explorer reports reached synthesis and
all five technical facts were correct, but the controller substantially rewrote
the delivered explanation. That violates How's presentation rule. The
[separate artifact reanalysis](evidence/playbook-investigation-reanalysis.json)
fixes an overly narrow citation check using actual Python symbol scopes; it
preserves the failed workflow verdict. Correct facts do not complete this workflow.

The [later Investigation attempt](evidence/playbook-investigation-concat.json)
also remains failed. Both delivered explorer reports reached the synthesis brief
in full, but inline Python composition was outside the native evidence grammar.
Independent review also found a real synthesis error: stored stale totals do not
necessarily survive export and reimport unchanged. The controller correctly
withheld the explanation instead of rewriting it. This is evidence of stopping
on an unresolved result, not a successful presentation. The
[separate reanalysis](evidence/playbook-investigation-concat-reanalysis.json)
records ten of eleven artifact checks passing and preserves the failed native
audit and failed presentation gate.

The [two-session continuity attempt](evidence/playbook-continuity-route.json)
records **Pause safely pass / Session pickup fail**. Pause completed its original
four stages: one delivered money-only implementation, actual half-up observation,
an explicit stop, one matching WIP commit, a clean tree and an off-context note.
Session A closed before the distinct session B began. Independent review confirms
the recorded identities, hashes, native order and preserved checkpoint bytes.

Pickup's fixture was ambiguous: neither A's original goal nor its note established
a Feature workstream. B reasonably selected read-only Investigation, inspected
the inherited state and executed all six pending CLI cases without repeating
the money probe. The evaluator instead demanded Feature. Its original failure
remains unchanged; the refined fixture above does not retroactively promote it.

The [fresh continuity receipt](evidence/playbook-continuity.json) passes all four
Pause and five Pickup stages in 577.374 seconds, with 93 passing check records.
Independent review confirms that B was not supplied the expected Feature route
or step. It recovered them from the actual note/trail and Git state, then ran all
six pending CLI cases without repeating the money probe or dispatching a task.
Four rejected imports exited 2, preserved exact store bytes and left no pending
file. The successful six-row store totals 3751 cents and exports in sorted order.
All six independent CLI replays agree. Session identities, source/config hashes,
the inherited WIP, clean tree and owned cleanup match. This covers the bounded
local continuation, not earlier Feature design or later PR/review stages.

The [private-forge attempt](evidence/playbook-forge-scope.json) remains failed.
An investigator assigned only the fixture repository made an owner-wide issue
query and received records from another repository. Independent review caught
this, and the operator manually stopped the run before synthesis, implementation
or a new PR. The [separate scope audit](evidence/playbook-forge-scope-audit.json)
records native hashes, counts and cleanup without publishing unrelated content.
The lead had read a report containing the unrelated repository's identity, but
no returned issue titles. This was manual intervention, not an automatic adapter
denial. The unchanged failed receipt records `operator_interrupted`.

Do not repeat that live-query profile with broad forge access. The replacement
driver captures only the assigned repository's paginated issues, comments,
labels and PR1 discussion, then exposes an offline list/search/read gateway.
Its two investigators still examine the available issue and Git categories,
including empty results, before separate configured synthesis.

The delivery wrapper runs real `agent-workers wait` privately, retaining its exact argv
and raw receipt. It emits only fixed metadata until the closed worker's complete
native transcript passes a scope audit, including failed calls. The final driver
independently binds that audit, the original assignment and native delivery to
every report read or forwarding operation. Violations quarantine output before
synthesis. This lane still needs its own live evidence; it detects violations
after execution and does not prevent credential use or hidden application-level
network access. Snapshot stages, fixture behavior and Opening a PR have separate
verdicts. A passing fixture experiment would leave original live-source Why and
the full Bug fix workflow unresolved.

The [first snapshot-lane attempt](evidence/playbook-forge-quarantine.json) remains
failed. Its source investigator used `fffind` and `ffgrep`, violating the
explicit seven-tool protocol. The gate automatically quarantined delivery; the
lead received only fixed failure metadata and consumed no worker report or
result. No synthesis, coding or PR followed. The
[separate audit](evidence/playbook-forge-quarantine-audit.json) verifies that
bounded quarantine and owned cleanup. All requested search paths were within
the reader tree, and cross-repository leakage was not established. The audit
also found a hidden restriction on otherwise authorized local Git history flags.

Fresh reader support is restricted to typed FFF calls within the assigned cwd,
without cursors, traversal or surrounding whitespace/BOM. Reader trees must be
symlink-free before dispatch and after delivery. Existing startup settings stay
in force; concurrent external tree mutation remains an assumption. This new
support has no live passing receipt yet and makes no universal FFF or containment
claim.

The [second snapshot attempt](evidence/playbook-forge-shell.json) also remains
failed. The [independent metadata-only audit](evidence/playbook-forge-shell-audit.json)
locates the first rejection at `pwd && ls -la`; later composed commands and
Bash `ls` also exceeded the evidence grammar. FFF request shapes and owned
paths were valid. The lead received only pending/pending/quarantined metadata,
with zero report/result or raw-wait access and no synthesis, code or PR. Three
readers actually launched even though the failed receipt's finish snapshot
contains `tasks: []`. Owned cleanup and 217 source hashes match. Future briefs
explicitly name the forbidden shell characters and require native `ls`.
The failure establishes rejection and withholding, without cross-repository
access or successful audited delivery.

The [first Authoring receipt](evidence/playbook-authoring-literal.json) remains
failed at the controller literal-command gate. Its
[separate artifact audit](evidence/playbook-authoring-literal-reanalysis.json)
verifies actual creator guidance/validation, five portable links, two frozen
authored files and two real forward uses: six successful rows total 994 cents,
and a rejected import preserves the seeded 98-cent ledger byte for byte.
The complete staged diff also exposes an undeclared mnemonic-prefix mismatch
in the full-review checker. More importantly, mandatory Comment Sicko delegation
was omitted under the evaluator's extra-task restriction. A created ready PR
and correct usage do not complete Authoring or Opening a PR. Independent CLI
and remote-parent/ref replay stopped at the early failure and remain unverified.

The [second Authoring receipt](evidence/playbook-authoring-review.json) also
remains failed. Its [independent audit](evidence/playbook-authoring-review-audit.json)
verifies both real usages and retained independent replays, actual Comment
delivery and the lead's correct unresolved stop before commit/push/PR.
The checker compared the complete staged new-file patch against an empty
base-to-HEAD patch because no commit existed. The declared grammar also could
not produce the required delivered-report hash, and the typed finding contract
did not distinguish supported keeps from actionable changes. Those evaluator
repairs do not remove Comment's prohibited Bash listing or adjudicate its
deeper-work requests. The 217 source hashes, creator guidance, settings and
owned cleanup checks pass; no full Authoring or Opening a PR pass is claimed.

The [fourth Perf receipt](evidence/playbook-perf-comment.json) retains its
genuine exact-first-output failure. Its
[independent audit](evidence/playbook-perf-comment-audit.json) verifies complete
delivered How and implementation scopes, the measured first-wins index change,
six raw profile reductions and 36 correct measurement results. Native timings
fall from 132.397 to 39.448 ms; separate replay gives 131.283 to 39.360 ms.
The native and both independent six-flow CLI suites pass. Comment's scope-safe
report still violates its required first output and preserves open work; the lead
stops without commit/push/PR. A How iterator aside is also inaccurate outside the
exercised CLI list inputs. These narrower facts do not complete the workflow.
Future named-agent briefs explicitly load the original instructions through
tools before natural text, with native ordering evidence. No agent rules are
rewritten and no failed receipt is promoted.

The [first Runtime receipt](evidence/playbook-runtime-env.json) remains failed.
Its checker rejected legitimate `uptime` and `nproc` observations, then independent
review found two further mismatches: a valid checklist completion edit and the
prompted citation format. The [separate native/artifact audit](evidence/playbook-runtime-reanalysis.json)
supports all five observed stages without promoting the receipt. It replayed
1,707 profile samples and 19 matched Inspector requests/responses. Natural timer
callbacks produced 132,000 measured calls across 22 ticks, with zero HTTP requests
and the correct reconciliation result of 958008. Source identity and owned cleanup
matched. These are runtime observations, not a speedup or CPU-saturation claim.
The [second Runtime receipt](evidence/playbook-runtime-citations.json) also remains
failed, with 70 of 71 checks passing. It cited the actual capture, reduction and
observation records; the checker additionally required direct raw-profile and
full-reduction links that the prompt had not specified. Its
[independent audit](evidence/playbook-runtime-citations-reanalysis.json) verified
all five observed stages, exact reduction, raw Inspector bindings, source identity
and cleanup. The checker now accepts either the operation record or its raw
artifact for the signal and reduction, while retaining independent raw-data
checks. The prompt declares those citation groups and the literal shell grammar.
Those repairs did not promote either failed receipt.

The [third Runtime receipt](evidence/playbook-runtime-planning.json) preserves a
further ordering failure. Before capture, the controller appended explicitly
tentative measurement planning to the checklist's separate pending section,
then recorded completion after the actual observations. The checker incorrectly
treated every checklist edit as completion. The
[separate independent audit](evidence/playbook-runtime-planning-reanalysis.json)
supports all five stages, exact profile reduction, raw Inspector bindings,
source identity and cleanup. Chronological edit replay now permits earlier
planning while requiring final completion after all operations and source reads.
The original receipt remains failed.

The [fourth Runtime receipt](evidence/playbook-runtime-number.json) also remains
failed: its correct counter `1,127,037` did not match a hidden ungrouped-decimal
substring requirement. Its [independent audit](evidence/playbook-runtime-number-reanalysis.json)
verified all five stages and raw protocol/source bindings. The checker now accepts
the exact plain or canonical comma-grouped integer, including prose punctuation;
the prompt declares both forms. Its original verdict remains failed.

The [fresh Runtime receipt](evidence/playbook-runtime.json) passes all five stages
in 244.849 seconds, with 401 passing check records. Independent review reproduces
1,705 profile samples and all 19 Inspector request/response pairs on one context.
The existing-function counter grew from 800318 to 926318 during later natural
callbacks, with zero HTTP requests and the correct total 958008. Native stage
anchors, preserved checklist, source mapping, all 202 source hashes, configuration
and owned cleanup agree. Four earlier receipts retain their failures. This covers
the bounded diagnostic fixture, without a throughput, saturation, speedup, fix,
PR, cloud or large-artifact delegation claim.

The [first Perf receipt](evidence/playbook-perf-copy.json) remains failed after
the native auditor rejected a literal copy of an already delivered and read How
report. The attempt produced new profiles, alternating CLI timings, unchanged
outputs and a ready private child PR. Its
[separate independent audit](evidence/playbook-perf-copy-reanalysis.json) supports
all six observed stages. Five alternating full-CLI pairs measured a median
131.403 to 37.985 ms (71.1% reduction); independent replay measured 130.795 to
38.117 ms (70.9%). Work counts and total 958008 match across all 36 retained
measurement outputs, and all six CLI cases pass. Source, profiles, commit,
ready PR, remote body, parent/ref inventory and cleanup agree. The audit records
additional verifier/prompt mismatches without promoting the failed workflow.

The [second Perf machine receipt](evidence/playbook-perf-worker-tools.json)
records 146 passing checks, but it is not accepted as a complete Perf pass.
The [separate independent audit](evidence/playbook-perf-worker-tools-audit.json)
found that the delivered How worker used `fffind` despite
its explicit seven-tool restriction; the driver checked worker metadata and
results without auditing their native tools. The search requested only its
owned reader and returned owned filenames. No outside-repository or network
access was observed. The later symlink-free tree inspection is retrospective,
without a pre-dispatch attestation. The original machine verdict remains
unchanged. Native alternating timings measured 133.099 to 37.799 ms (71.6%
reduction), with correct work and all six CLI cases passing. Those observations
do not erase the protocol failure.
The earlier standalone Opening a PR judgment is
[withdrawn](evidence/playbook-opening-pr-correction.json). Its ready child PR,
reviewed commit, exact head/base/body and parent/ref integrity remain verified,
but the required `no-comments` skill unconditionally spawns Comment Sicko. That
task was omitted; reading the guidance and reviewing locally do not substitute
for it. Neither full Perf nor Opening a PR is eligible. The machine receipt and
earlier independent audit remain unchanged beside this correction.
The current Perf and Authoring drivers require a third configured Comment Sicko
task, live native evidence, full scoped review and lead disposition before their
final review/commit. Perf also audits every worker tool attempt and records
before/after reader-tree evidence. These repairs have independent code review;
a fresh complete live pass is still required.

The [third Babysit Check receipt](evidence/playbook-babysit-case.json) retains
FAIL after 87 of 88 checks. Its
[independent audit](evidence/playbook-babysit-case-audit.json) verifies all 43
scoped attempts, eleven exact artifacts, the original watcher and both real
PR rows, correct WAITING/merge-queue interpretation, exact declared footer
lines, full unslop reread and intact source/config/fixture/cleanup. The sole
rejected predicate is a lowercase-only cloud word match, although the reply
explicitly names the Cloud limitation. The reviewed forward repair casefolds
only ordinary-language gap terms; exact status/source/authority bindings stay
unchanged. This is not a new automated PASS or complete Babysit evidence.

The [fourth Check receipt](evidence/playbook-babysit-overlap.json) retains
FAIL/blocked in preparation. Its
[independent audit](evidence/playbook-babysit-overlap-audit.json) verifies all
ownership fields except the required empty visible-conflict list. The actual
brief requires a stop on visible same-repository babysitting, and the controller
correctly stopped on that ambiguity. The observed target is the unique caller
pane, and the displayed source/fixture match; no proof path, nonce, PID or
ancestry binds it to this invocation. Neither self-supervision nor a distinct
dispatcher is established. All 30 attempted tools, 15 full guide reads, five
note writes and source/config/fixture/cleanup observations are valid. No ready
barrier, watcher, forge snapshots or final report occurred. A run-specific
supervisor witness is required before another attempt; do not exempt the caller
or turn this supported blocked outcome into a PASS.
The available Herdr metadata does not link a truncated displayed background job
to a driver PID/start-time or run nonce. A standalone PID witness cannot fill
that link, and one caller may launch multiple jobs. This identity capability
remains unavailable under the current constraints.

The [second Babysit Check receipt](evidence/playbook-babysit-triage.json) retains
FAIL after 79 of 80 checks. Its
[independent retained-data audit](evidence/playbook-babysit-triage-audit.json)
verifies one original watcher invocation over an exact two-PR branch/commit
chain, with two passing checks per PR, zero threads and unchanged before/after
forge state. Original query responses reproduce both STATUS rows; the correct
interpretation is WAITING/merge-queue with owner authority pending. All 43 native
attempts, eleven exact writes, source/config/fixture integrity and cleanup agree.
The first failure is overly strict whole-object triage equality: the actual
empty findings include a truthful reason. A later unreached reply check also
demands undeclared exact strings. The reviewed forward contract permits only
the optional typed reason and declares exact private citation/authority footer
lines. The raw FAIL remains unchanged, and no fresh Check or full Babysit pass
is inferred from this analysis.

The [first Hillclimb receipt](evidence/playbook-hillclimb-shell.json) remains an
operator-stopped FAIL, with 28 passing setup/cleanup checks and no measured
attempt. The [metadata-only audit](evidence/playbook-hillclimb-shell-audit.json)
binds the configured How worker to a captured working session and records
explicitly excluded Bash listings inside its owned reader. No report reached
the lead; no application change, measurement, commit or PR followed. A separate
unreached checker split an internal Worker rules heading and would exclude
instructions that were actually present. It did not cause the manual stop.
The reviewed forward repair validates the exact nonce-bound Horch suffix and
inspects the complete authored prefix, with no shell-grammar relaxation or
new live pass.

The Design driver now uses a private same-file wait/audit entry point for
all slots. It keeps raw agent-workers waits private and releases only metadata and
declared output paths after done/closed delivery and native scope validation.
Its reviewed contract binds a captured working Pi UUID, role/model/cwd, exact
authored brief plus nonce-bound Horch suffix, declared inputs, hidden rubric
separation and all tool attempts. CommentSicko's original native bootstrap,
first output and scope observations are checked before forwarding. Independent
final validation checks the matching PASS before worker-output reads, reads
or execution of source owned by implementation tasks, content-producing Git
operations and dependent launches.
The [first Refactoring receipt](evidence/playbook-refactor-quarantine.json)
retains an automatic FAIL under the declared grammar. Its
[metadata-only audit](evidence/playbook-refactor-quarantine-audit.json) verifies
both working-session bindings, the private raw wait and six-field safe response,
zero lead worker-payload reads, zero dependent launches and no rows after the
quarantine response. Both workers attempted explicitly excluded local shell
listing/search. All 31 setup/cleanup checks passed, without a completed stage,
commit or new PR. The early-failure lifecycle records account for both launches.
Installed Pi defaults do not select the optional native grep/find/ls advertised
by that contract; installed FFF offers different tool names. This separate
compatibility gap warrants a deliberate bounded How contract and fresh evidence,
without changing startup settings or promoting the old FAIL. Report/result,
raw-wait and native-output/write/edit payloads remain unread. The first Feature
FAIL stays unchanged. Successful delivery and full workflow evidence are still
required; this gate does not establish a sandbox or credential containment.
The forward Design and Hillclimb repair admits only How's typed own-cwd
`fffind`/`ffgrep` subset and exact declared shell listings. Reader-tree
descriptors must match the pre-dispatch symlink-free snapshot. Other roles
retain their grammars, and startup settings remain unchanged. Independent code
review is complete; successful fresh live delivery remains required.

The [second Refactoring receipt](evidence/playbook-refactor-preservation.json)
retains manual FAIL after three approved How deliveries. Its
[independent audit](evidence/playbook-refactor-preservation-audit.json) verifies
87 worker attempts, all identities/scopes/input-output hashes, real bounded
FFF/listing compatibility and lead consumption after PASS. The before-only
behavior pin passes eleven checks and the original seven-flow suite, with
independent Decimal totals and byte-preserving rejection observations. Two
original explorer accuracy errors remain disclosed; the final explanation
correctly limits read/write ordering and actual validation-test coverage.
The lead's grounding changes only two Mermaid quote escapes. The actual
instruction permits complete-content preservation and original How permits
light edits, while the final checker requires literal full-body inclusion.
That predicate was not executed: the operator manually stopped before writable
implementation, and both unfinished Architect payloads remain unread. This was
not automatic quarantine or a machine checker rejection. The reviewed forward
prompt explicitly requires opaque/verbatim text, including escapes and
whitespace, and discloses the narrower witness; the checker stays unchanged.
No post-change equivalence, complete workflow or new PR is established.

The [first Babysit Check receipt](evidence/playbook-babysit-grammar.json) retains
its preparation FAIL: 34 of 35 checks passed, without executing the watcher or
creating before/after forge snapshots. Its
[independent audit](evidence/playbook-babysit-grammar-audit.json) identifies an
undeclared command restriction: the installed Herdr skill requires its exact
environment guard and CLI help, while the actual brief requests actor inspection.
The visible read followed the exact native actor-list capture and targeted a
unique actor in the caller workspace. The reviewed repair declares and permits
only those bounded forms, freezes the actor snapshot and retains all-attempt
auditing. It still needs new live evidence; no Check or full Babysit pass results
from correcting this verifier.

The [first Feature receipt](evidence/playbook-feature-scope.json) remains an
operator-stopped FAIL. Its [metadata-only audit](evidence/playbook-feature-scope-audit.json)
records unsupported explorer FFF tools and shell commands, including task-store
parent and sibling-directory listing. The lead had read both deliveries and
launched the explainer before the halt. There was no automatic quarantine,
source change, commit or PR. Explorer UUIDs match fresh native headers, but
the retained live observations were idle; a working-state binding is missing.
All 31 setup/cleanup checks passed, without a completed workflow audit.
Report bodies remain unread in this review. These facts do not complete Feature.

The [fresh live-replacement receipt](evidence/hot-swap.json) verifies two real
Pi tasks using distinct configured models. Both were held working while the
private alias was changed and removed. A dispatch after removal failed without
allocation; existing tasks retained their exact launch snapshots, delivered
correct 720-event reconciliations and independently rerunnable scripts. Native
session evidence confirms both selected models. Real worker configuration,
skill sources and tracked checkout remained unchanged; owned cleanup passed.
This verifies worker definition replacement, not automatic role or skill reload.

### Preserved failed attempts

| Receipt | Observed failure |
|---|---|
| [Prototype startup](evidence/playbook-prototype-startup.json) | Isolated XDG roots changed Mise's existing trust environment; no model prompt submitted |
| [Prototype contract](evidence/playbook-prototype-contract.json) | Controller ran both variants, but the fixture omitted exact JSON field names and the independent checker could not replay them |
| [Replacement launch](evidence/hot-swap-launch.json) | Verifier parsed an empty successful pane-run response as JSON before any worker allocation |
| [Replacement audit](evidence/hot-swap-audit.json) | Swap/removal gates passed, but verifier queried a live agent after delivery had automatically closed it |
| [Investigation tooling](evidence/playbook-investigation-codemode.json) | Native `codemode` was outside the auditor's grammar; separate review also found a substantive How rewrite |
| [Trace source path](evidence/playbook-trace-path.json) | All six native stages executed, but the checker rejected a valid worktree-relative source path |
| [Continuity Git setup](evidence/playbook-pause-git.json) | Isolated XDG hid existing Git identity before any model started |
| [Continuity audit call](evidence/playbook-pause-audit.json) | Inherited state shadowed an audit method after the implementation checkpoint |
| [Continuity empty output](evidence/playbook-pause-empty-output.json) | Pi rendered clean Git stdout as `(no output)`, which the checker rejected |
| [Continuity routing](evidence/playbook-continuity-route.json) | Pause passed; Pickup selected a defensible Investigation route that the fixture had not allowed |
| [Investigation composition](evidence/playbook-investigation-concat.json) | Unsupported inline file composition; separately, an erroneous synthesis correctly remained unresolved |
| [Forge authentication visibility](evidence/playbook-forge-auth.json) | Isolated XDG hid existing GitHub CLI configuration; preflight stopped before any model or remote mutation |
| [Forge repository scope](evidence/playbook-forge-scope.json) | Investigator queried outside the assigned repository; independent audit triggered manual halt before synthesis/fix/PR |
| [Runtime observation grammar](evidence/playbook-runtime-env.json) | Checker rejected required environment observations; separate review found checklist and citation format mismatches |
| [Runtime citation contract](evidence/playbook-runtime-citations.json) | Checker required undeclared direct raw-file links despite valid citations to independently bound operation records |
| [Runtime planning order](evidence/playbook-runtime-planning.json) | Checker treated an explicitly tentative planning edit as premature completion |
| [Perf report copy](evidence/playbook-perf-copy.json) | Native auditor rejected a legitimate verbatim copy of a delivered and fully read report |
| [Snapshot quarantine](evidence/playbook-forge-quarantine.json) | Unsupported FFF tools triggered automatic quarantine before report consumption; no cross-repository leakage established |
| [Runtime counter format](evidence/playbook-runtime-number.json) | Checker rejected a correct counter written with ordinary thousands separators |
| [Snapshot shell grammar](evidence/playbook-forge-shell.json) | Composed shell and Bash ls calls triggered automatic quarantine; no worker payload reached the lead |
| [Authoring command grammar](evidence/playbook-authoring-literal.json) | Undeclared controller restrictions and diff-prefix mismatch; mandatory Comment Sicko task also omitted |
| [Feature worker scope](evidence/playbook-feature-scope.json) | Unsupported explorer tools and task-store traversal; lead consumed reports before manual halt, so no automatic quarantine claim |
| [Hillclimb shell grammar](evidence/playbook-hillclimb-shell.json) | Manual stop on explicitly excluded local How shell listings; no delivered report, measured attempt or PR |
| [Refactoring quarantine](evidence/playbook-refactor-quarantine.json) | Automatic gate stopped explicitly excluded How shell forms before lead consumption; complete workflow unresolved |
| [Babysit visible overlap](evidence/playbook-babysit-overlap.json) | Conservative preparation stop on an ambiguously identified visible launch; no watcher or forge snapshots |
| [Refactoring preservation](evidence/playbook-refactor-preservation.json) | Manual stop before implementation after an undeclared literal How-copy requirement; three How deliveries and baseline verified |

Each attempt retained its failure verdict and confirmed owned cleanup. The first
prototype run did not execute a model task. The contract run produced real
observations; those do not replace a passing independent replay.

## Complete inventory

Five bounded scenarios have historical core-workflow evidence. Trace forensics also has a fresh six-stage run at the current pstack pin.

| Playbook | Scenario or remaining requirement |
|---|---|
| Investigation | [FAIL](evidence/playbook-investigation-concat.json): native grammar gap and unresolved synthesis; correct stop does not satisfy successful presentation |
| Bug fix | Original live-query [scope failure](evidence/playbook-forge-scope-audit.json) and later [snapshot quarantine](evidence/playbook-forge-quarantine-audit.json); full workflow unresolved |
| Feature | [Fifth, user-deferred FAIL/audit](evidence/playbook-feature-deferred-audit.json): complete main input now reads successfully; full original conformance stopped at the user's direction. One unfinished explorer's payloads remain unread. Earlier gate/capacity failures, accepted partial evidence and source-accuracy caveats remain retained |
| Refactoring | [Third FAIL/audit](evidence/playbook-refactor-comment-audit.json): eight deliveries, exact How preservation, design selection, source-grounded reader review and actual before/after equivalence verified; Comment first-output breach automatically withheld; no commit/PR |
| Prototype | [PASS: fixed-direction behavioral core workflow](evidence/playbook-prototype.json); open visual design search unverified |
| Perf issue | [Fourth FAIL with independent behavior audit](evidence/playbook-perf-comment-audit.json): 70.2% native / 70.0% replay reduction; original output rule and review unresolved |
| Hillclimb | [Third FAIL/audit](evidence/playbook-hillclimb-gate-audit.json): excluded owned Git status form automatically withheld before payload reads; no optimization. Separate second-run 71.3% timing/source evidence retained; final review/PR unresolved and unattended wake unavailable |
| Runtime forensics | [PASS: five-stage owned-process diagnosis](evidence/playbook-runtime.json); raw Inspector/profile/source independently checked; large-artifact delegation unverified |
| Trace forensics | [0.15.43 PASS](evidence/workflow-review-0.15.43.json) for all six stages with a real Pi controller. Independent raw-profile replay confirmed 6,000 calls before and zero afterward. [Earlier receipt](evidence/playbook-trace.json). Large-capture delegation remains unverified. |
| Visual parity | Local browser/diff tools available; UI fixture, untouched baseline, real migration, zero pixel diff and PR unrun; required `/loop` unavailable |
| Authoring a skill | [Second FAIL with independent audit](evidence/playbook-authoring-review-audit.json); usage and correct review stop verified, deeper work and complete integrated pass unresolved |
| Eval | Scoped Pi transcripts are accessible in principle; current global skill catalog violates strict blinding under unchanged settings |
| Multi-phase plan | Updated checklist workflow unverified. Upstream removed the validator and stops after delivering the plan. |
| Opening a PR | [Earlier eligibility withdrawn](evidence/playbook-opening-pr-correction.json): ready PR facts verified, mandatory Comment Sicko review omitted |
| Babysit | A 0.15.43 single-PR, read-only watcher check returned a terminal status. Drive and threads-only remain unverified. The [earlier Check fixture](evidence/playbook-babysit-overlap-audit.json) stopped on an ambiguous visible launch. |
| Shipping | **blocked**: cloud verifier unavailable; no authorization to merge test PRs |
| Autonomous run | **blocked**: required wake mechanism unavailable |
| Autopilot-full | **blocked**: cloud owners/verifiers and wake mechanism unavailable; no merge authorization |
| Autopilot-stack | **blocked**: cloud owners and wake mechanism unavailable. The verified, green-at-current-head handoff remains unverified. |
| Pause safely | [PASS: bounded local four-stage stop](evidence/playbook-continuity.json); original checkpoint, WIP and off-context note |
| Session pickup | [PASS: five-stage local continuation](evidence/playbook-continuity.json); distinct session, recovered route and real pending CLI verification |
| Worktree cleanup | Pinned and active-chat metadata unavailable; owned E2E teardown does not verify this playbook's deletion gates |

Cloud execution and `/loop` are not supplied by the current adapter. Gate-only
Shipping evidence cannot complete Shipping. Remote scenarios need a dedicated
test destination; this repository's default branch is not a test target.

## Retain artifacts and clean up

The runner closes only owned controller and worker panes. It retains the
worktree under `handoff/<run>/worktree` for inspection. Never commit that folder.
After inspection remove only the exact owned worktree with `git worktree remove`.
Keep external receipts and private diagnostics.

CI checks syntax, CLI entry points and installation. Authenticated scenarios
run locally. A green package CI run does not establish workflow coverage.
