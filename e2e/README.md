# End-to-end verification

These files are repository tooling, outside both installed Agent Skills. Run the public driver from a clone inside Herdr:

```bash
python3 e2e/review_loop.py \
  --writer gpt --reviewer glm --reviewer haiku \
  --repo . --output /tmp/horch-evidence
```

Choose configured workers and two reviewers with distinct model definitions. The driver makes real model calls, needs two free slots, and uses a detached worktree. It plants two independent invoice defects, checks a scoped implementation, requires two failing initial reviews, then checks a fresh fix and two passing final reviews. It also covers fractional/full discounts, zero quantities, and single-line invoices.

The run retains its worktree and writes `evidence.json` with assertions, source hashes, revisions, and observed CLI output. It cleans up only panes it started. Reports stay in the local task store; no transcripts go into evidence. Remove the retained worktree with `git worktree remove <printed-path>` after inspection.

## Evidence and source attribution

- [verification.json](evidence/verification.json): development runs, tested versions, source hashes, and limits.
- [review-e2e.json](evidence/review-e2e.json): the public six-task driver run and its observed outputs.
- [lifecycle.json](evidence/lifecycle.json), [recovery.json](evidence/recovery.json), and [completion.json](evidence/completion.json): sanitized historical real-worker probes, with original artifact hashes and tested source attribution. Their local drivers are not distributed; these records are supporting evidence, not additional portable test commands.

Historical evidence keeps its original source attribution. Moving the driver changes its hash; it does not retroactively change which code an earlier run exercised. The CLI itself is unchanged by the relocation.

The public driver controls `horch` directly. It does not test an AI controller following the skills or pstack rubric; those development runs are identified separately. GitHub Actions checks Python compatibility, configuration parsing, and installation into Claude Code, Codex, and Pi. Authenticated model E2Es run locally.

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

These findings support retaining the mechanisms rather than deleting them by line count. They do not establish that every defensive branch was triggered. Deliberate approval denial, turns longer than 30 minutes, macOS runtime, and pstack workflows outside the review loop remain unverified.
