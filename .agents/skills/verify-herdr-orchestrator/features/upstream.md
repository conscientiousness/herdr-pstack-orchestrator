# Upstream update detection

## Sub-features

Compare the pinned original pstack and required team-kit trees with upstream HEAD, recording exact revisions and changed paths without updating the installation.

## How to get to it (user POV)

The daily GitHub Actions monitor and README status badge use this check. Locally, require Git, Python, and network access to the manifest's public repository. Doctor: inspect `skills/pstack-herdr/references/upstream.json` and run `git --version`; network failures appear in the check's result.

## Driving it with existing scripts

```bash
python3 scripts/check_upstream.py --output "$proof/upstream.json"
```

Read the JSON as well as the exit code: 0 means current, 1 means updates need review, 2 means the check could not complete. An update is a valid detection result, not a driver failure. The script removes its temporary Git checkout; reopen the retained JSON after it exits. An optional `--manifest` can select an existing historical pin without editing the product manifest.

## Gotchas

This checks source drift, not runtime compatibility, and does not apply upgrades. Do not rewrite the pin or create an artificial old-pin scenario unless investigating update detection itself. See [update instructions](../../../../skills/pstack-herdr/references/compatibility.md) before acting on detected changes.
