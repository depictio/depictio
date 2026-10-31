#!/usr/bin/env python3
"""Guard template and catalog versions: content that changed must bump its version.

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
  pipeline's shared ``<pipeline>/recipes/`` that every version of the pipeline reads;
- the version of every catalog module it consumes: a ``recipe:`` that resolves in
  ``depictio/catalog/<module>/``, a dashboard ``use: <module>/...`` or
  ``catalog_source.toolId``, and a recipe importing ``depictio.catalog.<module>``.

Catalog modules are versioned the same way. Each ``depictio/catalog/<module>/module.yaml``
declares ``version`` (semver), and ``depictio/catalog/catalog_versions.lock.json``
records it with a hash of the module's ``.py`` and ``.yaml`` files (fixtures are not
part of it). A module edited without a bump fails; a bumped module moves the hash of
every template that consumes it, which then has to bump in turn.

Paths are hashed relative to the template or module, and line endings are normalised,
so the hash does not depend on where the checkout is or on the platform.

Usage::

    python scripts/update_template_lock.py --check    # fail on a change without a bump
    python scripts/update_template_lock.py --write    # refresh the locks after bumping

``--write`` refuses a template or module whose content changed under an unchanged
version (bump it first); ``--force`` records it anyway, for the rare change that does
not deserve a bump. ``--check`` with no lock file yet passes with a note, unless
``--require-lock`` is given. The catalog is looked up next to the projects directory
(``<projects-dir>/../catalog``) unless ``--catalog-dir`` says otherwise.
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
CATALOG_LOCK_NAME = "catalog_versions.lock.json"
MODULE_FILE = "module.yaml"
LOCK_SCHEMA = 1

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SKIPPED_PARTS = {"__pycache__", ".db_seeds", "node_modules"}
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_MODULE_SUFFIXES = (".py", ".yaml", ".yml")
_CATALOG_IMPORT = re.compile(r"\bdepictio\.catalog\.([A-Za-z0-9_]+)")

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


@dataclass(frozen=True)
class _Lock:
    """One lock file: what it versions and how its messages name the version."""

    what: str  # "template" or "catalog module"
    key: str  # top-level mapping in the lock file
    field: str
    where: str
    bump_hint: str


_TEMPLATES = _Lock(
    "template",
    "templates",
    "template.version",
    "its template.yaml",
    "Bump `template.version` in the template's template.yaml (major: a data collection, "
    "column or variable changed; minor: dashboards, figures or recipes changed; patch: "
    "text only)",
)
_MODULES = _Lock(
    "catalog module",
    "modules",
    "version",
    "its module.yaml",
    "Bump `version` in the module's module.yaml (major: an output column changed; minor: "
    "a reader, recipe or render changed; patch: text only), then bump every template "
    "that consumes it",
)


def _skipped(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    return any(part in _SKIPPED_PARTS or part.endswith(".pyc") for part in parts)


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), _LOADER)
    except (OSError, yaml.YAMLError):
        return None


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


def discover_modules(catalog_dir: Path | None) -> dict[str, Path]:
    """``{id: directory}`` of every catalog module (a folder holding ``module.yaml``)."""
    if catalog_dir is None or not catalog_dir.is_dir():
        return {}
    return {
        path.name: path
        for path in sorted(catalog_dir.iterdir())
        if path.is_dir() and not path.name.startswith((".", "_")) and (path / MODULE_FILE).is_file()
    }


def read_version(template_dir: Path) -> str | None:
    """``template.version`` of the template in ``template_dir``; None when unreadable."""
    doc = _load_yaml(template_dir / "template.yaml")
    block = doc.get("template") if isinstance(doc, dict) else None
    version = block.get("version") if isinstance(block, dict) else None
    return None if version is None else str(version).strip()


def read_module_version(module_dir: Path) -> str | None:
    """``version`` of the catalog module in ``module_dir``; None when unreadable."""
    doc = _load_yaml(module_dir / MODULE_FILE)
    version = doc.get("version") if isinstance(doc, dict) else None
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


def _walk(node: Any, key: str) -> list[Any]:
    """Every value stored under ``key`` anywhere in a parsed YAML document."""
    found: list[Any] = []
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for k, v in item.items():
                if k == key:
                    found.append(v)
                stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)
    return found


def catalog_dependencies(
    projects_dir: Path, template_dir: Path, modules: dict[str, Path]
) -> list[str]:
    """Ids of the catalog modules the template consumes, sorted.

    A ``recipe: <module>/<name>`` counts when it resolves in the catalog, as
    ``depictio.recipes.resolve_recipe_path`` resolves it (a pipeline-qualified
    ``nf-core/<pipeline>/<name>`` never does).
    """
    if not modules:
        return []
    used: set[str] = set()
    for ref in _walk(_load_yaml(template_dir / "template.yaml"), "recipe"):
        if isinstance(ref, str) and ref.count("/") == 1:
            module, name = ref.split("/")
            if module in modules and (modules[module] / name).is_file():
                used.add(module)
    for label, path in content_files(projects_dir, template_dir):
        if label == "template.yaml":
            continue
        if path.suffix in (".yaml", ".yml"):
            doc = _load_yaml(path)
            for ref in _walk(doc, "use"):
                if isinstance(ref, str) and "/" in ref:
                    used.add(ref.split("/", 1)[0])
            for source in _walk(doc, "catalog_source"):
                if isinstance(source, dict) and isinstance(source.get("toolId"), str):
                    used.add(source["toolId"])
        elif path.suffix == ".py":
            used.update(_CATALOG_IMPORT.findall(path.read_text(encoding="utf-8")))
    return sorted(used & set(modules))


def _digest(files: list[tuple[str, Path]], extra: list[str] | None = None) -> str:
    digest = hashlib.sha256()
    for label, path in files:
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(f"{label}\n{len(data)}\n".encode())
        digest.update(data)
        digest.update(b"\n")
    for line in extra or []:
        digest.update(f"{line}\n".encode())
    return digest.hexdigest()


def content_hash(
    projects_dir: Path,
    template_dir: Path,
    catalog_versions: dict[str, str] | None = None,
) -> str:
    """sha256 over the template's content (see the module docstring).

    ``catalog_versions`` maps each consumed catalog module to its version. The
    version, not the module's files, is what the template hash covers: a module
    change reaches its templates through the module's own bump.
    """
    extra = [f"catalog/{m}=={v}" for m, v in sorted((catalog_versions or {}).items())]
    return _digest(content_files(projects_dir, template_dir), extra)


def module_hash(module_dir: Path) -> str:
    """sha256 over a catalog module's ``.py`` and ``.yaml`` files (fixtures excluded)."""
    files = [
        (path.relative_to(module_dir).as_posix(), path)
        for path in _files_under(module_dir, _MODULE_SUFFIXES)
    ]
    return _digest(files)


def compute_catalog(catalog_dir: Path | None) -> dict[str, dict[str, Any]]:
    """``{module: {version, content_hash}}`` of the catalog as it is now."""
    return {
        module_id: {
            "version": read_module_version(module_dir) or "",
            "content_hash": module_hash(module_dir),
        }
        for module_id, module_dir in discover_modules(catalog_dir).items()
    }


def compute(projects_dir: Path, catalog_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """``{id: {version, content_hash[, catalog]}}`` of the tree as it is now.

    ``catalog`` lists the version of each catalog module the template consumes, so
    the lock says which module revisions a template revision was built against.
    """
    modules = discover_modules(catalog_dir)
    current: dict[str, dict[str, Any]] = {}
    for template_id, template_dir in discover_templates(projects_dir).items():
        used = {
            m: read_module_version(modules[m]) or ""
            for m in catalog_dependencies(projects_dir, template_dir, modules)
        }
        entry: dict[str, Any] = {
            "version": read_version(template_dir) or "",
            "content_hash": content_hash(projects_dir, template_dir, used),
        }
        if used:
            entry["catalog"] = used
        current[template_id] = entry
    return current


def load_lock(lock_path: Path, key: str = "templates") -> dict[str, dict[str, Any]] | None:
    """The lock's entries under ``key``, or None when there is no lock file."""
    if not lock_path.is_file():
        return None
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    entries = document.get(key)
    if not isinstance(entries, dict):
        raise ValueError(f"{lock_path}: no {key!r} mapping")
    return entries


def write_lock(
    lock_path: Path, entries: dict[str, dict[str, Any]], kind: _Lock = _TEMPLATES
) -> None:
    document: dict[str, Any] = {
        "_comment": (
            "Generated by scripts/update_template_lock.py: the version and content hash "
            f"of every {kind.what}. Bump {kind.field} in {kind.where}, then run the "
            "script with --write."
        ),
        "schema": LOCK_SCHEMA,
        kind.key: {key: entries[key] for key in sorted(entries)},
    }
    lock_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def compare(
    current: dict[str, dict[str, Any]],
    locked: dict[str, dict[str, Any]],
    field: str = _TEMPLATES.field,
    where: str = _TEMPLATES.where,
) -> list[Finding]:
    """What differs between the tree and the lock, as findings.

    ``field`` and ``where`` name the version in the messages (a catalog module's is
    ``version`` in its ``module.yaml``).
    """
    findings: list[Finding] = []
    for entry_id in sorted(current):
        now = current[entry_id]
        version = now["version"]
        if not _SEMVER.match(version):
            findings.append(
                Finding(INVALID, entry_id, f"{field} {version!r} is not X.Y.Z (major.minor.patch)")
            )
            continue
        before = locked.get(entry_id)
        if before is None:
            findings.append(
                Finding(NEW, entry_id, f"v{version} is not in the lock yet; refresh it")
            )
            continue
        changed = now["content_hash"] != before.get("content_hash")
        if version == before.get("version"):
            if changed:
                findings.append(
                    Finding(
                        UNBUMPED,
                        entry_id,
                        f"content changed but {field} is still {version}; bump it in {where}",
                    )
                )
            continue
        locked_version = str(before.get("version", ""))
        if _SEMVER.match(locked_version) and _version_key(version) < _version_key(locked_version):
            findings.append(
                Finding(
                    DOWNGRADED,
                    entry_id,
                    f"{field} went down: {locked_version} in the lock, {version} now",
                )
            )
            continue
        findings.append(
            Finding(
                STALE,
                entry_id,
                f"{field} is {version}, the lock still has {locked_version}; refresh the lock",
            )
        )
    for entry_id in sorted(set(locked) - set(current)):
        findings.append(
            Finding(REMOVED, entry_id, "is in the lock but no longer exists; refresh the lock")
        )
    return findings


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _locks(
    projects_dir: Path, lock_path: Path, catalog_dir: Path | None
) -> list[tuple[_Lock, Path, dict[str, dict[str, Any]]]]:
    """``(kind, lock file, current entries)`` of each lock this tree has."""
    locks = [(_TEMPLATES, lock_path, compute(projects_dir, catalog_dir))]
    if discover_modules(catalog_dir):
        assert catalog_dir is not None
        locks.append((_MODULES, catalog_dir / CATALOG_LOCK_NAME, compute_catalog(catalog_dir)))
    return locks


def run_check(
    projects_dir: Path, lock_path: Path, require_lock: bool, catalog_dir: Path | None = None
) -> int:
    status = 0
    for kind, path, current in _locks(projects_dir, lock_path, catalog_dir):
        locked = load_lock(path, kind.key)
        if locked is None:
            print(
                f"No {kind.what} lock yet ({_relative(path)}): nothing to compare. "
                "Create it with: python scripts/update_template_lock.py --write"
            )
            status |= 1 if require_lock else 0
            continue
        findings = compare(current, locked, kind.field, kind.where)
        if not findings:
            print(f"{kind.what.capitalize()} versions match the lock ({len(locked)} entries).")
            continue
        for finding in findings:
            print(f"{finding.template}: {finding.message}")
        print(
            f"\nA {kind.what}'s content changed without a version bump, or the lock is out "
            f"of date.\n{kind.bump_hint}, then run:\n"
            "    python scripts/update_template_lock.py --write"
        )
        status = 1
    return status


def run_write(
    projects_dir: Path, lock_path: Path, force: bool, catalog_dir: Path | None = None
) -> int:
    locks = _locks(projects_dir, lock_path, catalog_dir)
    refused: list[Finding] = []
    planned = []
    for kind, path, current in locks:
        findings = compare(current, load_lock(path, kind.key) or {}, kind.field, kind.where)
        refused += [f for f in findings if f.kind in (UNBUMPED, DOWNGRADED, INVALID)]
        planned.append((kind, path, current, findings))
    if refused and not force:
        for finding in refused:
            print(f"{finding.template}: {finding.message}")
        print("\nNothing written. Bump the versions above first (or pass --force).")
        return 1
    for kind, path, current, findings in planned:
        write_lock(path, current, kind)
        added = sum(1 for f in findings if f.kind == NEW)
        removed = sum(1 for f in findings if f.kind == REMOVED)
        moved = sum(1 for f in findings if f.kind == STALE)
        forced = sum(1 for f in findings if f.kind in (UNBUMPED, DOWNGRADED, INVALID))
        print(
            f"Wrote {_relative(path)}: {len(current)} {kind.what}s "
            f"({added} added, {moved} re-versioned, {removed} removed, {forced} forced)."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on a change without a bump")
    mode.add_argument("--write", action="store_true", help="refresh the lock files")
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
        help=f"template lock file (default: <projects-dir>/{LOCK_NAME})",
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=None,
        help="catalog of tool modules (default: <projects-dir>/../catalog, when it exists)",
    )
    parser.add_argument(
        "--require-lock", action="store_true", help="--check fails when there is no lock file"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="--write records a changed template or module whose version was not bumped",
    )
    args = parser.parse_args(argv)

    projects_dir = args.projects_dir.resolve()
    lock_path = (args.lock or projects_dir / LOCK_NAME).resolve()
    catalog_dir = (args.catalog_dir or projects_dir.parent / "catalog").resolve()
    if args.check:
        return run_check(projects_dir, lock_path, args.require_lock, catalog_dir)
    return run_write(projects_dir, lock_path, args.force, catalog_dir)


if __name__ == "__main__":
    sys.exit(main())
