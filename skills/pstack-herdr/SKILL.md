---
name: pstack-herdr
description: "Run original pstack workflows through configured Herdr workers. Use as the entry point for pstack with Herdr, including poteto-mode and individual pstack skills."
---

# pstack-herdr

Use Lauren Tan's original pstack from `cursor/plugins`. Read [herdr-tools.md](references/herdr-tools.md) and the companion [herdr-orchestrator skill](../herdr-orchestrator/SKILL.md) before starting. The controller runs inside a Herdr pane.

This mapping takes precedence over upstream tool names, model defaults, configuration paths, and delegation instructions. User and project instructions retain precedence over both skills. Keep upstream source files unchanged.

## Enter a workflow

1. Locate the original source checkout. Use the path supplied by the user or project instructions; otherwise use `$XDG_DATA_HOME/herdr-orchestrator/cursor-plugins`, defaulting to `~/.local/share/herdr-orchestrator/cursor-plugins`. Read [source installation and compatibility](references/compatibility.md) for the pinned revision and setup. Check the checkout revision before using it; reconcile a different revision through that update procedure.
2. Resolve pstack skills under `<checkout>/pstack/skills/<name>/SKILL.md`. Read the requested skill, or `poteto-mode/SKILL.md` in full for a general goal, then its chosen playbook and required references. Read each applied principle's own file. Resolve relative links from their owning file. Use this checkout consistently rather than another installation of a same-named skill.
3. Keep workflow coordination in this controller. Expand exploration, design, implementation, and review phases here, then send bounded assignments through `horch`. Put this task-specific rule in every worker brief: **Do not delegate, use native subagents, or run a whole playbook. Complete this assignment yourself; report any need for further delegation to the controller.** This overrides the companion skill's general permission for worker subagents.

Enter through `pstack-herdr` in each new session, including for a specific upstream skill. Reading source files does not install Cursor modes, hooks, or slash commands. Runtime verification is recorded separately from source compatibility; see the compatibility notes.

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
2. Read the original checkout's `interrogate` reviewer prompt, rubric, and code-quality lens (see [compatibility notes](references/compatibility.md)). State the intent and fix the review target to a commit or other stable revision. Use a detached snapshot if the branch may move during review. Send the same complete review brief to every `interrogate reviewers` worker. Tell them to make no file changes. Start all of them with separate `horch run` calls before waiting, subject to the configured worker limit.
3. Wait until `horch wait` reports `state: "done"` for every reviewer. A report already on disk does not finish a `running` task; keep waiting, and never close an unfinished reviewer to pass the gate. Read each `result.json` and listed report. Synthesize the findings using pstack's `interrogate` lead judgment. Check concrete claims against the code. A completed task is not automatically a passing review.
4. If a finding needs a fix, start a fresh implementation worker on the same branch after the prior writer has finished. Include the original goal, all accepted findings, prior reports, and current revision in its brief. Verify its result and changed behavior. Run the reviewer panel again on the new revision; do not reuse a reviewer session.
5. Finish when the independent review has no unresolved blocking finding. Report the final revision, verification, reviewer outcomes, and any remaining concerns. If a worker reports a problem, follow `herdr-orchestrator` problem handling and keep the review gate open.

Writers must never work concurrently in the same worktree. Reviewers may share a checkout only when their briefs are read-only. Every `horch run` starts a fresh process, including each fix and second review.
