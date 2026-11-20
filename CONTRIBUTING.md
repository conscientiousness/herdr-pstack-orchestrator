# Contributing

Bug reports and fixes are welcome. Include reproduction steps, relevant
versions, and sanitized evidence. Do not publish credentials, private paths, or
full worker transcripts, and do not commit `handoff/`. Write code,
documentation, and commit messages in English.

Work on a feature branch, commit and push verified milestones, then open or
update a pull request. Direct pushes to `main`, enabling auto-merge, and merging
PRs outside the routine pstack sync exception require explicit user authorization.

A request to sync pstack authorizes the agent to merge a routine sync PR after
verification and passing checks, then publish from verified `main`. If the
upstream diff is substantial, such as a change to workflow steps, delegation,
or worker role behavior, summarize the changes and wait for explicit approval
to merge.

Use the [existing end-to-end drivers](e2e/README.md) to verify affected behavior
when needed. Preserve their evidence and describe what was actually verified.

Releases use `vYYYY.MM.DD.N`, with the UTC date and a daily index beginning at
`1`. Publish from verified `main` after an explicit release request or an
authorized pstack sync. The pinned pstack version is tracked separately.
