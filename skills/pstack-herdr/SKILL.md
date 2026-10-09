---
name: pstack-herdr
description: "Route pstack delegation and review workflows through configured Herdr workers. Use when a controller runs pstack with Herdr instead of native subagents."
---

# pstack-herdr

Use pstack's playbooks and review rubric for the work itself. Use this skill for every delegated action in those playbooks. Read [herdr-tools.md](references/herdr-tools.md) before dispatching. Also read the companion [herdr-orchestrator skill](../herdr-orchestrator/SKILL.md) for `horch` commands, task results, setup, and problem handling. Install both skills. The controller runs inside a Herdr pane.

This mapping takes precedence over pstack's native `Agent`/`Task`, `SendMessage`, and runtime-specific subagent mappings. Never use native subagents while acting as this controller. Keep pstack's other tool mappings for ordinary reads, edits, searches, and task tracking. Do not change pstack's installed files.

## Resolve roles

Read `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`, or `~/.config/herdr-orchestrator/workers.toml` when `XDG_CONFIG_HOME` is unset. Its `[roles]` values name workers from `[workers]`. A single role is one worker name; a panel is a list, with one task per entry. For the first review loop, configure `"feature, refactoring"` and `"interrogate reviewers"`. Other pstack workflows need their matching role keys before they can delegate.

Use the configured worker's harness, model, and effort without substituting the pstack skill's Claude model defaults. If a role or worker is missing, invalid, or names `auto` or `inherit-parent`, stop before dispatch and complete the `herdr-orchestrator` setup with the user. Do not fall back to a native subagent. Ignore any `@<level>` suffix on a role value; the worker definition owns effort.

On setup, ask which configured workers should fill each role. For example:

```toml
[roles]
"feature, refactoring" = "glm"
"interrogate reviewers" = ["ds", "haiku"]
```

For Claude Code, replace the role lines in `pstack-models.md` with one `@` import of the resolved `workers.toml` path. Keep `session hook: off` in `pstack-models.md` itself if the user has disabled that hook, because the hook does not follow imports. On Codex and Pi, read `[roles]` directly from TOML; their pstack role-sheet loaders do not expand the Claude import. The TOML file is authoritative in every runtime.

## Review loop

1. State the intended behavior and create a git worktree for the implementing worker. Give it a complete brief, including the base revision, scope, constraints, verification, and output files. Dispatch the configured implementation worker with `horch run <worker> --cwd <worktree> --brief <file>`. Wait for a valid result, inspect its files and diff, and verify the changed behavior.
2. Read pstack's `interrogate` reviewer prompt and rubric. State the intent and fix the review target to a commit or other stable revision. Use a detached snapshot if the branch may move during review. Send the same complete review brief to every `interrogate reviewers` worker. Tell them to make no file changes. Start all of them with separate `horch run` calls before waiting, subject to the configured worker limit.
3. Wait for every reviewer. Read each `result.json` and listed report. Synthesize the findings using pstack's `interrogate` lead judgment. Check concrete claims against the code. A completed task is not automatically a passing review.
4. If a finding needs a fix, start a fresh implementation worker on the same branch after the prior writer has finished. Include the original goal, all accepted findings, prior reports, and current revision in its brief. Verify its result and changed behavior. Run the reviewer panel again on the new revision; do not reuse a reviewer session.
5. Finish when the independent review has no unresolved blocking finding. Report the final revision, verification, reviewer outcomes, and any remaining concerns. If a worker reports a problem, follow `herdr-orchestrator` problem handling and keep the review gate open.

Writers must never work concurrently in the same worktree. Reviewers may share a checkout only when their briefs are read-only. Every `horch run` starts a fresh process, including each fix and second review.
