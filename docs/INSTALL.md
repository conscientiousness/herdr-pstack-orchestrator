# Installation, updates, and removal

The [README](../README.md#install) covers installation with `npx skills`. The
commands use the latest bundle on this repository's `main` branch. Choose the
harnesses and project or global scope you want, and review same-name skill
conflicts before replacing anything.

## Manual installation

If you prefer not to use Node.js and npm, clone the repository:

```bash
git clone https://github.com/conscientiousness/herdr-pstack-orchestrator.git
cd herdr-pstack-orchestrator
```

Link the skills you want into your harness's skills directory. For example,
this installs the core skill for Claude Code:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/herdr-orchestrator" ~/.claude/skills/
```

For pstack workflows, install all sibling directories under `skills/` so the
adapter can find the other skills it needs. Do not overwrite an existing skill
without reviewing the conflict. Open a fresh agent session after installation.

From the clone, you can inspect the worker CLI directly:

```bash
python3 skills/herdr-orchestrator/scripts/horch.py detect
python3 skills/herdr-orchestrator/scripts/horch.py --help
```

The [command guide](../skills/herdr-orchestrator/SKILL.md#run-horch) describes
the available commands.

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
again. Keep your existing `workers.toml` rather than replacing it with the
example. After either update, start a new controller session inside Herdr.

## Remove

To remove the core skill from a project, run this in that project:

```bash
npx skills@1.7.1 remove herdr-orchestrator -y
```

To remove the full bundle, run `npx skills@1.7.1 remove` and select its entries,
leaving unrelated skills unselected. For complete project removal, omit `-a`;
selecting specific agents can leave shared copies. Use `-g` for a global
installation. Empty directories and installer lock metadata may remain. Start a
fresh agent session to see the changed skill catalog.
