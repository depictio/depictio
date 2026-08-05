"""Phase 4: advanced_viz data-path kinds are served LIVE by the static runtime.

Three things move together and are pinned here:

1. **Classification** — the 18 advanced_viz kinds split three ways. The
   data-path kinds go live in both producers (the in-browser engine recomputes
   ``/advanced_viz/data`` from the bundled Parquet); the Celery-computed kinds
   have no in-browser equivalent, so producer B omits them and producer A
   pre-computes them at export time into a frozen payload; ``phylogenetic``
   also reads a non-tabular Newick DC, so producer A keeps freezing it and
   producer B — which has no frozen path — omits it.
2. **Column derivation** — one implementation (``pruning.advanced_viz_columns``)
   feeds both producer A's ``/advanced_viz/data`` request and producer B's
   column pruning, so the bundled Parquet carries exactly the columns the
   request would have asked for.
3. **Runtime limits** — the manifest pins the building instance's sampling
   ceilings, because the browser engine has no settings of its own.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.models.serverless import ComponentTier, RuntimeLimits, TierReason
from depictio.serverless.preflight import classify_component
from depictio.serverless.producer_a import (
    advanced_viz_request,
    celery_compute_request,
    classify_stored_component,
)
from depictio.serverless.producer_b import _runtime_limits, build_manifest
from depictio.serverless.pruning import (
    CELERY_VIZ_KINDS,
    NON_TABULAR_VIZ_KINDS,
    advanced_viz_columns,
    advanced_viz_kind,
    advanced_viz_roles,
    compute_column_sets,
    serves_advanced_viz_live,
)

# Every kind of depictio/models/components/types.py::AdvancedVizKind.
ALL_VIZ_KINDS = (
    "volcano",
    "embedding",
    "manhattan",
    "stacked_taxonomy",
    "phylogenetic",
    "rarefaction",
    "da_barplot",
    "enrichment",
    "complex_heatmap",
    "upset_plot",
    "ma",
    "dot_plot",
    "lollipop",
    "qq",
    "sunburst",
    "oncoplot",
    "coverage_track",
    "sankey",
)

# The 13 kinds served by the /advanced_viz/data path (everything the Celery
# dispatch does not compute), of which the 12 purely tabular ones go live.
DATA_PATH_KINDS = tuple(k for k in ALL_VIZ_KINDS if k not in CELERY_VIZ_KINDS)
LIVE_KINDS = tuple(k for k in DATA_PATH_KINDS if k not in NON_TABULAR_VIZ_KINDS)


def _spec_comp(kind: str, **config) -> dict:
    """A producer-B spec component (tags, not ids)."""
    return {
        "tag": f"av-{kind}",
        "component_type": "advanced_viz",
        "workflow_tag": "wf",
        "data_collection_tag": "dc",
        "viz_kind": kind,
        "config": {"viz_kind": kind, **(config or {"x_col": "a", "y_col": "b"})},
    }


def _stored_comp(kind: str, **config) -> dict:
    """A producer-A stored_metadata component (real ids)."""
    return {
        "index": f"av-{kind}",
        "component_type": "advanced_viz",
        "wf_id": "6" * 24,
        "dc_id": "7" * 24,
        "viz_kind": kind,
        "config": {"viz_kind": kind, **(config or {"x_col": "a", "y_col": "b"})},
    }


# ---------------------------------------------------------------------------
# Classification matrix
# ---------------------------------------------------------------------------


def test_the_three_kind_families_partition_every_kind():
    """No kind falls between the stools: 12 live, 5 Celery, 1 tree = 18."""
    celery = [k for k in ALL_VIZ_KINDS if k in CELERY_VIZ_KINDS]
    assert len(celery) == 5  # 'upset' is a legacy alias of 'upset_plot'
    assert NON_TABULAR_VIZ_KINDS == {"phylogenetic"}
    assert len(DATA_PATH_KINDS) == 13
    assert len(LIVE_KINDS) == 12
    assert set(LIVE_KINDS) | set(celery) | NON_TABULAR_VIZ_KINDS == set(ALL_VIZ_KINDS)


@pytest.mark.parametrize("kind", LIVE_KINDS)
def test_data_path_kinds_are_live_in_both_producers(kind: str):
    b_tier, b_reason, b_detail = classify_component(_spec_comp(kind))
    assert (b_tier, b_reason) == (ComponentTier.LIVE, None)
    assert b_detail and kind in b_detail

    a_tier, a_reason, a_detail = classify_stored_component(_stored_comp(kind))
    assert (a_tier, a_reason) == (ComponentTier.LIVE, None)
    assert a_detail and "in-browser engine" in a_detail

    assert serves_advanced_viz_live(_spec_comp(kind)) is True


@pytest.mark.parametrize("kind", sorted(CELERY_VIZ_KINDS))
def test_celery_kinds_stay_omitted_in_producer_b(kind: str):
    """Producer B builds from a spec with no instance behind it — there is
    nothing to run the compute on, and no frozen path to fall back to."""
    b_tier, b_reason, b_detail = classify_component(_spec_comp(kind))
    assert (b_tier, b_reason) == (ComponentTier.OMITTED, TierReason.CELERY_COMPUTE)
    assert b_detail and "Celery" in b_detail

    assert serves_advanced_viz_live(_spec_comp(kind)) is False


def test_producer_a_freezes_a_derivable_celery_compute():
    """A config the task can be called with freezes with ``celery_compute``."""
    comp = _stored_comp("complex_heatmap", index_column="sample_id", value_columns=["f0", "f1"])
    tier, reason, detail = classify_stored_component(comp)
    assert (tier, reason) == (ComponentTier.FROZEN, TierReason.CELERY_COMPUTE)
    assert detail and "computed at export time" in detail

    task, request = celery_compute_request(comp)
    assert task == "compute_complex_heatmap"
    assert request["index_column"] == "sample_id"
    assert request["value_columns"] == ["f0", "f1"]
    assert request["filter_metadata"] == []  # the default filter state


def test_producer_a_freezes_a_table_driven_embedding_via_the_data_path():
    """No ``compute_method`` ⇒ the renderer never dispatches: it reads
    dim_*_col off the table, so that is the path producer A freezes."""
    comp = _stored_comp("embedding", sample_id_col="sample_id", dim_1_col="d1", dim_2_col="d2")
    assert celery_compute_request(comp) is None
    tier, reason, detail = classify_stored_component(comp)
    assert (tier, reason) == (ComponentTier.FROZEN, TierReason.UNSUPPORTED)
    assert detail and "compute_method" in detail


@pytest.mark.parametrize(
    "kind,config",
    [
        ("sankey", {"x_col": "a"}),  # needs >= 2 step_cols
        ("coverage_track", {"x_col": "a"}),  # needs chromosome/position/value
    ],
)
def test_producer_a_omits_a_celery_kind_it_cannot_call(kind: str, config: dict):
    comp = _stored_comp(kind, **config)
    assert celery_compute_request(comp) is None
    tier, reason, detail = classify_stored_component(comp)
    assert (tier, reason) == (ComponentTier.OMITTED, TierReason.CELERY_COMPUTE)
    assert detail and "no request can be derived" in detail


def test_phylogenetic_is_frozen_by_a_and_omitted_by_b():
    """Its Newick tree DC is a second, non-tabular source: producer A merges it
    into the frozen payload, producer B has no frozen path at all."""
    config = {"leaf_col": "tip", "tree_dc_id": "8" * 24}

    b_tier, b_reason, b_detail = classify_component(_spec_comp("phylogenetic", **config))
    assert (b_tier, b_reason) == (ComponentTier.OMITTED, TierReason.UNSUPPORTED)
    assert b_detail and "Newick" in b_detail

    a_tier, a_reason, a_detail = classify_stored_component(_stored_comp("phylogenetic", **config))
    assert (a_tier, a_reason) == (ComponentTier.FROZEN, TierReason.UNSUPPORTED)
    assert a_detail and "Newick" in a_detail

    assert serves_advanced_viz_live(_spec_comp("phylogenetic", **config)) is False


def test_a_config_binding_no_column_degrades_in_both_producers():
    """Nothing to project ⇒ nothing to serve live (and nothing to freeze)."""
    spec_comp = {
        "tag": "av-empty",
        "component_type": "advanced_viz",
        "workflow_tag": "wf",
        "data_collection_tag": "dc",
        "viz_kind": "volcano",
        "config": {"viz_kind": "volcano", "top_n": 20},
    }
    tier, reason, detail = classify_component(spec_comp)
    assert (tier, reason) == (ComponentTier.OMITTED, TierReason.UNSUPPORTED)
    assert detail and "binds no column" in detail

    stored = {"index": "av-empty", "component_type": "advanced_viz", "viz_kind": "volcano"}
    tier, reason, detail = classify_stored_component(stored)
    assert (tier, reason) == (ComponentTier.OMITTED, TierReason.UNSUPPORTED)
    assert detail and "no derivable request" in detail


def test_producer_b_omits_an_advanced_viz_without_a_data_collection():
    comp = {"tag": "av-nodc", "component_type": "advanced_viz", "viz_kind": "volcano"}
    tier, reason, detail = classify_component(comp)
    assert (tier, reason) == (ComponentTier.OMITTED, TierReason.UNSUPPORTED)
    assert detail and "no resolvable data collection" in detail


# ---------------------------------------------------------------------------
# Column / role derivation (one implementation, both producers)
# ---------------------------------------------------------------------------


def test_columns_come_from_col_scalars_and_rank_cols_deduplicated():
    comp = {
        "component_type": "advanced_viz",
        "config": {
            "viz_kind": "sunburst",
            "rank_cols": ["Phylum", "Genus", "Phylum"],  # duplicate inside the list
            "abundance_col": "rel_abundance",
            "sample_id_col": "Phylum",  # duplicate across roles
            "top_n": 15,  # scalar, not a column
            "normalise_to_one": True,  # scalar, not a column
            "sort_by": "abundance",  # does NOT end in _col
            "category_palette": {"a": "#fff"},  # non-str value
        },
    }
    # Config order, first occurrence wins.
    assert advanced_viz_columns(comp) == ["Phylum", "Genus", "rel_abundance"]
    # rank_cols carries no role — it is a hierarchy, not a single binding.
    assert advanced_viz_roles(comp) == {"abundance": "rel_abundance", "sample_id": "Phylum"}
    assert advanced_viz_kind(comp) == "sunburst"


def test_columns_include_the_switchable_metric_options_of_a_rarefaction():
    """Regression: a rarefaction's metric tabs switch between COLUMNS, listed in
    ``metric_options``. Dropping them left every tab rendering ``metric_col``
    (``rows[activeMetric] || rows[config.metric_col]``) — a wrong-but-plausible
    plot, which is exactly what the tiering exists to prevent."""
    comp = {
        "component_type": "advanced_viz",
        "config": {
            "viz_kind": "rarefaction",
            "sample_id_col": "sample_id",
            "depth_col": "depth",
            "metric_col": "shannon",
            "iter_col": "iter",
            "group_col": "group",
            "metric_options": ["shannon", "observed_features", "faith_pd"],
            "show_ci": True,
        },
    }
    columns = advanced_viz_columns(comp)
    assert set(columns) >= {"shannon", "observed_features", "faith_pd"}
    assert columns == [
        "sample_id",
        "depth",
        "shannon",
        "iter",
        "group",
        "observed_features",
        "faith_pd",
    ]
    # A switchable set carries no single binding, so it adds no role.
    assert "metric_options" not in advanced_viz_roles(comp)
    assert advanced_viz_roles(comp)["metric"] == "shannon"


@pytest.mark.parametrize(
    "config,expected",
    [
        # Every list-of-columns key of the config models, and the one scalar
        # that names a column without the `_col` spelling.
        ({"step_cols": ["a", "b"], "available_step_cols": ["a", "b", "c"]}, {"a", "b", "c"}),
        ({"row_annotation_cols": ["k"], "value_columns": ["v1", "v2"]}, {"k", "v1", "v2"}),
        (
            {"set_columns": ["s1", "s2"], "default_annotation_cols": ["taxon"]},
            {"s1", "s2", "taxon"},
        ),
        ({"color_by_columns": ["c1"], "extra_color_cols": ["c2"]}, {"c1", "c2"}),
        ({"index_column": "Phylum"}, {"Phylum"}),
        # …and the value lists that are NOT columns stay out.
        ({"chromosomes_filter": ["chr1"], "samples_filter": ["S1"]}, set()),
        ({"set_colors": {"Soil": "#fff"}, "top_n": 20, "sort_by": "abundance"}, set()),
    ],
)
def test_column_keys_are_recognised_by_their_naming_family(config: dict, expected: set[str]):
    comp = {"component_type": "advanced_viz", "config": {"viz_kind": "x", **config}}
    assert set(advanced_viz_columns(comp)) == expected


def test_kind_reads_the_top_level_field_before_the_config_blob():
    assert advanced_viz_kind({"viz_kind": "ma", "config": {"viz_kind": "volcano"}}) == "ma"
    assert advanced_viz_kind({"config": {"viz_kind": "volcano"}}) == "volcano"
    assert advanced_viz_kind({}) == ""


def test_producer_a_request_delegates_to_the_shared_derivation():
    """``advanced_viz_request`` must ask for exactly what pruning bundles."""
    comp = _stored_comp("sunburst", rank_cols=["species", "island"], abundance_col="body_mass_g")
    request = advanced_viz_request(comp)
    assert request is not None
    assert request["columns"] == advanced_viz_columns(comp) == ["species", "island", "body_mass_g"]
    assert request["roles"] == advanced_viz_roles(comp) == {"abundance": "body_mass_g"}
    assert request["viz_kind"] == "sunburst"
    assert request["filter_metadata"] == []


# ---------------------------------------------------------------------------
# Pruning: a live advanced_viz contributes its columns to its DC
# ---------------------------------------------------------------------------


def _spec(components: list[dict]) -> DashboardDataLite:
    return DashboardDataLite.model_validate({"title": "av", "components": components})


def test_pruning_unions_advanced_viz_columns_with_the_other_consumers():
    spec = _spec(
        [
            _spec_comp("sunburst", rank_cols=["species", "island"], abundance_col="mass"),
            {
                "tag": "card-1",
                "component_type": "card",
                "workflow_tag": "wf",
                "data_collection_tag": "dc",
                "aggregation": "average",
                "column_name": "bill",
                "column_type": "float64",
            },
        ]
    )
    assert compute_column_sets(spec) == {"wf:dc": {"species", "island", "mass", "bill"}}


def test_pruning_ignores_celery_and_phylogenetic_advanced_viz():
    """They are omitted, so they must not conjure a DC entry of their own."""
    spec = _spec(
        [
            _spec_comp("embedding", embedding_col="umap"),
            _spec_comp("phylogenetic", leaf_col="tip", tree_dc_id="8" * 24),
        ]
    )
    assert compute_column_sets(spec) == {}


def test_a_table_on_the_same_dc_still_widens_to_keep_all():
    spec = _spec(
        [
            _spec_comp("dot_plot", cluster_col="g", gene_col="f"),
            {
                "tag": "tbl",
                "component_type": "table",
                "workflow_tag": "wf",
                "data_collection_tag": "dc",
            },
        ]
    )
    assert compute_column_sets(spec) == {"wf:dc": None}


# ---------------------------------------------------------------------------
# End-to-end (producer B): the bundle carries the derived columns and no
# frozen payload
# ---------------------------------------------------------------------------


@pytest.fixture
def av_data_dir(tmp_path: Path) -> Path:
    (tmp_path / "wf").mkdir()
    pl.DataFrame(
        {
            "species": ["a", "b", "a"],
            "island": ["x", "y", "x"],
            "mass": [1.0, 2.0, 3.0],
            "unused": [7, 8, 9],
        }
    ).write_parquet(tmp_path / "wf" / "dc.parquet")
    return tmp_path


def test_live_advanced_viz_bundles_its_columns_and_freezes_nothing(av_data_dir: Path):
    spec = _spec([_spec_comp("sunburst", rank_cols=["species", "island"], abundance_col="mass")])
    manifest = build_manifest(spec, av_data_dir).manifest

    entry = manifest.tiers["av-sunburst"]
    assert entry.tier is ComponentTier.LIVE
    assert entry.reason is None
    # No frozen payload: the runtime recomputes the payload at every filter state.
    assert manifest.frozen == {}
    assert manifest.bindings == {}

    ref = next(iter(manifest.data_refs.values()))
    # Exactly the derived columns — `unused` is nobody's binding.
    assert {c.name for c in ref.columns} == {"species", "island", "mass"}
    assert ref.rows == 3
    assert manifest.inline_blobs[ref.uri.removeprefix("inline:")]


def test_omitted_advanced_viz_bundles_no_data(av_data_dir: Path):
    """A Celery kind is omitted, so its DC is never read at all."""
    spec = _spec([_spec_comp("embedding", embedding_col="species")])
    manifest = build_manifest(spec, av_data_dir).manifest
    assert manifest.tiers["av-embedding"].tier is ComponentTier.OMITTED
    assert manifest.data_refs == {} and manifest.inline_blobs == {}


# ---------------------------------------------------------------------------
# Runtime limits pinned from the building instance
# ---------------------------------------------------------------------------


def test_runtime_limits_mirror_the_instance_performance_config():
    from depictio.api.v1.configs.config import settings

    perf = settings.performance
    assert _runtime_limits() == RuntimeLimits(
        figure_max_points=perf.figure_max_points,
        advanced_viz_no_sample_max_rows=perf.advanced_viz_no_sample_max_rows,
        advanced_viz_tail_p_threshold=perf.advanced_viz_tail_p_threshold,
        advanced_viz_tail_effect_threshold=perf.advanced_viz_tail_effect_threshold,
    )


def test_manifest_pins_the_tuned_limits(av_data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """The browser engine has no settings of its own — a tuned instance must
    hand its ceilings to the bundle, not the schema defaults."""
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.performance, "figure_max_points", 1_234)
    monkeypatch.setattr(settings.performance, "advanced_viz_no_sample_max_rows", 5_000)
    monkeypatch.setattr(settings.performance, "advanced_viz_tail_p_threshold", 0.01)
    monkeypatch.setattr(settings.performance, "advanced_viz_tail_effect_threshold", 2.5)

    spec = _spec([_spec_comp("sunburst", rank_cols=["species", "island"], abundance_col="mass")])
    limits = build_manifest(spec, av_data_dir).manifest.limits
    assert limits.figure_max_points == 1_234
    assert limits.advanced_viz_no_sample_max_rows == 5_000
    assert limits.advanced_viz_tail_p_threshold == 0.01
    assert limits.advanced_viz_tail_effect_threshold == 2.5
