# Worker review loop

## Live worker replacement

Use two existing workers with different execution definitions. Their permission
flags and trust settings are preserved. The isolated alias is replaced while a
real reconciliation task is running, then removed while two tasks remain live.

```bash
python3 e2e/check_workers.py --hot-swap-only \
  --worker <configured-worker-a> --worker <configured-worker-b> \
  --cwd "$repo" --output "$proof" --max-seconds 1200
```

Require valid delivered results, independent 720-event reconciliation outputs,
rerunnable scripts, unchanged task launch snapshots across replacement/removal,
new-task selection of the second definition, refusal after alias removal without
allocation, unchanged real config/skills/checkout, and owned cleanup. Read native
model-audit availability and any limitations. Identical definitions produce a
skip, never a replacement pass. This checks worker config changes; it does not
prove an active controller reloads skill instructions.

The driver owns a separate workspace and uses its real shell ancestry. It
preserves original Mise roots when isolating XDG state and never answers a trust
dialog. Retain the printed receipt and private diagnostics after cleanup.

## Sub-features

Fresh implementation, two independent failing reviews, a fresh fix, and two passing reviews of an invoice CLI. The driver also executes edge-case invoices and checks scope, result delivery, and pane cleanup.

## How to get to it (user POV)

Use configured workers through `agent-workers`. Select `writer`, `reviewer_a`, and `reviewer_b` from workers.toml; reviewers must have distinct model definitions. Require two free slots, authenticated harnesses, a trusted repository, and Pi integration for Pi workers. Use the shared Doctor first.

## Driving it with existing scripts

```bash
python3 e2e/review_loop.py --writer "$writer" \
  --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Read the printed `evidence.json`: require a passing verdict, expected initial FAIL/final PASS reviews, observed invoice results, and confirmed pane cleanup. Inspect the retained worktree, then remove that exact worktree with Git while retaining the sibling receipt. See the [driver documentation](../../../../e2e/README.md) for the full scenario.

## Gotchas

This makes real model calls and tests `agent-workers` directly, not an AI controller or pstack rubric. A newly created worktree can need its own Pi trust decision; report a blocked startup without submitting input to the dialog. A historical passing receipt does not prove a new run passed.

## Worker setup checks

Select at least two distinct authenticated configured workers (mixed harnesses are optional). Use an already trusted checkout and the shared Doctor; verify the actual caller pane before running:

```bash
python3 e2e/check_workers.py --worker "$worker_a" --worker "$worker_b" \
  --cwd "$repo" --output "$proof"
```

The driver creates a dedicated workspace and isolated state, repeats the first worker selection, and forces batching with one slot. Require all 44 behavioral receipt assertions (20 existing checks plus 24 stats checks): deduplication bound to the sent selection, strictly ordered task-publication/previous-closure filesystem timestamps, valid nonce-bound results, no leaked panes before teardown, zero-slot skips, the deliberately injected acknowledged-worker exit, exhausted-budget skips, source/configuration integrity and owned cleanup. Inspect the printed sanitized `evidence.json`; preserve failures without retrying another model or clearing dialogs. No pane transcripts are captured. The verdict also requires full scenario completion. Herdr CLI and running-server versions are recorded separately. Known paths, including cwd/output and rerun arguments, are replaced; free-form message/error diagnostics are omitted. Retained config/task state and command/failure diagnostics outside the checkout are private, not publication artifacts; only their placeholder location is in the receipt. Coarse/equal lifecycle timestamps fail closed. The final phase also checks read-only `agent-workers stats` on the isolated store, globally and scoped to the owned workspace: known counts/states/statuses, invalid exclusion, removed and unused workers, timestamp/duration bounds, no args, and unchanged files, then closes one real running worker and verifies cancellation counts without extra problems. Fixed fixtures additionally verify recovered first-done durations, multi-sample percentiles, strict/deduplicated threshold estimates, day scope, dangling roles, provider/configuration facts, in-flight separation, and stored reminder firings per worker and in total across scopes. This directly exercises `agent-workers check` and `stats`, not an AI controller.

## Workspace worker limits

For quota changes, select one authenticated worker from the existing configuration and use a trusted checkout. The driver creates two temporary workspaces with their own caller panes, a shared isolated task store, and a two-slot limit in each workspace:

```bash
python3 e2e/workspace_limits.py --worker "$worker" --output "$proof"
```

It fills the first workspace, checks local `run` and `check` refusals, strips workspace metadata from its own records to exercise legacy installation compatibility, then fills the second workspace. After real result delivery and cleanup, a fresh setup check must succeed. Read the printed receipt and require all capacity, result, source-integrity, and cleanup assertions to pass. Preserve failed receipts and inspect owned problem panes before teardown. Never clear worker dialogs or change configured permission flags to make the check pass. The driver removes only its own workspaces; retained receipts and diagnostics stay outside the checkout.
