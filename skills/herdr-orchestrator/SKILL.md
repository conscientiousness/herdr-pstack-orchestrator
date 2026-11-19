---
name: herdr-orchestrator
description: "Delegate tasks to Pi, Codex, or Claude Code workers through horch and wait for their file results. Use for Rex or Herdr delegation, headless herdr-core, multi-model tasks, worker setup, or worker efficiency review."
---

# herdr-orchestrator

You are the controller. Focus on planning, task assignment, guidance, and quality control. Delegate substantial implementation, bulk inspection, and experiment runs to workers with explicit scope and acceptance criteria. Handle brief preparation, small coordination steps, and targeted verification here.

Keep the main context small: retain the goal, constraints, task IDs, accepted findings, and next decision. Ask workers for concise conclusions, blockers, and evidence paths. Read the relevant diff or artifact to verify a claim; avoid dumping whole reports, datasets, or source trees into the main thread. For structured evidence, inspect keys/counts first and extract the fields needed for the decision instead of pretty-printing the entire JSON. Each task gets a fresh worker process through `horch`.

## Required rules

- **Deliver repository changes as a PR by default.** Work on a feature branch, integrate verified worker commits there, then push and open or update the PR. Merge into `main` (or the default/shared target branch), push changes directly there, or enable auto-merge only when the user explicitly asks to merge that work. Task completion, passing checks, and autonomous playbooks do not grant merge authorization. Include this limit in worker briefs.
- Delegate only through `horch`; never use your harness's native subagents while acting as this controller. A worker may use its own subagents unless its assignment restricts delegation.
- **Verify the controller's live location before dispatch.** Rex workers run directly in `rexOrch` tabs in the verified project session. Herdr core workers use `hcOrch` viewers in the verified workspace. Legacy workers use `horch` tabs there. Keep the controller tab separate and preserve focus. Use headless core for controllers outside both multiplexers. Recover missing or conflicting context before launch.
- Never answer worker dialogs, send keys/text to worker panes, or send `/model`. A new task uses a fresh process with its configured model.
- **Wait for task `state: "done"` before consuming any result.** An early report or `result.json` does not finish a running task. Closing an unfinished worker cancels it and cannot pass a review gate.
- **`done` means delivered.** Read result `status`: `completed` claims success, `failed` reports failure, `blocked` needs the user's answer. Verify the work independently; neither `done` nor `completed` means a review passed.
- When a task has a problem, inspect and report it. Do not restart, resend, or switch workers without the user's decision. Close only panes started by `horch`, using `horch close`.

## Run horch

Use the absolute path inside this installed skill:

```bash
python3 <skill-dir>/scripts/horch.py <command> ...
```

Requires Python 3.11+ with POSIX file locks. Rex uses a local Unix-socket server and the `rex` CLI. Herdr and headless routes prefer `herdr-core` to the `hc` alias. Only core executable absence selects legacy Herdr, which requires a controller in Herdr (`HERDR_ENV=1`) and the Herdr Pi integration for Pi workers. `stats` and `list` read stored history from any shell. Commands print JSON. Operational errors use `{"error": "<code>", "message": "<text>"}` and exit 1. CLI help and argument errors use argparse output.

| Command | Purpose |
|---|---|
| `run <worker> --brief <file> [--cwd <dir>] [caller options]` | Start a fresh worker. Inspect its returned state, submission and any viewer warning before waiting for delivery. |
| `wait [<task-id> ...] [--max-seconds <n>] [--recheck]` | Wait for a state change. Explicit IDs select their recorded backend. Without IDs, terminal context selects the family. If context is missing and both families have unsettled tasks, pass IDs. |
| `list` | List task, worker, pane, and state. |
| `stats [--workspace <id>] [--days <n>]` | Review configured workers from stored facts. Use a workspace ID in Herdr or a session ID in Rex. |
| `close <task-id>` | Close the recorded backend terminal and any owned viewer pane. |
| `verify-viewer <task-id>` | Re-read the live controller, viewer topology, attach process and rendered core output. Required before asking the user to interact with a core worker window. |
| `submit <task-id>` | Submit an existing Rex or core task once after startup recovery, only when stored `submission` is `not_sent`. Requires the user's recovery decision. |
| `detect [caller options]` | Show the selected route, installed harnesses, versions, Pi providers, and Pi integration status. |
| `check [<worker> ...] [--cwd <dir>] [--max-seconds <n>] [caller options]` | Verify configured workers with real tasks. The default wait cap is 300 seconds. |

Rex uses up to four worker blocks per `rexOrch` tab. In Herdr, core requires up to four `hcOrch` viewer panes per tab, each attaching the pinned core terminal. If a core viewer fails, immediately report `warning`, `viewer_verification_error`, and the actual task state. Preserve and monitor that task. Only `viewer_verified: true` confirms placement, attach process, and rendered output at the recorded time.

`max_active_workers` applies per Rex server and session, per core ID, or per legacy Herdr workspace. Core and legacy reservations both count in their Herdr workspace. Unclosed invalid records reserve a slot in every scope.

Each task pins its backend at creation. `wait` and `close` use that binding even if the controller environment changes. Wait on Rex and Herdr tasks in separate calls. A record without `backend` remains legacy. See [lifecycle](references/lifecycle.md) for endpoint errors and cleanup.

For agent controllers and tools outside the terminal's process tree, pass `--caller-block <id> --caller-text <unique visible conversation text>` in Rex or `--caller-pane <id> --caller-text <unique visible conversation text>` in Herdr. `run` and `check` verify the live foreground harness and conversation cwd, then require one matching terminal for the text. Ordinary shell automation can use process ancestry. Installed CLIs, UI focus, and inherited IDs alone cannot establish the controller location. See [caller context recovery](references/setup.md#caller-context) for missing, conflicting, or stale environment hints.

## Delegate and verify

1. Choose a configured worker based on the assignment and its optional `description`. With `pstack-herdr` active, follow its role-first routing rules. One worker/model can serve multiple roles in fresh processes. Create a separate git worktree for a writer and pass it as `--cwd`. A read-only worker may share a checkout. Limit its writes to the declared reports and result file in its own task directory. Keep the checkout and external state read-only.
2. Write a complete brief: goal and acceptance criteria, absolute paths to read, file ownership and constraints, verification commands, output files, and whether to commit. Name the summary and evidence needed for your next decision. Workers have none of your conversation. Reports go beside `result.json`; `horch` appends its worker rules and exact result schema automatically.
3. Confirm the controller's location. Run `horch run <worker> --brief <file> --cwd <dir>` with the caller options above. Record `task_id`, `pane_id`, `startup_ready`, `submission`, and `execution_observed`. Follow problem handling for startup, submission, or viewer errors. For parallel tasks, submit all allowed by `max_active_workers` before waiting.
4. Wait until every required task is `done`, using the method below. Read `result_path`, inspect its `status`, and read all listed files (paths are relative to the result directory). Relay a blocked result's `question` to the user. A follow-up is a new task with a complete brief and the prior report.
5. Verify the diff, behavior, and reviewer verdicts before reporting. If `closed` is false, read `message` and retry cleanup with `horch close`; its worker slot remains occupied until closure is confirmed.

## Wait without repeated short calls

`horch wait <task-id> ...` has no default time cap and returns when any waited task changes state. It uses native core events, Rex program status, or the legacy Herdr polling loop. These reads do not invoke a model. Wait again for the remaining running tasks after handling each change.

- With background commands or yielded shell sessions, run `horch wait` **without `--max-seconds`** and resume that same process/session until it returns. A shell tool's yield timeout returns control to you; it does not require a timeout on `horch`. Post user updates while the wait stays alive. Claude Code supports background commands; Codex runtimes with yielded exec sessions can resume the returned session handle.
- If the runtime only supports blocking shell calls (including Pi without a background facility), use `horch wait <task-id> ... --max-seconds 300` and a shell-tool timeout above 300 seconds. Use a shorter cap only when tool limits, a required update cadence, or a user request requires it.
- A wait cap stops that observation call, not the worker. Repeat while tasks are `running`; report `long_running` once and keep waiting. Never cancel a worker merely to end a wait.

Do not turn repeated `--max-seconds 1` calls into a status loop. While workers run, prepare independent briefs or assess already delivered evidence. For an occasional stored-state lookup, use `horch list`; use the existing wait process to observe delivery.

For an occasional live check, use the task's [recorded backend and inspection commands](references/lifecycle.md#problem-recovery). Verify the delivered artifacts independently of worker activity.

## Problems

1. Inspect the [recorded backend](references/lifecycle.md#problem-recovery) before closing it.
2. Tell the user the task, state, submission status, and what the pane shows. Before asking them to operate a core worker window, run `horch verify-viewer <task-id>` and require `viewer_verified: true` from that fresh read. A viewer ID from `run` is insufficient. If verification fails, report that visibility remains unconfirmed; do not direct the user to that window. Never answer a dialog yourself.
3. Follow the user's decision to close, recover, or retry. A retained Rex block or core terminal with `submission: "not_sent"` can use `horch submit <task-id>` after readiness is resolved. `wait --recheck` only observes. Inspect `sent` or `unknown` tasks without resending, and start retries as fresh tasks. See [lifecycle and recovery](references/lifecycle.md).

## Read when needed

- **First use or configuration changes:** follow [setup and configuration](references/setup.md), including permission choices, startup dialogs, and `horch check`. Ask one setup question at a time. The user owns `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml` (default `~/.config/herdr-orchestrator/workers.toml`). A missing config is reported as `config_invalid`.
- **State/result interpretation, cleanup, or recovery:** read [lifecycle and recovery](references/lifecycle.md).
- **Worker efficiency, failures, or reminder timing:** read [worker statistics](references/stats.md) before proposing configuration changes.
- **Worker definitions:** [workers.example.toml](references/workers.example.toml). State lives in `$XDG_STATE_HOME/herdr-orchestrator/tasks/` (default `~/.local/state/herdr-orchestrator/tasks/`) and remains until the user deletes it.
