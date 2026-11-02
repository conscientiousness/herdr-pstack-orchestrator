# Rerun the adoption evidence

This procedure uses the existing `horch` CLI, fixture generator and application
oracle. It adds no test runner. Original 23-playbook conformance is separate.
Existing [worker replacement](evidence/hot-swap.json) and controller receipts
are reused; rerun those only when changing their behavior.

## Replay the accepted application change without models or a forge

Run from the repository root with Python 3.11+ and Git:

```bash
repo=$(pwd)
proof=$(mktemp -d "${TMPDIR:-/tmp}/practical-preview-XXXXXXXX")
python3 e2e/forge_loop.py --prepare-fixture "$proof/fixture"
python3 - "$proof/oracle.py" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'e2e')
from design_loop import ORACLE
Path(sys.argv[1]).write_text(ORACLE)
PY
python3 "$proof/oracle.py" --repo "$proof/fixture" --output "$proof/before" --mode characterize
git -C "$proof/fixture" init -q
git -C "$proof/fixture" apply "$repo/e2e/evidence/practical-import-preview.patch"
python3 "$proof/oracle.py" --repo "$proof/fixture" --output "$proof/after" --mode feature
python3 - "$proof" <<'PY'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
before = json.loads((p / 'before/observation.json').read_text())
after = json.loads((p / 'after/observation.json').read_text())
actual = {row['label']: row for row in after['record']}
assert before['verdict'] == after['verdict'] == 'pass'
assert all(actual[row['label']] == row for row in before['record'])
assert before['missing_field_fixed'] == after['missing_field_fixed']
print('Normal observations preserved; retain both observation.json receipts.')
PY
```

Expect 11 baseline observations / 13 checks and 20 final observations / 23
checks, plus the original seven-flow suite. These are application conditions,
not 23 playbooks. This replay verifies behavior, not a fresh model review or PR.
The published patch has been applied to a freshly generated baseline and all
four resulting source hashes match the reviewed implementation exactly; no
additional CLI execution is counted for that patch verification.

## Rerun the practical model and private-PR workflow

Use an existing authorized private fixture repository with the pristine invoice
baseline, an explicit open parent PR and a separate owned feature branch. The
[fixture setup procedure](PLAYBOOKS.md#continuity-and-writable-workflows)
describes preparation. Keep the parent and child PR unmerged.

1. Run `python3 skills/herdr-orchestrator/scripts/horch.py detect`, verify the
   actual caller pane and select the implementation and independent review
   workers from the existing role map. Preserve models, permissions and auth.
2. Create an isolated fixture worktree. Extract the existing oracle as above
   and retain a `characterize` before pin. Do not apply the published patch:
   the implementation worker must produce its own change.
3. Fill the [implementation brief](evidence/practical-implementation-task.md)
   with actual absolute paths and the selected worker. Dispatch with:

   ```bash
   python3 skills/herdr-orchestrator/scripts/horch.py run <implementation-worker> --brief <absolute-brief> --cwd <fixture-worktree> --caller-pane <verified-pane>
   python3 skills/herdr-orchestrator/scripts/horch.py wait <implementation-task>
   ```

4. Require `done`, a valid completed result and closed pane. Read the delivered
   report/artifacts, inspect the source diff and independently run the existing
   `feature` oracle. Compare every normal record with the before pin. Only
   `cli.py` and `storage.py` may change. Commit the verified change with existing
   Git settings, then pin that exact revision.
5. Fill the [review brief](evidence/practical-review-task.md) with that revision
   and dispatch the configured independent reviewer through the same ordinary
   `run`/`wait` commands. Read its completed result and findings. Source must stay
   unchanged. Material findings require resolution; a pass does not depend on a
   greeting, tool-call spelling or original CommentSicko conformance.
6. Push only the owned branch. Use `gh pr create` with explicit repository,
   parent `--base`, owned `--head` and a reviewed `--body-file`. Read the PR back
   to verify ready/open state, exact reviewed head, base and file scope. Check
   CI and that merge/auto-merge remain disabled. Retain normalized behavior,
   review, source and PR evidence; publish no credentials or full transcripts.

The [recorded workflow](evidence/practical-private-pr.json) completes these
steps using a Codex conversation, one implementation worker and one independent
review worker. Its two private PR checks pass. It is not a claim of original
Feature or Opening-a-PR conformance.

## Verify complete project removal

In a disposable project, install the full bundle using the existing
[discovery procedure](../.agents/skills/verify-herdr-orchestrator/features/discovery.md).
Record its exact skill names. After installation, add one unrelated local skill
and keep a sentinel application file. Remove only the recorded bundle names:

```bash
npx skills@latest remove <bundle-skill-name-1> <bundle-skill-name-2> ... -y
```

Omit agent selection for complete removal of shared copies. Do not use `--all`
or `-s '*'` when unrelated skills are present. Check that each selected entry
and its links are absent under `.agents/skills`, `.claude/skills` and `.pi/skills`;
the unrelated skill and application bytes must remain unchanged. Query fresh
Pi/Codex catalogs using the existing `skill_catalogs.catalog` interface to verify
only the unrelated skill remains. The normal `skill_catalogs.py` entry point
expects an installed bundle and is not a post-removal checker.

The [fresh removal receipt](evidence/project-removal.json) retains 11 passing
checks. Its earlier [agent-selected attempt](evidence/project-removal-agent-selection.json)
remains failed. Raw catalog responses and installer logs stay private. Empty
directories and lock metadata can remain; live-session unload and global scope
are unverified.
