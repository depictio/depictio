"""`UpsetPlotConfig` names its sets by list or by pattern, never both.

A template whose set columns are one per sample of the run cannot list them:
a list written against one run fails on every other. The pattern is the field
that makes such a template portable, so these tests pin that it is accepted,
that it must compile, and that it cannot be combined with a list.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import UpsetPlotConfig, VizConfig


def test_pattern_is_accepted() -> None:
    cfg = UpsetPlotConfig(set_columns_pattern=r"\.mLb\.clN$")
    assert cfg.set_columns_pattern == r"\.mLb\.clN$"
    assert cfg.set_columns is None


def test_neither_field_still_means_auto_detect() -> None:
    cfg = UpsetPlotConfig()
    assert cfg.set_columns is None
    assert cfg.set_columns_pattern is None


def test_explicit_list_is_still_accepted() -> None:
    assert UpsetPlotConfig(set_columns=["a", "b"]).set_columns == ["a", "b"]


def test_list_and_pattern_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        UpsetPlotConfig(set_columns=["a"], set_columns_pattern="a")


def test_pattern_must_compile() -> None:
    with pytest.raises(ValidationError, match="regular expression"):
        UpsetPlotConfig(set_columns_pattern="(unclosed")


def test_empty_pattern_is_rejected() -> None:
    # An empty pattern matches every binary column, which is auto-detect with
    # extra steps; omit the field instead.
    with pytest.raises(ValidationError):
        UpsetPlotConfig(set_columns_pattern="")


def test_pattern_survives_the_viz_config_union() -> None:
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "upset_plot", "set_columns_pattern": r"_R\d+$"}
    )
    assert isinstance(cfg, UpsetPlotConfig)
    assert cfg.set_columns_pattern == r"_R\d+$"


# --- Set colours and the intersection selection ------------------------------
#
# Both are YAML keys a dashboard writes, and the config is `extra="forbid"`: a
# key with no field makes the component unloadable on import. These pin that
# they validate, that the selection cannot be switched on without saying what
# it emits, and that they come back out of an export.


def test_colour_and_selection_keys_are_off_by_default() -> None:
    cfg = UpsetPlotConfig()
    assert cfg.set_category_column is None
    assert cfg.selection_enabled is False
    assert cfg.selection_column is None


def test_selection_and_set_category_column_are_accepted() -> None:
    cfg = TypeAdapter(VizConfig).validate_python(
        {
            "viz_kind": "upset_plot",
            "set_category_column": "locality",
            "selection_enabled": True,
            "selection_column": "Phylum",
        }
    )
    assert isinstance(cfg, UpsetPlotConfig)
    assert cfg.set_category_column == "locality"
    assert cfg.selection_enabled is True
    assert cfg.selection_column == "Phylum"


def test_selection_needs_a_column() -> None:
    # Nothing else names the matrix's element column, so this would validate,
    # persist, and leave every intersection unclickable.
    with pytest.raises(ValidationError, match="selection_enabled needs selection_column"):
        UpsetPlotConfig(selection_enabled=True)


def test_a_column_without_the_opt_in_stays_inert_but_valid() -> None:
    cfg = UpsetPlotConfig(selection_column="Phylum")
    assert cfg.selection_enabled is False


def test_selection_column_cannot_be_a_set() -> None:
    with pytest.raises(ValidationError, match="is one of the set columns"):
        UpsetPlotConfig(
            set_columns=["Athens", "Naples"], selection_enabled=True, selection_column="Naples"
        )


@pytest.mark.parametrize("key", ["set_category_column", "selection_column"])
def test_empty_column_names_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        UpsetPlotConfig(**{key: ""})


def test_new_keys_survive_a_dashboard_yaml_round_trip() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    yaml_in = """
title: Community
components:
  - component_type: advanced_viz
    workflow_tag: ampliseq
    data_collection_tag: upset_canonical
    viz_kind: upset_plot
    index: adv-upset
    config:
      viz_kind: upset_plot
      color_intersections_by: set
      set_category_column: locality
      selection_enabled: true
      selection_column: Phylum
"""
    exported = DashboardDataLite.from_yaml(yaml_in).to_yaml()
    for line in (
        "set_category_column: locality",
        "selection_enabled: true",
        "selection_column: Phylum",
    ):
        assert line in exported

    back = DashboardDataLite.from_yaml(exported).components[0]
    cfg = back.config  # type: ignore[union-attr]
    assert isinstance(cfg, UpsetPlotConfig)
    assert (cfg.set_category_column, cfg.selection_enabled, cfg.selection_column) == (
        "locality",
        True,
        "Phylum",
    )

    stored = DashboardDataLite.from_yaml(yaml_in).to_full()["stored_metadata"][0]["config"]
    assert stored["selection_column"] == "Phylum"
    assert stored["set_category_column"] == "locality"
