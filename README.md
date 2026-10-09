<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.png">
  <img alt="A Border Collie controller centered behind its laptop, with four awake Herdr sheep workers in terminal panes on each side" src="assets/banner-light.png" width="100%">
</picture>

# herdr-pstack-orchestrator

[![Package validation](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml/badge.svg)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/validate.yml)
[![Pstack upstream](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml/badge.svg?branch=main)](https://github.com/conscientiousness/herdr-pstack-orchestrator/actions/workflows/upstream.yml)
[![Pstack source: 0.15.15](https://img.shields.io/badge/pstack_source-0.15.15-blue)](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Run a visible team of coding agents from one conversation.** One model implements, other models review, and you can inspect every worker in [Herdr](https://herdr.dev).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/workflow-light.svg">
  <img alt="Your controller briefs an implementation worker, verifies its diff, and dispatches independent reviewers. After all reviewers finish, the controller assesses findings. Accepted findings go to a fresh fix worker and a fresh review panel; no unresolved blockers leads to a verified result." src="assets/workflow-light.svg" width="100%">
</picture>

**Delegate → implement → review → fix → review again.** Every worker runs in a visible Herdr pane. The optional `pstack-herdr` skill adapts original pstack workflows, including the review loop shown above.

[Download the interactive diagram](https://github.com/conscientiousness/herdr-pstack-orchestrator/raw/refs/heads/main/assets/workflow.html) and open it in your browser · [Diagram source and reproduction](assets/workflow.md)

Two Agent Skills connect your controller to Pi, Codex CLI, and Claude Code. Each task gets a fresh process, a complete brief, and a structured result. The `horch` CLI uses Python's standard library; no server or API integration is required beyond Herdr and your existing agent subscriptions or provider accounts.

- **herdr-orchestrator** — the core skill. Delegates work to Pi, Codex CLI, and Claude Code workers through a small CLI (`horch`), with first-use setup, setup checks, task states, and problem handling.
- **pstack-herdr** — optional. Reads Lauren Tan's original pstack from a pinned source checkout and routes its delegated work through Herdr. Workers receive bounded tasks; the controller owns the workflow.

Workers open in tabs labeled `horch` (at most four panes per tab) without stealing focus. The controller creates separate git worktrees for writers and submits tasks through Herdr's agent API. Every follow-up starts a fresh worker.

## Requirements

- [Herdr](https://herdr.dev) 0.9.3 or later, with the controller agent running inside a Herdr pane (`HERDR_ENV=1`)
- Python 3.11 or later on Linux or macOS (standard library only, including POSIX file locks)
- Node.js/npm for `npx skills add`; a manual clone needs neither
- The harnesses you want as workers — `pi`, `codex`, and/or `claude` — installed and authenticated with your provider
- For Pi workers: Herdr's Pi integration (`herdr integration install pi`); `horch detect` reports its status, missing integration fails before worker allocation, and task submission waits for its session readiness signal
- For pstack workflows: both skills above and the [original source checkout](skills/pstack-herdr/references/compatibility.md#install-discoverable-skills)

## Install

```bash
npx skills add conscientiousness/herdr-pstack-orchestrator -s herdr-orchestrator
# optional, for original pstack workflows:
npx skills add conscientiousness/herdr-pstack-orchestrator -s pstack-herdr
```

Open a new agent session inside Herdr so it can discover the installed skills.

Or clone and run directly:

```bash
git clone https://github.com/conscientiousness/herdr-pstack-orchestrator.git
cd herdr-pstack-orchestrator
python3 skills/herdr-orchestrator/scripts/horch.py detect
```

To make the skills discoverable by your agent, symlink them into its skills directory — for example `~/.claude/skills/` for Claude Code or `~/.pi/agent/skills/` for Pi:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/herdr-orchestrator" ~/.claude/skills/herdr-orchestrator
```

`horch` is a plain script. For the manual examples below, define this shell function from the clone:

```bash
HORCH_SCRIPT="$PWD/skills/herdr-orchestrator/scripts/horch.py"
horch() { python3 "$HORCH_SCRIPT" "$@"; }
```

Commands: `run`, `wait`, `list`, `close`, `detect` (installed harnesses and versions), and `check` (starts each worker once on a tiny task and reports whether it works). Operational output is JSON; errors use `{"error": ..., "message": ...}` and exit status 1. CLI help and argument errors use normal argparse output.

## Quickstart

Paste this to your agent inside Herdr:

```text
Set up the herdr-orchestrator skill with me: run horch detect, ask me which
workers to define (harness, model, effort, and permission flags), write my
workers.toml, then run horch check and show me which workers are ok.
```

Once setup is done, delegation is one sentence:

```text
Use herdr-orchestrator to fix the login redirect loop in this repository:
create a git worktree, delegate the fix to a worker, and have a worker on a
different model review the diff before you report back.
```

## Configuration

`horch` reads `~/.config/herdr-orchestrator/workers.toml` (`$XDG_CONFIG_HOME` is respected). Copy the complete example from this repository and edit it:

```bash
mkdir -p ~/.config/herdr-orchestrator
cp -i skills/herdr-orchestrator/references/workers.example.toml \
   ~/.config/herdr-orchestrator/workers.toml
```

The example defines one worker per harness:

| Worker | Harness | Model and effort |
|---|---|---|
| `glm` | Pi | provider `zai`, `glm-5.3-flash`, thinking `max` |
| `gpt` | Codex | `gpt-6.1-sol`, reasoning `medium` |
| `haiku` | Claude Code | `haiku`, effort `max` |

Model names are examples — what you can use depends on the providers you authenticated. Pi lists its models with `pi --list-models`.

**Permissions.** The controller never answers worker dialogs. Choose each worker's permission flags deliberately. These modes completed real tasks without prompts on 2026-10-09:

| Harness | Arguments |
|---|---|
| Pi | no per-tool approval by default; project-trust dialogs still apply |
| Codex | `-s workspace-write -a on-request -c 'approvals_reviewer="auto_review"'` |
| Codex | `-s workspace-write -a never` (writes in its cwd and the task directory) |
| Claude Code | `--permission-mode auto` |
| Claude Code | `--permission-mode acceptEdits` (shell commands outside the project can still prompt) |

Automatic approval can deny an action; denial handling is unverified (see [Verification](#verification)). The first run in a new location can also stop at trust dialogs — see [Troubleshooting](#troubleshooting).

Other keys: `max_active_workers` (default 4), `notify_after_minutes` (default 180), and the optional `[roles]` table for pstack (below). Task directories live under `~/.local/state/herdr-orchestrator/tasks/` (`$XDG_STATE_HOME` is respected) and keep every brief and result until you delete them. Processes sharing a task store serialize worker startup to enforce the limit; workers then execute concurrently.

## How delegation works

The controller chooses a configured Pi, Codex CLI, or Claude Code worker, sends a complete brief with `horch run`, and waits for its structured result with `horch wait`. It verifies the outcome before reporting back.

A manual example: first create a separate checkout and branch for the writer. A worktree separates edits; it is not a security sandbox.

```bash
git -C ~/src/myapp worktree add ~/src/myapp-fix-login -b fix/login
```

Then a brief that stands alone — the worker sees none of your conversation. State the goal, what to read first, what it may change, how to verify, and which files to write:

```markdown
# Fix the login redirect loop

After sign-in the app bounces back to /login instead of the page the user
came from.

- Read src/auth/session.ts and src/routes/login.ts first.
- Change only files under src/auth/ and src/routes/.
- Verify with npm run e2e -- login, including a return URL and an expired session.
- Commit on the current branch with a message explaining the cause.
- Write report.md next to result.json: cause, fix, verification output.
```

`horch` appends the worker rules and the `result.json` format to every brief, so do not add them yourself.

Start the worker and wait:

```bash
horch run gpt --brief /tmp/fix-login.md --cwd ~/src/myapp-fix-login
# prints JSON with task_id, pane_id, and state

horch wait t-0a1b2c  # use the task_id returned by run
```

`horch wait` has no default time cap. Prefer a background command or yielded shell session so the controller can post updates while the same wait process runs; use completion notifications when the harness provides them. With a blocking-only shell, use `--max-seconds 300` and a tool timeout above 300 seconds, or a shorter cap required by the runtime or update cadence. A wait cap never stops the worker. After each state change, handle the result and wait again for the remaining running tasks. When a task is `done`, read `result.json` and its listed files (paths are relative to the result directory). To run tasks in parallel, make one `horch run` per task first, then wait on all the IDs.

## Task states and result status

`horch wait` and `horch list` report task states:

| State | Meaning |
|---|---|
| `running` | The worker is working. |
| `long_running` | Passed `notify_after_minutes`; reported once. |
| `done` | Turn ended with a valid `result.json`; check `closed` and `message` for pane cleanup. |
| `blocked`, `start_failed`, `not_started`, `exited`, `result_missing`, `result_invalid` | Problems; the pane stays open for inspection. |

`done` means the worker's turn ended and a valid result was delivered. It is retained for compatibility with v0.1.0 clients and stored task records. Read the separate `status` inside `result.json`:

| Task state | Result status | Next action |
|---|---|---|
| `done` | `completed` | Verify the worker's claimed success and any review verdict. |
| `done` | `failed` | Inspect and report the worker's failure. |
| `done` | `blocked` | Relay the worker's question, then start a fresh task with the answer. |

Read the diff, run the tests, or request an independent review before accepting the work. A delivered review can still find blocking defects.

Wait for `state: "done"` before consuming a result. A worker can write files while its turn is still running, so `horch wait` withholds result summaries, files, and questions until completion. Closing a running worker cancels it; it does not complete the task or satisfy a review gate.

## Optional: original pstack through Herdr

This adapter tracks [original pstack](https://github.com/cursor/plugins/tree/main/pstack) directly. Keep its full source checkout at the revision in the [installation and update instructions](skills/pstack-herdr/references/compatibility.md). Skills, references, agent definitions, and licenses stay in that checkout, unchanged. The preparation command produces a discoverable skill package from that checkout. Install it into your harness so names and descriptions are available during skill selection. Workflow entries load the Herdr mapping automatically; pure guidance keeps its original body.

After [preparing and installing the package](skills/pstack-herdr/references/compatibility.md#install-discoverable-skills), start a fresh session and invoke a skill directly:

```text
Use poteto-mode for this goal: ...
Done means: ...
```

For a specific skill, ask `Use interrogate to review this branch.` Independent skills such as `unslop` are also discoverable. Installing only the two Herdr skills does not install the original skill catalog. Existing skills with the same names need an explicit installation choice. The generated package normalizes discovery metadata, including removing upstream explicit-only flags; Cursor modes and hooks remain unsupported.

All three controller harnesses read roles directly from `workers.toml`. Configure only the roles the chosen workflow needs. For the implementation/review loop:

```toml
[roles]
"feature, refactoring" = "gpt"
"interrogate reviewers" = ["glm", "haiku"]
```

A single role names one worker; a panel role lists one worker per review task. The `arena cross-judge pool` is a selection pool, from which the controller chooses one worker. Other workflows use their original role names, such as `how explorer` or `architect runners`. There is no separate model sheet to maintain.

The controller dispatches an implementation worker in a worktree, sends the same upstream review brief to every reviewer, assesses the delivered reports, and assigns accepted fixes and subsequent reviews to fresh workers. See the [entry point and review instructions](skills/pstack-herdr/SKILL.md). Read-only reviews are enforced by the brief and chosen harness permissions, not by a separate `horch` sandbox.

The README source badge identifies the pinned version, not a release of this repository. The upstream CI badge checks daily at 02:23 UTC for changes in `pstack/` or `cursor-team-kit/`. A failed check means an update needs review or the check failed; open its summary for the distinction. Detection never upgrades installed skills automatically.

Native Pi and Codex discovery passed for all 56 package entries. A fresh Pi controller directly invoked original `how` and completed three explorer tasks plus one explainer task through Herdr, with delivery-before-read and cleanup confirmed in the [receipt](e2e/evidence/skill-discovery.json). Other original skills and `poteto-mode` playbooks remain **runtime unverified**; discovery alone does not prove a workflow works. Earlier review-loop results retain their [historical source attribution](e2e/README.md#historical-pstack-source). Cursor modes, `/loop`, cloud execution, and unavailable MCP or app-driving tools are not supplied by this adapter; it reports a missing required capability instead of claiming the workflow finished.

## Verification

Measured during development on 2026-10-09 with end-to-end behavior tests:

| Area | Result |
|---|---|
| `horch` core behavior tests | 65/65 passed again on the release candidate, across all three worker harnesses |
| First-use setup flow | 14/14 passed again on the release candidate |
| Parallel starts, cross-workspace cleanup, repeated waits, notification | 8/8 passed |
| Invalid results, explicit recheck, concurrent wait/close, corrupt records | 13/13 passed |
| Early result delivery, final completion, cancellation | 10/10 passed on the release CLI |
| Release-era public six-task review-loop driver | 27/27 passed in 7m 19s, including two failing first reviews and two passing final reviews |
| Pi integration preflight | 15/15 passed; known missing integration rejected in about 0.05 seconds before allocation |
| Pi startup dialog guard | 11/11 passed; trust dialog and decisions remain untouched before task submission |
| Fresh six-task loop after startup fix | 27/27 passed in 7m 11s, using the relocated public driver |
| Codex controller, current skill and final driver | 47/47 passed in 12m 17s, including the integrated wait/delivery audit and six completed, closed tasks |
| Earlier Codex-controller runs | Both completed six tasks and passed 46 scenario/source/cleanup checks; their corrected transcript audits were separate reanalysis |
| Claude Code controller, skill end-to-end | 19/19 passed |
| Historical Claude Code controller, pstack review loop | 21/21 passed — the first reviewer panel FAILed the revision, and a fresh second panel PASSed it |
| Historical Codex controller, pstack review loop | 10/10 passed; direct TOML roles, six fresh workers, no native subagents |
| Codex and Pi as workers | Starting and completing real tasks verified |
| Permission-denial handling | Unverified |
| Completions longer than 30 minutes | Unverified |
| Original pstack skill discovery | All 56 package entries discovered in native Pi and Codex catalogs; Claude installation links checked |
| Original pstack 0.15.15 `how` | Fresh Pi controller loaded the installed skill and mapping; 4/4 delegated tasks delivered and closed |
| Other original pstack 0.15.15 workflows | Runtime unverified |
| Historical Pi controller, pstack review loop | 10/10 passed on the release CLI; direct TOML roles, six fresh workers, no native subagents |

Model names throughout are examples; availability depends on your provider.

The [E2E guide](e2e/README.md) explains the evidence and the mechanisms it covers. Tests and evidence live outside the installed skills. The [verification summary](e2e/evidence/verification.json) keeps versions, source hashes, and historical attribution: core/setup runs predate the release's final delivery gate. The later `agent_prompt_stalled` failures were traced to a Pi trust dialog misclassified as idle by Herdr; see the [reproduction and fix](e2e/startup-findings.md). The new guard passed its [real startup test](e2e/evidence/pi-startup.json), and the relocated driver has a [fresh full-loop pass](e2e/evidence/startup-fixed-review.json). The [original release receipt](e2e/evidence/review-e2e.json) and failed relocation receipt remain unchanged. Live runtime tests used Linux; macOS has not been measured.

The [fresh integrated controller receipt](e2e/evidence/controller-e2e.json) records a passing invocation of the final driver: six fresh tasks, two initial FAIL reviews, two final PASS reviews, committed CLI verification, and confirmed cleanup. Its transcript audit passed in the same invocation, with six yielded waits, 23 process-handle resumes, and no short wait caps. Source and configuration hashes stayed unchanged throughout the run. Earlier auditor failures, the GLM stall, the CommandCode HTTP 400 attempt, and their separate reanalyses remain in the [evidence history](e2e/README.md#evidence-and-source-attribution). The [historical Pi-controller receipt](e2e/evidence/pi-controller.json) is explicitly attributed to the v0.1.0 development line.

### Reproduce the review loop

From a clone inside Herdr, select one configured writer and two reviewers with different model definitions:

```bash
python3 e2e/review_loop.py \
  --writer gpt --reviewer glm --reviewer haiku \
  --repo . --output /tmp/horch-evidence
```

This makes real model calls and requires two free worker slots. It creates a detached worktree, plants two independent invoice defects, verifies a scoped implementation, requires both reviewers to find the remaining defect, then verifies a fresh fix and two fresh passing reviews. Additional CLI cases cover fractional discounts, full discounts, zero quantities, and single-line invoices.

The driver retains the worktree and writes `evidence.json` with task IDs, source hashes, revision IDs, CLI observations, and assertions. It cleans up only its own worker panes, including after failure. Reports stay in your local task store; transcripts are not copied into the evidence. Remove the retained checkout with `git worktree remove <printed-worktree-path>` when finished.

This driver controls `horch` directly. The [controller-level driver](e2e/README.md) instead starts a real Codex controller, asks it to follow the skill, and audits its tool transcript and actual work. GitHub Actions checks Python compatibility, configuration parsing, and installation into all three agents; real model E2Es run locally because they need Herdr and authenticated providers.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `{"error": "not_in_herdr"}` | `horch` runs only inside a Herdr pane (`HERDR_ENV=1`). |
| `{"error": "config_invalid"}` | `workers.toml` is missing or invalid at the config path; copy `workers.example.toml`. |
| `worker_limit` on `horch run` | `max_active_workers` tasks still have open panes; close finished or problem tasks with `horch close <task-id>`. |
| Worker stops at a dialog (`blocked` / `start_failed`) | Trust dialogs are cleared once per location, by you in the pane: Codex asks "Trust this folder?" for each new git repository, and Claude Code asks to trust folders and about external `CLAUDE.md` imports. The controller never answers them. Afterwards run `horch close <task-id>` and start a new task. |
| Pi `start_failed`: no ready session | Install `herdr integration install pi` and inspect the pane. Pi 1.1.0 can ask for project trust even for an empty ancestor `.agents/skills` directory. Herdr 0.9.3 may report that dialog as idle; horch withholds task input until the integration reports a ready session. Resolve trust yourself, close the old task, then start fresh. |
| Claude Code prompts when reading config or task directories | Add `~/.config/herdr-orchestrator` and `~/.local/state/herdr-orchestrator` to `permissions.additionalDirectories` in your Claude Code settings. |
| `result_missing` / `result_invalid` | Inspect the problem pane and task files. If the user wants a retry, close the old task and start a new one. |
| `not_started` | Herdr did not observe the prompt acknowledgement. The task may still be running. Inspect it before deciding; `horch wait <task-id> --recheck` checks the existing task again without resending anything. |
| `done` with `closed: false` | Read `message`, then retry cleanup with `horch close <task-id>`. The task still consumes a slot until closure is confirmed. |
| A task runs very long | `horch` has no timeout; you are notified once after `notify_after_minutes`. Keep waiting, or close the task and start a fresh one with a narrower brief. |

## Contributing

Issues and pull requests are welcome.

- **Bug reports**: include the error code, reproduction steps, and harness versions. Remove credentials, private paths, proprietary briefs, and full worker transcripts before posting.
- **Verification**: use real end-to-end behavior tests for complex changes. Include a reproducible scenario and sanitized evidence with your pull request. Start with the [public driver](e2e/review_loop.py); no unit test suite is required.
- **Scope**: the product is two skills, the CLI, and its reproducible E2E driver. Keep changes small and behavior-focused. Write code, documentation, and commit messages in English.

## Credits

- [Herdr](https://herdr.dev) — the terminal multiplexer for coding agents that hosts every worker pane; `horch` drives its CLI.
- The banner uses Herdr's ram icon as its visual reference. See the [generation prompt and provenance](assets/banner-prompt.md).
- The workflow diagram is generated with [Archify](https://github.com/tt-a1i/archify). Its standalone viewer includes Archify's MIT-licensed code; see [diagram provenance and notices](assets/workflow.md).
- [pstack](https://github.com/cursor/plugins/tree/main/pstack) — Lauren Tan's (poteto) original workflow skills, under MIT. This repository provides an independent Herdr adapter and reads original source files from a pinned checkout.

## License

[MIT](LICENSE). Copyright 2026 conscientiousness and contributors.
