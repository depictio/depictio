"""nanoseq's `dexseq_usage`: per-library transcript shares for the best-ranked DEXSeq genes."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

RECIPE = "nf-core/nanoseq/dexseq_usage.py"
N_GENES = 45  # more than the recipe keeps


def _sources() -> dict[str, pl.DataFrame]:
    results, counts = [], []
    for g in range(N_GENES):
        gene = f"ENSG{g + 1:011d}"
        for t in ("a", "b"):
            tx = f"ENST{g + 1:011d}{t}"
            # The gene's q-value grows with g: gene 0 is the most significant.
            results.append((tx, gene, 1.0 if t == "a" else -1.0, 10 ** -(N_GENES - g)))
            counts.append((tx, gene, 10.0, 20.0, 30.0, 5.0))
    res = pl.DataFrame(
        results,
        schema=["featureID", "groupID", "log2fold_B_A", "dex.padj$gene"],
        orient="row",
    ).with_columns(pl.all().cast(pl.Utf8))
    cnt = pl.DataFrame(
        counts, schema=["TXNAME", "GENEID", "A_R1", "A_R2", "B_R1", "B_R2"], orient="row"
    )
    return {"results": res, "counts": cnt}


@pytest.mark.no_db
def test_keeps_the_best_ranked_genes_so_the_dashboard_filter_can_pick_among_them():
    module = load_recipe(RECIPE, pipeline_version="3.0.0")
    out = module.transform(_sources())
    validate_schema(out, module.OUTPUT_SCHEMA, "dexseq_usage", None)
    assert module.TOP_GENES > 6  # the tile draws six unfiltered; the rest are for the Gene filter
    genes = out["gene_id"].unique()
    assert genes.len() == module.TOP_GENES
    # Ranked by gene-level q-value: the last gene of the input is the first dropped.
    assert f"ENSG{N_GENES:011d}" not in genes.to_list()
    assert out["gene_label"].n_unique() == module.TOP_GENES


@pytest.mark.no_db
def test_each_library_split_sums_to_one_hundred_per_gene():
    module = load_recipe(RECIPE, pipeline_version="3.0.0")
    out = module.transform(_sources())
    sums = out.group_by(["gene_id", "sample"]).agg(pl.col("usage_pct").sum())
    assert sums["usage_pct"].to_list() == pytest.approx([100.0] * sums.height)
    assert set(out["condition"].unique()) == {"A", "B"}
