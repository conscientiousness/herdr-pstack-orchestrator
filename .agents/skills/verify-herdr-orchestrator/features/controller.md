# AI controller loop

## Sub-features

A real Codex controller reads the current orchestration skill and coordinates the six-task invoice scenario. The driver audits delivery-before-read ordering, wait handles, delegation, results, and cleanup independently.

## How to get to it (user POV)

Select `controller` from workers.toml with **harness = codex**, explicit model, effort, and permission arguments. A Pi worker using an OpenAI model is not a Codex controller. Select writer and two reviewers as in [worker review](workers.md). The driver needs two free worker slots plus its separate controller pane and access to the controller's local Codex transcript. Stop other dispatchers; isolated task stores cannot reserve the shared worker limit atomically.

## Driving it with existing scripts

```bash
python3 e2e/controller_loop.py --controller "$controller" \
  --writer "$writer" --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Read the printed receipt and require the fresh run's scenario, transcript audit, and cleanup to pass together. Retain local diagnostics; inspect and remove the printed worktree without removing evidence. The [audit contract](../../../../e2e/README.md) defines supported transcript forms and limitations.

## Gotchas

If there is no configured Codex worker, report the prerequisite gap; do not relabel a Pi worker or edit configuration to force the run. Missing/ambiguous transcript evidence fails the audit even if the fixture is correct. Post-run reanalysis is not a fresh integrated pass. This driver does not test an original pstack playbook or a Pi controller.
