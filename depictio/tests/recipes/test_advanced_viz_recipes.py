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
# ampliseq: volcano
# ---------------------------------------------------------------------------


def test_ampliseq_volcano_canonical(tmp_path: Path) -> None:
    """Ampliseq volcano recipe rewrites ANCOM-BC columns to canonical schema."""
    src = tmp_path / "ancombc_habitat_level2.tsv"
    pl.DataFrame(
        {
            "id": ["k__Bacteria;p__Firmicutes", "k__Bacteria;p__Bacteroidetes"],
            "contrast": ["A_vs_B", "A_vs_B"],
            "lfc": [1.2, -0.7],
            "p_val": [0.001, 0.04],
            "q_val": [0.005, 0.06],
            "w": [3.1, -1.4],
            "Kingdom": ["Bacteria", "Bacteria"],
            "Phylum": ["Firmicutes", "Bacteroidetes"],
            "neg_log10_qval": [2.301, 1.222],
            "significant": [True, False],
        }
    ).write_csv(src, separator="\t")

    result = execute_recipe("nf-core/ampliseq/volcano_canonical.py", tmp_path)

    # The recipe engine has already enforced EXPECTED_SCHEMA at this point.
    assert not result.is_empty()
    assert set(["feature_id", "effect_size", "significance"]).issubset(result.columns)

    cfg = VolcanoConfig(
        feature_id_col="feature_id",
        effect_size_col="effect_size",
        significance_col="significance",
        label_col="label",
        category_col="category",
    )
    errors = validate_binding(cfg, _polars_schema_name(result))
    assert errors == [], f"binding errors: {errors}"


# ---------------------------------------------------------------------------
# ampliseq: stacked_taxonomy
# ---------------------------------------------------------------------------


def test_ampliseq_stacked_taxonomy_canonical(tmp_path: Path) -> None:
    src = tmp_path / "taxonomy_rel_abundance_long.tsv"
    pl.DataFrame(
        {
            "sample": ["S1", "S1", "S2", "S2"],
            "taxonomy": [
                "k__Bacteria;p__Firmicutes",
                "k__Bacteria;p__Bacteroidetes",
                "k__Bacteria;p__Firmicutes",
                "k__Bacteria;p__Bacteroidetes",
            ],
            "rel_abundance": [0.55, 0.30, 0.40, 0.50],
            "habitat": ["river", "river", "soil", "soil"],
            "Kingdom": ["Bacteria"] * 4,
            "Phylum": ["Firmicutes", "Bacteroidetes", "Firmicutes", "Bacteroidetes"],
        }
    ).write_csv(src, separator="\t")

    result = execute_recipe("nf-core/ampliseq/stacked_taxonomy_canonical.py", tmp_path)

    assert not result.is_empty()
    assert set(["sample_id", "taxon", "rank", "abundance"]).issubset(result.columns)
    # Both rows have 2-segment taxonomy ⇒ rank = "Phylum"
    assert set(result["rank"].unique().to_list()) == {"Phylum"}

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
    src = tmp_path / "taxonomy_heatmap.tsv"
    # 3 taxa x 4 samples; values are dummy relative abundances.
    rng = np.random.default_rng(seed=0)
    samples = ["S1", "S2", "S3", "S4"]
    matrix = rng.uniform(0, 1, size=(3, 4))
    pl.DataFrame(
        {
            "Phylum": ["Firmicutes", "Bacteroidetes", "Proteobacteria"],
            "Kingdom": ["Bacteria"] * 3,
            **{s: matrix[:, i].tolist() for i, s in enumerate(samples)},
        }
    ).write_csv(src, separator="\t")

    result = execute_recipe("nf-core/ampliseq/embedding_pcoa.py", tmp_path)

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
# viralrecon: manhattan
# ---------------------------------------------------------------------------


def test_viralrecon_manhattan_variants_canonical(tmp_path: Path) -> None:
    src_dir = tmp_path / "variants" / "ivar"
    src_dir.mkdir(parents=True)
    src = src_dir / "variants_long_table.csv"
    pl.DataFrame(
        {
            "SAMPLE": ["sampleA", "sampleA", "sampleB"],
            "CHROM": ["MN908947.3"] * 3,
            "POS": [100, 200, 300],
            "REF": ["A", "C", "G"],
            "ALT": ["T", "T", "A"],
            "FILTER": ["PASS", "PASS", "PASS"],
            "DP": [50, 80, 30],
            "REF_DP": [10, 5, 1],
            "ALT_DP": [40, 75, 29],
            "AF": [0.80, 0.94, 0.97],
            "GENE": ["S", "S", "N"],
            "EFFECT": ["missense_variant", "synonymous_variant", "missense_variant"],
        }
    ).write_csv(src)

    result = execute_recipe("nf-core/viralrecon/manhattan_variants_canonical.py", tmp_path)

    assert not result.is_empty()
    assert set(["chr", "pos", "score"]).issubset(result.columns)
    # score = -log10(1 - AF); for AF=0.8 → log10(0.2) ≈ -0.699 → score ≈ 0.699
    af_80_score = result.filter(pl.col("pos") == 100)["score"].item()
    assert 0.65 < af_80_score < 0.75

    cfg = ManhattanConfig(
        chr_col="chr",
        pos_col="pos",
        score_col="score",
        feature_col="feature",
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
