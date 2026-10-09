# Original pstack source and compatibility

This adapter tracks [Lauren Tan's original pstack](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack), version **0.15.15**, at commit `ccb5507cec1546dc88135c1139c811e6c59115ba`. The revision pins instructions and references; it is not a claim that every playbook works on every harness.

## Install discoverable skills

The source pin and adapted-skill list live in [upstream.json](upstream.json). The source checkout alone does not register skills. Prepare a local package, then install it with the same skill installer used for this repository.

From a clone of this repository:

```bash
pstack_source="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-orchestrator/cursor-plugins"
pstack_package="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-orchestrator/pstack-package-0.15.15"
mkdir -p "$(dirname "$pstack_source")"
git clone https://github.com/cursor/plugins.git "$pstack_source"
git -C "$pstack_source" checkout --detach ccb5507cec1546dc88135c1139c811e6c59115ba
python3 skills/pstack-herdr/scripts/prepare.py --source "$pstack_source" --output "$pstack_package"
npx skills@1.7.1 add "$pstack_package" -g -a codex -a claude-code -a pi
```

Run clone and preparation into new directories. For an existing source checkout, inspect its revision and local changes first. Preparation refuses a different revision, a dirty checkout, or an existing output directory. Use the installer's selection screen to choose skills and inspect name conflicts before installation. Preserve existing user skills unless replacing them is intended. A skipped skill is not installed from this package; workflow source reads still use the pinned checkout. Omit `-g` for project installation, or select only the harnesses you use.

If both adapter skills were installed without cloning this repository, run `scripts/prepare.py` from the installed `pstack-herdr` directory instead. The companion `herdr-orchestrator` directory must be beside it.

Preparation includes all original pstack skills and the referenced `control-cli`, `control-ui`, and `deslop` skills from `cursor-team-kit`, plus the two Herdr skills. Each skill retains its supporting files and upstream license. Names are normalized to directory names, descriptions are preserved, and Cursor-only metadata and `disable-model-invocation` are omitted so harnesses can discover and select the skills. This enables implicit selection; it does not promise that a model always selects the right skill.

Pure guidance, including `unslop`, `technical-writing`, and 23 principles, keeps its original body. The explicitly listed workflow/runtime skills receive one Herdr preamble before their original body. This includes `principle-guard-the-context-window`, which calls for subagents. The mapping covers direct delegation, composed workflows, model setup, transcript paths, generated skill locations, and Cursor-specific capabilities. `setup-pstack` uses TOML setup in place of the original Cursor rule-writing procedure. The original checkout remains unchanged. `make-bot-ui` is discoverable but requires Cursor routine and secret-request tools that this adapter does not provide; stop at that missing capability rather than attempting its credential flow.

The generated package records the absolute source location. Keep the checkout available for agent definitions and cross-package references. Generate on the target machine after moving the checkout; do not distribute the generated package as a portable upstream mirror. Installed copies stay fixed until you explicitly prepare and install a reviewed update.

Open a fresh harness session (or reload skills where supported), then ask:

```text
Use poteto-mode for this goal: ...
Done means: ...
```

Or invoke `how`, `interrogate`, or `unslop` directly. Pi supports `/skill:poteto-mode`; other harnesses expose their own skill invocation UI. `pstack-herdr` remains an explicit entry for troubleshooting and source-path overrides. Custom Cursor modes, hooks, and cloud capabilities are not installed.

## Source contract

| Original path or setting | Adapter use |
|---|---|
| `pstack/.cursor-plugin/plugin.json` and checkout commit | Identify the source version. Plugin metadata does not control execution. |
| `pstack/skills/poteto-mode/SKILL.md`, `playbooks/`, and `principle-*` skills | Controller reads the selected workflow and applied principles. |
| `pstack/skills/<name>/SKILL.md` and its relative references | Resolve skill calls from one source tree. |
| `pstack/agents/` | Read named agent instructions into bounded worker briefs. |
| `pstack/skills/interrogate/references/{reviewer-prompt,rubric,code-quality-review,lead-judgment}.md` | Original reviewer inputs and controller synthesis. No rubric is copied or parsed by `horch`. |
| Upstream role names | Resolve through `[roles]` in `workers.toml` on every harness. |

Source files and role contracts have been inspected for this revision. Native Pi and Codex catalogs discovered all 56 package entries. A fresh Pi controller directly invoked original `how`, loaded this mapping, completed three explorer tasks and one explainer task, and closed all four workers. See the [discovery and routing receipt](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/e2e/evidence/skill-discovery.json). Other original skills and `poteto-mode` playbooks remain **runtime unverified**. Claude Code installation was checked; native Claude discovery was not measured. Existing controller and review-loop receipts retain their historical source attribution in the [E2E guide](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/e2e/README.md#historical-pstack-source); they do not establish compatibility with this original revision. The ordinary `herdr-orchestrator` runtime remains independent of pstack.

## Update when needed

The [daily upstream check](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/.github/workflows/upstream.yml) compares tracked `pstack/` and `cursor-team-kit/` trees against the pin. It runs at 02:23 UTC and on manual dispatch; scheduled runs require the workflow on the default branch. The README badge links to the run summary and JSON artifact. `current` means no relevant tree changes, `update_required` means changes need review, and `error` means freshness is unknown. It never updates installed skills or the pin.

1. Choose a target `cursor/plugins` commit and compare it with the pin above. Inspect changed entry points, role names, agent definitions, prompts, references, and required tools.
2. Preserve original files. Update only this adapter where those changes affect its mapping, plus `upstream.json`, its adapted-skill classification, the README version badge, and the installation command here. Generate into a new package directory and inspect installer conflicts before replacing installed copies. Pure skill-content changes need no Herdr rewrite.
3. Address problems actually encountered with the smallest necessary verification. Keep unexecuted workflows marked unverified; record the exact source revision with any real task used as evidence. Historical receipts keep their original versions and hashes.

Fetch and inspect the chosen commit before checking it out. Never use an unreviewed `git pull` as an implicit adapter upgrade. No background updater is installed.
