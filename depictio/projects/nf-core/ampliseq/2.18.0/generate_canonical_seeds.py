#!/usr/bin/env python3
"""Materialise the ampliseq reference bundle's seed TSVs from a megatest download.

The reference-dataset resolver (``materialize_recipe_seeds`` in
``depictio/cli/cli/utils/templates.py``) turns every ``source: transformed`` DC
of the template into a file scan of ``{data_root}/{dc_tag}.tsv``. A seed that is
missing silently drops its DC — and every advanced_viz tile bound to it 404s at
runtime — while a stale seed keeps rendering the previous pipeline version's
numbers. So the committed TSVs next to this script *are* the reference project,
and they have to be rebuilt whenever the pipeline version (or a recipe) changes.

This script is driven by the recipes themselves: for each shipped seed DC it
loads the recipe ``template.yaml`` names, resolves the recipe's file sources
against a raw megatest download (``--raw-root``, laid out exactly like real
pipeline output — see ``download_test_data.sh``), injects ``dc_ref`` sources
from the seeds produced earlier in the run (or from the committed inputs, e.g.
the demo-augmented ``input/Metadata_full.tsv``), runs ``transform()``, asserts
``EXPECTED_SCHEMA`` and writes ``{dc_tag}.tsv``. Nothing about the recipes'
inputs is duplicated here, so the script cannot drift from them.

Usage (from repo root, inside the project venv)::

    bash depictio/projects/nf-core/ampliseq/2.18.0/download_test_data.sh /tmp/ampliseq-2.18.0-testdata
    python depictio/projects/nf-core/ampliseq/2.18.0/generate_canonical_seeds.py \\
        --raw-root /tmp/ampliseq-2.18.0-testdata

Then ``python -m depictio.dev_scripts.canonical_seed_freshness`` must report no
drift, and the seeds are ready to commit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import polars as pl
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from depictio.recipes import (  # noqa: E402
    RecipeError,
    load_recipe,
    resolve_sources,
    validate_schema,
)

DATA_ROOT = Path(__file__).resolve().parent
TEMPLATE = DATA_ROOT / "template.yaml"

# The DCs this bundle ships a seed for, i.e. the recipe outputs the reference
# project renders. Route-gated DCs the megatest never produces (sintax_*,
# sidle_*) and alpha_rarefaction_summary (not seeded, keeps parity with the
# previous bundle) are deliberately absent. Order is irrelevant: DCs are
# processed in template order, which is already dependency order.
SEED_TAGS = frozenset(
    {
        "alpha_rarefaction",
        "taxonomy_composition",
        "taxonomy_rel_abundance",
        "taxonomy_heatmap",
        "ancombc_results",
        "stacked_taxonomy_canonical",
        "embedding_pcoa",
        "rarefaction_canonical",
        "alpha_diversity_multi_canonical",
        "complex_heatmap_canonical",
        "sunburst_canonical",
        "sankey_canonical",
        "upset_canonical",
        "ma_canonical",
        "bray_curtis_canonical",
        "phylogenetic_tree_metadata_canonical",
    }
)

# dc_ref sources that are not recipe outputs: committed inputs under DATA_ROOT.
# `metadata` is the demo-augmented sample sheet (sampling_date / lon / lat /
# ctd_* columns that only this bundle carries), never the raw megatest file.
DC_REF_FILES: dict[str, str] = {"metadata": "input/Metadata_full.tsv"}


def _transformed_dcs(template: dict[str, Any]) -> list[dict[str, Any]]:
    """The template's ``source: transformed`` DCs, in declaration order."""
    out: list[dict[str, Any]] = []
    for workflow in template.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            config = dc.get("config", {})
            if config.get("source") == "transformed" and isinstance(config.get("transform"), dict):
                out.append(dc)
    return out


def _template_version(template: dict[str, Any]) -> str | None:
    """``nf-core/ampliseq/2.18.0`` → ``2.18.0`` (version-override recipe lookup)."""
    template_id = str(template.get("template", {}).get("template_id", ""))
    version = template_id.rsplit("/", 1)[-1]
    return version if version and version[0].isdigit() else None


def _read_seed_tsv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, separator="\t")


def build_seeds(raw_root: Path, only: set[str] | None = None) -> dict[str, pl.DataFrame]:
    """Run every shipped-seed recipe against ``raw_root`` and write the TSVs.

    Returns the produced frames keyed by dc_tag. Raises ``RecipeError`` when a
    required source cannot be resolved — a partial bundle is worse than none.
    """
    template = yaml.safe_load(TEMPLATE.read_text())
    version = _template_version(template)
    produced: dict[str, pl.DataFrame] = {}

    def dc_frame(dc_ref: str) -> pl.DataFrame | None:
        """A dc_ref source: produced this run, a committed input, or a committed seed."""
        if dc_ref in produced:
            return produced[dc_ref]
        if dc_ref in DC_REF_FILES:
            return _read_seed_tsv(DATA_ROOT / DC_REF_FILES[dc_ref])
        committed = DATA_ROOT / f"{dc_ref}.tsv"
        if committed.exists():
            print(f"     (dc_ref {dc_ref!r}: using committed seed — not rebuilt this run)")
            return _read_seed_tsv(committed)
        return None

    for dc in _transformed_dcs(template):
        tag = dc["data_collection_tag"]
        if tag not in SEED_TAGS or (only and tag not in only):
            continue
        recipe = dc["config"]["transform"]["recipe"]
        module = load_recipe(recipe, version)

        try:
            sources = resolve_sources(module, raw_root)
        except RecipeError as exc:
            raise RecipeError(
                f"{tag} ({recipe}): {exc}\n"
                f"  raw_root={raw_root} — populate it with download_test_data.sh"
            ) from exc
        for source in module.SOURCES:
            if source.dc_ref is None:
                continue
            frame = dc_frame(source.dc_ref)
            if frame is None and not source.optional:
                raise RecipeError(
                    f"{tag} ({recipe}): dc_ref source '{source.dc_ref}' is neither a "
                    "produced seed, a committed input nor a committed seed"
                )
            sources[source.ref] = frame  # type: ignore[assignment]

        result = module.transform(sources)
        if not isinstance(result, pl.DataFrame) or result.is_empty():
            raise RecipeError(f"{tag} ({recipe}): transform() produced no rows")
        validate_schema(
            result, module.EXPECTED_SCHEMA, recipe, getattr(module, "OPTIONAL_SCHEMA", None)
        )

        out_path = DATA_ROOT / f"{tag}.tsv"
        result.write_csv(out_path, separator="\t")
        produced[tag] = result
        print(f"  -> {out_path.name} ({result.height} rows × {result.width} cols)  [{recipe}]")

    missing = SEED_TAGS - set(produced) - (set() if only is None else SEED_TAGS - only)
    if missing:
        raise RecipeError(f"template no longer declares seed DC(s): {sorted(missing)}")
    return produced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--raw-root",
        default=str(DATA_ROOT / "data"),
        help="Megatest download laid out like real pipeline output (qiime2/…, multiqc/…). "
        "Default: <this dir>/data (git-ignored).",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="DC_TAG",
        help="Rebuild only this seed (repeatable); dc_ref inputs fall back to committed seeds.",
    )
    args = parser.parse_args(argv)
    raw_root = Path(args.raw_root).expanduser().resolve()
    if not raw_root.is_dir():
        print(f"error: --raw-root {raw_root} is not a directory", file=sys.stderr)
        return 1

    print(f"Materialising seeds from {raw_root} into {DATA_ROOT}")
    try:
        produced = build_seeds(raw_root, set(args.only) if args.only else None)
    except RecipeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Done — {len(produced)} seed TSV(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
