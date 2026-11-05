# AI controller loop

## Sub-features

A real Codex controller reads the current orchestration skill and coordinates the six-task invoice scenario. The driver audits delivery-before-read ordering, wait handles, delegation, results, and cleanup independently.

## How to get to it (user POV)

Select `controller` from workers.toml with **harness = codex**, explicit model, effort, and permission arguments. A Pi worker using an OpenAI model is not a Codex controller. Select writer and two reviewers as in [worker review](workers.md). The driver needs two free worker slots in the caller's workspace plus its separate controller pane and access to the controller's local Codex transcript. Stop other dispatchers in that workspace; isolated task stores cannot reserve the shared workspace limit atomically.

## Driving it with existing scripts

```bash
python3 e2e/controller_loop.py --controller "$controller" \
  --writer "$writer" --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Read the printed receipt and require the fresh run's scenario, transcript audit, and cleanup to pass together. Retain local diagnostics; inspect and remove the printed worktree without removing evidence. The [audit contract](../../../../e2e/README.md) defines supported transcript forms and limitations.

## Gotchas

If there is no configured Codex worker, report the prerequisite gap; do not relabel a Pi worker or edit configuration to force the run. Missing/ambiguous transcript evidence fails the audit even if the fixture is correct. Post-run reanalysis is not a fresh integrated pass. This driver does not test an original pstack playbook or a Pi controller.

## Caller context preflight

For stale inherited workspace/tab metadata or configuration preflight changes:

```bash
python3 e2e/caller_context.py --controller-pane <verified-controller-pane> \
  --controller-text '<at least 16 characters unique to this visible conversation>' --output "$proof"
```

The driver uses live Herdr reads and `run`/`check` without creating panes or launching workers. Missing, blank or unavailable inherited pane claims must fail. Explicit confirmed pane/text with stale workspace/tab variables must reach configuration loading through the pane's live IDs. Configuration cases check legacy and described workers, non-string description rejection and multiple roles naming one worker; they stop at a missing brief or unknown worker. Require every receipt assertion and confirm no task state was allocated. Preserve the printed evidence directory. This checks preflight only; actual pane moves and stale live-pane ownership use the identity driver below.

## Caller identity

For workers placed in another live pane's workspace, including a controller whose tools run in a shared agent daemon, independently read the actual controller's process information and visible screen, then use:

```bash
python3 e2e/caller_identity.py --controller-pane <verified-controller-pane> \
  --controller-text '<at least 16 characters unique to this visible conversation>' --output "$proof"
```

This can run from the controller's shared tool daemon; the driver creates its own shell probe pane for process-tree cases. It creates and closes one scratch tab and one scratch workspace. Require `verdict: pass`, every check true and `cleanup_ok: true` in the printed artifact. Caller cases stop at an empty isolated configuration, without launching a worker or model.

Coverage includes stale inherited live panes, contradictory explicit claims, detached environment rejection, missing/short/incorrect screen evidence, a confirmed live controller claim, and moved-pane aliases. A controller session marker also exercises the case where tool ancestry belongs to another pane but explicit conversation evidence identifies the controller. Session-mismatch coverage requires live `agent_session`; otherwise the receipt records that case as unverified. Detached cases use `setsid`; they do not launch an actual Codex app-server. Do not send input to the user's controller to manufacture a match.

Agent controllers must supply both `--caller-pane` and `--caller-text` to `horch run` and `check`, including when their process ancestry reaches a pane. A shared daemon can retain that ancestry from a different conversation. Only ordinary shell automation without agent context uses ancestry alone. For actual worker rendering, use the [core viewer procedure](core.md#viewer-placement); caller preflight does not prove it.
