---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
---

## Herdr runtime

Before following the original instructions below, read the sibling [pstack-herdr](../pstack-herdr/SKILL.md) skill and its required mapping. Resolve relative references from this installed skill directory. The mapping translates original repository paths to bundled resources; no separate upstream checkout is needed. The Herdr mapping overrides upstream delegation tools, model defaults, setup files, and Cursor-specific capabilities. Delegate only through horch, using workers.toml. Keep workflow coordination in the controller. A bounded worker assignment remains bounded: do not start nested workers. User and project instructions take precedence. Check required capabilities before acting; keep unavailable steps unresolved. For setup-pstack, use the adapter's role setup instead of the original Cursor rule-writing procedure.


# Guard the Context Window

The context window is finite and non-renewable within a session. Every token should be worth its cost.

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.

**Pattern:**
- **Isolate large payloads.** Route verbose outputs, screenshots, and large documents to subagents. The main context gets summaries, not raw data.
- **Keep frequently used content inline.** Templates and references used on every invocation belong in the skill file, not in separate files that cost a read each time.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.
