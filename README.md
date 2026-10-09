<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.png">
  <img alt="A Border Collie controller centered behind its laptop, with four awake Herdr sheep workers in terminal panes on each side" src="assets/banner-light.png" width="100%">
</picture>

# herdr-pstack-orchestrator

[![Package validation](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml/badge.svg)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml)
[![Pstack upstream](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml/badge.svg?branch=main)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml)
[![Pstack source: 0.15.15](https://img.shields.io/badge/pstack_source-0.15.15-blue)](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Run coding agents from one conversation and inspect their work in [Herdr](https://herdr.dev). The controller assigns tasks, waits for results, and verifies the work.

[Latest release: v0.2.0](https://github.com/conscientiousness/herdr-pstack-orchestrator/releases/tag/v0.2.0).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/workflow-light.svg">
  <img alt="Your controller briefs an implementation worker, verifies its diff, and dispatches independent reviewers. After all reviewers finish, the controller assesses findings. Accepted findings go to a fresh fix worker and a fresh review panel; no unresolved blockers leads to a verified result." src="assets/workflow-light.svg" width="100%">
</picture>

The diagram shows an implementation and review loop. The optional `pstack-herdr` adapter also routes original pstack workflows through configured Herdr workers.

[Download the interactive diagram](https://github.com/conscientiousness/herdr-pstack-orchestrator/raw/refs/heads/main/assets/workflow.html) and open it in your browser · [Diagram source and reproduction](assets/workflow.md)

Two Agent Skills connect your controller to Pi, Codex CLI, and Claude Code. Each task gets a fresh process, a complete brief, and a structured result. The `horch` CLI uses Python's standard library and your authenticated agent CLIs.

- `herdr-orchestrator` sets up workers and delegates tasks through the `horch` CLI.
- `pstack-herdr` maps the bundled original pstack skills, roles, and delegation to Herdr. The controller coordinates the workflow; workers receive bounded assignments.

Workers open in separate tabs labeled `horch`, at most four panes per tab, without taking focus or using the controller's tab. The controller creates separate git worktrees for writers and submits tasks through Herdr's agent API. Every follow-up starts a fresh worker.

## Requirements

- [Herdr](https://herdr.dev) 0.9.3 or later, with the controller agent running inside a Herdr pane (`HERDR_ENV=1`)
- Python 3.11 or later with POSIX file locks. Runtime verification has been on Linux; macOS is unverified.
- Node.js/npm for `npx skills add`; a manual clone needs neither
- Your chosen worker harnesses, `pi`, `codex`, or `claude`, installed and authenticated
- For Pi workers, Herdr's Pi integration: `herdr integration install pi`

## Install

Install pstack and both Herdr adapters together:

```bash
npx skills@1.7.1 add https://github.com/conscientiousness/herdr-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose your harnesses and installation scope, review any existing skill-name conflicts, then open a new agent session inside Herdr. The command installs the bundled skills and resources from this repository; no upstream clone or preparation step is needed. It installs from `main`; v0.2.0 predates this bundled layout.

For delegation without pstack, install only the core skill:

```bash
npx skills@1.7.1 add conscientiousness/herdr-pstack-orchestrator -s herdr-orchestrator
```

Or clone and run directly:

```bash
git clone https://github.com/conscientiousness/herdr-pstack-orchestrator.git
cd herdr-pstack-orchestrator
python3 skills/herdr-orchestrator/scripts/horch.py detect
```

For manual installation, symlink each skill into your harness's skills directory. This example installs the core skill for Claude Code:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/herdr-orchestrator" ~/.claude/skills/herdr-orchestrator
```

`horch` is a plain script. For the manual examples below, define this shell function from the clone:

```bash
HORCH_SCRIPT="$PWD/skills/herdr-orchestrator/scripts/horch.py"
horch() { python3 "$HORCH_SCRIPT" "$@"; }
```

Commands are `run`, `wait`, `list`, `close`, `detect`, and `check`. `detect` reports installed harnesses and Pi integration status; `check` runs real tasks with configured workers. Operational output is JSON; errors use `{"error": ..., "message": ...}` and exit status 1. See the [command guide](skills/herdr-orchestrator/SKILL.md#run-horch).

## Quickstart

Paste this to your agent inside Herdr:

```text
Set up the herdr-orchestrator skill with me: run horch detect, ask me which
workers to define (harness, model, effort, and permission flags), write my
workers.toml, then run horch check and show me which workers are ok.
```

Once setup is done, delegation is one sentence:

```text
Use herdr-orchestrator to fix the login redirect loop in this repository:
create a git worktree, delegate the fix to a worker, and have a worker on a
different model review the diff before you report back.
```

## Configuration

`horch` reads `~/.config/herdr-orchestrator/workers.toml` (`$XDG_CONFIG_HOME` is respected). Copy the complete example from this repository and edit it:

```bash
mkdir -p ~/.config/herdr-orchestrator
cp -i skills/herdr-orchestrator/references/workers.example.toml \
   ~/.config/herdr-orchestrator/workers.toml
```

The example defines one worker per harness:

| Worker | Harness | Model and effort |
|---|---|---|
| `glm` | Pi | provider `zai`, `glm-5.3-flash`, thinking `max` |
| `gpt` | Codex | `gpt-6.1-sol`, reasoning `medium` |
| `haiku` | Claude Code | `haiku`, effort `max` |

Worker names and models are examples. Read each worker's configured harness; a name such as `gpt` does not imply Codex. Pi lists available models with `pi --list-models`.

The controller never answers worker dialogs. Choose permission flags during setup. These modes completed real tasks on 2026-10-09:

| Harness | Arguments |
|---|---|
| Pi | no per-tool approval by default; project-trust dialogs still apply |
| Codex | `-s workspace-write -a on-request -c 'approvals_reviewer="auto_review"'` |
| Codex | `-s workspace-write -a never` (writes in its cwd and the task directory) |
| Claude Code | `--permission-mode auto` |
| Claude Code | `--permission-mode acceptEdits` (shell commands outside the project can still prompt) |

Automatic approval can deny an action; denial handling is unverified. A new location can also trigger a trust dialog. See [setup and dialog handling](skills/herdr-orchestrator/references/setup.md).

`max_active_workers` defaults to 4; `notify_after_minutes` defaults to 180. The notification reports elapsed time, not whether the worker is making useful progress. The optional `[roles]` table selects workers for pstack.

Task directories live under `~/.local/state/herdr-orchestrator/tasks/`, or the corresponding `$XDG_STATE_HOME` path. Briefs and results remain until you delete them. Controllers sharing that task store share the worker limit; workers execute concurrently after startup.

## How delegation works

The controller chooses a configured Pi, Codex CLI, or Claude Code worker, sends a complete brief with `horch run`, and waits for its structured result with `horch wait`. It verifies the outcome before reporting back.

A manual example: first create a separate checkout and branch for the writer. A worktree separates edits; it is not a security sandbox.

```bash
git -C ~/src/myapp worktree add ~/src/myapp-fix-login -b fix/login
```

Write a complete brief to `/tmp/fix-login.md`. The worker has none of your conversation:

```markdown
# Fix the login redirect loop

After sign-in the app bounces back to /login instead of the page the user
came from.

- Read src/auth/session.ts and src/routes/login.ts first.
- Change only files under src/auth/ and src/routes/.
- Verify with npm run e2e -- login, including a return URL and an expired session.
- Commit on the current branch with a message explaining the cause.
- Write report.md next to result.json: cause, fix, verification output.
```

`horch` appends the worker rules and the `result.json` format to every brief, so do not add them yourself.

Start the worker and wait:

```bash
horch run gpt --brief /tmp/fix-login.md --cwd ~/src/myapp-fix-login
# prints JSON with task_id, pane_id, and state

horch wait t-0a1b2c  # use the task_id returned by run
```

`horch wait` has no default time cap. Use a background command or yielded shell session so the controller can post updates while waiting. For blocking-only tools, use `--max-seconds 300` with a longer tool timeout, or a shorter cap if the runtime requires it. The cap ends the wait call, not the worker.

For parallel work, launch each task before waiting on all returned IDs. Handle each state change, then keep waiting for unfinished tasks. After `done`, read `result.json` and its listed files; file paths are relative to the result directory.

## Task states and result status

`horch wait` reports observed task states; `horch list` shows stored states without polling workers:

| State | Meaning |
|---|---|
| `running` | The worker is working. |
| `long_running` | One-time `wait` notification after `notify_after_minutes`; the stored state remains `running`. |
| `done` | Turn ended with a valid `result.json`; check `closed` and `message` for pane cleanup. |
| `blocked`, `start_failed`, `not_started`, `exited`, `result_missing`, `result_invalid` | Problems; the pane stays open for inspection. |

After `done`, read the separate `status` inside `result.json`:

| Task state | Result status | Next action |
|---|---|---|
| `done` | `completed` | Verify the worker's claimed success and any review verdict. |
| `done` | `failed` | Inspect and report the worker's failure. |
| `done` | `blocked` | Relay the worker's question, then start a fresh task with the answer. |

Read the diff, run the tests, or request an independent review before accepting the work. A delivered review can still find blocking defects.

Wait for `state: "done"` before consuming a result. A worker can write files while its turn is still running, so `horch wait` withholds result summaries, files, and questions until completion. Closing a running worker cancels it; it does not complete the task or satisfy a review gate.

## Optional: original pstack through Herdr

The adapter tracks [original pstack](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack) 0.15.15. The bundle contains 53 installable entries: 48 pstack skills, three team-kit dependencies, and two Herdr adapters. It preserves supporting files and licenses. Workflow entries load the Herdr mapping; pure guidance keeps its original body.

After installation, start a fresh session and invoke a skill directly:

```text
Use poteto-mode for this goal: ...
Done means: ...
```

You can also ask `Use interrogate to review this branch.` Independent skills such as `unslop` are discoverable too. Review conflicts with existing skill names when installing. The bundle removes upstream explicit-only flags so harnesses can select skills implicitly. It excludes Cursor-specific `make-bot-ui`, `poteto-help`, and `setup-pstack`; role setup uses `workers.toml`. See the [selection and compatibility notes](skills/pstack-herdr/references/compatibility.md).

All three controller harnesses read roles directly from `workers.toml`. Configure only the roles the chosen workflow needs. For the implementation/review loop:

```toml
[roles]
"feature, refactoring" = "gpt"
"interrogate reviewers" = ["glm", "haiku"]
```

A single role names one worker; a panel lists one worker per task. The controller selects one worker from `arena cross-judge pool`. Other workflows use their original role names, such as `how explorer` or `architect runners`.

The [adapter instructions](skills/pstack-herdr/SKILL.md) define workflow coordination and review. Read-only assignments rely on worker briefs and harness permissions; `horch` does not enforce a separate sandbox.

The source badge identifies the upstream pin. The upstream monitor checks `pstack/` and `cursor-team-kit/` daily at 02:23 UTC. Its summary distinguishes changes needing review from a failed check. It never upgrades installed skills automatically.

Cursor modes, hooks, `/loop`, cloud execution, and unavailable MCP or app-driving tools are not supplied by this adapter. Workflows requiring a missing capability stop at that step. See the verification scope below.

## Verification

The v0.2.0 integration has these recorded results:

| Scope | Evidence |
|---|---|
| Skill discovery | All 56 entries appeared in native Pi and Codex catalogs. Claude Code installation was checked; native discovery was not measured. |
| Original pstack `how` | A Pi controller completed three explorer tasks and one explainer task through Herdr, with delivery and cleanup verified. |
| Package installation | CI checks Python 3.11/3.14 and installation for Claude Code, Codex, and Pi. |

The [discovery receipt](e2e/evidence/skill-discovery.json) records the first two results. Other original skills and `poteto-mode` playbooks remain runtime unverified. Discovery does not prove workflow execution.

Earlier core, review-loop, and controller tests retain their original source revisions in the [E2E guide](e2e/README.md#evidence-and-source-attribution). They are not new v0.2.0 workflow tests. Runtime checks used Linux; macOS, deliberate approval denial, and task completion beyond 30 minutes remain unverified.

For commands, prerequisites, evidence locations, and cleanup, use [verify-herdr-orchestrator](.agents/skills/verify-herdr-orchestrator/SKILL.md).

## Troubleshooting

Start with `horch detect`. For worker dialogs or failed tasks, inspect the recorded pane before closing it; never resend a prompt or switch models automatically. Follow [setup and dialog handling](skills/herdr-orchestrator/references/setup.md) or [task recovery](skills/herdr-orchestrator/references/lifecycle.md#problem-recovery).

## Contributing

Include reproduction steps, relevant versions, and sanitized evidence with a bug report or fix. Verify affected behavior using the [existing E2E drivers](e2e/README.md). Keep changes focused and write code, documentation, and commit messages in English. Never publish credentials, private paths, or full worker transcripts.

## Credits

[Herdr](https://herdr.dev) hosts the worker panes. [pstack](https://github.com/cursor/plugins/tree/main/pstack) is Lauren Tan's original MIT-licensed workflow collection; this repository provides an independent adapter.

The banner references Herdr's ram icon. See its [provenance](assets/banner-prompt.md). The diagram uses [Archify](https://github.com/tt-a1i/archify); its [provenance and notices](assets/workflow.md) include the viewer's license.

## License

[MIT](LICENSE). Copyright 2026 conscientiousness and contributors.
