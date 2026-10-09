---
name: verify-herdr-orchestrator
description: Verify herdr-pstack-orchestrator through its existing local E2E drivers. Use when checking skill discovery, worker or controller execution, Pi startup, or upstream monitoring in this repository.
---

# Verify herdr-orchestrator

Use the existing scripts for the behavior under investigation. Start with the [feature map](features/README.md); do not run every model E2E for a documentation change. This is repository tooling, not part of the published skill package.

## Launch

Run commands from this clone's root. There is no application server or build step. Python 3.11+ is required; each feature lists its other prerequisites. Create a private artifact parent outside the checkout:

```bash
repo=$(git rev-parse --show-toplevel)
cd "$repo"
proof=$(mktemp -d "${TMPDIR:-/tmp}/verify-herdr-XXXXXXXX")
git rev-parse HEAD > "$proof/revision.txt"
git diff --stat > "$proof/working-tree.txt"
```

Record the selected command and CLI versions with the receipt. Model runs require an authenticated harness, Herdr, and existing worker definitions in `${XDG_CONFIG_HOME:-$HOME/.config}/herdr-orchestrator/workers.toml`. Read actual harness/model definitions; names such as `gpt` do not imply Codex. Read [worker operation rules](../../../skills/herdr-orchestrator/SKILL.md) before a model run.

## Doctor

For model runs, first use this read-only check:

```bash
python3 skills/herdr-orchestrator/scripts/horch.py detect
```

Confirm required CLIs and Pi integration, `HERDR_ENV=1`, the actual controller pane/workspace, available slots, and each driver's prerequisites before launching. `horch check` makes real model calls; it is not a read-only doctor. Missing configuration, authentication, or trust is a prerequisite gap; do not change it silently.

For discovery and upstream checks, use the feature's source/CLI doctor instead; Herdr and model credentials are unnecessary.

## Drive

Follow only the selected [feature procedure](features/README.md). Keep the original long-running command/session alive while posting progress updates. All evaluation controllers and workers belong in separate Herdr tabs, never the user's controller tab. Stop other dispatchers during isolated-state model E2Es.

On a problem, preserve the receipt and inspect the recorded pane before cleanup. Never answer worker dialogs or automatically retry with another model. A delivered result requires `state: done`; review success also requires the driver's outcome assertions. Follow the companion skill for manual recovery.

## Evidence

The printed receipt path is authoritative: most drivers create a child directory beneath `--output`; the catalog driver chooses its own temporary directory. Read `verdict`, assertions, observed outputs, and cleanup results, not just process exit status. Preserve failed receipts as failures and distinguish a fresh run from historical evidence or transcript reanalysis.

Keep receipts, command/version records, and diagnostics locally after cleanup. [Published evidence](../../../e2e/README.md#evidence-and-source-attribution) documents earlier source revisions, not the current checkout. Review and sanitize any artifact before publication; raw catalogs, transcripts, pane text, and configuration can contain private paths or data.

## Cleanup

Drivers close only their own subprocesses or panes. Verify the receipt's cleanup result; never kill by process name or close unrelated panes. Model loop drivers retain worktrees: inspect first, then use `git worktree remove` on the exact printed path. Preserve its sibling receipt/diagnostics. For isolated-state runs, any manual `horch` cleanup must use the run's recorded configuration and state roots.

The discovery procedure removes its owned installation scratch directory. Never delete the artifact parent or catalog output as cleanup. After teardown, open the receipt again and confirm it still exists. Record any incomplete cleanup explicitly.

## Helpers

No new helper scripts. The feature map links the existing repository drivers and their maintained [E2E documentation](../../../e2e/README.md). Use `maintain-verification-skill` with this directory when these procedures drift; report product defects separately from documentation corrections.
