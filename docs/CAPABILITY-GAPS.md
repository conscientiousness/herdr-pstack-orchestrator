# Capability and evidence gaps

Release readiness is tracked in [adoption evidence](RELEASE-EVIDENCE.md):
installation/removal, configured role routing, worker replacement and one
practical implementation/review/private-PR workflow. Full original-playbook
conformance is a later milestone, not a release prerequisite. No further full
conformance reruns are scheduled to clear formatting-only differences.

The adapter has five bounded core-playbook passes out of the original 23.
A passing worker, installation, delivery gate or CLI replay is a separate claim.
The [complete inventory](../e2e/PLAYBOOKS.md#complete-inventory) retains the
original receipts and current workflow verdicts.

## Capabilities that block original workflows

| Status | Missing capability in the current adapter or captured runtime | Affected work | What would unlock verification |
| --- | --- | --- | --- |
| **blocked** | An authorized remote/cloud execution lane | Shipping verifiers, Multi-phase plan, Orchestrate, Autopilot owners and verifiers | A specified provider or remote Herdr environment with an explicit execution interface, credentials already configured, an owned test destination and any required configured swarm role |
| **blocked** | Durable scheduled wake and resume | Autonomous run, Orchestrate, Autopilot, unattended Hillclimb and Babysit | An explicit scheduler/runtime that can persist the run identity and wake the correct controller after it exits; an attended local wait does not provide this |
| **blocked** | The original per-component `/loop` execution surface | Visual parity | An explicit controller loop for repeated comparison until zero pixel difference, together with the real UI baseline and migration scenario |
| **blocked** | A supervisor witness binding a visible shell job to its actual invocation | Babysit's overlapping-dispatcher preparation check | A displayed-job to PID/start-time/run-nonce link; caller-pane equality cannot identify which of several jobs launched the work |
| **blocked** | Strictly blinded evaluation under the current Pi startup configuration | Original Eval | An explicitly chosen evaluation environment whose model-visible catalog cannot reveal the target skills; current global discovery is not blinded |
| **blocked** | Pinned-worktree and active-chat ownership metadata | Original Worktree cleanup | Authoritative pin and active-chat facts before selecting a deletion target; owned E2E teardown verifies only its own cleanup |

No cloud provider or remote Herdr environment has been authorized for these
experiments. These prerequisites remain gaps; this change does not create a
cloud service, scheduler, background watcher or replacement ownership witness.

## Core backend verification

The unchanged `e2e/core_backend.py --core-only` driver verifies real core 0.1.17
with a deterministic interactive Pi fixture and no models. Its scenarios cover
headless core preference, early-result rejection, ended native turns, missing
and invalid results, blocked/cancel cleanup, and an installed but unusable core
refusing legacy fallback. Private receipts remain outside the public checkout.

Native startup probes reported idle for installed Pi, Codex with `--no-daemon`,
and Claude Code. These probes and deterministic fixtures do not prove configured
model delivery for every harness. A configured Pi worker completed a decimal-ledger
CLI task through core and through genuine executable-absence fallback. Independent
CLI oracles verified both results. The controller observed `hcOrch` and `horch`
tabs without focus changes and confirmed worker/viewer cleanup. Waiting still used
the stored core endpoint after session and PATH changes; the legacy task still used
legacy execution after core became visible on PATH. A repeated core run confirmed
that successful empty viewer-launch output produces no warning.

Configured Codex and Claude task delivery remains unverified beyond native startup.
No new Herdr app is installed or required. Core support
currently uses local POSIX endpoints; remote core orchestration is not provided.

## Evidence still needed

| Evidence gap | Current boundary |
| --- | --- |
| Complete local writable playbooks | Feature, Refactoring, Perf issue, Hillclimb and skill Authoring retain failed original runs and independently audited partial behavior. Successful delivery and final mandatory review must occur together in a fresh run. |
| Complete Investigation and Bug fix | Investigation retains an unresolved synthesis error. The Bug fix snapshot/gateway lane does not establish original live-source Why or full Bug fix eligibility. |
| Opening a PR | Actual ready private child PR facts are recorded, but earlier full eligibility was withdrawn because mandatory delegated Comment Sicko review was omitted. |
| Original Visual parity | Browser/diff tools alone do not establish an untouched UI baseline, real migration, zero-pixel difference, final PR or the required loop. |
| The same original playbooks on every controller harness | Core worker/controller interoperability has Codex and Claude Code evidence. The maintained original-playbook drivers use Pi native capture; full Codex/Claude Code playbook execution is unverified. |
| Other operating systems and recovery branches | Runtime evidence is on Linux. macOS, deliberate approval denial and worker turns longer than 30 minutes remain unverified. |

The [evidence guide](../e2e/README.md) distinguishes original FAIL receipts,
separate metadata or behavior audits, fresh CLI replays and complete passing
scenarios. A quarantined worker's report, result and native payload bodies remain
unread. Static fixes and package CI do not promote an old run to PASS.

## Authorization boundaries

All forge experiments use an independent private fixture repository. Its test
PRs stay unmerged. No default-branch write, merge or auto-merge is authorized;
Shipping and Autopilot cannot claim those actions without a separate user
instruction. Permission and authentication settings are not silently changed
to make a workflow pass.

The low-intrusion claim is narrower: the controller uses existing agent CLIs and
one worker configuration, with no application-code changes required. Verified
worker-definition replacement affects new dispatches; existing tasks keep their
launch snapshots. Skill loading and role selection remain controller duties,
and skill updates can require a fresh session. Low intrusion does not supply the
missing runtime capabilities above.
