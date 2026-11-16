---
name: how
description: "Use for \"how does X work\", code walkthroughs before changing something, and placement / ownership / layering questions (\"where should this live\", \"which package owns this\", \"is this the right layer\"). Explains subsystem architecture, runtime flow, onboarding mental models. Use why for motivation."
---

## Herdr runtime

Before following the original instructions below, read the sibling [pstack-herdr](../pstack-herdr/SKILL.md) skill and its required mapping. Resolve relative references from this installed skill directory. Use a named sibling skill by reading ../<name>/SKILL.md, because explicit-only siblings are not in the harness skill list. The mapping translates original repository paths to bundled resources; no separate upstream checkout is needed. The Herdr mapping overrides upstream delegation tools, model defaults, setup files, and Cursor-specific capabilities. Delegate only through horch, using workers.toml. Keep workflow coordination in the controller. A bounded worker assignment remains bounded: do not start nested workers. User and project instructions take precedence. Check required capabilities before acting; keep unavailable steps unresolved. For setup-pstack, use the adapter's role setup instead of the original Cursor rule-writing procedure.


# How

Explore the codebase to answer "how does X work?" questions.

If the scope is ambiguous, state your interpretation and explore. The user can redirect.

## 1. Explain

Spawn one Task subagent with `subagent_type: generalPurpose` and `readonly: true` that explores and explains in one pass. Give it the user's question and this brief:

> You are writing an architectural explanation for a senior engineer. Explore the codebase and write an explanation that a senior engineer unfamiliar with this area could read and walk away with a solid mental model. They should understand the architecture well enough to start working in it confidently. You have read-only access to the codebase.

## 2. Present

Present the subagent's output. Light edits for clarity or context from the conversation are fine. Do not substantially rewrite it.
