#!/usr/bin/env python3
"""Prepare discoverable pstack skills from the reviewed original checkout."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ADAPTER = Path(__file__).resolve().parents[1]


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def portable_skill(path, preamble):
    original = path.read_text()
    parts = original.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"Missing frontmatter: {path}")
    # Retain the original YAML scalar, including folded multiline descriptions.
    match = re.search(r"^description:.*(?:\n[ \t]+[^\n]*)*", parts[1], re.MULTILINE)
    if not match:
        raise ValueError(f"Missing description: {path}")
    header = f"---\nname: {path.parent.name}\n{match.group()}\n---"
    return header + ("\n\n" + preamble if preamble else "") + parts[2]


def prepare(source, output):
    manifest = json.loads((ADAPTER / "references/upstream.json").read_text())
    if git(source, "rev-parse", "HEAD") != manifest["revision"]:
        raise ValueError("Source revision differs from references/upstream.json")
    if git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Source checkout has local changes; preserve them and use a clean checkout")
    metadata = json.loads((source / "pstack/.cursor-plugin/plugin.json").read_text())
    if metadata["version"] != manifest["version"]:
        raise ValueError("Source version differs from references/upstream.json")
    if output.exists():
        raise ValueError("Output already exists; use a new directory and inspect before reinstalling")

    selected = list(sorted((source / "pstack/skills").glob("*/SKILL.md")))
    selected += [source / "cursor-team-kit/skills" / name / "SKILL.md"
                 for name in manifest["team_kit_skills"]]
    adapted = set(manifest["adapted_skills"])
    names = [path.parent.name for path in selected]
    if len(names) != len(set(names)) or not adapted <= set(names):
        raise ValueError("Duplicate skill name or missing adapted skill in source")

    entries = []
    for path in selected:
        name = path.parent.name
        preamble = ""
        if name in adapted:
            preamble = (
                "## Herdr runtime\n\n"
                "Before following the original instructions below, read the sibling "
                "[pstack-herdr](../pstack-herdr/SKILL.md) skill and its required mapping. "
                f"Use `{source}` as the pinned original source checkout. "
                f"Resolve upstream relative references from `{path}`, including links "
                "outside this installed skill directory. "
                "The Herdr mapping overrides upstream delegation tools, model defaults, "
                "setup files, and Cursor-specific capabilities. Delegate only through horch, "
                "using workers.toml. Keep workflow coordination in the controller. "
                "A bounded worker assignment remains bounded: do not start nested workers. "
                "User and project instructions take precedence. "
                "Check required capabilities before acting; keep unavailable steps unresolved. "
                "For setup-pstack, use the adapter's role setup instead of the original "
                "Cursor rule-writing procedure.\n"
            )
        entries.append((path, portable_skill(path, preamble), bool(preamble)))

    for name in ("herdr-orchestrator", "pstack-herdr"):
        if not (ADAPTER.parent / name / "SKILL.md").is_file():
            raise ValueError(f"Install the companion {name} skill beside this skill first")

    output.mkdir(parents=True)
    records = []
    for path, content, adapted_entry in entries:
        target = output / "skills" / path.parent.name
        shutil.copytree(path.parent, target)
        (target / "SKILL.md").write_text(content)
        group = path.relative_to(source).parts[0]
        shutil.copyfile(source / group / "LICENSE", target / "UPSTREAM-LICENSE.txt")
        records.append({"name": path.parent.name, "adapted": adapted_entry,
                        "source": path.relative_to(source).as_posix(),
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ("herdr-orchestrator", "pstack-herdr"):
        shutil.copytree(ADAPTER.parent / name, output / "skills" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    receipt = {"repository": manifest["repository"], "revision": manifest["revision"],
               "version": manifest["version"], "source_checkout": str(source),
               "skills": records}
    (output / "provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {"output": str(output), "upstream_skills": len(records),
            "adapted_skills": sum(row["adapted"] for row in records),
            "companion_skills": 2, "revision": manifest["revision"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Clean pinned cursor/plugins checkout")
    parser.add_argument("--output", type=Path, required=True, help="New local skill package directory")
    args = parser.parse_args()
    try:
        result = prepare(args.source.expanduser().resolve(), args.output.expanduser().resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
