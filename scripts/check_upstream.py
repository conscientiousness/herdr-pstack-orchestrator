#!/usr/bin/env python3
"""Read-only comparison of the pinned pstack bundle with upstream's default HEAD."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


PLUGINS = ("pstack", "cursor-team-kit")
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "skills/pstack-herdr/references/upstream.json"
)


def git(repo, *args):
    # Do not use credential helpers, global config, hooks, or interactive prompts.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    command = ["git", "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null"]
    if repo is not None:
        command += ["-C", str(repo)]
    result = subprocess.run(
        command + list(args), env=env, capture_output=True, timeout=180
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {detail}")
    return result.stdout.decode("utf-8", errors="surrogateescape")


def check(manifest_path, result):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository = manifest["repository"]
    pinned = manifest["revision"]
    version = manifest["version"]
    if not isinstance(repository, str) or not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("repository must be a public HTTPS GitHub repository URL")
    if not isinstance(pinned, str) or not re.fullmatch(r"[0-9a-f]{40}", pinned):
        raise ValueError("revision must be a full lowercase Git commit ID")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must be a nonempty string")
    result.update(repository=repository, pinned_revision=pinned, pinned_version=version)
    advertised = git(None, "ls-remote", "--symref", repository, "HEAD")
    branch = None
    upstream = None
    for line in advertised.splitlines():
        value, ref = line.split("\t", 1)
        if ref == "HEAD" and value.startswith("ref: refs/heads/"):
            branch = value.removeprefix("ref: ")
        elif ref == "HEAD" and re.fullmatch(r"[0-9a-f]{40}", value):
            upstream = value
    if branch is None or upstream is None:
        raise RuntimeError("remote did not advertise a default branch and HEAD commit")
    web_url = repository.removesuffix(".git")
    result.update(
        default_branch=branch.removeprefix("refs/heads/"),
        upstream_revision=upstream,
        compare_url=f"{web_url}/compare/{pinned}...{upstream}",
    )
    with tempfile.TemporaryDirectory(prefix="pstack-upstream-") as directory:
        repo = Path(directory)
        git(None, "init", "--quiet", "--template=", str(repo))
        for revision in dict.fromkeys((pinned, upstream)):
            git(repo, "fetch", "--quiet", "--no-tags", "--depth=1", repository, revision)
            actual = git(repo, "rev-parse", f"{revision}^{{commit}}").strip()
            if actual != revision:
                raise RuntimeError(f"fetched revision does not match {revision}")
        for plugin in PLUGINS:
            if git(repo, "cat-file", "-t", f"{pinned}:{plugin}").strip() != "tree":
                raise RuntimeError(f"{plugin}/ is not a tracked tree at {pinned}")
        metadata_path = "pstack/.cursor-plugin/plugin.json"
        if git(repo, "ls-tree", upstream, "--", metadata_path).strip():
            metadata = json.loads(git(repo, "show", f"{upstream}:{metadata_path}"))
            upstream_version = metadata["version"]
            if not isinstance(upstream_version, str) or not upstream_version.strip():
                raise ValueError("upstream pstack metadata has no valid version")
        else:
            # Removing a plugin or its metadata is a real update, not a git failure.
            upstream_version = "unavailable (pstack metadata removed)"
        # No rename detection: both paths remain visible when files move.
        names = git(
            repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-only", "-z", pinned, upstream, "--", *PLUGINS
        )
        changed = names.rstrip("\0").split("\0") if names else []
        result.update(
            upstream_version=upstream_version,
            changed_files=changed,
            status="update_required" if changed else "current",
        )


def summary(result):
    lines = ["# Pstack upstream", "", f"Status: **{result['status']}**", ""]
    for label, key in (
        ("Repository", "repository"),
        ("Pinned revision", "pinned_revision"),
        ("Pinned version", "pinned_version"),
        ("Default branch", "default_branch"),
        ("Upstream revision", "upstream_revision"),
        ("Upstream pstack version", "upstream_version"),
        ("Compare", "compare_url"),
    ):
        if key in result:
            lines.append(f"{label}: {result[key]}")
    if "error" in result:
        lines += ["", "Check failed; upstream freshness is unknown.", "", result["error"]]
    if "changed_files" in result:
        lines += ["", f"Changed tracked files ({len(result['changed_files'])}):"]
        lines += [f"- {json.dumps(name, ensure_ascii=True)}" for name in result["changed_files"]]
        if not result["changed_files"]:
            lines.append("None in pstack/ or cursor-team-kit/ (other plugins are ignored).")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, help="Write a JSON result, including failures")
    args = parser.parse_args()
    result = {"status": "error", "compared_paths": [f"{name}/" for name in PLUGINS]}
    try:
        check(args.manifest, result)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        result.update(status="error", error=str(exc))
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(summary(result))
    except OSError as exc:
        result.update(status="error", error=f"Could not publish check result: {exc}")
        # Preserve an error artifact if summary publication failed after JSON was written.
        if args.output:
            try:
                args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
    print(summary(result), end="")
    return {"current": 0, "update_required": 1, "error": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
