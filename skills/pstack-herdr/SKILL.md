---
name: pstack-herdr
description: "Run original pstack workflows through configured Herdr workers. Loaded by installed pstack workflow skills to map their tools and roles to Herdr; also usable as an explicit entry point."
---

# pstack-herdr

Installed workflow skills load this mapping before their original instructions. You can invoke `poteto-mode`, `how`, or `interrogate` directly. The bundle contains selected skills from Lauren Tan's original `cursor/plugins`, their resources, and both Herdr adapters. Read [herdr-tools.md](references/herdr-tools.md) and the companion [herdr-orchestrator skill](../herdr-orchestrator/SKILL.md) before starting. The controller runs inside a Herdr pane.

This mapping takes precedence over upstream tool names, model defaults, configuration paths, and delegation instructions. User and project instructions retain precedence over both skills. Preserve bundled upstream instructions; report required compatibility changes separately.

## Enter a workflow

1. Use the sibling skills installed with this adapter. The [bundle provenance](references/bundle.json) records their reviewed source revision; a separate source checkout is unnecessary. If a required sibling is missing, report an incomplete installation and follow [bundle installation](references/compatibility.md#install). Do not fetch missing instructions from a different revision during a workflow.
2. Read the requested sibling `<name>/SKILL.md`, or [poteto-mode](../poteto-mode/SKILL.md) in full for a general goal, then its chosen playbook and required references. Read each applied principle's own file. Resolve relative links from their owning file. Use this installed bundle consistently rather than another same-named skill.
3. Keep workflow coordination in this controller. Expand exploration, design, implementation, and review phases here, then send bounded assignments through `horch`. Put this task-specific rule in every worker brief: **Do not delegate, use native subagents, or run a whole playbook. Complete this assignment yourself; report any need for further delegation to the controller.** This overrides the companion skill's general permission for worker subagents.

The bundle's workflow entries load this mapping automatically; pure guidance keeps its original body. Cursor custom modes and hooks are not installed. Runtime verification is separate from discovery and source compatibility.

## Resolve roles

On Claude Code, Codex, and Pi, read `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`, or `~/.config/herdr-orchestrator/workers.toml` when `XDG_CONFIG_HOME` is unset. Its `[roles]` values name workers from `[workers]`. This is the only role configuration. Upstream `setup-pstack` maps to the companion skill's setup and these TOML roles; do not create a separate model sheet or import one.

Keep upstream role names. A single role names one worker, which may handle several fresh tasks. Panels (`interrogate reviewers`, `arena runners`, `architect runners`) are lists with one task per entry. `arena cross-judge pool` is also a list, but the controller selects one entry as the skill directs. Configure only roles needed by the selected workflow; preserve its required panel size and model diversity.

Use each worker's configured harness, model, and effort. If a needed role or worker is missing, invalid, or names `auto` or `inherit-parent`, complete setup with the user before dispatch. Never substitute upstream model defaults or native subagents. For an ad-hoc task without a named upstream role, explicitly select a suitable configured worker.

On setup, ask which configured workers should fill each role. For example:

```toml
[roles]
"feature, refactoring" = "glm"
"interrogate reviewers" = ["ds", "haiku"]
```

## Review loop

1. State the intended behavior and create a git worktree for the implementing worker. Give it a complete brief, including the base revision, scope, constraints, verification, and output files. Dispatch the configured implementation worker with `horch run <worker> --cwd <worktree> --brief <file>`. Wait for a valid result, inspect its files and diff, and verify the changed behavior.
2. Read the sibling `interrogate/references/` reviewer prompt, rubric, and code-quality lens (see [compatibility notes](references/compatibility.md)). State the intent and fix the review target to a commit or other stable revision. Use a detached snapshot if the branch may move during review. Send the same complete review brief to every `interrogate reviewers` worker. Tell them to make no file changes. Start all of them with separate `horch run` calls before waiting, subject to the configured worker limit.
3. Wait until `horch wait` reports `state: "done"` for every reviewer. A report already on disk does not finish a `running` task; keep waiting, and never close an unfinished reviewer to pass the gate. Read each `result.json` and listed report. Synthesize the findings using pstack's `interrogate` lead judgment. Check concrete claims against the code. A completed task is not automatically a passing review.
4. If a finding needs a fix, start a fresh implementation worker on the same branch after the prior writer has finished. Include the original goal, all accepted findings, prior reports, and current revision in its brief. Verify its result and changed behavior. Run the reviewer panel again on the new revision; do not reuse a reviewer session.
5. Finish when the independent review has no unresolved blocking finding. Report the final revision, verification, reviewer outcomes, and any remaining concerns. If a worker reports a problem, follow `herdr-orchestrator` problem handling and keep the review gate open.

Writers must never work concurrently in the same worktree. Reviewers may share a checkout only when their briefs are read-only. Every `horch run` starts a fresh process, including each fix and second review.
