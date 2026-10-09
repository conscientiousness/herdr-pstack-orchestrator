# Skill installation and discovery

## Sub-features

Prepare the pinned original skill tree and adapters, install into a disposable project, and verify enabled, described entries in Pi and Codex's native catalogs.

## How to get to it (user POV)

Follow [source preparation and installation](../../../../skills/pstack-herdr/references/compatibility.md#install-discoverable-skills). Set `source_checkout` to the existing clean checkout at the revision in `skills/pstack-herdr/references/upstream.json`. Keep this checkout available throughout the run.

## Driving it with existing scripts

Doctor: `git -C "$source_checkout" status --porcelain` must be empty, and `git -C "$source_checkout" rev-parse HEAD` must match the manifest. Check `python3 --version`, `npx --version`, `pi --version`, and `codex --version`. Preparation also enforces the pin/version. No Herdr or model authentication is required.

```bash
scratch=$(mktemp -d "${TMPDIR:-/tmp}/herdr-install-XXXXXXXX")
mkdir "$scratch/consumer"
python3 skills/pstack-herdr/scripts/prepare.py \
  --source "$source_checkout" --output "$scratch/package" > "$proof/prepare.json"
```

Only after preparation succeeds:

```bash
(cd "$scratch/consumer" && npx --yes skills@1.7.1 add \
  "$scratch/package" -s '*' -a codex -a claude-code -a pi -y) \
  > "$proof/install.log" 2>&1
```

Only after installation succeeds:

```bash
python3 e2e/skill_catalogs.py "$scratch/consumer" > "$proof/catalog-result.json"
cat "$proof/catalog-result.json"
```

Read the printed `evidence` path. Expect `verdict: pass`, both catalog comparisons true, and no Codex catalog errors. The receipt includes installed entry hashes; raw catalogs and stderr logs are beside it. Record the driver/source revision with it. This proves discovery, not model execution or Claude Code runtime discovery.

After all owned catalog subprocesses have exited, remove only this run's `scratch` directory on success or failure. Reopen the receipt at the printed path after removal; it lives outside `scratch`. Keep `proof` and the catalog output.

## Gotchas

Do not install globally for this check. Never create `.agents/skills` in a shared temporary ancestor: even an empty directory previously triggered Pi trust dialogs for unrelated worktrees. The catalog script has no `--output` flag and retains isolated harness homes with its evidence. If installation fails, preserve its log and clean scratch without running the catalog check.
