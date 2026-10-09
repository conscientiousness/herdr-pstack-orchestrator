---
name: herdr-orchestrator
description: "Delegate tasks to worker agents (Pi, Codex, Claude Code) that run in their own herdr panes, then wait for and read their file results. Use when the user asks to delegate, dispatch, or parallelize work through herdr or horch, to run several models on one task, or to set up herdr workers. Requires HERDR_ENV=1."
---

# herdr-orchestrator

You are the controller. Delegate one task to each fresh worker process through `horch`, wait for delivery, then verify the result.

## Required rules

- Delegate only through `horch`; never use your harness's native subagents while acting as this controller. Workers may use their own subagents.
- Never answer worker dialogs, send keys/text to worker panes, or send `/model`. A new task uses a fresh process with its configured model.
- **Wait for task `state: "done"` before consuming any result.** An early report or `result.json` does not finish a running task. Closing an unfinished worker cancels it and cannot pass a review gate.
- **`done` means delivered.** Read result `status`: `completed` claims success, `failed` reports failure, `blocked` needs the user's answer. Verify the work independently; neither `done` nor `completed` means a review passed.
- When a task has a problem, inspect and report it. Do not restart, resend, or switch workers without the user's decision. Close only panes started by `horch`, using `horch close`.

## Run horch

Use the absolute path inside this installed skill:

```bash
python3 <skill-dir>/scripts/horch.py <command> ...
```

Requires Python 3.11+ on Linux/macOS and a controller inside Herdr (`HERDR_ENV=1`). Pi workers also require `herdr integration install pi` so startup dialogs cannot receive task prompts. Commands print JSON; operational errors use `{"error": "<code>", "message": "<text>"}` and exit 1. CLI help and argument errors use argparse output.

| Command | Purpose |
|---|---|
| `run <worker> --brief <file> [--cwd <dir>]` | Start a fresh worker and submit its brief; returns after startup and prompt acknowledgement, before task completion. |
| `wait [<task-id> ...] [--max-seconds <n>] [--recheck]` | Wait for a state change. No IDs selects all unsettled tasks. See waiting below. |
| `list` | List task, worker, pane, and state. |
| `close <task-id>` | Close that task's recorded pane. |
| `detect` | List installed harnesses, versions, and Pi providers. |
| `check [<worker> ...] [--cwd <dir>] [--max-seconds <n>]` | Verify configured workers with real tasks; default wait cap 300 seconds. |

Workers open in `horch` tabs in your workspace, at most four panes per tab, without taking focus or using your tab.

## Delegate and verify

1. Choose a configured worker. Create a separate git worktree for a writer and pass it as `--cwd`. A read-only worker may share a checkout; explicitly forbid file and external-state changes in its brief.
2. Write a complete brief: goal, absolute paths to read, file ownership and constraints, verification commands, output files, and whether to commit. Workers have none of your conversation. Reports go beside `result.json`; `horch` appends its worker rules and exact result schema automatically.
3. Run `horch run <worker> --brief <file> --cwd <dir>`. Record `task_id` and `pane_id`; any state other than `running` needs problem handling. For parallel tasks, submit all allowed by `max_active_workers` before waiting.
4. Wait until every required task is `done`, using the method below. Read `result_path`, inspect its `status`, and read all listed files (paths are relative to the result directory). Relay a blocked result's `question` to the user. A follow-up is a new task with a complete brief and the prior report.
5. Verify the diff, behavior, and reviewer verdicts before reporting. If `closed` is false, read `message` and retry cleanup with `horch close`; its worker slot remains occupied until closure is confirmed.

## Wait without repeated short calls

`horch wait <task-id> ...` has no default time cap and returns when any waited task changes state. It polls Herdr internally; those polls do not invoke a model. Wait again for the remaining running tasks after handling each change.

- Prefer your harness's background command or yielded shell session for `horch wait`. Keep that same process/session until it returns; use completion notifications when available. Post required user updates while it runs. Claude Code supports background commands; Codex runtimes with yielded exec sessions can resume the returned session handle.
- If the runtime only supports blocking shell calls (including Pi without a background facility), use `horch wait <task-id> ... --max-seconds 300` and a shell-tool timeout above 300 seconds. Use a shorter cap only when tool limits, a required update cadence, or a user request requires it.
- A wait cap stops that observation call, not the worker. Repeat while tasks are `running`; report `long_running` once and keep waiting. Never cancel a worker merely to end a wait.

## Problems

1. Read the pane before closing it: `herdr pane read <pane_id> --source recent --lines 40`.
2. Tell the user the task, state, and what the pane shows. Never answer a dialog yourself.
3. Follow the user's decision to close or retry. Start retries as fresh tasks. If the original task recovered after inspection, use explicit `--recheck` as described in [lifecycle and recovery](references/lifecycle.md).

## Read when needed

- **First use or configuration changes:** follow [setup and configuration](references/setup.md), including permission choices, startup dialogs, and `horch check`. Ask one setup question at a time. The user owns `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml` (default `~/.config/herdr-orchestrator/workers.toml`). A missing config is reported as `config_invalid`.
- **State/result interpretation, cleanup, or recovery:** read [lifecycle and recovery](references/lifecycle.md).
- **Worker definitions:** [workers.example.toml](references/workers.example.toml). State lives in `$XDG_STATE_HOME/herdr-orchestrator/tasks/` (default `~/.local/state/herdr-orchestrator/tasks/`) and remains until the user deletes it.
