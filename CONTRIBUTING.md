# Contributing

Bug reports and fixes are welcome. Include reproduction steps, relevant
versions, and sanitized evidence. Do not publish credentials, private paths, or
full worker transcripts, and do not commit `handoff/`. Write code,
documentation, and commit messages in English.

Work on a feature branch, commit and push verified milestones, then open or
update a pull request. Merging into `main`, pushing changes directly there, or
enabling auto-merge requires an explicit user request.

Use the [existing end-to-end drivers](e2e/README.md) to verify affected behavior
when needed. Preserve their evidence and describe what was actually verified.

Releases use `vYYYY.MM.DD.N`, with the UTC date and a daily index beginning at
`1`. Publish from verified `main` after an explicit release request. The pinned
pstack version is tracked separately.
