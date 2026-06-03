"""Tests for advanced-viz authoring ergonomics:

(a) role-name defaults — ``*_col`` fields default to their role name, so a
    config bound to a DC whose columns already match the canonical roles needs
    no explicit bindings;
(b) ``use: <tool>/<output>`` — expands at load time into ``viz_kind`` +
    ``config`` from the catalog output's advanced_viz ``renders_as`` entry.

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
    with pytest.raises(ValueError, match="has no output"):
        _component(use="qiime2/does_not_exist")


def test_use_bad_ref_format_raises():
    with pytest.raises(ValueError, match="must be '<tool>/<output>'"):
        _component(use="missingslash")


def test_no_use_still_requires_explicit_binding_path():
    """Without `use`, the classic explicit form still works."""
    c = _component(viz_kind="volcano", config={"viz_kind": "volcano", "feature_id_col": "id"})
    assert c.viz_kind == "volcano"
    assert c.config.feature_id_col == "id"
