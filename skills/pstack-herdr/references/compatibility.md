# Original pstack source and compatibility

This adapter tracks [Lauren Tan's original pstack](https://github.com/cursor/plugins/tree/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack), version **0.15.15**, at commit `ccb5507cec1546dc88135c1139c811e6c59115ba`. The revision pins instructions and references; it is not a claim that every playbook works on every harness.

## Keep one source checkout

Install `herdr-orchestrator` and `pstack-herdr`, then retain the original repository:

```bash
pstack_source="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-orchestrator/cursor-plugins"
mkdir -p "$(dirname "$pstack_source")"
git clone https://github.com/cursor/plugins.git "$pstack_source"
git -C "$pstack_source" checkout --detach ccb5507cec1546dc88135c1139c811e6c59115ba
```

Run this once into a new directory. For an existing checkout, inspect its revision and local changes before updating it; do not reset or overwrite local work. A different location is fine when the prompt or project instructions supply its absolute path.

The full checkout keeps `pstack/skills/`, its playbooks, references and scripts, `pstack/agents/`, and `pstack/LICENSE` together. It also retains the separate `cursor-team-kit` skills referenced by pstack, with their own license. The adapter reads these files directly. No bulk skill rewrite, plugin installation, or automatic slash-command registration is required.

Start a task with:

```text
Use pstack-herdr to run original pstack's poteto-mode for this goal: ...
Done means: ...
```

For an individual skill, use `Use pstack-herdr with original pstack's interrogate to review this branch.` The same entry works for `unslop` and other named skills; read only their required dependencies. If another pstack integration is installed, enter through `pstack-herdr` and this checkout explicitly. Existing user configuration remains untouched.

## Source contract

| Original path or setting | Adapter use |
|---|---|
| `pstack/.cursor-plugin/plugin.json` and checkout commit | Identify the source version. Plugin metadata does not control execution. |
| `pstack/skills/poteto-mode/SKILL.md`, `playbooks/`, and `principle-*` skills | Controller reads the selected workflow and applied principles. |
| `pstack/skills/<name>/SKILL.md` and its relative references | Resolve skill calls from one source tree. |
| `pstack/agents/` | Read named agent instructions into bounded worker briefs. |
| `pstack/skills/interrogate/references/{reviewer-prompt,rubric,code-quality-review,lead-judgment}.md` | Original reviewer inputs and controller synthesis. No rubric is copied or parsed by `horch`. |
| Upstream role names | Resolve through `[roles]` in `workers.toml` on every harness. |

Source files and role contracts have been inspected for this revision. Live original-pstack playbooks are **unverified**. Existing controller and review-loop receipts retain their historical source attribution in the [E2E guide](https://github.com/conscientiousness/herdr-pstack-orchestrator/blob/main/e2e/README.md#historical-pstack-source); they do not establish compatibility with this original revision. The ordinary `herdr-orchestrator` runtime remains independent of pstack.

## Update when needed

1. Choose a target `cursor/plugins` commit and compare it with the pin above. Inspect changed entry points, role names, agent definitions, prompts, references, and required tools.
2. Preserve original files. Update only this adapter where those changes affect its mapping, plus the pin and installation command here. Pure skill-content changes need no Herdr rewrite.
3. Address problems actually encountered with the smallest necessary verification. Keep unexecuted workflows marked unverified; record the exact source revision with any real task used as evidence. Historical receipts keep their original versions and hashes.

Fetch and inspect the chosen commit before checking it out. Never use an unreviewed `git pull` as an implicit adapter upgrade. No background updater is installed.
