"""End-to-end tests for the canonical-schema advanced-viz recipes.

Each test writes a minimal synthetic input file into a temp data_dir, runs
the recipe via ``execute_recipe``, and asserts:

  1. The recipe's own ``EXPECTED_SCHEMA`` is met (this is enforced by the
     recipe engine — checkpoint 4 in depictio/recipes/__init__.py:288).
  2. The result is non-empty.
  3. The canonical viz binding validates against the produced schema via
     ``advanced_viz.schemas.validate_binding``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from depictio.models.components.advanced_viz.configs import (
    EmbeddingConfig,
    ManhattanConfig,
    StackedTaxonomyConfig,
    VolcanoConfig,
)
from depictio.models.components.advanced_viz.schemas import validate_binding
from depictio.recipes import execute_recipe


def _polars_schema_name(df: pl.DataFrame) -> dict[str, str]:
    """Stringify a polars DataFrame schema in the form used by validate_binding."""
    return {name: str(dtype) for name, dtype in df.schema.items()}


# ---------------------------------------------------------------------------
# ampliseq: stacked_taxonomy
# ---------------------------------------------------------------------------


def test_ampliseq_stacked_taxonomy_canonical(tmp_path: Path) -> None:
    # The recipe fans in QIIME2 rel-table-{2..6}.tsv (one wide table per rank,
    # taxa × samples) via dc_ref sources — injected here as `extra_sources`.
    # Only the Phylum level (rel-table-2) is supplied; the recipe tolerates the
    # deeper levels being absent and derives a Kingdom level from the Phylum rows.
    phylum = pl.DataFrame(
        {
            "#OTU ID": ["k__Bacteria;p__Firmicutes", "k__Bacteria;p__Bacteroidetes"],
            "S1": [0.55, 0.30],
            "S2": [0.40, 0.50],
        }
    )
    empty = pl.DataFrame()

    result = execute_recipe(
        "qiime2/stacked_taxonomy_canonical.py",
        tmp_path,
        extra_sources={
            "phylum": phylum,
            "class_": empty,
            "order": empty,
            "family": empty,
            "genus": empty,
        },
    )

    assert not result.is_empty()
    assert set(["sample_id", "taxon", "rank", "abundance"]).issubset(result.columns)
    # Phylum rows plus a Kingdom level the recipe derives by summing Phylum.
    assert set(result["rank"].unique().to_list()) == {"Kingdom", "Phylum"}

    cfg = StackedTaxonomyConfig(
        sample_id_col="sample_id",
        taxon_col="taxon",
        rank_col="rank",
        abundance_col="abundance",
    )
    errors = validate_binding(cfg, _polars_schema_name(result))
    assert errors == [], f"binding errors: {errors}"


# ---------------------------------------------------------------------------
# ampliseq: embedding (PCoA)
# ---------------------------------------------------------------------------


def test_ampliseq_embedding_pcoa(tmp_path: Path) -> None:
    # The recipe consumes the derived `taxonomy_heatmap` DC (wide matrix:
    # Phylum/Kingdom row-ids + per-sample columns) via a dc_ref source — injected
    # here as `extra_sources`. 3 taxa x 4 samples of dummy relative abundances.
    rng = np.random.default_rng(seed=0)
    samples = ["S1", "S2", "S3", "S4"]
    matrix = rng.uniform(0, 1, size=(3, 4))
    heatmap = pl.DataFrame(
        {
            "Phylum": ["Firmicutes", "Bacteroidetes", "Proteobacteria"],
            "Kingdom": ["Bacteria"] * 3,
            **{s: matrix[:, i].tolist() for i, s in enumerate(samples)},
        }
    )

    result = execute_recipe(
        "qiime2/embedding_pcoa.py", tmp_path, extra_sources={"taxonomy_heatmap": heatmap}
    )

    assert not result.is_empty()
    assert set(["sample_id", "dim_1", "dim_2"]).issubset(result.columns)
    assert sorted(result["sample_id"].to_list()) == sorted(samples)

    cfg = EmbeddingConfig(
        sample_id_col="sample_id",
        dim_1_col="dim_1",
        dim_2_col="dim_2",
    )
    errors = validate_binding(cfg, _polars_schema_name(result))
    assert errors == [], f"binding errors: {errors}"


# ---------------------------------------------------------------------------
# Negative-path: binding validator catches missing + wrong-dtype columns
# ---------------------------------------------------------------------------


def test_validate_binding_missing_column() -> None:
    cfg = VolcanoConfig(
        feature_id_col="feature_id",
        effect_size_col="lfc",  # not in schema below
        significance_col="significance",
    )
    schema = {"feature_id": "String", "significance": "Float64"}
    errors = validate_binding(cfg, schema)
    assert any(e.role == "effect_size" and "not in DC" in e.reason for e in errors)


def test_validate_binding_wrong_dtype() -> None:
    cfg = VolcanoConfig(
        feature_id_col="feature_id",
        effect_size_col="lfc",
        significance_col="significance",
    )
    schema = {"feature_id": "String", "lfc": "Int64", "significance": "Float64"}
    errors = validate_binding(cfg, schema)
    assert any(e.role == "effect_size" and "Int64" in e.reason for e in errors)


def test_validate_binding_ok() -> None:
    cfg = VolcanoConfig(
        feature_id_col="feature_id",
        effect_size_col="lfc",
        significance_col="q_val",
    )
    schema = {"feature_id": "Utf8", "lfc": "Float64", "q_val": "Float64"}
    assert validate_binding(cfg, schema) == []


@pytest.mark.parametrize(
    ("kind", "cfg"),
    [
        (
            "embedding",
            EmbeddingConfig(sample_id_col="s", dim_1_col="d1", dim_2_col="d2"),
        ),
        (
            "manhattan",
            ManhattanConfig(chr_col="chr", pos_col="pos", score_col="sc"),
        ),
        (
            "stacked_taxonomy",
            StackedTaxonomyConfig(
                sample_id_col="s",
                taxon_col="t",
                rank_col="r",
                abundance_col="a",
            ),
        ),
    ],
)
def test_validate_binding_per_kind_happy_path(kind, cfg) -> None:
    """Each kind is happy when DC has correctly-named, correctly-typed columns."""
    if kind == "embedding":
        schema = {"s": "String", "d1": "Float64", "d2": "Float64"}
    elif kind == "manhattan":
        schema = {"chr": "String", "pos": "Int64", "sc": "Float64"}
    else:  # stacked_taxonomy
        schema = {"s": "String", "t": "String", "r": "String", "a": "Float64"}
    assert validate_binding(cfg, schema) == []
