"""Suggest function tests, grounded in real nf-core megatest outputs.

Each test takes a fixture file's actual column×dtype schema (read via
polars) and asserts that `suggest_viz_kinds()` / `suggest_producers()`
return the viz kinds and producer name the docs catalog promised.

The fixtures themselves live under `dev/advanced_viz_docs_screenshots/
fixtures/` (gitignored — regenerate via `extract_nfcore_fixtures.py`).
Tests skip silently when the fixture isn't present locally so CI doesn't
require S3 access; running ``python3 dev/advanced_viz_docs_screenshots/
extract_nfcore_fixtures.py`` first activates them.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.models.components.advanced_viz.schemas import (
    suggest_producers,
    suggest_viz_kinds,
)

FIXTURES_DIR = (
    Path(__file__).resolve().parents[3] / "dev" / "advanced_viz_docs_screenshots" / "fixtures"
)


def _read_schema(path: Path, **read_kwargs) -> dict[str, str]:
    """Read a fixture and return {col_name: polars-dtype-str}.

    Mirrors what `_get_data_collection_polars_schema()` produces server-side.
    """
    # n_rows=20 to keep tests fast — we only need the schema.
    if path.suffix in {".tsv", ".txt"}:
        df = pl.read_csv(path, separator="\t", n_rows=20, **read_kwargs)
    elif path.suffix == ".csv":
        df = pl.read_csv(path, n_rows=20, **read_kwargs)
    else:
        raise ValueError(f"unsupported fixture suffix: {path.suffix}")
    return {col: str(dtype) for col, dtype in df.schema.items()}


# (fixture_path, expected_viz_kinds, expected_producer_name, read_kwargs)
# expected_viz_kinds is a subset assertion — the function may surface
# additional kinds that coincidentally match dtype shapes. The fixture
# *must* at minimum return everything in this list.
CASES: list[tuple[str, set[str], str | None, dict]] = [
    (
        "volcano/deseq2_results.tsv",
        {"volcano", "ma", "qq"},
        "deseq2_results",
        {},
    ),
    (
        "coverage_track/mosdepth_coverage.tsv",
        {"coverage_track"},
        "mosdepth_coverage",
        {},
    ),
    (
        # Bracken's per-sample output has no `sample_id` column (the sample
        # identity comes from the filename), so the name-aware suggester
        # surfaces only sunburst. Stacked_taxonomy is still reachable via
        # the producer's `feeds_viz` after the reshape declared in
        # `bracken_sample.role_mapping["stacked_taxonomy"]`.
        "sunburst/bracken_sample.tsv",
        {"sunburst"},
        "bracken_sample",
        {},
    ),
    (
        "embedding/rnaseq_deseq2_pca.txt",
        {"embedding"},
        "rnaseq_deseq2_pca",
        {},
    ),
]


@pytest.mark.parametrize(
    "rel_path, expected_kinds, expected_producer, read_kwargs",
    CASES,
    ids=lambda x: str(x) if not isinstance(x, dict) and not isinstance(x, set) else "",
)
def test_suggestions_against_nfcore_fixtures(
    rel_path: str, expected_kinds: set[str], expected_producer: str | None, read_kwargs: dict
) -> None:
    """Real-data check: each fixture must light up the promised viz kinds."""
    path = FIXTURES_DIR / rel_path
    if not path.is_file():
        pytest.skip(
            f"fixture {rel_path} not downloaded — run "
            f"dev/advanced_viz_docs_screenshots/extract_nfcore_fixtures.py"
        )
    schema = _read_schema(path, **read_kwargs)
    viz = suggest_viz_kinds(schema)
    suggested_kinds = {s.viz_kind for s in viz}
    missing = expected_kinds - suggested_kinds
    assert not missing, (
        f"{rel_path}: schema {schema} did not suggest {missing}; got {suggested_kinds}"
    )

    if expected_producer:
        producer_names = {name for name, _ in suggest_producers(schema)}
        assert expected_producer in producer_names, (
            f"{rel_path}: producer {expected_producer!r} not detected; got {producer_names}"
        )


# Pure-function tests below don't need fixture files — they exercise the
# suggestion engine with synthetic schemas to lock down edge-case behaviour.


def test_suggest_viz_kinds_returns_empty_on_unfitting_schema() -> None:
    # Pure-string schema with a column that doesn't match any role's
    # name-alias set — the suggester should reject everything, including
    # phylogenetic (whose `taxon` role no longer matches an arbitrary
    # String column under the name-aware rules).
    schema = {"only_string_col": "String"}
    suggestions = suggest_viz_kinds(schema)
    kinds = {s.viz_kind for s in suggestions}
    assert kinds == set(), f"expected no suggestions, got {kinds}"


def test_phylogenetic_matches_on_taxon_aliases() -> None:
    # A String column whose name IS in the phylogenetic taxon alias set
    # (e.g. `taxon`, `tip_label`, `label`) should light up phylogenetic.
    for col_name in ("taxon", "tip_label", "label"):
        kinds = {s.viz_kind for s in suggest_viz_kinds({col_name: "String"})}
        assert "phylogenetic" in kinds, f"{col_name}: phylogenetic missing from {kinds}"


def test_suggest_viz_kinds_role_candidates_populated() -> None:
    schema = {
        "gene_id": "String",
        "log2FoldChange": "Float64",
        "padj": "Float64",
    }
    [vol] = [s for s in suggest_viz_kinds(schema) if s.viz_kind == "volcano"]
    assert vol.confidence == 1.0
    # Every required volcano role has at least one candidate column from
    # the schema (dtype-compatible). The UI uses this to pre-fill bindings.
    assert vol.role_candidates["feature_id"] == ["gene_id"]
    assert set(vol.role_candidates["effect_size"]) == {"log2FoldChange", "padj"}
    assert set(vol.role_candidates["significance"]) == {"log2FoldChange", "padj"}


def test_suggest_viz_kinds_min_confidence_filters() -> None:
    # Only feature_id is satisfied (String); effect_size + significance are
    # both Float but the schema has no Float column at all.
    schema = {"feature_id": "String"}
    strict = suggest_viz_kinds(schema, min_confidence=1.0)
    relaxed = suggest_viz_kinds(schema, min_confidence=0.3)
    strict_kinds = {s.viz_kind for s in strict}
    relaxed_kinds = {s.viz_kind for s in relaxed}
    assert "volcano" not in strict_kinds
    assert "volcano" in relaxed_kinds  # 1/3 roles satisfied → conf ≈ 0.33


def test_suggest_producers_requires_full_fingerprint() -> None:
    # Two of three deseq2 required cols — should NOT match.
    partial = {"baseMean": "Float64", "log2FoldChange": "Float64"}
    assert suggest_producers(partial) == []
    # All three — matches.
    full = {**partial, "padj": "Float64"}
    matches = suggest_producers(full)
    assert ("deseq2_results", 1.0) in matches


def test_producer_fingerprint_works_without_dtypes() -> None:
    """The DC creation modal calls the suggestion engine with column names
    only — before the file is uploaded and dtypes are inferred. Producer
    fingerprints match on names alone, so this must still light up."""
    # Sentinel dtype since the function only inspects schema keys for
    # producer fingerprinting.
    name_only_schema = {col: "" for col in ("baseMean", "log2FoldChange", "padj", "gene_id")}
    matches = {name for name, _ in suggest_producers(name_only_schema)}
    assert "deseq2_results" in matches


def test_ancombc_joined_results_suggests_volcano_and_da_barplot() -> None:
    """Joined ANCOM-BC results (ampliseq `ancombc.py` recipe output) must
    fingerprint as `ancombc_results_joined`, which feeds volcano + da_barplot.
    Regression for the React DC creation modal: uploading the joined TSV
    previously surfaced no producer hint at all."""
    schema = {col: "" for col in ("id", "contrast", "lfc", "q_val", "w")}
    matches = {name for name, _ in suggest_producers(schema)}
    assert "ancombc_results_joined" in matches


def test_volcano_role_table_fingerprint() -> None:
    """Files already in role-named volcano shape (feature_id / effect_size /
    significance) must light up — used by ampliseq's volcano DC and any
    hand-curated DE results saved with role-named columns."""
    schema = {col: "" for col in ("feature_id", "effect_size", "significance")}
    matches = {name for name, _ in suggest_producers(schema)}
    assert "volcano_role_table" in matches


def test_da_barplot_role_table_fingerprint() -> None:
    schema = {col: "" for col in ("feature_id", "contrast", "lfc")}
    matches = {name for name, _ in suggest_producers(schema)}
    assert "da_barplot_role_table" in matches


def test_taxonomy_levels_long_fingerprint() -> None:
    """Files with Kingdom..Genus + abundance must fingerprint as the
    hierarchical taxonomy producer that feeds both sankey + sunburst.
    Regression for the demo upload flow: sankey/sunburst files used to
    surface no producer hint at all."""
    schema = {
        col: ""
        for col in (
            "sample_id",
            "Habitat",
            "Kingdom",
            "Phylum",
            "Class",
            "Order",
            "Family",
            "Genus",
            "abundance",
        )
    }
    matches = dict(suggest_producers(schema))
    assert "taxonomy_levels_long" in matches
    # Producer must advertise feeding both sankey and sunburst so the UI
    # surfaces both viz kinds in the modal's "looks like" hint.
    from depictio.models.components.advanced_viz.producers import get_producer

    p = get_producer("taxonomy_levels_long")
    assert p is not None
    assert set(p.feeds_viz) == {"sankey", "sunburst"}


def test_rarefaction_iter_long_fingerprint() -> None:
    """Long-form rarefaction with raw metric columns (sample_id / depth /
    iter / shannon / observed_features / faith_pd) must fingerprint —
    distinct from the role-named `rarefaction_role_table` which requires
    a literal `metric` column."""
    schema = {
        col: ""
        for col in (
            "sample_id",
            "depth",
            "iter",
            "shannon",
            "observed_features",
            "faith_pd",
            "group",
        )
    }
    matches = {name for name, _ in suggest_producers(schema)}
    assert "rarefaction_iter_long" in matches


def test_taxonomy_abundance_long_fingerprint() -> None:
    """Long-form ampliseq taxonomy-heatmap source (sample_id × taxonomy ×
    rel_abundance × Kingdom × Phylum) must fingerprint so the drop modal
    surfaces complex_heatmap as a downstream option."""
    schema = {
        col: ""
        for col in (
            "sample_id",
            "taxonomy",
            "rel_abundance",
            "habitat",
            "Kingdom",
            "Phylum",
        )
    }
    matches = dict(suggest_producers(schema))
    assert "taxonomy_abundance_long" in matches

    from depictio.models.components.advanced_viz.producers import get_producer

    p = get_producer("taxonomy_abundance_long")
    assert p is not None
    assert "complex_heatmap" in p.feeds_viz


def test_alpha_diversity_wide_fingerprint() -> None:
    """Wide alpha-diversity summary (sample_id × shannon × observed_features
    × faith_pd × evenness) must fingerprint so the modal shows the badge,
    even though no advanced-viz kind consumes it directly yet."""
    schema = {
        col: ""
        for col in (
            "sample_id",
            "habitat",
            "shannon",
            "observed_features",
            "faith_pd",
            "evenness",
        )
    }
    matches = {name for name, _ in suggest_producers(schema)}
    assert "alpha_diversity_wide" in matches


def test_viralrecon_variants_long_fingerprint() -> None:
    """nf-core/viralrecon `variants_long` DC — sample × CHROM × POS × REF ×
    ALT × GENE × EFFECT. Distinct from raw VCF (`ivar_variants_vcf`,
    fingerprinted on `#CHROM`)."""
    schema = {
        col: ""
        for col in (
            "sample",
            "CHROM",
            "POS",
            "REF",
            "ALT",
            "GENE",
            "EFFECT",
            "AF",
        )
    }
    matches = {name for name, _ in suggest_producers(schema)}
    assert "viralrecon_variants_long" in matches
    assert "ivar_variants_vcf" not in matches  # would fire on raw `#CHROM`


def test_ancombc_lfc_slice_no_longer_fires_on_bare_id_column() -> None:
    """Regression: the old `{id}` fingerprint matched every TSV with an `id`
    column, polluting suggestions on unrelated tables. The producer is
    strengthened to `{id, lfc}` so it only fires on real slice files."""
    bare_id = {"id": "", "name": "", "value": ""}
    assert "ancombc_lfc_slice" not in {name for name, _ in suggest_producers(bare_id)}


def test_suggest_producers_returns_multiple_on_ambiguous_schemas() -> None:
    # Bracken's fingerprint includes name + taxonomy_id + taxonomy_lvl which
    # is unusual enough that no other producer in the registry collides.
    bracken_schema = {
        "name": "String",
        "taxonomy_id": "Int64",
        "taxonomy_lvl": "String",
        "kraken_assigned_reads": "Int64",
        "added_reads": "Int64",
        "new_est_reads": "Int64",
        "fraction_total_reads": "Float64",
    }
    matches = {name for name, _ in suggest_producers(bracken_schema)}
    assert "bracken_sample" in matches
    assert "deseq2_results" not in matches
