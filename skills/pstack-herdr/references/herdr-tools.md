# Herdr tool mapping for pstack

pstack skills describe delegation using Claude Code's `Agent`/`Task` and `SendMessage` tools. With `pstack-herdr` active, the controller uses `herdr-orchestrator` and its `horch` CLI for those actions on Claude Code, Codex, and Pi. This mapping overrides only delegated actions; use the runtime's normal tools for everything else.

| pstack action | Herdr equivalent |
|---|---|
| Dispatch a subagent (`Agent` or `Task`) | Write a complete brief file, then `horch run <worker> --brief <file> --cwd <dir>`. Record the returned task ID. |
| Dispatch N subagents in one message | Make N `horch run` calls before waiting. Respect `max_active_workers`; wait for a slot before launching the rest. |
| `run_in_background: true` | `horch run` already returns after the prompt is accepted. |
| Wait for a subagent result | `horch wait <task-id> ...` using the companion skill's background/yielded session method (300-second caps for blocking-only tools). Repeat for remaining running tasks; read results only after `done`. |
| `model` and `@<level>` from a role line | Look up the role's worker name in `workers.toml`. The worker definition fixes harness, model, and effort. Ignore the role suffix. |
| `readonly: true` | State in the brief that the worker must not change files or external state. This is an instruction, not an enforced sandbox; verify the checkout stayed unchanged. |
| `isolation: "worktree"` | Create a git worktree first and pass it as `--cwd`. Give each concurrent writer a different worktree. |
| Fresh subagent | Every `horch run` starts a new worker process. |
| Follow up with `SendMessage` | Wait for the prior task to settle. Start a new task with the complete brief, previous report, and current branch or revision. |
| Stop a subagent | `horch close <task-id>` closes only that task's recorded pane. Read a problem pane before closing it. |

For a panel role such as `interrogate reviewers`, start one task for each configured worker name. Give every reviewer the same intent, revision, rubric, and code scope. A panel with distinct configured models supplies model diversity; version 1 does not check model families. Do not use pstack's Claude defaults when a Herdr role is absent. Configure the role first.

`horch wait` returns when at least one task changes state, so keep waiting until every required review reports `state: "done"`. An early report or result file cannot replace that state. Closing a running worker cancels it and leaves the review gate unresolved. A `done` state confirms a valid task result and an ended turn; it does not approve the code. Treat `blocked`, `start_failed`, `not_started`, `exited`, `result_missing`, and `result_invalid` as unresolved review work. Follow `herdr-orchestrator` for notification and pane inspection.
