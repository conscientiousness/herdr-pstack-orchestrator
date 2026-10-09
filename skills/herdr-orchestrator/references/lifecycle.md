# Task lifecycle and recovery

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

Herdr must also report that the turn ended: an idle/done agent with `completion_seq` newer than the pre-prompt baseline, or the observed working-to-idle fallback when no completion sequence is available. An idle agent alone does not establish completion.

## States


| State | Meaning | What to do |
|---|---|---|
| `running` | The worker is working. | Wait again. |
| `long_running` | The task passed `notify_after_minutes`. Reported once. | Tell the user, then wait again. |
| `done` | The turn ended with a valid `result.json`. | Read the result and check `closed` / `message`. |
| `start_failed` | The harness did not start, usually a dialog. | See "Problems". |
| `not_started` | Herdr did not observe acknowledgement within the prompt wait. The task may still be running. | See "Problems". |
| `blocked` | The worker waits at a dialog or permission prompt. | See "Problems". |
| `exited` | The worker process is gone. | See "Problems". |
| `result_missing` | The turn ended without a valid `result.json`, often after a provider API error. | See "Problems". |
| `result_invalid` | `result.json` does not parse or its `task_id` or `nonce` is wrong. | See "Problems". |

## Problem recovery

Follow the [controller's problem procedure](../SKILL.md#problems) before cleanup. Ordinary waits return stored problem states without polling them again.

If inspection shows a previously unacknowledged task started, or the user cleared a dialog, use `horch wait <task-id> --recheck`. Apply the same background or bounded waiting method as a normal wait. Recheck requires explicit task IDs, never resends a prompt, and never restarts a process. Closed and completed tasks are not reopened. An exited process's result stays on disk for inspection; without turn-completion evidence it is not promoted to `done`.

When `done` has `closed: false`, read `message` and retry `horch close <task-id>`. The worker slot remains occupied until closure is confirmed. Closing an unfinished worker cancels it and cannot satisfy a completion or review gate.

A pane-placement error can leave an empty pane when Herdr's response was lost. No worker has started at that point. Inspect Herdr before removing it; never close an unrelated pane. A `task_invalid` record requires inspection of its task directory before repair or removal. `list` reports corrupt records without hiding healthy history.

## Task store and concurrency

Processes sharing a task store serialize startup to enforce `max_active_workers`; workers execute concurrently after launch. Use the same state directory for controllers that should share one limit. Short per-task transactions prevent a concurrent wait from overwriting confirmed closure. JSON updates replace files atomically.

`horch close` resolves the recorded pane directly, even from another workspace. Only explicit pane/tab/workspace-not-found responses establish that it is already gone; other Herdr errors leave cleanup unresolved.

`check` batches at `max_active_workers` and deduplicates repeated worker names. Each row has `worker`, `task_id`, `state`, `ok`, `pane_id`, `seconds`, and `message`. Workers that cannot start before the wait cap or have no free slot are `not_checked`, with null task, pane, and duration. Unfinished/problem tasks retain their panes; inspect `message` before acting.
