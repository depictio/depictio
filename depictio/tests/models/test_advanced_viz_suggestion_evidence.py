"""Calibration of the advanced-viz kind suggester on real template schemas.

The schemas are the `EXPECTED_SCHEMA` of the catalog recipes the nf-core
templates bind (the exact columns and dtypes their Delta tables carry), so a
recipe change that reshapes a table shows up here as a ranking change.

What the suggester must get right:

- a generic numeric table (a PCA frame, an assembly QC table) is read by its
  shape, not lost under domain kinds whose vocabularies half-match it;
- a domain kind still wins when its roles are genuinely named (volcano on a
  differential-expression table);
- a record card is recommended only when the dashboard tab has a tile whose
  selection it can follow.
"""

from __future__ import annotations

import importlib

import polars as pl
import pytest

from depictio.models.components.advanced_viz.schemas import (
    RECOMMENDED_SCORE,
    SuggestionContext,
    VizSuggestion,
    suggest_viz_kinds,
)


def _recipe_schema(module: str) -> dict[str, str]:
    """A catalog recipe's EXPECTED_SCHEMA as ``{column: polars dtype name}``."""
    expected = importlib.import_module(module).EXPECTED_SCHEMA
    return {
        col: str(dtype() if isinstance(dtype, type) else dtype) for col, dtype in expected.items()
    }


def _by_kind(schema: dict[str, str], **kwargs) -> dict[str, VizSuggestion]:
    return {s.viz_kind: s for s in suggest_viz_kinds(schema, dc_type="table", **kwargs)}


def _recommended(schema: dict[str, str], **kwargs) -> set[str]:
    return {k for k, s in _by_kind(schema, **kwargs).items() if s.score >= RECOMMENDED_SCORE}


# rnasplice / rnaseq sample space: sample_id, dim_1, dim_2, group, library summary.
SAMPLE_PCA = "depictio.catalog.salmon.sample_pca"
# DESeq2 results with gene annotation: gene_id, log2fc, padj, coordinates, ...
DESEQ2_RESULTS = "depictio.catalog.deseq2.results_annotated"
# genomeassembler / mag QUAST report: assembly_id, n50, gc_percent, ...
QUAST_REPORT = "depictio.catalog.quast.assembly_report"
# genomeassembler Merqury: assembly_id, qv, error_rate, kmer_completeness, ...
MERQURY_QV = "depictio.catalog.merqury.assembly_qv"


def test_sample_space_reads_as_an_embedding_not_a_domain_kind() -> None:
    by = _by_kind(_recipe_schema(SAMPLE_PCA))
    ranked = sorted(by.values(), key=lambda s: -s.score)
    assert ranked[0].viz_kind == "embedding"
    assert by["embedding"].match == "named"
    # The dim_1/dim_2 pair is also a sound scatter, ranked under the embedding.
    assert by["scatter_xy"].match == "shape"
    assert RECOMMENDED_SCORE <= by["scatter_xy"].score < by["embedding"].score
    assert "x/y: numeric pair dim_1, dim_2" in by["scatter_xy"].reasons
    # Kinds whose vocabularies only half-match must stay under the bar.
    for kind in ("knee_plot", "sunburst", "da_barplot", "rarefaction", "profile"):
        assert by[kind].score < RECOMMENDED_SCORE, (kind, by[kind])
        assert by[kind].match == "weak", (kind, by[kind])


def test_scatter_prefills_two_distinct_axes() -> None:
    by = _by_kind(_recipe_schema(SAMPLE_PCA))
    candidates = by["scatter_xy"].role_candidates
    assert (candidates["x"][0], candidates["y"][0]) == ("dim_1", "dim_2")


def test_gene_results_table_recommends_volcano_on_named_roles() -> None:
    by = _by_kind(_recipe_schema(DESEQ2_RESULTS))
    volcano = by["volcano"]
    assert volcano.match == "named"
    assert volcano.score == max(s.score for s in by.values())
    assert "effect_size: log2fc" in volcano.reasons
    assert "significance: padj" in volcano.reasons
    # A statistics table is not a parallel-coordinates plot: its floats are
    # statistics and its integers are coordinates.
    assert by["parallel_coordinates"].score < RECOMMENDED_SCORE


@pytest.mark.parametrize("module", [QUAST_REPORT, MERQURY_QV])
def test_assembly_qc_table_recommends_generic_kinds(module: str) -> None:
    by = _by_kind(_recipe_schema(module))
    recommended = _recommended(_recipe_schema(module))
    assert {"scatter_xy", "parallel_coordinates"} <= recommended, recommended
    assert by["scatter_xy"].match == "shape"
    assert by["parallel_coordinates"].match == "shape"
    # Nothing from a domain vocabulary is announced on an assembly table.
    for kind in ("knee_plot", "sunburst", "oncoplot", "volcano", "phylogenetic"):
        assert kind not in recommended, (kind, by[kind])


def test_record_card_needs_dashboard_context() -> None:
    schema = _recipe_schema(QUAST_REPORT)
    without = _by_kind(schema)["record_card"]
    assert without.score < RECOMMENDED_SCORE
    assert without.match == "weak"
    assert any("selecting component" in r for r in without.reasons)

    unrelated = _by_kind(schema, context=SuggestionContext(selection_columns=frozenset({"gene"})))
    assert unrelated["record_card"].score < RECOMMENDED_SCORE

    ctx = SuggestionContext(selection_columns=frozenset({"assembly_id"}))
    card = _by_kind(schema, context=ctx)["record_card"]
    assert card.score >= RECOMMENDED_SCORE
    assert card.match == "context"
    assert card.role_candidates["id"][0] == "assembly_id"
    assert "id column assembly_id matches the selection on this tab" in card.reasons


def test_record_card_needs_enough_fields_to_show() -> None:
    schema = {"sample_id": "String", "dim_1": "Float64", "dim_2": "Float64"}
    ctx = SuggestionContext(selection_columns=frozenset({"sample_id"}))
    card = _by_kind(schema, context=ctx)["record_card"]
    assert card.score < RECOMMENDED_SCORE
    assert card.match == "weak"


def test_generic_coordinate_pair_prefers_scatter_over_embedding() -> None:
    # `*_x` / `*_y` is a coordinate pair but not a dimensionality reduction.
    schema = {"cell_id": "String", "centroid_x": "Float64", "centroid_y": "Float64"}
    by = _by_kind(schema)
    assert by["scatter_xy"].score >= RECOMMENDED_SCORE
    assert by["scatter_xy"].score > by["embedding"].score


def test_reduction_pairs_are_named_embeddings() -> None:
    schema = {"barcode": "String", "UMAP_1": "Float64", "UMAP_2": "Float64", "n_genes": "Int64"}
    by = _by_kind(schema)
    assert by["embedding"].match == "named"
    assert by["embedding"].score > by["scatter_xy"].score >= RECOMMENDED_SCORE


def test_numeric_table_without_a_label_stays_under_the_bar() -> None:
    by = _by_kind({"a": "Float64", "b": "Float64"})
    assert by["scatter_xy"].match == "shape"
    assert by["scatter_xy"].score < RECOMMENDED_SCORE


def test_every_suggestion_carries_a_match_and_reasons() -> None:
    for s in suggest_viz_kinds(_recipe_schema(QUAST_REPORT), dc_type="table"):
        assert s.match in {"named", "shape", "context", "weak"}
        # A recommended kind always says why.
        if s.score >= RECOMMENDED_SCORE:
            assert s.reasons, s
            assert s.match != "weak", s


def test_existing_kinds_are_flagged_without_changing_the_score() -> None:
    schema = _recipe_schema(SAMPLE_PCA)
    plain = _by_kind(schema)["embedding"]
    ctx = SuggestionContext(existing_kinds=frozenset({"embedding"}))
    flagged = _by_kind(schema, context=ctx)["embedding"]
    assert flagged.score == plain.score
    assert "already used on this tab" in flagged.reasons


def test_recipe_schemas_are_polars_dtype_names() -> None:
    # Guards the helper: the suggester matches on the names polars emits.
    schema = _recipe_schema(SAMPLE_PCA)
    assert schema["sample_id"] == str(pl.String)
    assert schema["dim_1"] == "Float64"
