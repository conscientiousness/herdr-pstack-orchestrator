# Setup and configuration


Run the setup when the user asks for it, or when `horch run` fails with `config_invalid` because `workers.toml` does not exist. Ask the user one question at a time.

1. Run `horch detect`. Show the user which harnesses are installed, which Pi providers have models, and the `pi_integration` status and version.
2. Ask which workers to define. A worker is a name plus a harness, a model, an optional effort, optional extra arguments, and an optional `description` of its intended tasks and boundaries. One worker/model is sufficient; multiple roles may share it. Different models can provide additional review perspectives when configured.
   - Pi: run `pi --list-models <text>` to find a model. Use the `provider` key with the model ID from that list. `effort` is the Pi thinking level (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`).
   - Codex: the model name that `codex -m` accepts. `effort` is the value for Codex's `model_reasoning_effort`, such as `medium` or `high`.
   - Claude Code: an alias such as `opus`, `sonnet`, or `haiku`, or a full model ID. `effort` is the value for `claude --effort`, such as `high` or `max`.
3. Ask for the permission arguments of each worker. A worker that stops at a permission prompt stays stuck, because you never answer dialogs. Tell the user that the flags they choose are their authorization for that worker. Recommend automatic approval modes. These flags completed real worker tasks without permission prompts on 2026-10-09:

   | Harness | Arguments | Effect |
   |---|---|---|
   | `pi` | none | No per-tool approval by default; Pi 1.1.0 can still ask for project trust before startup. |
   | `codex` | `-s workspace-write -a on-request -c approvals_reviewer='"auto_review"'` | Recommended. Automatically reviews approval requests. Verified for shell commands and writes in the task directory outside cwd. |
   | `codex` | `-s workspace-write -a never` | Writes in its cwd and in the task directory, never prompts. Verified. |
   | `claude` | `--permission-mode auto` | Recommended. Automatically reviews actions. Verified for a worker and a controller that ran shell commands, delegated tasks, and read result files. |
   | `claude` | `--permission-mode acceptEdits` | Edits files without a prompt. Shell commands and reads outside the project can still prompt. Verified for file writes. |

   Automatic approval can deny an action. These runs verified successful workflows; they did not deliberately trigger a denial. Inspect and report any worker problem as described below. Startup trust dialogs are separate from action approval.

4. Ask for `max_active_workers` (default 4) and `notify_after_minutes` (default 180).
   The controller needs access to both the configuration directory (`~/.config/herdr-orchestrator/`) and the task directory (`~/.local/state/herdr-orchestrator/`, or their XDG equivalents). Claude Code's `auto` mode completed a skill E2E that read the configured `workers.toml` and task results outside the project. With other permission modes, reads outside the project can prompt; the user can add the directories to `permissions.additionalDirectories` in their Claude Code settings.
5. Write `~/.config/herdr-orchestrator/workers.toml` (or `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`) in the format under "Configuration" below. Show the user the file.
6. For Pi workers, install Herdr's Pi integration with `herdr integration install pi`. `horch` requires its ready-session signal before submitting a task. Run `horch check --cwd <a directory the workers will work in>`. If Herdr reports the Pi integration as missing, `run` and any `check` batch selecting Pi fail with `pi_integration_missing` before allocating any worker. Unknown or unavailable integration status still uses the live ready-session guard. Successful check output has one `ok` field per worker. For a line with `ok: false`, read `message`, look at the pane it names (see [problem handling](../SKILL.md#problems)), and tell the user. After the user clears a dialog, run `horch close <task-id>` and `horch check <worker>` again.

## Caller context

`run` and `check` require `HERDR_ENV=1` and a nonblank `HERDR_PANE_ID`. They resolve the caller with `herdr pane current --current` and use its returned workspace and tab for placement. Missing or unavailable caller panes produce `caller_context_invalid` before task allocation; an unavailable Herdr service remains a `herdr_error`. Reject a blank pane ID before using `--current`: Herdr 0.9.3 can otherwise fall back to the focused pane.

A harness shell snapshot can restore another pane's ID even when the controller process was launched correctly. Confirm the actual controller's identity from its launch context, restore that `HERDR_PANE_ID` in the shell running `horch`, and resolve it through `pane current --current`. Never substitute the currently focused pane. If the controller identity cannot be established, report the mismatch and leave dispatch stopped.

Moving a pane is different from restoring another pane's shell snapshot. Herdr preserves the moved terminal's launch-time ID as an alias; its live workspace/tab may legitimately differ from the inherited environment. No manual refresh of those two variables is needed. See the official [agent automation guide](https://github.com/herdrdev/herdr/blob/v0.9.3/docs/next/website/src/content/docs/agent-automation.mdx).

This check cannot prove ownership when a snapshot names another still-live pane. Verify identity when resuming; do not relocate workers and edit task records as routine recovery.

## Dialogs that stop a worker before it starts

These appear before the worker reads its task. `horch` reports `start_failed` and leaves the pane open. The user must clear each one once, in the pane or by starting the harness there themselves.

- Codex asks "Trust this folder?" for every git repository it has not trusted yet. Trust belongs to the git root. A trusted parent folder does not cover a new repository below it. Worktrees of a trusted repository are covered.
- Claude Code asks whether to trust a folder the first time it runs there.
- Claude Code asks "Allow external CLAUDE.md file imports?" when the worker's cwd is a subdirectory of a project whose `CLAUDE.md` imports a file with `@`.
- Pi 1.1.0 asks "Trust project folder?" when an untrusted directory has project resources, including an empty `.agents/skills` directory in an ancestor. Herdr 0.9.3 can misclassify this dialog as idle. `horch` therefore waits for the Pi integration's session signal and sends no task prompt if it is absent. Trust is path-based; a git worktree outside a trusted directory may need its own decision. The user can choose Pi's `--approve` or `--no-approve` in worker `args` to explicitly allow or ignore project resources for that process; never add those flags to dismiss a dialog automatically.

## Configuration


`horch` reads `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`, by default `~/.config/herdr-orchestrator/workers.toml`. The user owns this file.

`description` is optional controller guidance. Existing configurations remain valid without it. Role mappings take precedence over descriptions, and `horch` does not select models or pass descriptions to harness commands. Describe task scope rather than unverified capability or cost rankings. Upgrade every installed `horch` that reads a shared configuration before adding this key; older versions reject unknown keys.

```toml
# If you are the controller (you start herdr workers with horch), delegate only
# through the herdr-orchestrator skill. Never use native subagents.

max_active_workers = 4
notify_after_minutes = 180

[workers.glm]
description = "Bounded tooling changes and mechanical edits."
harness = "pi"
provider = "zai"
model = "glm-5.3-flash"
effort = "max"

[workers.gpt]
description = "Implementation, ordinary fixes, and refactoring."
harness = "codex"
model = "gpt-6.1-sol"
effort = "medium"
args = ["-s", "workspace-write", "-a", "on-request", "-c", 'approvals_reviewer="auto_review"']

[workers.haiku]
description = "Independent review of a bounded diff and its evidence."
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
| `workers.<name>.description` | Optional string describing intended tasks and boundaries for the controller. |
| `workers.<name>.args` | Optional extra arguments, such as permission flags. They come last. |
| `roles` | Optional. Read only by the `pstack-herdr` skill. |

A worker name matches `[a-z][a-z0-9-]{0,15}`. Task directories live in `$XDG_STATE_HOME/herdr-orchestrator/tasks/`, by default `~/.local/state/herdr-orchestrator/tasks/`, and stay until the user deletes them.
