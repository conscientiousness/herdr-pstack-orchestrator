# Skill installation and discovery

## Sub-features

Install the committed bundle into a disposable project, remove the temporary installation source, and verify all files plus enabled, described entries in Pi and Codex's native catalogs.

## How to get to it (user POV)

Use the [single bundle installation command](../../../../skills/pstack-herdr/references/compatibility.md#install). No separate upstream checkout is required. The procedure below exercises the current local bundle without changing global skills.

## Driving it with existing scripts

Doctor: check `python3 --version`, `npx --version`, `pi --version`, and `codex --version`. No Herdr or model authentication is required. Run from the repository root with `repo` and `proof` from the verification skill's Launch section.

```bash
scratch=$(mktemp -d "${TMPDIR:-/tmp}/herdr-install-XXXXXXXX")
mkdir "$scratch/consumer"
cp -R skills "$scratch/source"
(cd "$scratch/consumer" && npx --yes skills@1.7.1 add \
  "$scratch/source" -s '*' -a codex -a claude-code -a pi -y) \
  > "$proof/install.log" 2>&1
```

Only after installation succeeds, delete this run's temporary source and query the installed bundle:

```bash
rm -rf "$scratch/source"
python3 e2e/skill_catalogs.py "$scratch/consumer" > "$proof/catalog-result.json"
cat "$proof/catalog-result.json"
```

Read the printed `evidence` path. Expect `verdict: pass`, the full installed file comparison and Claude entry checks to pass, both native catalogs to match the repository bundle, and no Codex catalog errors. The receipt includes installed hashes and differing paths; raw catalogs and stderr logs are beside it. Record the driver/source revision with it. This proves portable installation and discovery, not model execution or Claude Code runtime discovery. CI uses `--installation-only` when the harness CLIs are unavailable.

For a remote-install check, replace the local installer source with the documented GitHub `tree/<reviewed-commit>/skills` URL. The installer downloads it automatically. Run the same catalog command against the consumer and retain the exact source revision with the receipt.

After all owned catalog subprocesses have exited, remove only this run's `scratch` directory on success or failure. Reopen the receipt at the printed path after removal; it lives outside `scratch`. Keep `proof` and the catalog output.

## Gotchas

Do not install globally for this check. Never create `.agents/skills` in a shared temporary ancestor: even an empty directory previously triggered Pi trust dialogs for unrelated worktrees. The catalog script has no `--output` flag and retains isolated harness homes with its evidence. If installation fails, preserve its log and clean scratch without running the catalog check.
