# Setup and configuration


Run the setup when the user asks for it, or when `agent-workers run` fails with `config_invalid` because `workers.toml` does not exist. Ask the user one question at a time.

1. Run `agent-workers detect`. Show the selected `backend`, available harnesses, and Pi providers. Rex and core use native status reporting. Legacy mode reports the `pi_integration` status and version. Recover any missing or conflicting caller context before launching.
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

4. Ask for `max_active_workers` (default 4) and `notify_after_minutes` (default 180). Rex counts unclosed tasks per server and session. Core counts unclosed tasks by core ID in this store, plus legacy reservations in the GUI caller's workspace. Legacy execution uses per-workspace quotas.
   The controller needs access to both the configuration directory (`~/.config/agent-workers/`) and the task directory (`~/.local/state/agent-workers/`, or their XDG equivalents). Claude Code's `auto` mode completed a skill E2E that read the configured `workers.toml` and task results outside the project. With other permission modes, reads outside the project can prompt; the user can add the directories to `permissions.additionalDirectories` in their Claude Code settings.
5. Write `~/.config/herdr-orchestrator/workers.toml` (or `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`) in the format under "Configuration" below. Show the user the file.
6. Rex and core use the harness's native OSC 7501 idle readiness. Codex runs interactively with `--no-daemon`. Conflicting daemon arguments are rejected. Run `agent-workers check --cwd <worker directory>` with the caller options below to verify actual configured delivery. Startup trust dialogs remain the user's decision.

   For legacy Pi workers, install Herdr's Pi integration with `herdr integration install pi`. `agent-workers` requires its ready-session signal before submitting a task. Run `agent-workers check --cwd <a directory the workers will work in>`. If Herdr reports the Pi integration as missing, `run` and any `check` batch selecting Pi fail with `pi_integration_missing` before allocating any worker. Unknown or unavailable integration status still uses the live ready-session guard. Successful check output has one `ok` field per worker. For a line with `ok: false`, read `message`, look at the pane it names (see [problem handling](../SKILL.md#problems)), and tell the user. After the user clears a dialog, run `agent-workers close <task-id>` and `agent-workers check <worker>` again.

## Caller context

`agent-workers detect` reports the route indicated by caller context. `run` and `check`
verify that context before creating anything. When both Rex and Herdr hints are
inherited, supply the explicit caller option for this conversation. A shared
daemon can retain an older conversation's environment. Use the local terminal
that actually hosts this conversation. Controllers outside both multiplexers can
use core headless.

### Rex caller

Rex ordinary shell callers can use `REX_SESSION` and `REX_BLOCK` when the block's
process tree contains `agent-workers`. If `REX_SERVER` is supplied, it must identify a
local Unix-socket server. Set it to the endpoint for a nondefault local server.
Workers start directly in `Workers` blocks in the verified session. `agent-workers`
reuses its own worker tabs up to four blocks per tab, keeps them separate
from the controller's tab, and preserves focus.

For an agent controller or tools outside the caller's process tree, find the
full block ID with `rex ls --json` and `rex block ls -s <session> --json`. Use
`rex block call -s <session> -b <block> process` and
`rex capture -s <session> -b <block> --trim` to confirm the live harness, cwd,
and text unique to this conversation's visible screen. An installed CLI,
the first listed session, or app focus is insufficient. Rerun with the verified
block and distinctive text of at least 16 characters:

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <worker-dir> \
  --caller-block <confirmed-block-id> --caller-text '<distinctive visible conversation text>'
```

Pass the same caller options to `check`. If no unique block can be confirmed,
report the missing context and leave dispatch stopped. See the [Rex CLI guide](https://www.superlogical.com/rex/docs/automate/cli).

### Herdr caller

Controllers in Herdr must present each core worker in an owned attach pane in
`Workers` tabs in the verified caller's live workspace. Legacy runtime uses
`Workers` tabs. Both paths verify the caller before layout writes and preserve its
tab and focus. Report any presentation failure at the recorded backend.

Legacy execution requires `HERDR_ENV=1`. Core requires caller verification whenever `--caller-pane` or `--caller-text` is supplied, `HERDR_ENV=1`, or any nonempty `HERDR_PANE_ID`, `HERDR_TAB_ID`, `HERDR_WORKSPACE_ID`, or `HERDR_SOCKET_PATH` is inherited. This preserves viewer placement when tools lose `HERDR_ENV`. Core also requires `HERDR_SOCKET_PATH` before launch to pin viewer cleanup. A nonblank caller pane ID comes from `--caller-pane` when given, otherwise `HERDR_PANE_ID`. Herdr's `--current` only reads `HERDR_PANE_ID`; it does not check that the pane hosts the caller. `agent-workers` therefore proves the caller before task allocation:

1. For ordinary shell automation without controller session variables or a harness ancestor, the named pane's shell (`herdr pane process-info`, `shell_pid`) must be an ancestor of `agent-workers`. Its live workspace and tab are then used for placement. A contradictory pane claim is rejected.
2. Agent controllers require explicit `--caller-pane` and `--caller-text` even when a pane shell is an ancestor: a shared daemon may still descend from another conversation's pane. An explicit conversation proof selects the actual controller rather than the daemon's process host. Tools outside all pane trees also require this proof.
3. The confirmed pane's foreground must run the controller's harness in this conversation's cwd (the cwd of the `agent-workers` command, which can differ from the worker's `--cwd`). The text must contain at least 16 characters and, after whitespace normalization, match only that pane among live panes running the controller harness. Use distinctive text from this conversation's visible screen. When the controller exports `CODEX_THREAD_ID` or `CLAUDE_CODE_SESSION_ID` and the pane reports a session for that harness, the two must match; session metadata alone never replaces the screen check.

Missing or unavailable caller panes also produce `caller_context_invalid`; an unavailable Herdr service remains a `herdr_error`. Never substitute the currently focused pane.

If this conversation is in Herdr but its tool environment has lost all Herdr context, restore the controller's context before `run` or `check`; the CLI cannot infer an absent association. Do not treat a missing environment flag as a headless request or clear inherited context to bypass a failure. After launching, verify `viewer` belongs to the confirmed workspace and an `Workers` tab, and report any viewer warning or failed attachment immediately. Preserve the running task rather than redispatching it.

A shared agent daemon requires the conversation proof in cases 2–3. Codex 0.162 runs a conversation's tools in a `codex app-server` process with parent PID 1 that keeps the environment of the pane that started it, so every Codex conversation using that daemon sees that pane's ID. Herdr's Codex hook runs there too, so Herdr can attach a Codex session to the wrong pane. Before passing `--caller-pane`, confirm the controller pane and record the evidence for the user:

- `herdr pane list` and `herdr pane process-info --pane <id>`: the candidate pane's foreground runs the controller's harness in the conversation's working directory. A pane whose foreground is a plain shell is not the controller.
- If more than one pane runs that harness, read each candidate with `herdr pane read <id> --source visible` and match text unique to this conversation, such as your latest command. If no single pane matches, report the candidates and leave dispatch stopped.

Pass the confirmed ID and text to every `run` and `check` in this conversation:

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <worker-dir> \
  --caller-pane <confirmed-id> --caller-text '<distinctive visible conversation text>'
```

The tool reads process information and visible screens itself. Missing, incorrect or ambiguous evidence stops dispatch before allocating a task. It saves `controller_verification` in the task record before launching the worker: live pane/tab/workspace IDs, conversation cwd, shell and foreground harness PIDs, verification method and time, and a SHA-256 screen hash. Full pane text is not saved. Process ancestry produces the same record for ordinary shell automation inside its pane. Recheck after resuming the controller; do not relocate workers and edit task records as routine recovery.

After core viewer creation, the tool re-reads the controller's live workspace, viewer pane and tab, foreground process argv, and visible screen. `viewer_verified: true` requires a separate `Workers` tab in that workspace, the pinned executable attaching the exact core terminal, and recognizable rendered output read from that terminal. It is a timestamped observation, not a guarantee that the user has focused or seen the tab. Before asking the user to operate a worker window, run `agent-workers verify-viewer <task-id>` and require a fresh successful verification. On failure, report `viewer_verification_error` and leave interaction stopped; a returned viewer ID is not evidence of visibility.

Moving a pane is different from a stale ID. Herdr preserves the moved terminal's launch-time ID as an alias and the shell keeps its process, so the check above still passes and the live workspace/tab are used. See the official [CLI reference](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx).

## Dialogs that stop a worker before it starts

Rex and core require native idle before task submission. Check `startup_ready`,
`submission`, and `execution_observed` separately. After a startup failure with
`submission: "not_sent"`, `wait --recheck` may observe native idle while leaving
the task unsent. Once the user resolves readiness and chooses recovery, `agent-workers
submit <task-id>` sends the original brief once on that retained block or
terminal. It rejects `sent`, `unknown`, historical, closed, or completed tasks.
A send timeout leaves the outcome `unknown`. Legacy recovery requires
inspection, closure, and a fresh task.

These appear before the worker reads its task. `agent-workers` reports `start_failed` and leaves the pane open. The user must clear each one once, in the pane or by starting the harness there themselves.

- Codex asks "Trust this folder?" for every git repository it has not trusted yet. Trust belongs to the git root. A trusted parent folder does not cover a new repository below it. Worktrees of a trusted repository are covered.
- Claude Code asks whether to trust a folder the first time it runs there.
- Claude Code asks "Allow external CLAUDE.md file imports?" when the worker's cwd is a subdirectory of a project whose `CLAUDE.md` imports a file with `@`.
- Pi 1.1.0 asks "Trust project folder?" when an untrusted directory has project resources, including an empty `.agents/skills` directory in an ancestor. Herdr 0.9.3 can misclassify this dialog as idle. `agent-workers` therefore waits for the Pi integration's session signal and sends no task prompt if it is absent. Trust is path-based; a git worktree outside a trusted directory may need its own decision. The user can choose Pi's `--approve` or `--no-approve` in worker `args` to explicitly allow or ignore project resources for that process; never add those flags to dismiss a dialog automatically.

## Reviewing configured workers

Use `agent-workers stats [--workspace <id>] [--days <n>]` before proposing changes to this file. It reads the store and configuration without multiplexer calls or writes. See [worker statistics](stats.md) for fields, limitations, and interpreting the numbers with the user.

## Configuration


`agent-workers` reads `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`, by default `~/.config/herdr-orchestrator/workers.toml`. The user owns this file.

`description` is optional controller guidance. Existing configurations remain valid without it. Role mappings take precedence over descriptions, and `agent-workers` does not select models or pass descriptions to harness commands. Describe task scope rather than unverified capability or cost rankings. Upgrade every installed `agent-workers` that reads a shared configuration before adding this key; older versions reject unknown keys.

```toml
# If you are the controller (you start workers with agent-workers), delegate only
# through the agent-workers skill. Never use native subagents.

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
| `max_active_workers` | Default 4. Rex scopes reservations to a server and session. Core scopes them to the core ID and counts legacy tasks in a GUI caller's workspace. Legacy launches keep workspace limits. |
| `notify_after_minutes` | When a task runs longer than this, `agent-workers wait` notifies once. Default 180. |
| `workers.<name>.harness` | `pi`, `codex`, or `claude`. |
| `workers.<name>.model` | The model as the harness accepts it on its command line. |
| `workers.<name>.provider` | Pi only. Passed as `--provider`. |
| `workers.<name>.effort` | Optional reasoning effort. |
| `workers.<name>.description` | Optional string describing intended tasks and boundaries for the controller. |
| `workers.<name>.args` | Optional extra arguments, such as permission flags. They come last. |
| `roles` | Optional. Used by `pstack-herdr` for routing and `agent-workers stats` to report unconfigured assignments. |

A worker name matches `[a-z][a-z0-9-]{0,15}`. Task directories live in `$XDG_STATE_HOME/herdr-orchestrator/tasks/`, by default `~/.local/state/herdr-orchestrator/tasks/`, and stay until the user deletes them.
