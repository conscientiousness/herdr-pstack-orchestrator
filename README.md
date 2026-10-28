<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.png">
  <img alt="A Border Collie controller centered behind its laptop, with four awake Herdr sheep workers in terminal panes on each side" src="assets/banner-light.png" width="100%">
</picture>

# herdr-pstack-orchestrator

[![Package validation](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml/badge.svg)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml)
[![Pstack upstream](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml/badge.svg?branch=main)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml)
[![Pstack source: 0.15.36](https://img.shields.io/badge/pstack_source-0.15.36-blue)](https://github.com/cursor/plugins/tree/c742dd61706fbacc1b95f1a20b7b988cf096ce6c/pstack)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Add agent orchestration to your existing workflow without changing application
code. Run coding agents from one conversation and inspect their work in
[Herdr](https://herdr.dev). The controller assigns tasks, waits for results,
and verifies the work.

[Latest release](https://github.com/conscientiousness/herdr-pstack-orchestrator/releases/latest).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/workflow-light.svg">
  <img alt="Your controller briefs an implementation worker, verifies its diff, and dispatches independent reviewers. After all reviewers finish, the controller assesses findings. Accepted findings go to a fresh fix worker and a fresh review panel; no unresolved blockers leads to a verified result." src="assets/workflow-light.svg" width="100%">
</picture>

Two Agent Skills connect your controller to Pi, Codex CLI, and Claude Code. Each task gets a fresh process, a complete brief, and a structured result. The `horch` CLI uses Python's standard library and your authenticated agent CLIs.

- `herdr-orchestrator` sets up workers and delegates tasks through the `horch` CLI.
- `pstack-herdr` maps the bundled original pstack skills, roles, and delegation to Herdr.

Workers open in separate tabs labeled `horch`, at most four panes per tab, without taking focus or using the controller's tab.

The controller uses your existing agent CLIs and one worker configuration. No
application-code changes are required. Worker definitions are read for each new
task; an existing task retains its recorded launch arguments. Installing or
updating skills can require a fresh controller session. Review same-name skill
conflicts before installing.

Live [worker replacement evidence](e2e/evidence/hot-swap.json) records two tasks
running across a definition change and removal, with correct independently
replayed results and unchanged user configuration. This covers worker
definitions; role selection and skill loading remain controller responsibilities.

Release readiness focuses on reversible setup, configured role routing, worker
replacement and a practical implementation/review/private-PR workflow. See the
[adoption evidence](docs/RELEASE-EVIDENCE.md). Full compatibility with all 23
original playbooks is a later milestone; the [inventory](e2e/PLAYBOOKS.md)
retains failures and blocked capabilities separately.

## Requirements

- [Herdr](https://herdr.dev) 0.9.3 or later, with the controller agent running inside a Herdr pane (`HERDR_ENV=1`)
- Python 3.11 or later with POSIX file locks. Runtime verification has been on Linux; macOS is unverified.
- Node.js/npm for `npx skills add`; a manual clone needs neither
- Your chosen worker harnesses, `pi`, `codex`, or `claude`, installed and authenticated
- For Pi workers, Herdr's Pi integration: `herdr integration install pi`

## Install

Start with the core delegation skill:

```bash
npx skills@1.7.1 add conscientiousness/herdr-pstack-orchestrator -s herdr-orchestrator
```

For original pstack guidance and both Herdr adapters, install the full bundle:

```bash
npx skills@1.7.1 add https://github.com/conscientiousness/herdr-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose harnesses and installation scope, review skill-name conflicts, then open a new agent session inside Herdr. The commands use this repository's `main`; no upstream clone is needed, and v0.2.0 predates the bundle layout.

To remove the core skill from a project:

```bash
npx skills@1.7.1 remove herdr-orchestrator -y
```

For a full bundle, run `npx skills@1.7.1 remove` and select its entries while
keeping unrelated skills. Omit `-a` for complete project removal: selecting
agents can leave shared `.agents/skills` copies. The [removal receipt](e2e/evidence/project-removal.json)
verifies all 56 named entries disappear from a disposable project while an
unrelated skill and application files remain. Empty directories and installer
lock metadata may remain; fresh sessions observe the updated catalogs.

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

Commands are `run`, `wait`, `list`, `close`, `detect`, `check`, and `stats`. `detect` reports installed harnesses and Pi integration status; `check` runs real tasks with configured workers. Operational output is JSON; operational errors use `{"error": ..., "message": ...}` and exit status 1. CLI help and argument errors use argparse output. See the [command guide](skills/herdr-orchestrator/SKILL.md#run-horch).

`horch stats` summarizes stored worker performance without Herdr calls or writes; see [worker statistics](skills/herdr-orchestrator/references/stats.md).

## Update

Updates are manual. The [install commands](#install) track `main`, so they
receive changes before a tagged release.

To update skills from this repository, rerun the matching install command.
For a project installation, run it from the project where you installed the skills.

For the core skill:

```bash
npx skills@1.7.1 add conscientiousness/herdr-pstack-orchestrator -s herdr-orchestrator
```

For the full bundle, including newly added skills:

```bash
npx skills@1.7.1 add https://github.com/conscientiousness/herdr-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose the same agents and scope as before. Add `-g` for a global installation.
Review same-name skill conflicts before confirming replacement.
Avoid an unfiltered `skills update -p` or `skills update -g` when updating this
repository, since those commands also update skills from other repositories.

For a manual clone, run this in the clone on `main`:

```bash
git pull --ff-only
```

Symlinked skills use the updated files. If you copied skills by hand, copy them
again after pulling. Keep your existing `workers.toml`; copying the example
configuration again would overwrite your worker settings.

After updating, open a new controller session inside Herdr to load the updated skills.

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
create a git worktree, delegate the fix to a worker, and have a fresh worker
independently review the diff before you report back.
```

## Configuration

`horch` reads `~/.config/herdr-orchestrator/workers.toml` (`$XDG_CONFIG_HOME` is respected). Copy the complete example from this repository and edit it:

```bash
mkdir -p ~/.config/herdr-orchestrator
cp -i skills/herdr-orchestrator/references/workers.example.toml \
   ~/.config/herdr-orchestrator/workers.toml
```

The copied example defines one worker per harness (`glm`, `gpt`, `haiku`). Names and models are examples; read each worker's configured harness, because a name such as `gpt` does not imply Codex. Pi lists available models with `pi --list-models`.

The controller never answers worker dialogs, so the permission flags you choose are the worker's authorization; automatic approval can still deny an action, and denial handling is unverified. Verified flag choices and dialog handling are in [setup and dialog handling](skills/herdr-orchestrator/references/setup.md).

Other keys are documented in [configuration](skills/herdr-orchestrator/references/setup.md#configuration):

- `max_active_workers` (default 4) caps unclosed tasks per workspace. Controllers in the same workspace share that cap when they share the task store.
- `notify_after_minutes` (default 180) reports elapsed time, not useful progress.
- An optional `[roles]` table selects workers for pstack.
- A worker can carry an optional `description` of its intended tasks.

Task directories live under `~/.local/state/herdr-orchestrator/tasks/`, or the corresponding `$XDG_STATE_HOME` path, until you delete them.

## How delegation works

The controller sends a complete brief with `horch run`, waits for the structured result with `horch wait`, and verifies the outcome before reporting back. Commands, waiting rules, and recovery are in the [herdr-orchestrator skill](skills/herdr-orchestrator/SKILL.md).

`horch wait` has no default time cap. Run it in a background command or a yielded shell session so the controller can post updates while waiting; with blocking-only tools, use `--max-seconds 300` and a longer tool timeout. The cap ends the wait call, not the worker. For parallel work, launch each task first, then wait on the returned IDs.

After `done`, read the separate `status` inside `result.json`: verify a `completed` claim, inspect a `failed` report, and relay a `blocked` question to the user, then start a fresh task with their answer. A `blocked` status means the worker delivered a question and its turn ended. A `blocked` task state means the worker is stopped at a dialog, and the pane stays open for inspection.

`horch wait` withholds summaries, files, and questions until the turn ends, so wait for `done` before consuming a result. A worker can write files while it runs, and closing a running worker cancels it. The full state and status tables and the recovery steps are in [task lifecycle and recovery](skills/herdr-orchestrator/references/lifecycle.md).

The Quickstart delegates through the agent skill. To drive `horch` by hand instead, use the manual example below.

<details>
<summary>Manual delegation example, driving <code>horch</code> by hand</summary>

First create a separate checkout and branch for the writer. A worktree separates edits; it is not a security sandbox.

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

`horch wait` reports task states:

| State | Meaning |
|---|---|
| `running` | The worker is working. |
| `long_running` | A one-time notification after `notify_after_minutes`, not a state change. |
| `done` | The turn ended with a valid `result.json`. |
| `blocked`, `start_failed`, `not_started`, `exited`, `result_missing`, `result_invalid` | Problems; the pane stays open for inspection. |

</details>

## Optional: original pstack through Herdr

The adapter tracks [original pstack](https://github.com/cursor/plugins/tree/c742dd61706fbacc1b95f1a20b7b988cf096ce6c/pstack) 0.15.36 at `c742dd6` and bundles 60 installable entries: 55 pstack skills, three team-kit dependencies, and two Herdr adapters, with supporting files and licenses preserved. Nineteen adapted workflow entries load the Herdr mapping; the rest keep their complete original `SKILL.md`.

After installation, start a fresh session and invoke a skill directly:

```text
Use poteto-mode for this goal: ...
Done means: ...
```

You can also ask `Use interrogate to review this branch.`

All three controller harnesses read roles directly from `workers.toml`. Configure only the roles the chosen workflow needs. For the implementation/review loop:

```toml
[roles]
"feature, refactoring" = "gpt"
"interrogate reviewers" = ["glm", "haiku"]
```

A single role names one worker; a panel lists one worker per task. Same-model reviews are separate processes, not cross-model validation, so disclose an unmet panel-size or model-diversity requirement. The [adapter instructions](skills/pstack-herdr/SKILL.md) define workflow coordination, role routing, and review. Read-only assignments rely on worker briefs and harness permissions; `horch` is not a sandbox. A [live forge attempt](e2e/evidence/playbook-forge-scope-audit.json) was manually stopped after an investigator queried outside its assigned repository; that workflow remains failed.

Cursor modes, hooks, `/loop`, cloud execution, and unavailable MCP or app-driving tools are not supplied; a workflow requiring one stops at that step. For the pinned source, adaptations, exclusions, discovery behavior, and the maintainer sync procedure, see the [selection and compatibility notes](skills/pstack-herdr/references/compatibility.md).

## Verification

The [practical delivery receipt](e2e/evidence/practical-private-pr.json) completes
one requirement-to-implementation-to-independent-review-to-ready-private-PR
workflow. Its reviewed change passes 20 real CLI observations, preserves all
11 baseline normal observations and passes private Python 3.11/3.14 CI. This is
ordinary functionality review; original playbook eligibility remains separate.
The [adoption evidence page](docs/RELEASE-EVIDENCE.md) collects this workflow,
reversible installation, role routing and live worker replacement.

Runtime checks run on Linux with real Pi workers. Real Codex and Claude Code controller runs are also recorded. The verified set covers worker setup, the implementation and review loop, a controller-level run, workspace limits, invalid record handling, and Pi preflight. The 0.15.36 bundle at `c742dd6` passed a local installation check and native discovery in the Pi and Codex catalogs. A receipt for each verified claim is linked in [evidence and source attribution](e2e/README.md#evidence-and-source-attribution).

The original Prototype playbook has an [ordered six-stage core workflow receipt](e2e/evidence/playbook-prototype.json) for a fixed-direction behavioral fork. Both independent alternatives and their labeled runner were replayed; the production build remains a separate Feature task. Live worker replacement also has [independent evidence](e2e/evidence/hot-swap.json).

[Trace forensics](e2e/evidence/playbook-trace.json) also passed its six-stage paired-capture workflow. Independent review checked all profile rows and caller edges, replayed the SQL observations, and verified source attribution and unchanged inputs. [Pause and Pickup](e2e/evidence/playbook-continuity.json) passed their four- and five-stage local workflows in distinct sessions, with six real CLI cases independently replayed. Earlier failed continuity fixtures remain published. Investigation retains both an earlier explanation rewrite and a later erroneous synthesis that the controller correctly withheld.

[Runtime forensics](e2e/evidence/playbook-runtime.json) passed its five-stage owned-process scenario: live CPU capture, exact reduction, benign instrumentation, later natural counter growth and source mapping. Independent review checked the raw Inspector exchange and preserved inputs; this is a diagnostic result, without a fix or speedup claim.

Ready private child PRs have independently checked parent, head, body and remote state. The earlier complete Opening a PR judgment is [withdrawn](e2e/evidence/playbook-opening-pr-correction.json): the required Comment Sicko review was omitted. Full Perf also remains unresolved.

Not verified: macOS, deliberate approval denial, task turns longer than 30 minutes, and Claude Code native discovery, which was not measured although installation was checked. Most original pstack skills and 18 other playbooks lack a complete passing scenario; see the [complete inventory](e2e/PLAYBOOKS.md), including cloud and wake capabilities this adapter does not supply. Discovery does not prove workflow execution. The [capability and evidence gaps](docs/CAPABILITY-GAPS.md) separate missing runtime facilities, unverified scenarios and authorization boundaries.

Historical receipts keep their original source attribution in [evidence and source attribution](e2e/README.md#evidence-and-source-attribution). To rerun the checks, use [verify-herdr-orchestrator](.agents/skills/verify-herdr-orchestrator/SKILL.md).

## Troubleshooting

Start with `horch detect`. For worker dialogs or failed tasks, inspect the recorded pane before closing it; never resend a prompt or switch models automatically. Follow [setup and dialog handling](skills/herdr-orchestrator/references/setup.md) or [task recovery](skills/herdr-orchestrator/references/lifecycle.md#problem-recovery).

## Contributing

Send reproduction steps, relevant versions, and sanitized evidence with a bug report or fix, and verify affected behavior with the [existing E2E drivers](e2e/README.md). Write code, documentation, and commit messages in English. Never publish credentials, private paths, or full worker transcripts.

Controllers deliver changes on a feature branch and open or update a PR by default. Merging into `main` or enabling auto-merge requires an explicit user request, even when an upstream playbook calls for autonomous shipping.

Release tags use `vYYYY.MM.DD.N`, the UTC date plus a daily index from `1` (`v2026.10.10.1`, then `v2026.10.10.2`). Publish from verified `main` after an explicit release request. Existing tags stay unchanged, and the upstream pstack version is tracked separately.

## Credits

[Herdr](https://herdr.dev) hosts the worker panes. [pstack](https://github.com/cursor/plugins/tree/main/pstack) is Lauren Tan's original MIT-licensed workflow collection; this repository provides an independent adapter.

The banner references Herdr's ram icon. See its [provenance](assets/banner-prompt.md). The diagram uses [Archify](https://github.com/tt-a1i/archify); its [provenance and notices](assets/workflow.md) include the viewer's license.

## License

[MIT](LICENSE). Copyright 2026 conscientiousness and contributors.
