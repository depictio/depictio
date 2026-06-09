"""Suggest function tests, grounded in real nf-core megatest outputs.

Each test takes a fixture file's actual column×dtype schema (read via
polars) and asserts that `suggest_viz_kinds()` returns the viz kinds the
docs catalog promised.

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

from depictio.models.components.advanced_viz.schemas import RECOMMENDED_SCORE, suggest_viz_kinds

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


# (fixture_path, expected_viz_kinds, read_kwargs)
# The graded suggester ranks *every* kind, so we assert that each promised kind
# scores well (>= _EXPECTED_SCORE) rather than that it's the only one returned.
_EXPECTED_SCORE = 0.5

CASES: list[tuple[str, set[str], dict]] = [
    (
        "volcano/deseq2_results.tsv",
        {"volcano", "ma", "qq"},
        {},
    ),
    (
        "coverage_track/mosdepth_coverage.tsv",
        {"coverage_track"},
        {},
    ),
    (
        # Bracken's per-sample output has no `sample_id` column (the sample
        # identity comes from the filename), so the name-aware suggester
        # surfaces only sunburst.
        "sunburst/bracken_sample.tsv",
        {"sunburst"},
        {},
    ),
    (
        "embedding/rnaseq_deseq2_pca.txt",
        {"embedding"},
        {},
    ),
]


@pytest.mark.parametrize(
    "rel_path, expected_kinds, read_kwargs",
    CASES,
    ids=lambda x: str(x) if not isinstance(x, dict) and not isinstance(x, set) else "",
)
def test_suggestions_against_nfcore_fixtures(
    rel_path: str, expected_kinds: set[str], read_kwargs: dict
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
    scored = {s.viz_kind: s.score for s in viz}
    well_scored = {k for k, score in scored.items() if score >= _EXPECTED_SCORE}
    missing = expected_kinds - well_scored
    assert not missing, (
        f"{rel_path}: schema {schema} did not score {missing} >= {_EXPECTED_SCORE}; scores={scored}"
    )


# Pure-function tests below don't need fixture files — they exercise the
# suggestion engine with synthetic schemas to lock down edge-case behaviour.


def test_suggest_viz_kinds_returns_all_kinds_ranked() -> None:
    # The graded suggester always returns every kind, sorted by score desc.
    schema = {"gene_id": "String", "log2FoldChange": "Float64", "padj": "Float64"}
    viz = suggest_viz_kinds(schema)
    scores = [s.score for s in viz]
    assert len(viz) == len({s.viz_kind for s in viz})  # one entry per kind
    assert scores == sorted(scores, reverse=True)  # ranked
    assert 0.0 <= min(scores) and max(scores) <= 1.0


def test_unfitting_schema_recommends_nothing() -> None:
    # A lone String column with a name that matches no role alias should leave
    # nothing in the "recommended" band — every kind is at most a weak,
    # dtype-only match.
    schema = {"only_string_col": "String"}
    recommended = [s for s in suggest_viz_kinds(schema) if s.score >= RECOMMENDED_SCORE]
    assert recommended == [], f"expected nothing recommended, got {recommended}"


def test_phylogenetic_matches_on_taxon_aliases() -> None:
    # A String column whose name IS in the phylogenetic taxon alias set
    # (e.g. `taxon`, `tip_label`, `label`) should score phylogenetic highly.
    for col_name in ("taxon", "tip_label", "label"):
        [phylo] = [
            s for s in suggest_viz_kinds({col_name: "String"}) if s.viz_kind == "phylogenetic"
        ]
        assert phylo.score >= RECOMMENDED_SCORE, f"{col_name}: phylogenetic score {phylo.score}"


def test_suggest_viz_kinds_role_candidates_populated() -> None:
    schema = {
        "gene_id": "String",
        "log2FoldChange": "Float64",
        "padj": "Float64",
    }
    [vol] = [s for s in suggest_viz_kinds(schema) if s.viz_kind == "volcano"]
    assert vol.score == 1.0
    assert vol.unmet_roles == []
    assert vol.weak_roles == []
    # Every required volcano role has at least one candidate column from
    # the schema (dtype-compatible), ranked best-first. The UI uses this to
    # pre-fill bindings.
    assert vol.role_candidates["feature_id"] == ["gene_id"]
    assert set(vol.role_candidates["effect_size"]) == {"log2FoldChange", "padj"}
    assert set(vol.role_candidates["significance"]) == {"log2FoldChange", "padj"}
    # The best-named candidate ranks first for each numeric role.
    assert vol.role_candidates["effect_size"][0] == "log2FoldChange"
    assert vol.role_candidates["significance"][0] == "padj"


def test_suggest_viz_kinds_min_confidence_filters() -> None:
    # Only feature_id is satisfied (String); effect_size + significance are
    # both Float but the schema has no Float column at all → volcano scores low.
    schema = {"feature_id": "String"}
    strict_kinds = {s.viz_kind for s in suggest_viz_kinds(schema, min_confidence=1.0)}
    relaxed_kinds = {s.viz_kind for s in suggest_viz_kinds(schema, min_confidence=0.3)}
    assert "volcano" not in strict_kinds  # ~0.38 < 1.0
    assert "volcano" in relaxed_kinds  # 1/3 roles satisfied → score ≈ 0.38


def test_castable_dtype_scores_below_exact() -> None:
    # An Int column feeds a Float role (manhattan score) as a castable match —
    # it should rank, but below a schema with the exact Float dtype.
    exact = {"chr": "String", "pos": "Int64", "score": "Float64"}
    castable = {"chr": "String", "pos": "Int64", "score": "Int64"}
    [exact_man] = [s for s in suggest_viz_kinds(exact) if s.viz_kind == "manhattan"]
    [cast_man] = [s for s in suggest_viz_kinds(castable) if s.viz_kind == "manhattan"]
    assert exact_man.score > cast_man.score > 0.0


def test_short_aliases_do_not_cause_substring_false_positives() -> None:
    # Regression: a 1-2 char alias ("p", "x", "y") must NOT match a column that
    # merely contains that letter. A generic penguin morphometrics table scored
    # qq ~0.99 (via "p" inside "bill_depth_mm") and embedding ~0.80 (via the
    # "x"/"y" dim aliases) before the fix — pure false positives.
    schema = {
        "individual_id": "String",
        "bill_length_mm": "Float64",
        "bill_depth_mm": "Float64",
        "flipper_length_mm": "Float64",
        "body_mass_g": "Float64",
    }
    by = {s.viz_kind: s.score for s in suggest_viz_kinds(schema)}
    assert by["qq"] < 0.6, f"qq still spuriously high via short-alias substring: {by['qq']}"
    assert by["embedding"] < RECOMMENDED_SCORE, f"embedding still recommended: {by['embedding']}"
