# End-to-end verification

For agent-driven verification, use the project-local [verify-herdr-orchestrator skill](../.agents/skills/verify-herdr-orchestrator/SKILL.md). Its feature map selects existing drivers and records prerequisites, evidence locations, and cleanup without adding another test harness.

These files are repository tooling, outside both installed Agent Skills. Run the public driver from a clone inside Herdr:

```bash
python3 e2e/review_loop.py \
  --writer gpt --reviewer glm --reviewer haiku \
  --repo . --output /tmp/horch-evidence
```

Choose configured workers and two reviewers with distinct model definitions. The driver makes real model calls, needs two free slots, and uses a detached worktree. It plants two independent invoice defects, checks a scoped implementation, requires two failing initial reviews, then checks a fresh fix and two passing final reviews. It also covers fractional/full discounts, zero quantities, and single-line invoices.

The run retains its worktree and writes `evidence.json` with assertions, source hashes, revisions, and observed CLI output. It cleans up only panes it started. Reports stay in the local task store; no transcripts go into evidence. Remove the retained worktree with `git worktree remove <printed-path>` after inspection.

For a controller-level test, configure a Codex worker with explicit model, effort, and permission arguments, then run:

```bash
python3 e2e/controller_loop.py \
  --controller gpt --writer glm --reviewer ds --reviewer glm \
  --repo . --output /tmp/horch-controller-evidence
```

This starts a real Codex controller that reads the current skill and handles the six-task scenario itself. The task prompt does not prescribe wait duration, background commands, or the skill's delegation rules. The driver verifies task records, nonce-bound results, reviewer verdicts, both committed CLI versions, file scope, and cleanup independently of the controller's optional report. It then audits the actual Codex tool transcript for wait launches, resumed process handles, delivery-before-read ordering, and native delegation or pane-input calls.

The controller run copies the existing worker configuration and isolates task state. The configured concurrency limit remains in force, and existing Herdr workers count against preflight capacity. Keep other dispatchers stopped during the run: separate task stores cannot reserve a shared limit atomically. The transcript audit recognizes literal shell-tool calls (including fixed-string addition), sequential `text(await ...)` results, ordered `Promise.allSettled(...).forEach(text)` results, and the measured `const cmds=[...]; text(await Promise.all(cmds.map(cmd=>tools.exec_command({cmd,max_output_tokens:N}))));` form with immutable JSON strings and a literal positive cap. The latter must return a complete, uniquely identified array of tool envelopes in input order. It follows partial outputs across a yielded exec cell and subsequent waits, distinguishes literal brief-writing heredocs from reads, and checks delivery against independently observed state-file write times. An `invalid_task_id` rejection is counted separately and supplies no delivery evidence. Dynamic artifact reads cannot establish delivery evidence. Redundant final verification is allowed only after all six tasks already have explicit gated reads and their independently observed delivery times precede that call. Earlier unresolved reads, shell loops around waits, combined wait/read commands, and ambiguous required evidence fail the audit. It is not a proof of arbitrary shell semantics. Missing transcripts fail the run. Full transcripts stay in the harness's local store; private diagnostics stay beside the retained worktree, outside the repo.

Pi workers require the Herdr Pi integration. A git worktree can still need a separate Pi trust decision when its directory inherits project resources. The [startup investigation](startup-findings.md) explains the reproduced failure and provides a real dialog-preservation test.

To verify Pi preflight against real Herdr, including a mixed batch that must allocate no workers when Pi integration is absent:

```bash
python3 e2e/pi_preflight.py --pi ds --pi glm --other gpt \
  --cwd . --output /tmp/horch-pi-preflight
```

The driver uses Herdr's supported `PI_CODING_AGENT_DIR` override with an empty directory. It does not uninstall the user's integration. It checks immediate rejection of `run` and a mixed `check`, then completes a non-Pi task under the same missing-integration environment and two Pi tasks with the normal installation. It validates nonce-bound results, cleanup, and unchanged sources/configuration/integration. Use an existing trusted checkout, two free slots, and stop other dispatchers. Only its sanitized receipt should be published; diagnostic outputs stay local.

## Evidence and source attribution

- [controller-e2e.json](evidence/controller-e2e.json): a fresh invocation of the final driver passed 47/47 in 736.836 seconds. The six-task scenario, original transcript audit, source/configuration integrity, and actual pane cleanup passed together. Six yielded waits resumed through 23 handle calls, with no short caps. This supersedes the earlier verification gap without changing the historical failed receipts.
- [pi-preflight.json](evidence/pi-preflight.json): 15/15 real integration-preflight and worker-delivery checks, with missing integration rejected in about 0.05 seconds before allocation.
- [pi-controller.json](evidence/pi-controller.json): the original historical Pi-controller 10/10 receipt, with original artifact hashes and explicit source attribution. It predates the updated wait guidance and is not a v0.1.1 test.
- [verification.json](evidence/verification.json): development runs, tested versions, source hashes, and limits.
- [review-e2e.json](evidence/review-e2e.json): the release-era public six-task driver pass and its observed outputs.
- [relocation-e2e.json](evidence/relocation-e2e.json): the historical failing attempt after moving the driver. It failed at initial worker acknowledgement (`not_started` / Herdr `agent_prompt_stalled`), before implementation. Three attempts stopped there. The [subsequent investigation](startup-findings.md) identified the trust-dialog cause; this receipt remains unchanged.
- [startup-diagnosis.json](evidence/startup-diagnosis.json): sanitized failure, withheld-prompt dialog observation, and successful unchanged-code control after removing the leftover empty directory.
- [pi-startup.json](evidence/pi-startup.json): the fixed guard passed 11/11 checks with a real trust dialog, unchanged trust decisions, fresh explicitly declined-resource work, and confirmed cleanup.
- [startup-fixed-review.json](evidence/startup-fixed-review.json): a fresh six-task review loop on the fixed horch passed 27/27 in 431 seconds.
- [controller-audit-initial.json](evidence/controller-audit-initial.json): the first new Codex-controller run completed all six tasks and passed outcome/cleanup checks, but its initial transcript auditor mistook a literal brief-writing heredoc for reading results. That failing receipt is preserved. Corrections distinguish writes from reads and map real tool outputs to their process handles.
- [controller-audit-second.json](evidence/controller-audit-second.json): the second real run also passed all 46 scenario/source/cleanup assertions. Its original invocation failed because the auditor rejected fixed-string addition. The completed trace also exposed a rejected mistyped wait request and partial tool outputs across a yielded cell; the auditor now accounts for both.
- [controller-array-reanalysis.json](evidence/controller-array-reanalysis.json): the corrected auditor passes the three unchanged real traces. Older wait/handle counts are unchanged; the new trace has six unbounded yielded waits and 36 handle resumes. This is reanalysis, not a new integrated pass.
- [controller-audit-array.json](evidence/controller-audit-array.json): all six tasks and 46 scenario/source/cleanup assertions passed, but the auditor rejected a literal command array mapped through `Promise.all` during initial context reads. This original invocation remains a failure.
- [controller-provider-error.json](evidence/controller-provider-error.json): the next attempt completed implementation but a first-round DeepSeek reviewer received CommandCode HTTP 400 before delivering its result. The controller inspected the problem and asked whether to retry, leading to `controller_blocked`. The partial report did not pass the review gate; source integrity and cleanup passed.
- [controller-stalled.json](evidence/controller-stalled.json): a fresh invocation of the final driver stopped after 1,214 seconds. The first GLM worker stayed working without visible progress; the controller asked whether to retry, producing `controller_blocked`. Source integrity and cleanup passed, but the six-task scenario and transcript audit did not complete. The worker stall root cause is undetermined.
- [controller-reanalysis.json](evidence/controller-reanalysis.json): the corrected auditor passes both unchanged real transcripts. Each controller launched six unbounded waits, resumed the same yielded processes, and used no short wait caps. The second controller corrected one rejected task-ID typo. This is post-run reanalysis; neither original driver invocation is relabeled as passing, and this reanalysis is not a fresh integrated pass. The separate current-driver attempt is recorded above.
- [lifecycle.json](evidence/lifecycle.json), [recovery.json](evidence/recovery.json), and [completion.json](evidence/completion.json): sanitized historical real-worker probes, with original artifact hashes and tested source attribution. Their local drivers are not distributed; these records are supporting evidence, not additional portable test commands.

Historical evidence keeps its original source attribution. Moving the driver changes its hash; it does not retroactively change which code an earlier run exercised. The CLI itself is unchanged by the relocation.

`review_loop.py` controls `horch` directly; `controller_loop.py` tests an AI controller following `herdr-orchestrator`. Neither exercises the pstack rubric. Earlier controller/pstack development runs remain attributed to their original sources. GitHub Actions checks Python compatibility, configuration parsing, and installation into Claude Code, Codex, and Pi. Authenticated model E2Es run locally.

## Reproduce original skill discovery

[skill-discovery.json](evidence/skill-discovery.json) records the real 56-entry Pi/Codex catalog checks, preserved original content/resources/licenses, a fresh original `how` invocation with four delivered and closed workers, and real current/older-pin upstream comparisons. The receipt discloses the evaluation controller's corrected tab placement, the user's mid-run role change, and the limited scope of the source walkthrough. The trace review was manual; full transcripts remain private. These results do not validate other original workflows.

Follow [source preparation and installation](../skills/pstack-herdr/references/compatibility.md#install-discoverable-skills). For an isolated installation, use a new directory and omit `-g`:

```bash
consumer=$(mktemp -d)
cd "$consumer"
npx --yes skills@1.7.1 add "$pstack_package" -s '*' -a codex -a claude-code -a pi -y
```

From the repository clone, run the real catalog check (requires installed Pi and Codex, but makes no model calls):

```bash
python3 e2e/skill_catalogs.py "$consumer"
```

It queries Pi's native RPC command catalog and Codex's `skills/list`, verifies that installed names have descriptions and enabled catalog entries, and retains `evidence.json` plus raw catalogs outside the repository. Pi reads the installed files through an isolated user skill directory; Codex discovers them in the disposable project. Unrelated user/system skills are excluded from the comparison. No authentication or trust settings are changed. This measures actual discovery on Pi and Codex. Claude Code's installation links are checked separately; its runtime discovery is not claimed by this script.

For a live routing check, install into the controller's normal skill locations, start a fresh controller in its own Herdr tab, and ask it to use `how` to explain the worker lifecycle across configuration, startup, delivery, and cleanup. Supply the repository, read-only scope, and a local output path, but no skill file path or dispatch sequence. The real invocation should discover `how`, load its adapter, use the configured explorer/explainer roles, wait for delivered results, and clean up its own workers. Inspect actual task records and the controller's local tool trace before accepting the explanation. Keep transcripts and machine-specific paths private. This checks one original skill workflow, not every `poteto-mode` playbook.

The daily monitor can also run locally without models:

```bash
python3 scripts/check_upstream.py --output /tmp/pstack-upstream-result.json
```

It returns 0 for unchanged relevant trees, 1 for changes requiring review, and 2 when the check could not complete. Use `--manifest <file>` to compare a deliberately selected historical upstream revision without changing the repository's pin. The JSON and stdout identify the exact two revisions and changed paths.

## Historical pstack source

The controller/pstack review-loop runs recorded on 2026-10-09 used **pstack-claude 0.9.73**, the port by Michael Denyer, at commit `8d3aa5719ab836e89482c894bbedd710224f4424` ([source](https://github.com/michael-denyer/pstack-claude/tree/v0.9.73/plugins/pstack)). Their role-sheet and runtime mappings belonged to that integration. The original receipts, versions, and hashes remain unchanged.

The current adapter reads Lauren Tan's original `cursor/plugins` checkout directly. Those historical passes do not verify the new source or entry instructions. The [current source pin and update procedure](../skills/pstack-herdr/references/compatibility.md) distinguish source inspection from actual runtime evidence. Neither public loop driver exercises the original pstack rubric.

## Why the lifecycle mechanisms remain

An evidence audit should distinguish a naturally observed failure, a deliberate fault/race exercise, and static reasoning. A passing exercise shows the current behavior; it is not proof of a prior production incident or an exhaustive concurrency test.

| Mechanism | Evidence | Scope of the conclusion |
|---|---|---|
| Startup `flock` | `lifecycle.json`: `simultaneous starts honor one slot` | Two simultaneous real launches with one slot produced one accepted task and one `worker_limit`. Deliberate concurrency exercise. The lock covers startup, not worker execution. |
| Per-task `flock` and monotonic closure | `recovery.json`: `explicit close succeeds during wait`, `background poll preserves confirmed closure`, `background wait exposes closure` | A real worker was explicitly closed while another process waited. Deliberate race exercise; confirmed closure survived polling. |
| Explicit `--recheck` | `recovery.json`: `normal wait preserves problem state`, `explicit recheck recovers original task` | A finished worker's result was deliberately damaged, observed as invalid, then restored. Recheck recovered the same task without another prompt. |
| `task_invalid` | `recovery.json`: `corrupt record does not hide healthy history`, `targeted corrupt record gives task_invalid` | A malformed task record was injected into a store with real task history. Healthy entries remained visible and targeting the damaged record produced a clear error. |
| Explicit missing-pane error codes | `lifecycle.json`: cross-workspace cleanup and `already closed is idempotent` | Confirms direct lookup and already-gone cleanup. The three individual pane/tab/workspace-not-found responses were not each isolated by this probe. Keep the narrow allowlist so other Herdr errors do not falsely confirm closure. |
| Withhold results until turn completion | `verification.json`: Pi controller's `prior_failure`; `completion.json`: early fields, final delivery, cancellation | A real controller previously consumed early reports and closed unfinished reviewers. A later focused probe deliberately injected provisional results and verified withholding. A fresh controller loop passed after the fix. |

These findings support retaining the mechanisms rather than deleting them by line count. They do not establish that every defensive branch was triggered. Deliberate approval denial, turns longer than 30 minutes, macOS runtime, and original-pstack workflows beyond the recorded `how` run remain unverified.
