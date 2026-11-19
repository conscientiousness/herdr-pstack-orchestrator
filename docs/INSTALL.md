# Installation, updates, and removal

The [README](../README.md#install) covers installation with `npx skills`. The
commands use the latest bundle on this repository's `main` branch. Choose the
harnesses and project or global scope you want, and review same-name skill
conflicts before replacing anything.

## Manual installation

If you prefer not to use Node.js and npm, clone the repository:

```bash
git clone https://github.com/conscientiousness/herdr-rex-pstack-orchestrator.git
cd herdr-rex-pstack-orchestrator
```

Link the skills you want into your harness's skills directory. For example,
this installs the core skill for Claude Code:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/agent-workers" ~/.claude/skills/
```

For pstack workflows, install all sibling directories under `skills/` so the
adapter can find the other skills it needs. Do not overwrite an existing skill
without reviewing the conflict. Open a fresh agent session after installation.

From the clone, you can inspect the worker CLI directly:

```bash
python3 skills/agent-workers/scripts/agent-workers.py detect
python3 skills/agent-workers/scripts/agent-workers.py --help
```

The [command guide](../skills/agent-workers/SKILL.md#run-agent-workers) describes
the available commands. Keep the entire `scripts/` directory when copying the
skill, including `core_backend.py` and `rex_backend.py`. The skill has no
third-party Python dependencies.

To use `agent-workers` directly from your shell, link the executable into a
directory on your `PATH`. For example, if `~/.local/bin` is on your `PATH`,
run this from the clone:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/skills/agent-workers/scripts/agent-workers" ~/.local/bin/agent-workers
```

Start the controller inside the multiplexer you want to use. Rex controllers
use a local Unix-socket [Rex server and CLI](https://www.superlogical.com/rex/docs/automate/cli)
and run workers in a **Workers** tab in the verified project session. Herdr uses
the same tab name in the verified workspace, with attached viewers when core is
installed and native panes otherwise. `herdr-core` takes priority over a verified
`hc` alias. Controllers outside both multiplexers can use core headless. Both
Rex and core use native harness status.

Recover missing or ambiguous [caller context](../skills/agent-workers/references/setup.md#caller-context)
before dispatch. A connection, readiness, or viewer error stays on the selected
backend. Stored Rex and core tasks retain their original endpoint. Keep each
legacy task store scoped to its original Herdr server.

## Upgrade from herdr-orchestrator

Install `agent-workers` with the [current install command](../README.md#install)
using your previous harnesses and scope. If you installed the pstack bundle,
update the whole bundle together so its adapter and workflow skills agree.
Remove the old `herdr-orchestrator` skill from that same scope with
`npx skills@latest remove herdr-orchestrator -y` (add `-g` for a global install).
For a manual install, replace the old skill link or copy with
`skills/agent-workers`. Start a fresh controller session.

The new CLI reads the same `herdr-orchestrator/workers.toml` and task store.
Existing tasks keep their terminal bindings. New launches use the **Workers**
tab name. Update scripted paths to `skills/agent-workers/scripts/agent-workers.py`.
The new skill also includes `scripts/horch.py` as a compatibility entry point.

## Update

For an installer-managed copy, rerun the same [install command](../README.md#install)
from the original project, selecting the same harnesses and scope. Use `-g` for
a global installation. Review conflicts before confirming replacement. Avoid
unfiltered `skills update -p` or `skills update -g`: they can update skills from
other repositories too.

For a manual clone on `main`:

```bash
git pull --ff-only
```

Symlinks use the updated files; if you copied the skills instead, copy them
again. Keep your existing `workers.toml`. After either update, start a new
controller session in your chosen multiplexer, or use core headless.

## Remove

To remove the core skill from a project, run this in that project:

```bash
npx skills@latest remove agent-workers -y
```

To remove the full bundle, run `npx skills@latest remove` and select its entries,
leaving unrelated skills unselected. For complete project removal, omit `-a`;
selecting specific agents can leave shared copies. Use `-g` for a global
installation. Empty directories and installer lock metadata may remain. Start a
fresh agent session to see the changed skill catalog.
