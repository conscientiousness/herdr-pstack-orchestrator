# pstack compatibility

The controller review-loop E2Es recorded on 2026-10-09 used the installed **pstack-claude 0.9.73** package. Its upstream release is [v0.9.73](https://github.com/michael-denyer/pstack-claude/tree/v0.9.73/plugins/pstack), commit `8d3aa5719ab836e89482c894bbedd710224f4424`. That is the tested version, not a promise that later versions retain the same instructions. Other versions and workflows (including Arena) are unverified.

This integration replaces delegation instructions; it neither copies nor parses pstack's rubric. It relies on these parts of the installed package:

| Dependency | How the mapping uses it |
|---|---|
| `skills/interrogate/SKILL.md` | Same intent and pinned revision for every reviewer; synthesize findings with lead judgment. |
| `skills/interrogate/references/reviewer-prompt.md` | Fill the shared reviewer brief. |
| `skills/interrogate/references/rubric.md` and `code-quality-review.md` | Include both the rubric and code-quality lens in that brief. |
| `skills/interrogate/references/lead-judgment.md` | Evaluate findings after all required reviews arrive. |
| `feature, refactoring` and `interrogate reviewers` role names | Resolve to worker names in the authoritative TOML `[roles]` table. |
| User-owned `pstack-models.md` and the session hook | Claude imports TOML; retain `session hook: off` in the sheet itself when configured. Codex/Pi read TOML directly. |

When installing or upgrading pstack:

1. Read its installed plugin metadata to identify the version. Locate `interrogate` and the references above; follow any renamed paths in its current instructions.
2. Compare delegation, role resolution, reviewer inputs, and lead judgment against this mapping. Preserve the Herdr overrides: no native controller subagents, no default-model substitution, fresh processes, and `done` required for every reviewer.
3. If the workflow or role contract changed, reconcile the mapping before dispatch. Do not silently use an obsolete rubric or native fallback.
4. Run a real implementation/review/fix/re-review through an AI controller using both skills before claiming the new version is verified. The repository's `e2e/review_loop.py` exercises `horch` directly and does not establish pstack skill compatibility on its own.

Keep pstack's installed files unchanged. Record newly verified versions and source evidence in the repository's `e2e/evidence/verification.json`.
