# Verification feature map

Commands run from the repository root, using `repo` and `proof` from [Launch](../SKILL.md#launch). Select the feature relevant to the change or observed failure.

| Feature | Driver | Preconditions and scope |
|---|---|---|
| [Skill installation and discovery](discovery.md) | `skill_catalogs.py` | Bundled skills, npm, Pi, Codex; no models |
| [Practical delivery and removal](../../../../e2e/ADOPTION.md) | Existing `horch.py`, fixture generator and CLI oracle | Two configured workers, authorized private fixture/parent PR; complete project removal preserves an unrelated skill |
| [Core backend lifecycle](core.md) | `core_backend.py --horch skills/herdr-orchestrator/scripts/horch.py --output "$proof" --core-only` | Official herdr-core, private HC_SESSION and XDG paths; deterministic interactive fixture, no models. Includes unsent startup recovery, observation-only recheck and duplicate-submit refusal. No configured delivery, visible tabs or legacy runtime. |
| [Core viewer placement](core.md#viewer-placement) | `core_backend.py --horch skills/herdr-orchestrator/scripts/horch.py --output "$proof" --viewer` | Adds real attach viewers in an owned workspace; requires `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and Herdr CLI. Verifies controller receipts, same-workspace `hcOrch` panes, pinned attach/rendering, fresh viewer verification failure/recovery, unchanged focus and owned cleanup. |
| [Worker review loop](workers.md) | `review_loop.py` | Authenticated workers, two free slots; six real tasks |
| [Worker setup checks](workers.md#worker-setup-checks) | `check_workers.py` | At least two authenticated configured workers, owned workspace, one-slot batching and injected exit |
| [Workspace worker limits](workers.md#workspace-worker-limits) | `workspace_limits.py` | One authenticated worker, two owned workspaces, shared isolated task store |
| [AI controller loop](controller.md) | `controller_loop.py` | Configured Codex controller plus workers; transcript audit |
| [Original playbook scenarios](playbooks.md) | `playbook_loop.py` | Configured Pi controller; native session audit and independent artifacts |
| [Pause and pickup](playbooks.md) | `pause_pickup.py` | Two fresh Pi sessions, normal Git identity and local WIP; no forge writes |
| [Private PR workflows](playbooks.md) | `forge_loop.py`, `design_loop.py`, `perf_loop.py`, `hillclimb_loop.py`, `authoring_loop.py` | Eight Refactoring deliveries and before/after equivalence verified; final Comment quarantine and earlier failures retained; full workflows unresolved; private fixture and ready parent PR |
| [Live runtime diagnosis](playbooks.md) | `runtime_loop.py` | Fresh five-stage owned-process pass; earlier failed receipts and separate audits retained |
| [PR-chain status](playbooks.md) | `babysit_loop.py` | Fourth Check blocked on ambiguous visible launch; supervisor witness needed before another run; explicit private chain and Bun; one Check only |
| [Live worker replacement](workers.md#live-worker-replacement) | `check_workers.py --hot-swap-only` | Two distinct configured execution definitions; owned workspace and in-flight gates |
| [Caller/config preflight](controller.md#caller-context-preflight) | `caller_context.py --controller-pane <id> --controller-text '<unique visible conversation text>' --output "$proof"` | Verified live controller pane and text; read-only Herdr checks, no models |
| [Caller identity and preflight](controller.md#caller-identity) | `caller_identity.py --controller-pane <id> --controller-text '<unique visible conversation text>' --output "$proof"` | Verified live controller pane and conversation text; owned scratch tab/workspace, process-tree and shared-daemon claims, no models |
| [Pi integration and startup](pi.md) | `pi_preflight.py`, `pi_startup.py` | Select the reproduced failure; different prerequisites |
| [Upstream update detection](upstream.md) | `check_upstream.py` | Git and network; no models |

This is the map of reproducible drivers, not a claim of complete workflow coverage. The invoice loop drivers do not exercise the original pstack rubric. The playbook driver audits declared original-workflow stages; full workflow eligibility and the 23-playbook inventory remain separate gates. A historical manual `how` run is recorded in [skill-discovery.json](../../../../e2e/evidence/skill-discovery.json). Approval denial, turns longer than 30 minutes, and macOS runtime remain unverified. Historical lifecycle/recovery/completion receipts have no distributed driver.
