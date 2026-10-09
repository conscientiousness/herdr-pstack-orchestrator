# Original pstack source and compatibility

This bundle tracks [Lauren Tan's original pstack](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack), version **0.15.15**, at commit `ccb5507cec1546dc88135c1139c811e6c59115ba`. The revision pins instructions and references; it does not establish runtime support for every playbook.

## Install

```bash
npx skills@1.7.1 add https://github.com/conscientiousness/herdr-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose your harnesses and project or global scope in the installer. Review existing skill-name conflicts before replacing user skills. The `skills/` URL installs the bundled catalog and both Herdr adapters, leaving out repository development skills. Selecting only `-s pstack-herdr` installs only that adapter; the installer does not resolve dependencies.

No separate source checkout is needed. The installer copies complete skill directories into standard sibling locations. Open a fresh session (or reload skills where supported), then invoke `poteto-mode`, `how`, `interrogate`, or standalone guidance such as `unslop`. Pi supports `/skill:poteto-mode`; other harnesses provide their own invocation UI. This layout is available on `main`; v0.2.0 used the earlier preparation procedure.

## Included skills and adaptations

The bundle contains **53 entries**: 48 pstack skills, the three referenced team-kit skills (`control-cli`, `control-ui`, `deslop`), and two Herdr adapters. Each upstream skill retains its resource tree and `UPSTREAM-LICENSE.txt`. The two original agent instructions and their license live in [agents/](agents/). The [bundle provenance](bundle.json) records source paths and hashes; [upstream.json](upstream.json) defines the pin, adaptations, and exclusions.

| Excluded original skill | Reason |
|---|---|
| `make-bot-ui` | Requires Cursor Routines and secret-request/webhook tools that this adapter does not provide. No included coding playbook requires it. |
| `poteto-help` | Cursor-specific setup and navigation depend on guides outside the skill tree. This adapter documents installation and entry points. |
| `setup-pstack` | Writes Cursor model rules. Its workflow references map to Herdr setup and `[roles]` in `workers.toml`. |

Generic guidance remains included: `unslop`, `bro`, technical writing, TypeScript guidance, and all 24 principles. Being independent of delegation is not a reason to exclude a useful skill.

Names are normalized to directory names and original descriptions are preserved. Cursor-only metadata and `disable-model-invocation` are omitted so harnesses can discover and select skills implicitly. Eighteen workflow/runtime entries prepend the Herdr mapping; all original bodies and supporting files are preserved. This includes `principle-guard-the-context-window`, whose instructions call for subagents. No plugin registration, hooks, or custom installer are required.

## Resource and runtime mapping

| Original path or setting | Installed equivalent |
|---|---|
| `pstack/skills/<name>/` and relative references | Sibling `<name>/` directory; resolve scripts to absolute paths before running them. |
| `pstack/agents/` | Bundled `pstack-herdr/references/agents/`; include the applicable instructions in a bounded worker brief. |
| `cursor-team-kit/skills/{control-cli,control-ui,deslop}/` | Sibling skill directories with their supporting files. |
| `interrogate/references/` | Installed review prompts and rubric; `horch` does not parse them. |
| Upstream role names and model defaults | `[roles]` and `[workers]` in `workers.toml` on every harness. |

Read [herdr-tools.md](herdr-tools.md) for tool substitutions and unavailable capabilities. Cursor modes, `/loop`, cloud execution, and missing MCP/app tools remain unavailable unless the environment supplies an equivalent. A workflow requiring one stops at that step. Scripts may require their own tools; bundling them does not install those dependencies.

The recorded original `how` run completed three explorer tasks and one explainer task through Herdr. Its [historical receipt](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/e2e/evidence/skill-discovery.json) used the earlier prepared package. Other original skills and `poteto-mode` playbooks remain **runtime unverified**. Native discovery and workflow execution are separate checks; native Claude Code discovery has not been measured. Earlier controller/review-loop receipts keep their original attribution in the [E2E guide](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/e2e/README.md#historical-pstack-source).

## Maintainer updates

The [daily upstream check](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/.github/workflows/upstream.yml) compares `pstack/` and `cursor-team-kit/` against the pin at 02:23 UTC and on manual dispatch. The README badge links to its summary and JSON artifact: `current` means no relevant tree changes, `update_required` means review is needed, and `error` means freshness is unknown. It never updates installed skills or the pin.

1. Inspect the target commit's changed instructions, roles, agents, resources, and required tools. Update the adapter mapping and `upstream.json` only where needed; review exclusions and the README version badge.
2. From this repository's root, regenerate into a new directory with a clean checkout at the reviewed revision:

   ```bash
   python3 scripts/prepare_pstack.py --source /path/to/cursor-plugins --output /tmp/pstack-next
   ```

   This is maintainer tooling, not an installation step. It rejects a dirty or differently pinned source and an existing output directory. Inspect the generated `skills/` tree, replace the bundled upstream directories and generated agent/provenance resources, and remove entries no longer selected. Preserve the two local adapters. CI checks that the committed bundle matches regeneration.
3. Verify affected installation or runtime behavior with the existing E2E procedures, then commit the reviewed bundle. Users receive it when they explicitly reinstall. Keep unexecuted workflows marked unverified and historical receipts unchanged.
