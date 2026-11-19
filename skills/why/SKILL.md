---
name: why
description: "Use for 'why does X work this way', 'why we picked Y', design rationale, regressions, postmortems, or data-backed thresholds. Returns a cited read on decisions and tradeoffs. Use how for runtime behavior."
---

## Agent Workers runtime

Before following the original instructions below, read the sibling [pstack-herdr](../pstack-herdr/SKILL.md) skill and its required mapping. Resolve relative references from this installed skill directory. Use a named sibling skill by reading ../<name>/SKILL.md, because explicit-only siblings are not in the harness skill list. The mapping translates original repository paths to bundled resources; no separate upstream checkout is needed. The adapter overrides upstream delegation tools, model defaults, setup files, and Cursor-specific capabilities. Delegate only through agent-workers, using workers.toml. Keep workflow coordination in the controller. A bounded worker assignment remains bounded: do not start nested workers. User and project instructions take precedence. Check required capabilities before acting; keep unavailable steps unresolved. For setup-pstack, use the adapter's role setup instead of the original Cursor rule-writing procedure.


# Why

Answer from the record, not the code: read the commits and PR discussions that introduced the target and each later change, and other sources if the trail is thin. Cite what the authors wrote, mark your own inferences as inferences, and say what the record does not answer.
