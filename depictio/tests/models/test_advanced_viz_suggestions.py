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

from depictio.models.components.advanced_viz.schemas import suggest_viz_kinds

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
# expected_viz_kinds is a subset assertion — the function may surface
# additional kinds that coincidentally match dtype shapes. The fixture
# *must* at minimum return everything in this list.
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
    suggested_kinds = {s.viz_kind for s in viz}
    missing = expected_kinds - suggested_kinds
    assert not missing, (
        f"{rel_path}: schema {schema} did not suggest {missing}; got {suggested_kinds}"
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
