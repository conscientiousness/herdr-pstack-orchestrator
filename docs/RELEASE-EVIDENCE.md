# Adoption evidence

The current release bar is a useful, reversible delegation workflow. Full
conformance with the [current playbook inventory](../e2e/PLAYBOOKS.md#complete-inventory) is a later milestone.

| User capability | Evidence | Boundary |
| --- | --- | --- |
| Install and remove | [Project removal PASS](../e2e/evidence/project-removal.json): 56 skills / 198 files installed exactly; all named bundle entries removed; unrelated skill and application files preserved; fresh Pi/Codex catalogs change from 57 entries to the one unrelated skill. | Local source installation and project removal. Empty directories/lock metadata remain; native Claude discovery and global removal are unverified. |
| Route work by role | [Practical delivery PASS](../e2e/evidence/practical-private-pr.json): actual implementation and independent review launches match the configured roles, models and arguments. Historical [Pi](../e2e/evidence/pi-controller.json) and [Codex](../e2e/evidence/controller-e2e.json) controller evidence is retained. | The controller reads the role map and chooses workers. `horch` takes an explicit worker name; it is not a global automatic router. |
| Replace a worker | [Live replacement PASS](../e2e/evidence/hot-swap.json): 42 checks, two models, correct independently replayed results; existing tasks survive definition replacement/removal and new dispatches observe the change. | Worker definitions affect new tasks. Skill loading, role selection and session reload remain controller duties. |
| Deliver a practical change | [Private-PR workflow PASS](../e2e/evidence/practical-private-pr.json): requirement, implementation, independent review of the exact commit, ready private child PR and Python 3.11/3.14 CI. Both workers delivered and closed; PRs stay unmerged. | Attended Codex controller with two configured Pi workers on Linux; ordinary functionality review, separate from original playbook conformance. |

The practical change adds a non-mutating invoice import preview. Twenty real
CLI observations pass 23 application checks; all 11 normal observations match
the frozen before pin. Coverage includes multi-file rounding, duplicate and late
input rejection, absent ledgers, existing pending bytes and the known error
after normal ledger replacement. The original seven-flow suite also passes.
The public [exact patch](../e2e/evidence/practical-import-preview.patch),
[before](../e2e/evidence/practical-before.json) and
[after](../e2e/evidence/practical-after.json) observations let others inspect and
replay the behavior. Private fixture identities and worker transcripts stay private.

Start with the single core skill and existing authenticated agent CLIs; no
application-code changes are needed to add orchestration. The application
patch above is the task delivered by workers, not an installation requirement.
See [installation and removal](../README.md#install) and the
[rerun procedure](../e2e/ADOPTION.md).

The selected-agent removal attempt is retained as [FAIL](../e2e/evidence/project-removal-agent-selection.json):
the command returned success but left shared canonical copies. Complete project
removal uses explicit bundle names and the default all-agent behavior, omitting
`-a`; unrelated skills are not selected.

Original failures remain in the [playbook inventory](../e2e/PLAYBOOKS.md).
No full-conformance rerun is a prerequisite for this release scope. Cloud
execution, durable wake and other missing runtime prerequisites are explicitly
**blocked** in [capability gaps](CAPABILITY-GAPS.md). No cloud provider or merge
authorization is assumed.
