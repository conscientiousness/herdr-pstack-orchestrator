# Workflow diagram

The overview near the top of the README shows delegation and the optional pstack implementation/review/fix loop. The controller owns dispatch, verification, and lead judgment. Workers execute in Herdr panes; every fix and review round starts fresh processes. A completed review task is not automatically a passing review.

Files:

- [workflow.json](workflow.json): editable Archify workflow source, with references to the skills at repository revision `2350959bfc1ed8c08764bfebb19b40884f602edb`.
- [workflow.html](workflow.html): standalone interactive viewer. Download it and open it locally; GitHub displays HTML source rather than running it. The source references use local repository paths, preserving this repository's SSH origin in the provenance.
- [workflow-light.svg](workflow-light.svg) and [workflow-dark.svg](workflow-dark.svg): canonical SVG exports used by the README's theme-aware picture.
- [workflow-verification.json](workflow-verification.json): sanitized validation summary and file hashes.

## Reproduce

Generated with [Archify](https://github.com/tt-a1i/archify) 3.0.1, pinned to upstream commit `bb990b17b886e83d633e273221615eb259a92c78`. Node.js 18+ and Chrome or Chromium are required to render, check, and export; readers need only a browser. This is documentation tooling and adds no runtime dependency to `horch`.

From this repository's root:

```bash
archify_run=".archify/workflow-$(date +%Y%m%d-%H%M%S)"
git clone https://github.com/tt-a1i/archify.git "$archify_run/tool"
git -C "$archify_run/tool" checkout bb990b17b886e83d633e273221615eb259a92c78

node "$archify_run/tool/archify/bin/archify.mjs" finalize workflow \
  assets/workflow.json assets/workflow.html \
  --repo-root . --quality showcase --out-dir "$archify_run/checks" --json

node assets/export-workflow.mjs "$archify_run/tool"

node "$archify_run/tool/archify/bin/archify.mjs" visual-check \
  assets/workflow.html --out-dir "$archify_run/captures" \
  --summary --require-provenance
```

Inspect both theme captures and the SVGs at README width after changing the source. The exporter uses Archify's own SVG serialization, including embedded fonts and theme colors; it does not redraw the graph. Keep local receipts and captures uncommitted because they contain machine-specific paths. Refresh the public hash summary when publishing regenerated assets.

The published diagram passed 9/9 showcase checks with no errors or warnings, strict artifact checks, and Archify's Chromium browser checks. Light and dark captures and the README SVG exports were also visually inspected. These checks cover the documentation artifact; they do not add to the runtime E2E results in the main README.

## Notices

The generated viewer contains code from Archify, copyright 2026 tt-a1i, based on Cocoon AI, copyright 2025. The complete [MIT notice](archify-LICENSE.txt) accompanies it. Embedded JetBrains Mono fonts retain their copyright and SIL Open Font License notice inside the HTML and SVG assets.
