# Verification feature map

Commands run from the repository root, using `repo` and `proof` from [Launch](../SKILL.md#launch). Select the feature relevant to the change or observed failure.

| Feature | Driver | Preconditions and scope |
|---|---|---|
| [Skill installation and discovery](discovery.md) | `skill_catalogs.py` | Bundled skills, npm, Pi, Codex; no models |
| [Worker review loop](workers.md) | `review_loop.py` | Authenticated workers, two free slots; six real tasks |
| [AI controller loop](controller.md) | `controller_loop.py` | Configured Codex controller plus workers; transcript audit |
| [Caller context preflight](controller.md#caller-context-preflight) | `caller_context.py` | Verified live controller pane; read-only Herdr checks, no models |
| [Pi integration and startup](pi.md) | `pi_preflight.py`, `pi_startup.py` | Select the reproduced failure; different prerequisites |
| [Upstream update detection](upstream.md) | `check_upstream.py` | Git and network; no models |

This is the map of existing reproducible drivers, not a claim of complete workflow coverage. Neither loop driver exercises the original pstack rubric. A separate manual `how` run is recorded in [skill-discovery.json](../../../../e2e/evidence/skill-discovery.json); other original playbooks remain unverified. Approval denial, turns longer than 30 minutes, and macOS runtime also remain unverified. Historical lifecycle/recovery/completion receipts have no distributed driver.
