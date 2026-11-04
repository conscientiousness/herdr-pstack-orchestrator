# Task lifecycle and recovery

## Core API boundary

New launches prefer installed `herdr-core`, then a verified `hc` alias. Only absence selects legacy Herdr. Startup, connection, namespace, configuration and readiness failures never select another backend. Core needs no GUI or `HERDR_ENV`.

`task.json.backend` is a tagged object. `kind: "core"` records `executable`, `session`, `endpoint`, permanent `core_id`, `terminal`, owned `name` and `nonce`, plus only the XDG paths needed for CLI affinity. `kind: "legacy"` uses the original pane/agent path. Records without `backend` always mean legacy; unknown tags are invalid. Optional `viewer` contains separate legacy pane/tab IDs and a pinned legacy socket path, and is not runtime identity.

The core module speaks the official JSON RPC protocol at the pinned local endpoint. Every connection checks core identity with `hello`. Full `terminal.get` facts drive lifecycle evaluation; CLI `ls --json` summaries omit fields and are not equivalent. `events.subscribe` snapshots close the get/subscribe race and wake waits on native changes. Core-only waits have bounded check-ins for reminders; mixed waits retain the legacy polling cadence. No screen text or private transcript determines lifecycle.

Core launches the configured interactive harness without a task. Native OSC 7501 must report idle before a turn baseline is saved and the brief pointer is sent once with an idle guard. Pi, Codex and Claude Code installed during verification natively reported idle. Missing reporting or a startup trust dialog leaves `start_failed` without sending the task. No hooks, extensions, global configuration or permission changes are added. Codex receives `--no-daemon`; conflicting daemon arguments fail rather than replace user arguments. A task-local exec wrapper clears inherited legacy Herdr and controller session variables before starting the harness.

The same shared result evaluator requires idle/done and a native `turn` greater than the saved baseline, plus the exact nonce-bound result. Core increments `turn` on any departure from working, including blocked/error, so an advanced turn alone cannot deliver. Native error, blocked and finished remain distinct. Initial idle and an early result file cannot deliver.

Creation and send failures reconcile only by owned name/nonce at the same endpoint. Uncertain outcomes retain the reservation and an actionable problem. No automatic resend or second-backend launch occurs. Inspect the terminal and use explicit `wait --recheck` after resolving the problem.

Core closure verifies identity, kills only its terminal, observes `finished`, removes it and confirms authoritative absence. An owned viewer is closed separately. `close` returns terminal and viewer cleanup facts; `closed` is true only when both succeed. Connection/namespace failures and identity mismatches never mean already gone. Headless tasks do not invoke legacy Herdr for notifications.

For controllers in Herdr, caller proof and a nonblank `HERDR_SOCKET_PATH` are required before worker allocation. An explicit `--caller-pane` or inherited Herdr context still requires verification when `HERDR_ENV` is missing. Owned attach panes must use `hcOrch` tabs in the verified caller's live workspace, with up to four panes, and never use the caller's tab or take focus. Viewer failure reports and stores a warning without runtime fallback; the controller must immediately report that visibility is unconfirmed and keep monitoring the existing worker. A non-null `viewer` records placement, not proof that attachment rendered successfully. Viewer creation pins `HERDR_SOCKET_PATH` so later cleanup cannot follow a changed legacy endpoint. An ambiguous placement keeps `viewer_unresolved` and its endpoint in the task record; cleanup cannot release that reservation until the owned viewer outcome is reconciled manually. Do not clear that fact merely because the core terminal was removed.

## Legacy Herdr API boundary

The legacy integration follows Herdr 0.9.3's [agent automation](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/agent-automation.mdx) and [socket API guidance](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/socket-api.mdx): use CLI wrappers for ordinary orchestration, response IDs for layout, `agent start` for readiness, and `agent prompt --wait` for acknowledgement. `--no-focus` and separate worker tabs implement this project's layout policy.

Herdr supplies agent lifecycle state; `horch` adds task identity, file delivery, review gates, and cleanup. Its single two-second `agent list` poll covers all waited tasks and the notification timer without invoking a model. Herdr's event-driven `agent wait` targets one agent; replacing this loop with subscriptions would also require reconnect and lost-event reconciliation. The current loop is an orchestration choice, not a missing Herdr wait capability.

Use `visible` reads for passive inspection. Recent-history reads can send mouse-scroll input to an idle full-screen agent before restoring its viewport. Routine status checks should use Herdr's agent metadata, not parse a harness's private session files. The Pi readiness guard below also reads Herdr metadata.

## Delivery, outcome, and review verdict

`horch wait` reports the transport state; `result.json` reports the worker's outcome. The controller verifies that outcome separately.

| Task state | Result status | Meaning and next action |
|---|---|---|
| `running` / `long_running` | Any file on disk | Keep waiting. The worker may still change it. |
| `done` | `completed` | Delivery finished; verify the work and any review verdict. |
| `done` | `failed` | Delivery finished; the worker reports failure. Read its report and tell the user. |
| `done` | `blocked` | Delivery finished; relay `question`, then start a fresh task with the answer. |

The existing `done` value is kept for compatibility with v0.1.0 clients and stored task records. It means a finished turn with a valid result, not a successful implementation or a passing review. `horch check` reports `ok: true` only for `done`, a valid result with `status: "completed"`, and confirmed pane closure.

Each `horch wait` line has `task_id`, `state`, `summary`, `result_path`, `files`, `question`, `closed`, and `message`. Until the task is `done` with a valid result, `summary` and `question` are null and `files` is empty. `result_path` always names the expected location; it does not signal completion. Result file paths in `files` are relative to the directory of `result_path`.

A valid result has exactly six keys: matching `task_id` and `nonce`, `status` (`completed`, `failed`, or `blocked`), a string `summary`, a list of string `files`, and `question` (nonempty string when blocked, otherwise null).

For legacy tasks, Herdr must also report that the turn ended: an idle/done agent with `completion_seq` newer than the pre-prompt baseline, or the observed working-to-idle fallback when no completion sequence is available. An idle agent alone does not establish completion.

Before submitting a legacy Pi task, `horch` additionally waits for the installed Herdr Pi integration to report an idle/done session within the startup budget. Herdr 0.9.3's `interactive_ready` alone can describe Pi 1.1.0's trust dialog. Without the session signal, startup returns `start_failed`, retains the pane, and sends no task prompt. Install the integration and let the user resolve any dialog before starting a fresh task.

## States


| State | Meaning | What to do |
|---|---|---|
| `running` | The worker is working. | Wait again. |
| `long_running` | The task passed `notify_after_minutes`. Reported once. | Tell the user, then wait again. |
| `done` | The turn ended with a valid `result.json`. | Read the result and check `closed` / `message`. |
| `start_failed` | The harness did not start, usually a dialog. | See "Problems". |
| `not_started` | Herdr did not observe acknowledgement within the prompt wait. The task may still be running. | See "Problems". |
| `blocked` | The worker waits at a dialog or permission prompt. | See "Problems". |
| `exited` | The worker process is gone or the core terminal finished without delivery. | See "Problems". |
| `error` | The core worker reported a native error. | Inspect without resending or changing backend. |
| `result_missing` | The turn ended without a valid `result.json`, often after a provider API error. | See "Problems". |
| `result_invalid` | `result.json` does not parse or its `task_id` or `nonce` is wrong. | See "Problems". |

## Problem recovery

Follow the [controller's problem procedure](../SKILL.md#problems) before cleanup. Ordinary waits return stored problem states without polling them again.

If inspection shows a previously unacknowledged task started, or the user cleared a dialog, use `horch wait <task-id> --recheck`. Apply the same background or bounded waiting method as a normal wait. Recheck requires explicit task IDs, never resends a prompt, and never restarts a process. Closed and completed tasks are not reopened. An exited process's result stays on disk for inspection; without turn-completion evidence it is not promoted to `done`.

When `done` has `closed: false`, read `message` and retry `horch close <task-id>`. The worker slot remains occupied until closure is confirmed. Closing an unfinished worker cancels it and cannot satisfy a completion or review gate.

A pane-placement error can leave an empty pane when Herdr's response was lost. No worker has started at that point. Inspect Herdr before removing it; never close an unrelated pane. `list` reports `task_invalid` records without hiding healthy history. Each unclosed invalid record reserves one slot in every caller workspace because its owner and pane are unknown; a full `run` returns `worker_limit`, naming the invalid IDs and `horch list`. `check` keeps polling its started tasks and starts pending workers as slots free; workers it cannot start are `not_checked`, with invalid IDs and `horch list` in their message when invalid records held capacity. No-ID `wait` skips them; targeted `wait` still returns `task_invalid`. `close` also returns `task_invalid`: check `herdr pane list` for a leftover `horch` pane, then remove the task directory by hand. Nothing is deleted automatically.

## Task store and concurrency

Core admission counts all unclosed tasks with the same permanent core ID in this store, plus legacy reservations in the GUI caller's workspace when present. This conservative core quota is session-wide, including headless controllers. Core addresses never enter the older-record legacy pane-membership heuristic. Invalid unclosed records reserve capacity in every scope.

For legacy launches, processes sharing a task store serialize startup to enforce `max_active_workers` independently for each workspace; workers execute concurrently after launch. Controllers in the same workspace share its slots when they use the same state directory. The shared startup lock prevents two controllers from claiming the last slot together; it does not turn workspace quotas into a total limit. Short per-task transactions prevent a concurrent wait from overwriting confirmed closure. JSON updates replace files atomically.

New task records retain the live caller's `workspace_id` at launch. An unclosed task keeps occupying that workspace's slot, including after a manual pane move or a failed startup. Older records without `workspace_id` count when their recorded pane is present in that workspace's live pane list. A missing legacy pane cannot reserve a slot in another workspace; pane-list failures leave admission unresolved instead of assuming capacity is free. No configuration migration is required.

Core records retain endpoint and core identity, so a store can hold tasks from different core sessions. Legacy records still require one legacy Herdr server per store. Scope legacy use of each task store to one Herdr server. Pane IDs and agent names are server-local, and legacy task records do not retain their originating socket. If using multiple named sessions or machines, give each a separate `XDG_STATE_HOME` and operate its tasks only through that server. Cross-server cleanup with a shared store is unsupported and can target an unrelated pane with the same ID.

A Pi worker waiting for its session signal can use the full 90-second startup budget while holding the startup lock. Install the integration and resolve startup dialogs before checking several workers; `check` stops launching new checks when its overall budget expires.

`horch close` resolves the recorded pane directly, even from another workspace. Only explicit pane/tab/workspace-not-found responses establish that it is already gone; other Herdr errors leave cleanup unresolved.

`check` batches at its caller workspace's `max_active_workers` and deduplicates repeated worker names. Each row has `worker`, `task_id`, `state`, `ok`, `pane_id`, `seconds`, and `message`. Workers that cannot start before the wait cap or have no free slot are `not_checked`, with null task, pane, and duration. Invalid reservations do not abort a batch: started tasks are still polled and pending workers launch as slots free. If invalid records held capacity, never-started workers' messages name those IDs and recommend `horch list`. Unfinished/problem tasks retain their panes; inspect `message` before acting.
