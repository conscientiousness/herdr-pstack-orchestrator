---
name: herdr-orchestrator
description: "Delegate tasks to worker agents (Pi, Codex, Claude Code) that run in their own herdr panes, then wait for and read their file results. Use when the user asks to delegate, dispatch, or parallelize work through herdr or horch, to run several models on one task, or to set up herdr workers. Requires HERDR_ENV=1."
---

# herdr-orchestrator

You are the controller. You start worker agents in other herdr panes with `horch`, give each worker one task through a brief file, wait for the task to end, and read the result files. Each worker can be a different harness and model.

## Rules

- Delegate only through `horch`. Never use your own harness's native subagents (such as the Claude Code `Agent` tool) while you act as the controller. Workers may use their own subagents.
- Never answer a dialog in a worker pane. Never send keys or text to a worker pane. Never send `/model` to a worker. To use another model, start a new task with another worker.
- One task per worker. `horch` never reuses a worker. For a follow-up, start a new task whose brief carries everything the worker needs.
- When a task has a problem, do not restart it, resend it, or switch workers on your own. Tell the user what happened and let them decide.
- Close only panes that `horch` started, with `horch close`.

## Running horch

`horch` is `scripts/horch.py` in this skill's directory. Run it with its absolute path:

```
python3 <skill-dir>/scripts/horch.py <command> ...
```

It needs Python 3.11 or later on a POSIX system (Linux or macOS) and must run inside a herdr pane (`HERDR_ENV=1`). Operational commands print JSON on stdout. An error is one object `{"error": "<code>", "message": "<text>"}` with exit status 1. CLI help and argument errors use normal argparse output.

| Command | What it does |
|---|---|
| `run <worker> --brief <file> [--cwd <dir>]` | Start a worker in a new pane and give it the task. Returns at once. |
| `wait [<task-id> ...] [--max-seconds <n>] [--recheck]` | Block until a waited task changes state, then print one line per task. No IDs means every unsettled task. `--recheck` requires IDs and checks existing unclosed problem tasks again without resending prompts. |
| `list` | Print every task with its worker, pane, and state. |
| `close <task-id>` | Close the pane of a task. |
| `detect` | Print installed harnesses, versions, and the Pi providers. |
| `check [<worker> ...] [--cwd <dir>] [--max-seconds <n>]` | Start each selected worker once on a tiny task and report whether it works. Default wait cap 300 seconds. |

Workers open in tabs labeled `horch` in your workspace, at most four panes per tab, without taking focus. Your own tab never gets a worker pane.

Processes sharing a task store serialize startup to enforce `max_active_workers`; workers execute concurrently after launch. Use the same state directory for controllers that should share one worker limit. `horch close` resolves a recorded pane directly, even when the caller is in another workspace.

`check` batches at `max_active_workers` and ignores repeated worker names. Each row has `worker`, `task_id`, `state`, `ok`, `pane_id`, `seconds`, and `message`. A worker that cannot start before the wait cap or has no free slot is `not_checked`, with null task, pane, and duration. Unfinished or problem tasks keep their panes; read `message` before deciding what to do.

## First-use setup

Run the setup when the user asks for it, or when `horch run` fails with `config_invalid` because `workers.toml` does not exist. Ask the user one question at a time.

1. Run `horch detect`. Show the user which harnesses are installed and which Pi providers have models.
2. Ask which workers to define. A worker is a name plus a harness, a model, an optional effort, and optional extra arguments. Users often want two or more workers on different models, so that one can review another's work.
   - Pi: run `pi --list-models <text>` to find a model. Use the `provider` key with the model ID from that list. `effort` is the Pi thinking level (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`).
   - Codex: the model name that `codex -m` accepts. `effort` is the value for Codex's `model_reasoning_effort`, such as `medium` or `high`.
   - Claude Code: an alias such as `opus`, `sonnet`, or `haiku`, or a full model ID. `effort` is the value for `claude --effort`, such as `high` or `max`.
3. Ask for the permission arguments of each worker. A worker that stops at a permission prompt stays stuck, because you never answer dialogs. Tell the user that the flags they choose are their authorization for that worker. Recommend automatic approval modes. These flags completed real worker tasks without permission prompts on 2026-10-09:

   | Harness | Arguments | Effect |
   |---|---|---|
   | `pi` | none | Pi does not prompt by default. |
   | `codex` | `-s workspace-write -a on-request -c approvals_reviewer='"auto_review"'` | Recommended. Automatically reviews approval requests. Verified for shell commands and writes in the task directory outside cwd. |
   | `codex` | `-s workspace-write -a never` | Writes in its cwd and in the task directory, never prompts. Verified. |
   | `claude` | `--permission-mode auto` | Recommended. Automatically reviews actions. Verified for a worker and a controller that ran shell commands, delegated tasks, and read result files. |
   | `claude` | `--permission-mode acceptEdits` | Edits files without a prompt. Shell commands and reads outside the project can still prompt. Verified for file writes. |

   Automatic approval can deny an action. These runs verified successful workflows; they did not deliberately trigger a denial. Inspect and report any worker problem as described below. Startup trust dialogs are separate from action approval.

4. Ask for `max_active_workers` (default 4) and `notify_after_minutes` (default 180).
   The controller needs access to both the configuration directory (`~/.config/herdr-orchestrator/`) and the task directory (`~/.local/state/herdr-orchestrator/`, or their XDG equivalents). Claude Code's `auto` mode completed a skill E2E that read the configured `workers.toml` and task results outside the project. With other permission modes, reads outside the project can prompt; the user can add the directories to `permissions.additionalDirectories` in their Claude Code settings.
5. Write `~/.config/herdr-orchestrator/workers.toml` (or `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`) in the format under "Configuration". Show the user the file.
6. Run `horch check --cwd <a directory the workers will work in>`. Each line has `ok`. For a line with `ok: false`, read `message`, look at the pane it names (see "Problems"), and tell the user. After the user clears a dialog, run `horch close <task-id>` and `horch check <worker>` again.

## Dialogs that stop a worker before it starts

These appear before the worker reads its task. `horch` reports `start_failed` and leaves the pane open. The user must clear each one once, in the pane or by starting the harness there themselves.

- Codex asks "Trust this folder?" for every git repository it has not trusted yet. Trust belongs to the git root. A trusted parent folder does not cover a new repository below it. Worktrees of a trusted repository are covered.
- Claude Code asks whether to trust a folder the first time it runs there.
- Claude Code asks "Allow external CLAUDE.md file imports?" when the worker's cwd is a subdirectory of a project whose `CLAUDE.md` imports a file with `@`.

## Delegating a task

1. Choose the worker and the directory it works in.
   - A worker that changes files works in its own git worktree. Create it first, for example `git worktree add <path> -b <branch>`, and pass it as `--cwd`.
   - A read-only worker can share a directory. Say in the brief that it must not change files.
2. Write the brief to a file. The worker has none of your conversation, so the brief must stand alone:
   - the goal and why it matters,
   - absolute paths of everything to read first,
   - what it may change, and what it must not touch,
   - how to verify the work (commands to run),
   - which output files to write and what goes in each, and whether to commit.

   Output files go in the task directory, next to `result.json`. `horch` appends the worker rules, the `result.json` path, and the result format to the brief, so do not repeat them.
3. Run `horch run <worker> --brief <file> --cwd <dir>`. The output has `task_id`, `pane_id`, and `state`. `running` means the worker accepted the task. Any other state is a problem.
4. To run tasks in parallel, call `horch run` once for each task, then wait on all of them. `horch run` refuses with `worker_limit` when `max_active_workers` tasks still have open panes.
5. Wait with `horch wait <task-id> ...`. It returns when any waited task changes state. Call it again until every task you need is settled. Tasks can run for hours, and `horch` has no timeout.
   - Claude Code: run `horch wait` as a background command and continue when it finishes.
   - Codex and Pi: run `horch wait <task-id> ... --max-seconds 45` and call it again while tasks are still `running`, so you can give the user progress updates between waits.
6. Only consume a task's result after `horch wait` reports `state: "done"`. An existing report or `result.json` with `status: "completed"` is not completion evidence while the task is `running` or `long_running`; keep waiting. Never use `horch close` to finish an unsettled task: it cancels the worker and does not satisfy a completion or review gate. When a task is `done`, read `result_path` and the files that `files` lists. They are relative to the directory of `result_path`. Inspect the result's `status`: `done` confirms delivery, while `completed`, `failed`, or `blocked` describes the worker's outcome. If `question` is not null, relay it to the user, then start a new task with the answer. If `closed` is false, read `message` and retry cleanup with `horch close <task-id>`; its slot remains occupied until closure is confirmed.
7. Check what the worker claims before you report it. Read the diff, run the tests, or give the work to a second worker on a different model to review.

Each `horch wait` line has `task_id`, `state`, `summary`, `result_path`, `files`, `question`, `closed`, and `message`. Until the task is `done` with a valid result, `summary` and `question` are null and `files` is empty. `result_path` always identifies the expected file location; its presence does not signal completion. A valid result must include matching identity, a supported status, a string summary, a list of file names, and a question only when blocked.

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

## Problems

`horch` sends the user a herdr notification for each problem and keeps the pane open.

1. Read the pane before anything closes it: `herdr pane read <pane_id> --source recent --lines 40`. It prints plain text.
2. Tell the user the state, the task, and what the pane shows. Never answer the dialog yourself.
3. When the user has decided, run `horch close <task-id>`. If they want to retry, start a new task.

If inspection shows a previously unacknowledged task started, or a dialog was cleared, use `horch wait <task-id> --recheck --max-seconds 45` to resume observation. This never resends the prompt or restarts the process. Ordinary waits return stored problem states without re-polling them. Closed and completed tasks are not reopened. A result from an exited process stays on disk for inspection, but without turn-completion evidence it is not promoted to `done`.

A pane-placement error can leave an empty pane when Herdr's response was lost. No worker has been started at that point. Inspect Herdr before removing any empty pane; never close an unrelated pane. A `task_invalid` record requires inspection of its task directory before repair or removal.

## Configuration

`horch` reads `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`, by default `~/.config/herdr-orchestrator/workers.toml`. The user owns this file.

```toml
# If you are the controller (you start herdr workers with horch), delegate only
# through the herdr-orchestrator skill. Never use native subagents.

max_active_workers = 4
notify_after_minutes = 180

[workers.glm]
harness = "pi"
provider = "zai"
model = "glm-5.3-flash"
effort = "max"

[workers.gpt]
harness = "codex"
model = "gpt-6.1-sol"
effort = "medium"
args = ["-s", "workspace-write", "-a", "on-request", "-c", 'approvals_reviewer="auto_review"']

[workers.haiku]
harness = "claude"
model = "haiku"
effort = "max"
args = ["--permission-mode", "auto"]
```

| Key | Meaning |
|---|---|
| `max_active_workers` | Most tasks with an open pane at one time. Default 4. |
| `notify_after_minutes` | When a task runs longer than this, `horch wait` notifies once. Default 180. |
| `workers.<name>.harness` | `pi`, `codex`, or `claude`. |
| `workers.<name>.model` | The model as the harness accepts it on its command line. |
| `workers.<name>.provider` | Pi only. Passed as `--provider`. |
| `workers.<name>.effort` | Optional reasoning effort. |
| `workers.<name>.args` | Optional extra arguments, such as permission flags. They come last. |
| `roles` | Optional. Read only by the `pstack-herdr` skill. |

A worker name matches `[a-z][a-z0-9-]{0,15}`. Task directories live in `$XDG_STATE_HOME/herdr-orchestrator/tasks/`, by default `~/.local/state/herdr-orchestrator/tasks/`, and stay until the user deletes them.
