#!/usr/bin/env python3
"""Bump an nf-core template project to a new pipeline version.

Maintainer tool (like ``nfcore_monitor.py`` — not shipped with depictio-cli).
Since seeding, CLI (``--template nf-core/<pipeline>/latest``), CI and the docs
generator all resolve the *highest* version directory automatically, shipping a
new template version is just: create the new version directory with its files
updated — this script does that mechanical part.

What it does:

1. Copies ``depictio/projects/nf-core/<pipeline>/<from>/`` (default: the current
   latest) to ``<new-version>/`` — template.yaml, dashboards, ``.db_seeds`` and
   bundled demo data included, as a working starting point.
2. Rewrites the old version string to the new one in every text file of the new
   directory (template_id, headers, helper scripts…). Binary files are left
   untouched.
3. Prints the follow-up checklist (refresh demo data, drift-check via
   nfcore_monitor, reseed if dashboards changed, regenerate docs partials).

Usage::

    python scripts/bump_template_version.py --pipeline ampliseq --new-version 2.18.0
    python scripts/bump_template_version.py --pipeline ampliseq --new-version 2.18.0 --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
NFCORE_PROJECTS_DIR = _REPO_ROOT / "depictio" / "projects" / "nf-core"
_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")

# Never rewrite content in these (binary or data) suffixes.
_BINARY_SUFFIXES = {".parquet", ".biom", ".gz", ".png", ".pdf", ".qza", ".qzv", ".nwk"}


def latest_version(pipeline_dir: Path) -> str | None:
    """Highest numeric version subdirectory holding a template.yaml."""
    versions = [
        d.name
        for d in pipeline_dir.iterdir()
        if d.is_dir() and _VERSION_RE.match(d.name) and (d / "template.yaml").is_file()
    ]
    if not versions:
        return None
    return max(versions, key=lambda v: tuple(int(p) for p in v.split(".")))


def rewrite_versions(new_dir: Path, old_version: str, new_version: str) -> list[Path]:
    """Replace the exact old version string in every text file under ``new_dir``.

    Returns the files that changed. Files that are binary (by suffix or decode
    failure) are skipped.
    """
    changed: list[Path] = []
    for path in sorted(new_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() in _BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if old_version not in text:
            continue
        path.write_text(text.replace(old_version, new_version), encoding="utf-8")
        changed.append(path)
    return changed


def bump(
    pipeline: str,
    new_version: str,
    from_version: str | None = None,
    projects_dir: Path = NFCORE_PROJECTS_DIR,
    dry_run: bool = False,
) -> Path:
    """Create ``<pipeline>/<new_version>/`` from the previous version directory."""
    pipeline_dir = projects_dir / pipeline
    if not pipeline_dir.is_dir():
        raise FileNotFoundError(f"Unknown pipeline directory: {pipeline_dir}")
    if not _VERSION_RE.match(new_version):
        raise ValueError(f"New version must be numeric dotted (got {new_version!r})")

    old_version = from_version or latest_version(pipeline_dir)
    if old_version is None:
        raise FileNotFoundError(f"No versioned template found under {pipeline_dir}")
    old_dir = pipeline_dir / old_version
    if not (old_dir / "template.yaml").is_file():
        raise FileNotFoundError(f"No template.yaml in source version dir {old_dir}")

    new_dir = pipeline_dir / new_version
    if new_dir.exists():
        raise FileExistsError(f"Target version dir already exists: {new_dir}")
    if tuple(int(p) for p in new_version.split(".")) <= tuple(
        int(p) for p in old_version.split(".")
    ):
        raise ValueError(
            f"New version {new_version} does not sort above {old_version} — the "
            "latest-resolution (seeding/CLI/docs) would keep picking the old one."
        )

    n_files = sum(1 for p in old_dir.rglob("*") if p.is_file())
    print(f"→ {pipeline}: {old_version} → {new_version}  ({n_files} files)")
    if dry_run:
        print(f"  [dry-run] would copy {old_dir} → {new_dir} and rewrite version strings")
        return new_dir

    shutil.copytree(old_dir, new_dir)
    changed = rewrite_versions(new_dir, old_version, new_version)
    print(f"→ copied to {new_dir}")
    for path in changed:
        print(f"  rewrote {old_version} → {new_version} in {path.relative_to(new_dir)}")

    try:
        new_dir_display = new_dir.relative_to(_REPO_ROOT)
    except ValueError:  # custom --projects-dir outside the repo
        new_dir_display = new_dir
    print(
        f"""
Done. Follow-up checklist for {pipeline} {new_version}:

  1. Refresh the bundled demo data from a real {new_version} run — the copied
     TSV/multiqc files still hold {old_version} outputs (see
     {new_dir_display}/download_test_data.sh / generate_validation_runs.sh
     where present).
  2. Drift-check the template against the new release's megatest:
       python scripts/nfcore_monitor.py report --pipeline {pipeline}
     Fix any moved/renamed recipe source paths it reports.
  3. If dashboards changed, regenerate the JSON seeds
     (generate_seeds.sh + remap_seeds_to_static_ids.py in the version dir) —
     fresh deployments seed from .db_seeds/*.json, not YAML.
  4. Regenerate the docs partials (also refreshes {pipeline}-latest.md):
       python -m depictio.dev_scripts.gen_template_docs
  5. Guard tests (seeding auto-resolves to {new_version} from now on):
       uv run pytest depictio/tests/api/v1/test_reference_seed_dashboards.py \\
                     depictio/tests/unit/test_nfcore_monitor.py -q
"""
    )
    return new_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pipeline", required=True, help="e.g. ampliseq")
    parser.add_argument("--new-version", required=True, help="e.g. 2.18.0")
    parser.add_argument(
        "--from-version",
        default=None,
        help="Source version to copy from (default: current latest).",
    )
    parser.add_argument(
        "--projects-dir",
        default=str(NFCORE_PROJECTS_DIR),
        help="nf-core projects root (default: repo's depictio/projects/nf-core).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without writing.")
    args = parser.parse_args(argv)
    try:
        bump(
            args.pipeline,
            args.new_version,
            from_version=args.from_version,
            projects_dir=Path(args.projects_dir),
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
