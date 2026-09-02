"""Keep the committed ``*_canonical.tsv`` seeds in step with the recipes that build them.

Why this is needed at all: **a reference project never runs its recipes.**
``materialize_recipe_seeds`` (``depictio/cli/cli/utils/templates.py``) rewrites
every ``source: transformed`` DC into a single-file scan of
``{data_root}/{dc_tag}.tsv``, so what a fresh deployment renders is the
committed TSV — not what the recipe would produce today. Fixing a recipe
therefore changes nothing anyone can see until someone also regenerates the
file, and there was nothing to remind them.

``upset_canonical`` is what that costs. Its recipe gained
``_attach_taxon_annotations`` in ``c99a6702`` for one stated purpose — carry
``Kingdom``/``Phylum`` onto the presence matrix so a dashboard filter on a
taxonomic rank has a column to bite on — and the shipped TSV never got them.
The fix was real, reviewed, merged, and inert.

Only DCs whose sources are **all** committed under the project directory can be
checked here. The rest read from ``data/qiime2/``, which is downloaded test
data and deliberately not in the repo; those are reported as skipped, with the
reason, rather than quietly counting as passing.

Usage::

    # report drift (exit 1 if any)
    venv/bin/python -m depictio.dev_scripts.canonical_seed_freshness
    # rewrite the drifted seeds
    venv/bin/python -m depictio.dev_scripts.canonical_seed_freshness --write
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from depictio.cli.cli.utils.templates import latest_template_version

REPO_ROOT = Path(__file__).resolve().parents[2]
_AMPLISEQ_DIR = REPO_ROOT / "depictio/projects/nf-core/ampliseq"

# Float columns survive a TSV round-trip only to within the decimal repr, so an
# exact comparison reports every seed as drifted. `ma_canonical` differs from
# its own recipe's output by 4.4e-16 for exactly this reason and nothing else.
RTOL = 1e-9
ATOL = 1e-12


@dataclass(frozen=True)
class ProjectSeeds:
    """Where one project's canonical seeds, recipes and sources live."""

    name: str
    data_root: Path
    recipe_dirs: tuple[Path, ...]
    # dc_ref → path relative to data_root, for sources that are not simply
    # `{dc_ref}.tsv` (ampliseq's metadata is the samplesheet-adjacent TSV).
    source_overrides: dict[str, str]


PROJECTS: tuple[ProjectSeeds, ...] = (
    ProjectSeeds(
        name="ampliseq",
        # The bundle db_init actually seeds: the highest shipped template version.
        data_root=_AMPLISEQ_DIR / (latest_template_version(_AMPLISEQ_DIR) or ""),
        recipe_dirs=(
            _AMPLISEQ_DIR / "recipes",
            REPO_ROOT / "depictio/catalog",
        ),
        source_overrides={"metadata": "input/Metadata_full.tsv"},
    ),
)


@dataclass(frozen=True)
class SeedSpec:
    project: str
    dc_tag: str
    recipe_path: Path
    seed_path: Path
    # ref → (path, read kwargs the recipe declared, e.g. skipping a QIIME2
    # `#q2:types` row that would otherwise be read as data)
    sources: dict[str, tuple[Path, dict[str, Any]]]


def _find_recipe(dc_tag: str, recipe_dirs: tuple[Path, ...]) -> Path | None:
    """The recipe module for a dc tag, pipeline-keyed dir first.

    Mirrors `generate_canonical_seeds.py`'s lookup: a pipeline may override a
    module-owned catalog recipe, and the pipeline's copy wins.
    """
    for directory in recipe_dirs:
        direct = directory / f"{dc_tag}.py"
        if direct.exists():
            return direct
        nested = sorted(directory.glob(f"*/{dc_tag}.py"))
        if nested:
            return nested[0]
    return None


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover(project: ProjectSeeds) -> tuple[list[SeedSpec], list[tuple[str, str]]]:
    """(checkable seeds, [(dc_tag, why it was skipped)]) for one project."""
    checkable: list[SeedSpec] = []
    skipped: list[tuple[str, str]] = []

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    for seed_path in sorted(project.data_root.glob("*_canonical.tsv")):
        dc_tag = seed_path.stem
        recipe_path = _find_recipe(dc_tag, project.recipe_dirs)
        if recipe_path is None:
            skipped.append(
                (dc_tag, "no recipe module — the TSV is a committed input, not an output")
            )
            continue

        module = _load_module(recipe_path)
        sources: dict[str, tuple[Path, dict[str, Any]]] = {}
        missing: list[str] = []
        for source in getattr(module, "SOURCES", []):
            path = _source_path(project, source)
            if path is None:
                missing.append(source.dc_ref or source.glob_pattern or "<unresolvable>")
                continue
            if path.exists():
                sources[source.ref] = (path, dict(source.read_kwargs or {}))
            elif not source.optional:
                missing.append(str(path.relative_to(project.data_root)))
        if missing:
            skipped.append((dc_tag, f"source(s) not committed: {', '.join(sorted(missing))}"))
            continue

        checkable.append(
            SeedSpec(
                project=project.name,
                dc_tag=dc_tag,
                recipe_path=recipe_path,
                seed_path=seed_path,
                sources=sources,
            )
        )
    return checkable, skipped


def _source_path(project: ProjectSeeds, source: Any) -> Path | None:
    """Where one recipe source reads from, or None when it cannot be resolved.

    A source names either a sibling DC (`dc_ref`, whose seed is
    `{dc_tag}.tsv` at the data root) or a file relative to the data root
    (`path`). `glob_pattern` sources are not resolvable offline and fall
    through to None, which is reported as a skip.
    """
    if source.dc_ref:
        rel = project.source_overrides.get(source.dc_ref, f"{source.dc_ref}.tsv")
        return project.data_root / rel
    if source.path:
        return project.data_root / source.path
    return None


def produce(spec: SeedSpec) -> pl.DataFrame:
    """Run the recipe on its committed sources."""
    module = _load_module(spec.recipe_path)
    frames = {
        ref: pl.read_csv(path, separator="\t" if path.suffix != ".csv" else ",", **kwargs)
        for ref, (path, kwargs) in spec.sources.items()
    }
    return module.transform(frames)


def _values_match(produced: pl.Series, committed: pl.Series) -> bool:
    if produced.dtype in (pl.Float32, pl.Float64):
        for a, b in zip(produced.to_list(), committed.to_list()):
            if a is None or b is None:
                if a is not b:
                    return False
                continue
            if not math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL):
                return False
        return True
    return produced.to_list() == committed.to_list()


def compare(produced: pl.DataFrame, committed: pl.DataFrame) -> str | None:
    """None when the seed is current, else a message naming what drifted.

    Column ORDER is not compared. A pivot emits its columns in encounter order,
    which is stable for a given input but carries no meaning — holding a seed to
    it would turn a reordered metadata file into a spurious failure.
    """
    produced_cols, committed_cols = set(produced.columns), set(committed.columns)
    if produced_cols != committed_cols:
        parts = []
        if produced_cols - committed_cols:
            parts.append(f"recipe now emits {sorted(produced_cols - committed_cols)}")
        if committed_cols - produced_cols:
            parts.append(f"seed still has {sorted(committed_cols - produced_cols)}")
        return "; ".join(parts)

    if produced.height != committed.height:
        return f"{produced.height} rows from the recipe vs {committed.height} in the seed"

    order = produced.columns[0]
    left = produced.select(committed.columns).sort(order)
    right = committed.sort(order)
    drifted = [c for c in committed.columns if not _values_match(left[c], right[c])]
    if drifted:
        return f"differing values in {drifted}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite drifted seeds instead of only reporting them",
    )
    args = parser.parse_args()

    drift = 0
    for project in PROJECTS:
        checkable, skipped = discover(project)
        print(f"\n{project.name}: {len(checkable)} checkable, {len(skipped)} skipped")
        for dc_tag, reason in skipped:
            print(f"  ~ {dc_tag}: {reason}")
        for spec in checkable:
            produced = produce(spec)
            committed = pl.read_csv(spec.seed_path, separator="\t")
            message = compare(produced, committed)
            if message is None:
                print(f"  ✓ {spec.dc_tag}")
                continue
            drift += 1
            if args.write:
                produced.write_csv(spec.seed_path, separator="\t")
                print(f"  → {spec.dc_tag}: rewritten ({message})")
            else:
                print(f"  ✗ {spec.dc_tag}: {message}")

    if drift and not args.write:
        print(f"\n{drift} seed(s) out of step with their recipe. Re-run with --write.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
