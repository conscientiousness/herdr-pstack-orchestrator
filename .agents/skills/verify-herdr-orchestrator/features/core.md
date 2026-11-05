# Core lifecycle and viewers

## Preconditions

Use Python 3.11+ and installed official `herdr-core`. Check `herdr-core --version`, `herdr-core --skill` and the selected command's help; the installed `herdr-core schema` defines RPC facts. The driver creates its own `HC_SESSION`, XDG roots and deterministic interactive Pi fixture. It makes no model calls and changes no user configuration, trust or integration settings. Keep its artifact parent outside the checkout.

## Lifecycle and startup recovery

```bash
python3 e2e/core_backend.py --horch skills/herdr-orchestrator/scripts/horch.py \
  --output "$proof" --core-only
```

Read the printed `evidence.json`. Require the nonce-bound early-result, completed-turn delivery, missing/invalid result, native blocked state, cancellation, pinned endpoint, and cleanup assertions. Startup recovery must preserve a blocked terminal with `submission: not_sent`, then observe native idle through `wait --recheck` without promoting it to running or submitting input. Explicit `submit` must retain its original task and terminal; a duplicate must fail with `submission_unsafe`. Delivery requires the original task's valid result and completed turn.

`startup_ready` records readiness achieved before submission; `submission` records `not_sent`, `unknown` or `sent`; `execution_observed` records working observed; `native_status` is the latest program report. Successful `terminal.send` means submitted even when `started` is false. A transport error leaves submission unknown. Screen text is presentation evidence only and never determines lifecycle.

## Viewer placement

From inside Herdr with `HERDR_ENV=1`, a reachable `HERDR_SOCKET_PATH`, and the real `herdr` CLI:

```bash
python3 e2e/core_backend.py --horch skills/herdr-orchestrator/scripts/horch.py \
  --output "$proof" --viewer
```

This includes the lifecycle checks and creates an owned workspace without focusing it. Two workers launched from its ordinary shell controller must have separate attach panes in a shared `hcOrch` tab in that controller's live workspace, with `HERDR_ENV` removed. Require `task.json.controller_verification` and successful `viewer_verified` facts, plus the independent pane/tab and actual worker-output checks. It renames the owned viewer tab to invalidate placement, requires `verify-viewer` to fail while retaining workers, restores the label and requires fresh success. Require unchanged user focus, preflight rejection without worker allocation, delivery/cancellation cleanup, and owned workspace removal.

Before directing a user to a real worker window, run `horch verify-viewer <task-id>` afresh. It verifies the live controller process, workspace and separate tab, exact pinned attach argv, and recognizable screen output from the pinned core terminal. A returned viewer ID or old verification does not prove current visibility. Failure must report `viewer_verification_error`; retain the task and stop window-interaction instructions.

## Evidence and limits

Require `verdict: pass`, all receipt checks true, and successful cleanup, including any child core receipts. Reopen the receipt after cleanup. Preserve failed receipts and command diagnostics. These drivers prove deterministic lifecycle and real attach presentation, not real harness auth, model execution, actual trust decisions, legacy runtime, or whether the user has personally seen a tab. See the maintained [E2E documentation](../../../../e2e/README.md#verify-the-preferred-core-backend).

The implementation follows the official [Herdr stable documentation index](https://herdr.dev/llms.txt), [agent automation semantics](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/agent-automation.mdx), and [core schema](https://github.com/herdrdev/herdr-core/blob/master/schema/README.md). Do not upgrade or restart the user's core for verification; tests own their isolated runtime.
