<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.png">
  <img alt="A Border Collie controller and Herdr sheep workers at their terminals" src="assets/banner-light.png" width="100%">
</picture>

# herdr-rex-pstack-orchestrator

[![Package validation](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/actions/workflows/validate.yml/badge.svg)](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/actions/workflows/validate.yml)
[![Pstack upstream](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/actions/workflows/upstream.yml/badge.svg?branch=main)](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/actions/workflows/upstream.yml)
[![Pstack source: 0.15.43](https://img.shields.io/badge/pstack_source-0.15.43-blue)](https://github.com/cursor/plugins/tree/2f87c854fe3e2fcda44ca86b46ede35aad3c46b7/pstack)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Give your coding agent a team of workers in [Herdr](https://herdr.dev) or
[Rex](https://www.superlogical.com/rex/docs/automate/cli). One agent coordinates
the task, delegates investigation or implementation to Pi, Codex CLI, or Claude
Code workers, and verifies their results.

The **Workers** tab keeps delegated work visible without taking focus from the
controller. Rex runs workers in split blocks in the verified project session.
Herdr uses panes in the verified workspace, with attached viewers when
herdr-core is installed. Herdr-core also supports headless operation.

Use the core skill for delegation, or add the optional **pstack** bundle for
workflows such as independent review and multi-step implementation. You can use
one configured worker or several, including workers from different harnesses.
No changes to your application code are needed.

[Latest release](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/releases/latest).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/workflow-light.svg">
  <img alt="Your controller briefs an implementation worker, verifies its diff, and dispatches independent reviewers. After all reviewers finish, the controller assesses findings. Accepted findings go to a fresh fix worker and a fresh review panel; no unresolved blockers leads to a verified result." src="assets/workflow-light.svg" width="100%">
</picture>

## Requirements

- In Rex, a local Unix-socket Rex server and the `rex` CLI. In Herdr or headless,
  use [herdr-core](https://github.com/herdrdev/herdr-core). Core 0.1.17 has Linux
  E2E coverage. If core is absent and your controller runs inside Herdr,
  [Herdr](https://herdr.dev) 0.9.3 or later supplies the legacy runtime.
- Python 3.11 or later with POSIX file locks. Linux has been tested; macOS is not yet verified.
- Node.js 22.20 or later and npm for the installer.
- The agent CLIs you want to use—`pi`, `codex`, or `claude`—installed and authenticated.
- For Rex and core, use harness versions that report native OSC 7501 status.
  For legacy Pi workers, install Herdr's integration with `herdr integration install pi`.

## Install

Run one of these commands from your project. `skills@latest` uses the latest
[Skills CLI](https://github.com/vercel-labs/skills) from npm. For delegation
alone, install the core skill:

```bash
npx skills@latest add conscientiousness/herdr-rex-pstack-orchestrator -s agent-workers
```

For pstack workflows as well, install the full bundle:

```bash
npx skills@latest add https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose your agent harnesses and project or global scope in the installer, and
review any same-name skill conflicts. Then start a **new agent session** so it
can load the skills. See the [installation guide](docs/INSTALL.md) for manual
installation, updates, and removal.

## Quickstart

In your new controller session, ask your agent to set up its workers:

```text
Set up the agent-workers skill with me. Find the available harnesses,
ask me which workers, models, and permissions to use, then check the setup.
```

After setup, give it a task. For example:

```text
Use agent-workers to fix the login redirect bug in this repository.
Delegate the implementation and have a fresh worker review the result before
reporting back.
```

The controller creates a separate process for each task, waits for the result,
and checks the work. You can inspect the worker panes as it goes.

## Configuration

Your agent helps you create `~/.config/herdr-orchestrator/workers.toml` (or the
equivalent under `$XDG_CONFIG_HOME`). It records each worker's harness, model,
and permission settings; new tasks use the current definitions. One worker is
enough to start, and you can add more later.

Workers run with the permissions you choose. `agent-workers` does not enforce a sandbox,
and separate worktrees only keep edits apart. See [setup and configuration](skills/agent-workers/references/setup.md)
for the available options and permission behavior.

## Optional pstack workflows

The full bundle includes selected original [pstack](https://github.com/cursor/plugins/tree/2f87c854fe3e2fcda44ca86b46ede35aad3c46b7/pstack)
skills and an adapter that delegates through `agent-workers`. After installing
the bundle and configuring workers, try:

```text
Use interrogate to review this branch.
```

Or ask for `poteto-mode` when you want a broader workflow. The controller can
help configure the worker roles that a workflow needs. For the included skills,
role mapping, and compatibility details, see the [pstack guide](skills/pstack-herdr/references/compatibility.md).

The playbook defines what to prove and when to stop. `agent-workers` dispatches through
the roles, models and effort in your `workers.toml`. The controller checks
worker results and handles PR delivery under the project's rules. See the
[workflow review](e2e/PLAYBOOKS.md#workflow-review-for-pstack-01543) for all 22
playbooks, their evidence and any required cloud, scheduling or workspace capabilities.

## Update

If you installed `herdr-orchestrator`, follow the [rename upgrade guide](docs/INSTALL.md#upgrade-from-herdr-orchestrator).
For subsequent updates, rerun the [install command](#install) you chose, select the same
harnesses and scope, and start a new controller session. These commands install from
this repository's `main` branch. The [installation guide](docs/INSTALL.md) also
explains how to update a manual clone or remove the skills.

## Troubleshooting

Ask your agent to run `agent-workers detect` to see the selected route, available
harnesses, and Pi integration status. Tasks keep their launch backend. Rex and
core tasks also pin their server endpoint for later observation and cleanup.
If a worker stops or fails, inspect its recorded terminal before closing it.
See the [setup guide](skills/agent-workers/references/setup.md) and [task
recovery guide](skills/agent-workers/references/lifecycle.md#problem-recovery).

## More information

- [Worker commands and lifecycle](skills/agent-workers/SKILL.md)
- [Verification evidence](docs/RELEASE-EVIDENCE.md) and [known gaps](docs/CAPABILITY-GAPS.md)
- [Contributing](CONTRIBUTING.md)

Includes an independent adapter for Lauren Tan's
[pstack](https://github.com/cursor/plugins/tree/main/pstack). The banner
and workflow diagram have their own [asset notes](assets/banner-prompt.md) and
[diagram notices](assets/workflow.md). Licensed under the [MIT License](LICENSE).
