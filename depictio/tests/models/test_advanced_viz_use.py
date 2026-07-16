"""Tests for advanced-viz authoring ergonomics:

(a) role-name defaults — ``*_col`` fields default to their role name, so a
    config bound to a DC whose columns already match the canonical roles needs
    no explicit bindings;
(b) ``use: <tool>/<ref>`` — expands at load time into ``viz_kind`` + ``config``
    from a catalog advanced_viz ``renders_as`` entry. ``<ref>`` is a render id
    (``ivar/manhattan``) or, for back-compat, an output id (``qiime2/ancombc``
    + a ``viz_kind`` to disambiguate).

Pure-model + catalog tests — no numpy/polars/DB, so they run in any env.
"""

import pytest

from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.models.components.advanced_viz.configs import (
    CoverageTrackConfig,
    DaBarplotConfig,
    LollipopConfig,
    ManhattanConfig,
    QQConfig,
    VolcanoConfig,
)

# ---------------------------------------------------------------------------
# (a) role-name defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "config_cls, field, expected",
    [
        (VolcanoConfig, "feature_id_col", "feature_id"),
        (VolcanoConfig, "effect_size_col", "effect_size"),
        (VolcanoConfig, "significance_col", "significance"),
        (CoverageTrackConfig, "chromosome_col", "chromosome"),
        (CoverageTrackConfig, "position_col", "position"),
        (CoverageTrackConfig, "value_col", "value"),
        (ManhattanConfig, "chr_col", "chr"),
        (LollipopConfig, "category_col", "category"),
        (DaBarplotConfig, "contrast_col", "contrast"),
        (QQConfig, "p_value_col", "p_value"),
    ],
)
def test_col_fields_default_to_role_name(config_cls, field, expected):
    """A config instantiates without explicit *_col; each defaults to its role."""
    cfg = config_cls()  # no bindings supplied
    assert getattr(cfg, field) == expected


# ---------------------------------------------------------------------------
# (b) `use: <tool>/<output>` catalog expansion
# ---------------------------------------------------------------------------


def _component(**kw):
    kw.setdefault("workflow_tag", "wf")
    kw.setdefault("data_collection_tag", "dc")
    return AdvancedVizLiteComponent(**kw)


def test_use_single_render_infers_kind_and_roles():
    """An output with one advanced_viz render: kind inferred, roles inherited."""
    c = _component(use="mosdepth/genome_coverage")
    assert c.viz_kind == "coverage_track"
    assert c.config.chromosome_col == "chromosome"
    assert c.config.value_col == "value"


def test_use_render_id_resolves_directly():
    """A render id is a first-class handle: no viz_kind needed, roles inherited."""
    c = _component(use="qiime2/volcano")
    assert c.viz_kind == "volcano"
    assert c.config.feature_id_col == "id"
    assert c.config.effect_size_col == "lfc"
    assert c.config.significance_col == "q_val"


def test_use_render_id_disambiguates_multi_kind_output():
    """ivar/variants_long renders 3 kinds; each render id picks one directly."""
    assert _component(use="ivar/manhattan").viz_kind == "manhattan"
    assert _component(use="ivar/lollipop").viz_kind == "lollipop"
    assert _component(use="ivar/oncoplot").viz_kind == "oncoplot"


def test_use_render_id_disambiguates_same_kind_across_outputs():
    """Same kind in two outputs → distinct render ids select the right columns."""
    canonical = _component(use="qiime2/rarefaction")  # rarefaction_canonical
    alpha = _component(use="qiime2/rarefaction_alpha")  # alpha_rarefaction
    assert canonical.viz_kind == alpha.viz_kind == "rarefaction"
    assert canonical.config.metric_col == "shannon"
    assert alpha.config.metric_col == "faith_pd"


def test_use_multi_render_requires_viz_kind():
    """An output rendering several kinds is ambiguous without viz_kind."""
    with pytest.raises(ValueError, match="multiple kinds"):
        _component(use="qiime2/ancombc")


def test_use_multi_render_with_viz_kind_maps_catalog_roles():
    """viz_kind picks the render; roles come from the catalog (feature_id→id…)."""
    c = _component(use="qiime2/ancombc", viz_kind="volcano")
    assert c.viz_kind == "volcano"
    assert c.config.feature_id_col == "id"
    assert c.config.effect_size_col == "lfc"
    assert c.config.significance_col == "q_val"


def test_use_user_config_overrides_inherited_binding():
    """An explicit config value wins over the catalog-inherited one."""
    c = _component(use="qiime2/ancombc", viz_kind="qq", config={"p_value_col": "custom_p"})
    assert c.config.p_value_col == "custom_p"


def test_use_unknown_tool_raises():
    with pytest.raises(ValueError, match="unknown catalog tool"):
        _component(use="nope/x")


def test_use_unknown_output_raises():
    with pytest.raises(ValueError, match="has no render id or output"):
        _component(use="qiime2/does_not_exist")


def test_use_bad_ref_format_raises():
    with pytest.raises(ValueError, match="must be '<tool>/"):
        _component(use="missingslash")


def test_no_use_still_requires_explicit_binding_path():
    """Without `use`, the classic explicit form still works."""
    c = _component(viz_kind="volcano", config={"viz_kind": "volcano", "feature_id_col": "id"})
    assert c.viz_kind == "volcano"
    assert c.config.feature_id_col == "id"


# ---------------------------------------------------------------------------
# (c) `use:` for non-advanced_viz kinds (multiqc / card / figure / table /
#     interactive) — expanded via DashboardDataLite before union discrimination.
# ---------------------------------------------------------------------------


def _tile(**kw):
    """Parse a single tile through the dashboard's `use:` expansion + routing."""
    from depictio.models.models.dashboards import DashboardDataLite

    kw.setdefault("workflow_tag", "wf")
    return DashboardDataLite(title="t", components=[kw]).components[0]


def test_use_multiqc_inherits_module_and_keeps_plot():
    c = _tile(
        use="multiqc/fastqc",
        data_collection_tag="multiqc_data",
        config={"selected_plot": "Status Checks"},
    )
    assert type(c).__name__ == "MultiQCLiteComponent"
    assert c.selected_module == "fastqc" and c.selected_plot == "Status Checks"


def test_use_card_inherits_column_and_aggregation():
    c = _tile(use="pangolin/lineage_count", data_collection_tag="pangolin_lineages")
    assert type(c).__name__ == "CardLiteComponent"
    assert c.column_name == "lineage" and c.aggregation == "nunique"


def test_use_card_explicit_field_overrides_catalog_default():
    """A tile's own top-level value wins over the catalog render default."""
    c = _tile(use="qiime2/shannon_card", data_collection_tag="alpha", aggregation="median")
    assert c.column_name == "shannon" and c.aggregation == "median"  # catalog avg overridden


def test_use_figure_inherits_code_mode_body():
    c = _tile(use="ivar/variants_by_gene", data_collection_tag="variants_long")
    assert type(c).__name__ == "FigureLiteComponent"
    assert c.mode == "code" and "group_by" in (c.code_content or "")


def test_use_table_routes_to_table_component():
    c = _tile(use="ivar/table", data_collection_tag="variants_long")
    assert type(c).__name__ == "TableLiteComponent"


def test_use_interactive_inherits_type_and_column():
    c = _tile(use="ivar/af_slider", data_collection_tag="variants_long")
    assert type(c).__name__ == "InteractiveLiteComponent"
    assert c.interactive_component_type == "RangeSlider" and c.column_name == "AF"
