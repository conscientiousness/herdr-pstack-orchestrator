# Pi startup investigation

The relocated review driver failed before its first implementation because a Pi project-trust dialog received the task submission. This was reproduced with Herdr 0.9.3, Pi 1.1.0, and the Herdr Pi integration v9. It was not a provider latency failure.

## Reproduction and cause

An earlier local package-install check left an empty `.agents/skills` directory in the shared temporary parent. Its files had been removed, but the directory remained. Pi treats the existence of that directory in any ancestor as project resources requiring a trust decision, even when it is empty. Every fresh fixture directory therefore required trust; an existing directory could already have a saved decision.

The observations were:

1. Herdr returned `agent_started`, `interactive_ready: true`, and `idle` while Pi had no reported session.
2. A fresh diagnostic that withheld the prompt showed Pi's **Trust project folder?** dialog. `herdr agent explain` reported `default_known_agent_idle_fallback`, no matched rule, and `visible_blocker: false`.
3. In the failing runs, the task submission's Enter selected the dialog's default **Trust** option. Pi subsequently showed an empty editor, with no task message or result. The fresh fixture paths appeared as trusted in Pi's store. Herdr returned `agent_prompt_stalled`; horch recorded `not_started`.
4. Removing the empty directory restored normal submission with the original, unchanged horch code in another fresh fixture. The worker delivered a valid result and the corrected line CLI returned `936`.

This explains the earlier pattern: three fresh worktrees failed, while a later manual dispatch in one of those same worktrees succeeded. The reproduction exposed an upstream detection gap and a horch assumption: a reported idle/ready state did not guarantee that task input would reach the agent's conversation.

The upstream code supports these observations:

- [Pi 1.1.0 trust-resource detection and parent-directory decisions](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/core/trust-manager.ts) and [trust-dialog selection](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/core/project-trust.ts).
- [Herdr 0.9.3 managed startup readiness](https://github.com/herdrdev/herdr/blob/7b116c05bfda646af39d2524c54e70c751f57ee8/src/terminal/state.rs) accepts the known agent's idle state after its startup settling interval.
- [Pi's interactive initialization](https://github.com/earendil-works/pi/blob/abe508e1b89912adde45528136c3221eb69acdd7/packages/coding-agent/src/modes/interactive/interactive-mode.ts) installs the input handler before initializing session extensions. Herdr's Pi integration reports the session from `session_start`, after the earlier trust decision.

## Fix and verification

For Pi workers, horch now requires the installed Herdr integration to report a Pi session in idle/done state before capturing the baseline and submitting the task. It shares the existing startup budget. If no session arrives, horch returns `start_failed`, leaves the pane open, and sends no task prompt. The controller can report the dialog or a missing integration. This intentionally makes `herdr integration install pi` a requirement for Pi workers; it does not change the other harnesses or authorize trust automatically.

The public [pi_startup.py](pi_startup.py) reproduces the difficult case with an empty project `.agents/skills` directory in an untrusted location. It verifies that the dialog remains, no prompt baseline or result exists, and Pi's trust decisions remain unchanged. It then starts a fresh worker with an explicit, run-local `--no-approve` setting, verifies real model work and result delivery, and confirms pane cleanup. `--no-approve` declines project resources; the test never accepts a trust dialog.

```bash
python3 e2e/pi_startup.py --worker glm --output /tmp/horch-pi-startup-evidence
```

Choose an authenticated Pi worker without a trust override and an output parent that Pi has not already trusted. The intentional blocked startup takes the normal 90-second budget. Evidence is sanitized; local diagnostic state and pane text remain in the printed run directory. No trust settings, detector manifests, or installed integration files are edited by this test.

The original [relocation failure](evidence/relocation-e2e.json) remains in the repository as historical evidence. Fresh receipts identify the fixed source separately. The guard is verified for the versions above; it is not a claim that every harness dialog is detected or that later upstream versions behave identically.
