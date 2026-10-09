# Pi integration and startup

## Sub-features

Reject missing integration before allocating workers; preserve a real project-trust dialog without sending it a task prompt. These are separate drivers for previously reproduced failures.

## How to get to it (user POV)

Use authenticated Pi workers with Herdr's Pi integration installed. Run the shared Doctor and read [the startup investigation](../../../../e2e/startup-findings.md) when diagnosing a trust dialog.

## Driving it with existing scripts

For missing-integration preflight, select two Pi workers (`pi_a`, `pi_b`) and one **non-Pi** worker (`other`) from configuration. Require two free slots, an existing trusted checkout, and no other dispatcher:

```bash
python3 e2e/pi_preflight.py --pi "$pi_a" --pi "$pi_b" --other "$other" \
  --cwd "$repo" --output "$proof"
```

The script uses an isolated empty `PI_CODING_AGENT_DIR`, without uninstalling the user's integration. A pass requires immediate rejection before allocation, successful non-Pi and normal Pi tasks, unchanged sources/configuration/integration, and pane cleanup. If every configured worker is Pi, this scenario is blocked by the missing non-Pi prerequisite.

For the reproduced trust-dialog issue only, select `pi_worker` without `--approve`/`--no-approve` overrides; require Pi 1.1.0+, one free slot, and an output parent Pi has not already trusted:

```bash
python3 e2e/pi_startup.py --worker "$pi_worker" --output "$proof"
```

Expect the intentional startup failure to take the normal 90-second budget. The driver then uses a fresh, run-local `--no-approve` worker to decline project resources and verify delivery. Require the receipt's preserved-dialog, unchanged-trust, delivery, and owned-pane cleanup assertions. It never accepts the dialog.

## Gotchas

Both drivers make real model calls and print a child `evidence.json` path beneath `proof`; keep its diagnostics private. They clean their panes, retaining local fixture/state files as evidence. Do not change user trust or integration settings to manufacture a pass. Do not run both scenarios merely to expand coverage.
