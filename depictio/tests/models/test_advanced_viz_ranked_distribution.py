"""The `ranked_distribution` kind: config, roles, the two shapes and its fixtures.

A ranked distribution reads its features in one of two shapes: long form (one
row per feature and sample, the renderer computes each box) or pre-aggregated
(one row per feature with its quartiles, what a cohort of thousands of samples
ships as). Neither is a required role, so which one a binding gives is checked
twice: the model refuses half a shape and both at once, and `validate_binding`
refuses none. Both showcase fixtures are checked against their real columns.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import RankedDistributionConfig, VizConfig
from depictio.models.components.advanced_viz.record_link import SELECTION_EMITTING_KINDS
from depictio.models.components.advanced_viz.sampling import policy_for_kind
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    KIND_METADATA,
    ROLE_NAMES,
    role_dtype_specs,
    suggest_viz_kinds,
    validate_binding,
)

REPO = Path(__file__).resolve().parents[3]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
STATS_FIXTURE = SHOWCASE / "data" / "ranked_distribution_demo.tsv"
LONG_FIXTURE = SHOWCASE / "data" / "ranked_distribution_values_demo.tsv"

VIZ_CONFIG = TypeAdapter(VizConfig)

_STATS_BINDING = {
    "feature_id_col": "gene_id",
    "score_col": "stability_score",
    "rank_col": "rank",
    "label_col": "gene_name",
    "group_col": "section",
    "q1_col": "q1",
    "median_col": "median",
    "q3_col": "q3",
    "lower_col": "lower",
    "upper_col": "upper",
    "mean_col": "mean",
}
_LONG_BINDING = {
    "feature_id_col": "gene_id",
    "score_col": "stability_score",
    "label_col": "gene_name",
    "group_col": "section",
    "value_col": "value",
}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows, f"{path} has a header but no data rows"
    return rows


def _schema(path: Path) -> dict[str, str]:
    """Column -> polars dtype name, inferred the way a scanned DC would report it."""
    rows = _read(path)
    schema: dict[str, str] = {}
    for column in rows[0]:
        values = [row[column] for row in rows if row[column] != ""]
        if values and all(v.lstrip("-").isdigit() for v in values):
            schema[column] = "Int64"
        else:
            try:
                for v in values:
                    float(v)
                schema[column] = "Float64"
            except ValueError:
                schema[column] = "String"
    return schema


# ---------------------------------------------------------------------------
# The row contract
# ---------------------------------------------------------------------------


def test_required_roles_are_the_feature_and_its_score():
    assert set(CANONICAL_SCHEMAS["ranked_distribution"]) == {"feature_id", "score"}
    assert set(_OPTIONAL_ROLES["ranked_distribution"]) == {
        "rank",
        "label",
        "group",
        "value",
        "q1",
        "median",
        "q3",
        "lower",
        "upper",
        "mean",
    }


def test_every_role_has_a_config_field_and_a_description():
    fields = RankedDistributionConfig.model_fields
    specs = role_dtype_specs("ranked_distribution")
    for role in (
        *CANONICAL_SCHEMAS["ranked_distribution"],
        *_OPTIONAL_ROLES["ranked_distribution"],
    ):
        assert f"{role}_col" in fields, role
        assert specs[role]["description"], role
    config = RankedDistributionConfig()
    assert (config.feature_id_col, config.score_col) == ("feature_id", "score")
    # Every optional role starts unbound: a shape nobody declared is no shape.
    for role in _OPTIONAL_ROLES["ranked_distribution"]:
        assert getattr(config, f"{role}_col") is None, role


def test_the_kind_is_listed_and_its_aliases_name_stableexpression():
    meta = KIND_METADATA["ranked_distribution"]
    assert meta["label"] and meta["icon"].startswith("tabler:")
    assert "stability_score" in ROLE_NAMES["ranked_distribution"]["score"]
    assert "gene_id" in ROLE_NAMES["ranked_distribution"]["feature_id"]
    # A bare `score` is far too common a column name to claim.
    assert "score" not in ROLE_NAMES["ranked_distribution"]["score"]


def test_sampling_never_thins_the_rows_it_ranks():
    assert policy_for_kind("ranked_distribution") == "none"


def test_a_click_selects_the_feature_id_by_default():
    assert SELECTION_EMITTING_KINDS["ranked_distribution"] == (
        "selection_column",
        "feature_id_col",
        "=feature_id",
    )


# ---------------------------------------------------------------------------
# Config defaults, guards and the shape check
# ---------------------------------------------------------------------------


def test_defaults():
    config = RankedDistributionConfig()
    assert config.top_n == 25
    assert config.ascending is True  # lower is more stable
    assert config.distribution == "box"
    assert config.orientation == "horizontal"
    assert config.log_value is False
    assert config.max_features == 200
    assert config.selection_enabled is False
    assert config.selection_column is None
    assert config.controls_placement == "popover"


@pytest.mark.parametrize(
    "overrides",
    [{"top_n": 0}, {"max_features": 0}, {"max_features": 50_000}, {"distribution": "strip"}],
)
def test_guards_refuse_out_of_range_settings(overrides: dict):
    with pytest.raises(ValidationError):
        RankedDistributionConfig(**overrides)


def test_half_a_pre_aggregated_shape_is_refused():
    with pytest.raises(ValidationError, match="median_col"):
        RankedDistributionConfig(q1_col="q1", q3_col="q3")


def test_both_shapes_at_once_are_refused():
    with pytest.raises(ValidationError, match="not both"):
        RankedDistributionConfig(value_col="value", q1_col="q1", median_col="m", q3_col="q3")


def test_a_violin_needs_the_long_form():
    with pytest.raises(ValidationError, match="violin"):
        RankedDistributionConfig(**_STATS_BINDING, distribution="violin")
    assert RankedDistributionConfig(**_LONG_BINDING, distribution="violin").distribution == "violin"


def test_an_unbound_shape_loads_but_does_not_bind():
    """The builder stores a config before every role is bound, so the model
    accepts it; the binding check is what says it draws nothing."""
    config = RankedDistributionConfig(feature_id_col="gene_id", score_col="stability_score")
    errors = validate_binding(config, {"gene_id": "String", "stability_score": "Float64"})
    assert [(e.role, e.severity) for e in errors] == [("value", "error")]
    assert "q1, median" in errors[0].reason


def test_the_union_discriminates_and_round_trips():
    blob = {"viz_kind": "ranked_distribution", **_LONG_BINDING, "selection_enabled": True}
    parsed = VIZ_CONFIG.validate_python(blob)
    assert isinstance(parsed, RankedDistributionConfig)
    again = VIZ_CONFIG.validate_python(parsed.model_dump())
    assert again == parsed
    with pytest.raises(ValidationError):
        VIZ_CONFIG.validate_python({"viz_kind": "ranked_distribution", "no_such_key": 1})


# ---------------------------------------------------------------------------
# The two showcase fixtures, against their real columns
# ---------------------------------------------------------------------------


def test_pre_aggregated_fixture_binds_cleanly():
    config = RankedDistributionConfig(**_STATS_BINDING)
    assert validate_binding(config, _schema(STATS_FIXTURE)) == []


def test_long_form_fixture_binds_cleanly():
    config = RankedDistributionConfig(**_LONG_BINDING)
    assert validate_binding(config, _schema(LONG_FIXTURE)) == []


def test_pre_aggregated_fixture_is_one_coherent_box_per_gene():
    rows = _read(STATS_FIXTURE)
    assert len(rows) == 200
    assert len({r["gene_id"] for r in rows}) == 200
    assert {r["section"] for r in rows} == {"high", "medium", "low"}
    # The rank is the score's order, lowest first, as stableexpression ranks.
    by_rank = sorted(rows, key=lambda r: int(r["rank"]))
    scores = [float(r["stability_score"]) for r in by_rank]
    assert scores == sorted(scores)
    for r in rows:
        lower, q1, median, q3, upper = (
            float(r[k]) for k in ("lower", "q1", "median", "q3", "upper")
        )
        assert lower <= q1 <= median <= q3 <= upper, r["gene_id"]


def test_long_form_fixture_is_the_top_genes_over_the_same_samples():
    stats = {r["gene_id"]: r for r in _read(STATS_FIXTURE)}
    rows = _read(LONG_FIXTURE)
    genes = {r["gene_id"] for r in rows}
    samples = {r["sample"] for r in rows}
    assert (len(genes), len(samples), len(rows)) == (40, 60, 2400)
    # The same ids, so a gene picked on one tile is marked on the other, and
    # the 40 genes are the 40 best-ranked of the cohort.
    assert genes <= set(stats)
    assert {int(stats[g]["rank"]) for g in genes} == set(range(1, 41))
    for r in rows:
        assert r["stability_score"] == stats[r["gene_id"]]["stability_score"]


def test_the_suggester_ranks_the_kind_for_a_stability_table():
    suggestions = {s.viz_kind: s for s in suggest_viz_kinds(_schema(STATS_FIXTURE))}
    assert suggestions["ranked_distribution"].score > 0
