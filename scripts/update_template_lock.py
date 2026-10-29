#!/usr/bin/env python3
"""Guard template versions: a template whose content changed must bump ``template.version``.

Every ``template.yaml`` under ``depictio/projects/`` declares ``template.version``,
the template's own revision (semver, see "Template versioning" in
``depictio/projects/nf-core/RULES.md``). ``template_versions.lock.json`` records,
for each template, that version and a hash of the content it covers. A content
change with the same version is the mistake this catches: projects and dashboards
record the revision they came from, and two different bundles under one revision
make that record meaningless.

What a template's hash covers (docs, test data and ``.db_seeds`` are not part of
it, and neither are ``__pycache__`` files):

- its ``template.yaml``;
- its ``dashboards/**/*.yaml``;
- its own ``recipes/`` (a version override, ``<pipeline>/<version>/recipes/``) and the
  pipeline's shared ``<pipeline>/recipes/`` that every version of the pipeline reads.

Paths are hashed relative to the template, and line endings are normalised, so the
hash does not depend on where the checkout is or on the platform.

Usage::

    python scripts/update_template_lock.py --check    # fail on a change without a bump
    python scripts/update_template_lock.py --write    # refresh the lock after bumping

``--write`` refuses a template whose content changed under an unchanged version
(bump it first); ``--force`` records it anyway, for the rare change that does not
deserve a bump. ``--check`` with no lock file yet passes with a note, unless
``--require-lock`` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTS_DIR = REPO_ROOT / "depictio" / "projects"
LOCK_NAME = "template_versions.lock.json"
LOCK_SCHEMA = 1

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SKIPPED_PARTS = {"__pycache__", ".db_seeds", "node_modules"}
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

# What a finding means; ``--check`` fails on every one of them.
UNBUMPED = "unbumped"  # content changed, version did not
DOWNGRADED = "downgraded"  # version went down
STALE = "stale"  # version moved, lock not refreshed
NEW = "new"  # template not in the lock
REMOVED = "removed"  # lock entry whose template is gone
INVALID = "invalid"  # version is not X.Y.Z or unreadable


@dataclass(frozen=True)
class Finding:
    kind: str
    template: str
    message: str


def _skipped(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    return any(part in _SKIPPED_PARTS or part.endswith(".pyc") for part in parts)


def discover_templates(projects_dir: Path) -> dict[str, Path]:
    """``{id: directory}`` of every template under ``projects_dir``.

    The id is the directory relative to ``projects_dir`` (``nf-core/nascent/2.3.0``),
    which is also what each ``template_id`` says.
    """
    found: dict[str, Path] = {}
    for yaml_path in sorted(projects_dir.rglob("template.yaml")):
        if _skipped(yaml_path, projects_dir):
            continue
        template_dir = yaml_path.parent
        found["/".join(template_dir.relative_to(projects_dir).parts)] = template_dir
    return found


def read_version(template_dir: Path) -> str | None:
    """``template.version`` of the template in ``template_dir``; None when unreadable."""
    try:
        doc = yaml.load((template_dir / "template.yaml").read_text(encoding="utf-8"), _LOADER)
    except (OSError, yaml.YAMLError):
        return None
    block = doc.get("template") if isinstance(doc, dict) else None
    version = block.get("version") if isinstance(block, dict) else None
    return None if version is None else str(version).strip()


def _files_under(directory: Path, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and not _skipped(path, directory)
        and (suffixes is None or path.suffix in suffixes)
    )


def content_files(projects_dir: Path, template_dir: Path) -> list[tuple[str, Path]]:
    """``(label, path)`` of every file the template's hash covers, by label.

    The label is the path relative to the template; a shared recipe of the pipeline
    is labelled ``shared-recipes/<name>`` so that it cannot collide with a file of
    the template's own.
    """
    files: list[tuple[str, Path]] = [("template.yaml", template_dir / "template.yaml")]
    for path in _files_under(template_dir / "dashboards", (".yaml", ".yml")):
        files.append((path.relative_to(template_dir).as_posix(), path))
    for path in _files_under(template_dir / "recipes"):
        files.append((path.relative_to(template_dir).as_posix(), path))

    # <namespace>/<pipeline>/<version>[/...]: the pipeline's shared recipes.
    parts = template_dir.relative_to(projects_dir).parts
    if len(parts) >= 3:
        shared = projects_dir / parts[0] / parts[1] / "recipes"
        for path in _files_under(shared):
            files.append((f"shared-recipes/{path.relative_to(shared).as_posix()}", path))
    return sorted(files, key=lambda item: item[0])


def content_hash(projects_dir: Path, template_dir: Path) -> str:
    """sha256 over the template's content (see the module docstring)."""
    digest = hashlib.sha256()
    for label, path in content_files(projects_dir, template_dir):
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(f"{label}\n{len(data)}\n".encode())
        digest.update(data)
        digest.update(b"\n")
    return digest.hexdigest()


def compute(projects_dir: Path) -> dict[str, dict[str, str]]:
    """``{id: {version, content_hash}}`` of the tree as it is now."""
    current: dict[str, dict[str, str]] = {}
    for template_id, template_dir in discover_templates(projects_dir).items():
        current[template_id] = {
            "version": read_version(template_dir) or "",
            "content_hash": content_hash(projects_dir, template_dir),
        }
    return current


def load_lock(lock_path: Path) -> dict[str, dict[str, str]] | None:
    """The lock's templates, or None when there is no lock file."""
    if not lock_path.is_file():
        return None
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    templates = document.get("templates")
    if not isinstance(templates, dict):
        raise ValueError(f"{lock_path}: no 'templates' mapping")
    return templates


def write_lock(lock_path: Path, templates: dict[str, dict[str, str]]) -> None:
    document: dict[str, Any] = {
        "_comment": (
            "Generated by scripts/update_template_lock.py: the version and content hash "
            "of every template. Bump template.version, then run the script with --write."
        ),
        "schema": LOCK_SCHEMA,
        "templates": {key: templates[key] for key in sorted(templates)},
    }
    lock_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def compare(current: dict[str, dict[str, str]], locked: dict[str, dict[str, str]]) -> list[Finding]:
    """What differs between the tree and the lock, as findings."""
    findings: list[Finding] = []
    for template_id in sorted(current):
        now = current[template_id]
        version = now["version"]
        if not _SEMVER.match(version):
            findings.append(
                Finding(
                    INVALID,
                    template_id,
                    f"template.version {version!r} is not X.Y.Z (major.minor.patch)",
                )
            )
            continue
        before = locked.get(template_id)
        if before is None:
            findings.append(
                Finding(NEW, template_id, f"v{version} is not in the lock yet; refresh it")
            )
            continue
        changed = now["content_hash"] != before.get("content_hash")
        if version == before.get("version"):
            if changed:
                findings.append(
                    Finding(
                        UNBUMPED,
                        template_id,
                        f"content changed but template.version is still {version}; "
                        "bump it in its template.yaml",
                    )
                )
            continue
        locked_version = str(before.get("version", ""))
        if _SEMVER.match(locked_version) and _version_key(version) < _version_key(locked_version):
            findings.append(
                Finding(
                    DOWNGRADED,
                    template_id,
                    f"template.version went down: {locked_version} in the lock, {version} now",
                )
            )
            continue
        findings.append(
            Finding(
                STALE,
                template_id,
                f"template.version is {version}, the lock still has {locked_version}; "
                "refresh the lock",
            )
        )
    for template_id in sorted(set(locked) - set(current)):
        findings.append(
            Finding(REMOVED, template_id, "is in the lock but no longer exists; refresh the lock")
        )
    return findings


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def run_check(projects_dir: Path, lock_path: Path, require_lock: bool) -> int:
    locked = load_lock(lock_path)
    if locked is None:
        print(
            f"No template lock yet ({_relative(lock_path)}): nothing to compare. "
            "Create it with: python scripts/update_template_lock.py --write"
        )
        return 1 if require_lock else 0
    findings = compare(compute(projects_dir), locked)
    if not findings:
        print(f"Template versions match the lock ({len(locked)} templates).")
        return 0
    for finding in findings:
        print(f"{finding.template}: {finding.message}")
    print(
        "\nA template's content changed without a version bump, or the lock is out of date.\n"
        "Bump `template.version` in the template's template.yaml (major: a data collection, "
        "column or variable changed; minor: dashboards, figures or recipes changed; patch: "
        "text only), then run:\n"
        "    python scripts/update_template_lock.py --write"
    )
    return 1


def run_write(projects_dir: Path, lock_path: Path, force: bool) -> int:
    current = compute(projects_dir)
    locked = load_lock(lock_path) or {}
    findings = compare(current, locked)
    refused = [f for f in findings if f.kind in (UNBUMPED, DOWNGRADED, INVALID)]
    if refused and not force:
        for finding in refused:
            print(f"{finding.template}: {finding.message}")
        print("\nNothing written. Bump the versions above first (or pass --force).")
        return 1
    write_lock(lock_path, current)
    added = sum(1 for f in findings if f.kind == NEW)
    removed = sum(1 for f in findings if f.kind == REMOVED)
    moved = sum(1 for f in findings if f.kind == STALE)
    forced = len(refused)
    print(
        f"Wrote {_relative(lock_path)}: {len(current)} templates "
        f"({added} added, {moved} re-versioned, {removed} removed, {forced} forced)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on a change without a bump")
    mode.add_argument("--write", action="store_true", help="refresh the lock file")
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=DEFAULT_PROJECTS_DIR,
        help="directory holding the templates (default: depictio/projects)",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=None,
        help=f"lock file (default: <projects-dir>/{LOCK_NAME})",
    )
    parser.add_argument(
        "--require-lock", action="store_true", help="--check fails when there is no lock file"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="--write records a changed template whose version was not bumped",
    )
    args = parser.parse_args(argv)

    projects_dir = args.projects_dir.resolve()
    lock_path = (args.lock or projects_dir / LOCK_NAME).resolve()
    if args.check:
        return run_check(projects_dir, lock_path, args.require_lock)
    return run_write(projects_dir, lock_path, args.force)


if __name__ == "__main__":
    sys.exit(main())
