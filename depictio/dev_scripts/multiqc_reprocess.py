"""Re-run the pinned MultiQC over an old pipeline results folder.

    python -m depictio.dev_scripts.multiqc_reprocess --src DIR --dest DIR \\
        [--modules a,b] [--exclude GLOB ...] [--keep-json] [--dry-run]

Depictio reads only `multiqc.parquet` (MultiQC >= 1.31). A results folder
produced by an older MultiQC ships `multiqc_data.json` and no parquet, so its
report cannot back a template until MultiQC is run again over the raw tool
outputs. This script does that with the MultiQC pinned in the repo and writes
`<dest>/multiqc/multiqc_data/multiqc.parquet` plus a `REPROCESSED.json` that
records which MultiQC wrote the original report and which one wrote the parquet.

Two ideas are borrowed from the catalog conformance generator
(`depictio/projects/init/catalog_conformance/scripts/generate_project.py`):

* inputs are staged under a fixed `/tmp` path rather than `mkdtemp()`, because
  MultiQC bakes the absolute path of every input file into the parquet's
  `data_sources` and `config` columns, and a random directory would put one
  developer's machine into a committed artifact;
* `creation_date`, the only column MultiQC fills from the clock, is pinned to
  `FROZEN_CREATION_DATE` so a rerun over unchanged inputs is a no-op diff.

Both `FROZEN_CREATION_DATE` and `pin_creation_date` live here and the
conformance generator imports them back.

Exit codes: 0 ok, 2 bad arguments or missing source, 4 MultiQC parsed no module.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

# A fixed path, not mkdtemp: see the module docstring.
WORK_ROOT = Path("/tmp/depictio-multiqc-reprocess")
WORK_IN = WORK_ROOT / "in"
WORK_OUT = WORK_ROOT / "out"

# Files MultiQC must never re-parse: old reports (`multiqc/`, `multiqc_broadPeak/`,
# `multiqc_data/`, ...), the Nextflow work tree and its bookkeeping. A directory
# part is skipped when it matches; `.nextflow*` also skips files (`.nextflow.log`).
SKIP_DIR_PREFIXES = ("multiqc",)
SKIP_DIR_NAMES = ("work",)
SKIP_ANY_PREFIXES = (".nextflow",)

EXIT_OK = 0
EXIT_BAD_ARGS = 2
EXIT_NO_MODULES = 4

# A committed generated artifact has to be reproducible, and `creation_date` is
# the only column MultiQC fills from the clock. Any fixed instant will do; this
# one is the date the conformance project was first generated.
FROZEN_CREATION_DATE = datetime(2026, 8, 25, 0, 0, 0)


class NoModulesParsed(RuntimeError):
    """MultiQC ran but produced no parquet or a parquet with no module."""


def pin_creation_date(parquet: Path) -> None:
    """Freeze the report's creation timestamp so regeneration is a no-op diff.

    Without this every rerun rewrites 70 KB of parquet for no change in content,
    which both noises up the history and makes the drift test meaningless.
    """
    frame = pl.read_parquet(parquet)
    if "creation_date" not in frame.columns:
        return
    frame = frame.with_columns(
        pl.when(pl.col("creation_date").is_not_null())
        .then(pl.lit(FROZEN_CREATION_DATE).cast(frame.schema["creation_date"]))
        .otherwise(pl.col("creation_date"))
        .alias("creation_date")
    )
    frame.write_parquet(parquet)


# --------------------------------------------------------------------------
# Source version detection
# --------------------------------------------------------------------------

_LOG_BANNER = re.compile(r"This is MultiQC v(\S+)")


def _clean_version(raw: object) -> str | None:
    text = str(raw).strip() if raw is not None else ""
    text = text[1:] if text[:1] in ("v", "V") else text
    return text or None


def _version_from_parquet(src: Path) -> str | None:
    for parquet in sorted(src.rglob("*multiqc.parquet")):
        try:
            frame = pl.read_parquet(parquet, columns=["multiqc_version"])
        except Exception:
            continue
        values = frame["multiqc_version"].drop_nulls().unique().to_list()
        if values:
            return _clean_version(values[0])
    return None


def _version_from_data_json(src: Path) -> str | None:
    for data_json in sorted(src.rglob("multiqc_data.json")):
        try:
            payload = json.loads(data_json.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            for key in ("config_version", "config_short_version"):
                version = _clean_version(payload.get(key))
                if version:
                    return version
    return None


def _version_from_log(src: Path) -> str | None:
    for log in sorted(src.rglob("multiqc.log")):
        try:
            with log.open(errors="replace") as handle:
                for line in handle:
                    match = _LOG_BANNER.search(line)
                    if match:
                        return _clean_version(match.group(1))
        except OSError:
            continue
    return None


def _walk_for_multiqc(node: object) -> str | None:
    """`MultiQC:` or `multiqc:` under any process of an nf-core versions yml."""
    if not isinstance(node, dict):
        return None
    for key, value in node.items():
        if str(key).lower() == "multiqc" and not isinstance(value, dict):
            return _clean_version(value)
    for value in node.values():
        found = _walk_for_multiqc(value)
        if found:
            return found
    return None


def _version_from_software_versions(src: Path) -> str | None:
    import yaml

    for name in ("software_versions.yml", "software_versions.yaml"):
        for versions in sorted(src.rglob(name)):
            try:
                found = _walk_for_multiqc(yaml.safe_load(versions.read_text()))
            except (OSError, yaml.YAMLError):
                continue
            if found:
                return found
    # DSL1 pipelines (chipseq 1.2.0) wrote a tab-separated csv: `MultiQC\tv1.9`.
    for versions in sorted(src.rglob("software_versions.csv")):
        try:
            lines = versions.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            cells = [c.strip() for c in re.split(r"[\t,]", line) if c.strip()]
            if len(cells) >= 2 and cells[0].lower() == "multiqc":
                return _clean_version(cells[1])
    return None


def detect_source_multiqc_version(src: Path) -> str | None:
    """Which MultiQC wrote the report already in `src`, or None.

    Tried in order: an existing parquet's `multiqc_version` column, the
    `config_version` key of `multiqc_data.json`, the `This is MultiQC v` banner
    in `multiqc.log`, and finally the pipeline's `software_versions.yml` (or the
    DSL1 `software_versions.csv`). Old reports have no parquet, so in practice
    the json key is the one that answers for MultiQC 1.x runs.
    """
    src = Path(src)
    for probe in (
        _version_from_parquet,
        _version_from_data_json,
        _version_from_log,
        _version_from_software_versions,
    ):
        version = probe(src)
        if version:
            return version
    return None


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------


def _skipped(relative: Path, exclude: Sequence[str]) -> bool:
    parts = relative.parts
    if any(part.startswith(SKIP_DIR_PREFIXES) or part in SKIP_DIR_NAMES for part in parts[:-1]):
        return True
    if any(part.startswith(SKIP_ANY_PREFIXES) for part in parts):
        return True
    posix = relative.as_posix()
    return any(
        fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(relative.name, pattern)
        for pattern in exclude
    )


def plan_inputs(src: Path, exclude: Sequence[str] = ()) -> list[Path]:
    """The files under `src` MultiQC will see, as paths relative to `src`.

    Skips every `multiqc*/` directory (an old report must not be re-parsed as
    input), `work/`, anything named `.nextflow*`, and the user's `exclude`
    globs, which are matched against both the relative posix path and the bare
    file name (`*.bam` excludes BAMs at any depth).
    """
    src = Path(src)
    planned: list[Path] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(src)
        if _skipped(relative, exclude):
            continue
        planned.append(relative)
    return planned


def stage_inputs(src: Path, work_in: Path, exclude: Sequence[str] = ()) -> list[Path]:
    """Mirror the planned inputs into `work_in` and return the staged paths.

    Files are symlinked so a 100 GB results folder costs nothing to stage;
    when the filesystem refuses symlinks they are copied instead. `work_in`
    is recreated from scratch on every call.
    """
    src = Path(src).resolve()
    work_in = Path(work_in)
    shutil.rmtree(work_in, ignore_errors=True)
    work_in.mkdir(parents=True)
    staged: list[Path] = []
    for relative in plan_inputs(src, exclude):
        target = work_in / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (src / relative).resolve()
        try:
            target.symlink_to(source)
        except OSError:
            shutil.copy2(source, target)
        staged.append(target)
    return staged


# --------------------------------------------------------------------------
# MultiQC run
# --------------------------------------------------------------------------


def run_multiqc(work_in: Path, work_out: Path, modules: Sequence[str] | None = None) -> Path:
    """Run MultiQC over `work_in` into `work_out`; return the parquet path.

    `make_report=False` skips the HTML but MultiQC still writes
    `multiqc_data/multiqc.parquet` (the conformance generator relies on the
    same combination). `run_modules` is only set when the caller restricts the
    modules: `ClConfig` rejects `None` for that list field.
    """
    import multiqc
    from multiqc.core.update_config import ClConfig

    work_out = Path(work_out)
    shutil.rmtree(work_out, ignore_errors=True)
    work_out.mkdir(parents=True)
    options: dict[str, object] = {
        "output_dir": str(work_out),
        "force": True,
        "quiet": True,
        "make_report": False,
        "no_megaqc_upload": True,
        "no_version_check": True,
    }
    if modules:
        options["run_modules"] = list(modules)
    multiqc.reset()
    multiqc.run(str(work_in), cfg=ClConfig(**options))
    return work_out / "multiqc_data" / "multiqc.parquet"


def parquet_modules(parquet: Path) -> set[str]:
    """The MultiQC module anchors a report carries, read straight off the parquet."""
    parquet = Path(parquet)
    if not parquet.exists():
        return set()
    frame = pl.read_parquet(parquet, columns=["modules"])
    found: set[str] = set()
    for raw in frame["modules"].drop_nulls().to_list():
        for module in json.loads(raw) if isinstance(raw, str) else raw:
            anchor = module.get("anchor") if isinstance(module, dict) else module
            if anchor:
                found.add(str(anchor))
    return found


def _validate_parquet(parquet: Path) -> bool:
    """`multiqc_processor.validate_multiqc_parquet`, or a local polars check.

    The CLI package is what ingestion runs, so its validator is the authority.
    It is imported lazily and skipped only when the package cannot be imported
    at all (a venv without the CLI extras), in which case "at least one module
    row" is the fallback.
    """
    try:
        from depictio.cli.cli.utils.multiqc_processor import validate_multiqc_parquet
    except ImportError:
        return bool(parquet_modules(parquet))
    return bool(validate_multiqc_parquet(str(parquet)))


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def write_provenance(
    dest_multiqc_data: Path,
    *,
    source_version: str | None,
    reprocessed_with: str,
    modules: Iterable[str],
    n_inputs: int,
    src: Path | str | None = None,
    timestamp: datetime | None = None,
) -> Path:
    """Write `REPROCESSED.json` next to the parquet and return its path.

    The parquet itself is reproducible (fixed staging path, pinned
    `creation_date`), so `timestamp` is the one field that says when the
    reprocess really happened: it defaults to the current UTC time. Pass a
    fixed instant (tests use `FROZEN_CREATION_DATE`) to make the whole output
    byte-stable.
    """
    dest_multiqc_data = Path(dest_multiqc_data)
    dest_multiqc_data.mkdir(parents=True, exist_ok=True)
    when = timestamp or datetime.now(timezone.utc)
    payload = {
        "source_version": source_version,
        "reprocessed_with": reprocessed_with,
        "timestamp": when.isoformat(),
        "modules": sorted(modules),
        "n_inputs": n_inputs,
        "src": str(src) if src is not None else None,
    }
    target = dest_multiqc_data / "REPROCESSED.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def reprocess(
    src: Path | str,
    dest: Path | str,
    modules: Sequence[str] | None = None,
    exclude: Sequence[str] = (),
    keep_json: bool = False,
    dry_run: bool = False,
    timestamp: datetime | None = None,
) -> Path:
    """Stage `src`, run MultiQC, and write the parquet under `dest`.

    Returns the destination parquet path (`<dest>/multiqc/multiqc_data/multiqc.parquet`).
    `dry_run` prints the staged file count, the detected source version and the
    planned output paths, then returns without touching `/tmp` or `dest`.
    Raises `FileNotFoundError` when `src` is not a directory and
    `NoModulesParsed` when MultiQC parsed nothing.
    """
    src = Path(src).resolve()
    dest = Path(dest)
    if not src.is_dir():
        raise FileNotFoundError(f"source is not a directory: {src}")

    planned = plan_inputs(src, exclude)
    source_version = detect_source_multiqc_version(src)
    dest_data = dest / "multiqc" / "multiqc_data"
    parquet_dest = dest_data / "multiqc.parquet"

    if dry_run:
        print(f"source:            {src}")
        print(f"files to stage:    {len(planned)}")
        print(f"source MultiQC:    {source_version or 'unknown'}")
        print(f"modules:           {', '.join(modules) if modules else 'all'}")
        print(f"staging dir:       {WORK_IN}")
        print(f"parquet:           {parquet_dest}")
        print(f"provenance:        {dest_data / 'REPROCESSED.json'}")
        if keep_json:
            print(f"data json:         {dest_data / 'multiqc_data.json'}")
        return parquet_dest

    import multiqc

    staged = stage_inputs(src, WORK_IN, exclude)
    try:
        parquet = run_multiqc(WORK_IN, WORK_OUT, modules)
        if not parquet.exists():
            raise NoModulesParsed(
                f"MultiQC {multiqc.__version__} produced no parquet from {len(staged)} "
                f"staged file(s) under {src}: no module recognised any input"
            )
        pin_creation_date(parquet)
        found = parquet_modules(parquet)
        if not found or not _validate_parquet(parquet):
            raise NoModulesParsed(
                f"MultiQC {multiqc.__version__} parsed no module from {len(staged)} "
                f"staged file(s) under {src}"
            )
        dest_data.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parquet, parquet_dest)
        if keep_json:
            data_json = parquet.parent / "multiqc_data.json"
            if data_json.exists():
                shutil.copyfile(data_json, dest_data / "multiqc_data.json")
        write_provenance(
            dest_data,
            source_version=source_version,
            reprocessed_with=multiqc.__version__,
            modules=found,
            n_inputs=len(staged),
            src=src,
            timestamp=timestamp,
        )
    finally:
        shutil.rmtree(WORK_ROOT, ignore_errors=True)
    return parquet_dest


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m depictio.dev_scripts.multiqc_reprocess",
        description=(
            "Re-run the pinned MultiQC over a pipeline results folder and write "
            "<dest>/multiqc/multiqc_data/multiqc.parquet plus REPROCESSED.json."
        ),
    )
    parser.add_argument("--src", required=True, type=Path, help="results folder to re-parse")
    parser.add_argument("--dest", required=True, type=Path, help="where multiqc/ is written")
    parser.add_argument(
        "--modules",
        default=None,
        help="comma-separated MultiQC module ids to run (default: every module)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip inputs matching this glob (relative path or file name); repeatable",
    )
    parser.add_argument(
        "--keep-json",
        action="store_true",
        help="also copy the regenerated multiqc_data.json next to the parquet",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (file count, source version, output paths) and exit",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    modules = [m.strip() for m in args.modules.split(",") if m.strip()] if args.modules else None
    try:
        parquet = reprocess(
            args.src,
            args.dest,
            modules=modules,
            exclude=tuple(args.exclude),
            keep_json=args.keep_json,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_ARGS
    except NoModulesParsed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NO_MODULES
    if not args.dry_run:
        print(f"wrote {parquet}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
