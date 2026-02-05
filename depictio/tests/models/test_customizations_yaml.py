"""
Unit Tests for Figure Customizations YAML Integration.

Tests the YAML round-trip for customizations, preset resolution,
named references, linked sliders, and compound highlight conditions.

Note: Tests are split into two groups:
  - Lite model tests (FigureLiteComponent, DashboardDataLite YAML roundtrip) - no heavy deps
  - FigureCustomizations model tests - requires dash module imports (skipped if unavailable)
"""

from __future__ import annotations

import pytest

from depictio.models.components.lite import FigureLiteComponent
from depictio.models.models.dashboards import DashboardDataLite

# Conditionally import customization models (may not be available in all envs)
try:
    from depictio.dash.modules.figure_component.customizations.models import (
        AxesConfig,
        AxisConfig,
        FigureCustomizations,
        HighlightCondition,
        HighlightConditionOperator,
        HighlightConfig,
        HighlightLink,
        HighlightLinkType,
        HighlightStyle,
        ReferenceLineConfig,
        ReferenceLineType,
    )

    HAS_CUSTOMIZATION_MODELS = True
except ImportError:
    HAS_CUSTOMIZATION_MODELS = False

requires_customization_models = pytest.mark.skipif(
    not HAS_CUSTOMIZATION_MODELS,
    reason="Customization models not importable (missing dash dependencies)",
)


# ============================================================================
# Test FigureLiteComponent with Customizations
# ============================================================================


class TestFigureLiteComponentCustomizations:
    """Tests for FigureLiteComponent customizations field."""

    def test_figure_with_customizations_dict(self) -> None:
        """FigureLiteComponent should accept customizations as a dict."""
        comp = FigureLiteComponent(
            tag="volcano-1",
            visu_type="scatter",
            dict_kwargs={"x": "log2FC", "y": "neg_log10_pval"},
            customizations={
                "reference_lines": [
                    {"type": "hline", "y": 1.3, "line_color": "red"},
                ],
            },
        )
        assert comp.customizations is not None
        assert "reference_lines" in comp.customizations

    def test_figure_with_preset_customizations(self) -> None:
        """FigureLiteComponent should accept preset shorthand."""
        comp = FigureLiteComponent(
            tag="volcano-preset",
            visu_type="scatter",
            customizations={
                "preset": "volcano",
                "preset_params": {"significance_threshold": 0.01},
            },
        )
        assert comp.customizations is not None
        assert comp.customizations["preset"] == "volcano"

    def test_figure_without_customizations(self) -> None:
        """Customizations should be optional."""
        comp = FigureLiteComponent(tag="simple-scatter")
        assert comp.customizations is None

    def test_figure_with_linked_slider_in_customizations(self) -> None:
        """FigureLiteComponent should accept linked_slider in reference lines."""
        comp = FigureLiteComponent(
            tag="linked-figure",
            visu_type="scatter",
            dict_kwargs={"x": "fc", "y": "pval"},
            customizations={
                "reference_lines": [
                    {
                        "type": "hline",
                        "y": 1.3,
                        "linked_slider": "pvalue-slider",
                        "linked_highlights": [
                            {
                                "highlight_name": "upregulated",
                                "condition_name": "pvalue",
                                "transform": "inverse_log10",
                            },
                        ],
                    },
                ],
                "highlights": [
                    {
                        "name": "upregulated",
                        "conditions": [
                            {"name": "pvalue", "column": "pval", "operator": "lt", "value": 0.05},
                            {
                                "name": "condition",
                                "column": "group",
                                "operator": "eq",
                                "value": "treated",
                            },
                        ],
                        "logic": "and",
                        "style": {"marker_color": "red", "dim_opacity": 0.3},
                        "link_type": "dynamic",
                    },
                ],
            },
        )
        assert comp.customizations is not None
        refline = comp.customizations["reference_lines"][0]
        assert refline["linked_slider"] == "pvalue-slider"
        highlight = comp.customizations["highlights"][0]
        assert highlight["name"] == "upregulated"
        assert highlight["conditions"][1]["operator"] == "eq"
        assert highlight["link_type"] == "dynamic"


# ============================================================================
# Test YAML Roundtrip with Customizations
# ============================================================================


class TestYAMLRoundtripCustomizations:
    """Tests for YAML export/import with customizations."""

    def test_yaml_roundtrip_with_reflines(self) -> None:
        """YAML roundtrip should preserve reference lines."""
        original = DashboardDataLite(
            title="Roundtrip Test",
            components=[
                {
                    "tag": "scatter-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "col1", "y": "col2"},
                    "customizations": {
                        "reference_lines": [
                            {
                                "type": "hline",
                                "y": 0.05,
                                "line_color": "red",
                                "line_dash": "dash",
                                "annotation_text": "p = 0.05",
                            },
                        ],
                    },
                }
            ],
        )

        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        comp = restored.components[0]
        comp_dict = comp if isinstance(comp, dict) else comp.model_dump()
        assert "customizations" in comp_dict
        assert comp_dict["customizations"]["reference_lines"][0]["type"] == "hline"
        assert comp_dict["customizations"]["reference_lines"][0]["y"] == 0.05

    def test_yaml_roundtrip_with_highlights(self) -> None:
        """YAML roundtrip should preserve named highlights with conditions."""
        original = DashboardDataLite(
            title="Highlight Test",
            components=[
                {
                    "tag": "volcano-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "fc", "y": "pval"},
                    "customizations": {
                        "highlights": [
                            {
                                "name": "upregulated",
                                "conditions": [
                                    {
                                        "name": "pvalue",
                                        "column": "pval",
                                        "operator": "lt",
                                        "value": 0.05,
                                    },
                                    {
                                        "name": "condition",
                                        "column": "group",
                                        "operator": "eq",
                                        "value": "treated",
                                    },
                                ],
                                "logic": "and",
                                "style": {"marker_color": "red", "dim_opacity": 0.3},
                                "link_type": "dynamic",
                            }
                        ],
                    },
                }
            ],
        )

        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        comp = restored.components[0]
        comp_dict = comp if isinstance(comp, dict) else comp.model_dump()
        highlights = comp_dict["customizations"]["highlights"]
        assert highlights[0]["name"] == "upregulated"
        assert len(highlights[0]["conditions"]) == 2
        assert highlights[0]["conditions"][1]["operator"] == "eq"
        assert highlights[0]["link_type"] == "dynamic"

    def test_yaml_roundtrip_with_linked_slider(self) -> None:
        """YAML roundtrip should preserve linked_slider on reference lines."""
        original = DashboardDataLite(
            title="Slider Link Test",
            components=[
                {
                    "tag": "slider-1",
                    "component_type": "interactive",
                    "interactive_component_type": "RangeSlider",
                    "column_name": "pvalue",
                    "column_type": "float64",
                },
                {
                    "tag": "figure-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "fc", "y": "pval"},
                    "customizations": {
                        "reference_lines": [
                            {
                                "type": "hline",
                                "y": 1.3,
                                "linked_slider": "slider-1",
                                "linked_highlights": [
                                    {
                                        "highlight_name": "significant",
                                        "condition_name": "pvalue",
                                        "transform": "inverse_log10",
                                    }
                                ],
                            }
                        ],
                    },
                },
            ],
        )

        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        comps = restored.components
        figure_comp = comps[1] if isinstance(comps[1], dict) else comps[1].model_dump()
        refline = figure_comp["customizations"]["reference_lines"][0]
        assert refline["linked_slider"] == "slider-1"
        assert refline["linked_highlights"][0]["highlight_name"] == "significant"
        assert refline["linked_highlights"][0]["transform"] == "inverse_log10"

    def test_yaml_roundtrip_with_preset(self) -> None:
        """YAML roundtrip should preserve preset configuration."""
        original = DashboardDataLite(
            title="Preset Test",
            components=[
                {
                    "tag": "volcano-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "fc", "y": "pval"},
                    "customizations": {
                        "preset": "volcano",
                        "preset_params": {
                            "significance_threshold": 0.01,
                            "fold_change_threshold": 2.0,
                        },
                    },
                }
            ],
        )

        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        comp = restored.components[0]
        comp_dict = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp_dict["customizations"]["preset"] == "volcano"
        assert comp_dict["customizations"]["preset_params"]["significance_threshold"] == 0.01

    def test_to_full_preserves_customizations(self) -> None:
        """to_full() should preserve customizations in stored_metadata."""
        dash = DashboardDataLite(
            title="Full Test",
            components=[
                {
                    "tag": "fig-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "a", "y": "b"},
                    "customizations": {
                        "reference_lines": [{"type": "hline", "y": 0.05}],
                        "highlights": [
                            {
                                "name": "sig",
                                "conditions": [{"column": "p", "operator": "lt", "value": 0.05}],
                            }
                        ],
                    },
                }
            ],
        )
        full = dash.to_full()
        comp = full["stored_metadata"][0]
        assert "customizations" in comp
        assert comp["customizations"]["reference_lines"][0]["y"] == 0.05
        assert comp["customizations"]["highlights"][0]["name"] == "sig"

    def test_from_full_preserves_customizations(self) -> None:
        """from_full() should preserve customizations from stored_metadata."""
        full_dict: dict[str, object] = {
            "dashboard_id": "123",
            "title": "Test",
            "stored_metadata": [
                {
                    "index": "uuid-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "a", "y": "b"},
                    "customizations": {
                        "highlights": [
                            {
                                "name": "test",
                                "conditions": [{"column": "x", "operator": "gt", "value": 10}],
                            }
                        ],
                    },
                },
            ],
        }
        lite = DashboardDataLite.from_full(full_dict)
        comp = lite.components[0]
        comp_dict = comp if isinstance(comp, dict) else comp.model_dump()
        assert "customizations" in comp_dict
        assert comp_dict["customizations"]["highlights"][0]["name"] == "test"

    def test_yaml_excludes_empty_customizations(self) -> None:
        """YAML output should not include customizations when None."""
        dash = DashboardDataLite(
            title="No Customizations",
            components=[
                {
                    "tag": "fig-1",
                    "component_type": "figure",
                    "visu_type": "scatter",
                    "dict_kwargs": {"x": "a", "y": "b"},
                }
            ],
        )
        yaml_str = dash.to_yaml()
        assert "customizations" not in yaml_str


# ============================================================================
# Test Named References (requires customization models)
# ============================================================================


@requires_customization_models
class TestNamedReferences:
    """Tests for named highlight/condition references."""

    def test_highlight_with_name(self) -> None:
        """HighlightConfig should accept a name field."""
        highlight = HighlightConfig(
            name="upregulated",
            conditions=[
                HighlightCondition(
                    column="pvalue", operator=HighlightConditionOperator.LT, value=0.05
                ),
            ],
            style=HighlightStyle(marker_color="red"),
        )
        assert highlight.name == "upregulated"

    def test_condition_with_name(self) -> None:
        """HighlightCondition should accept a name field."""
        condition = HighlightCondition(
            name="pvalue",
            column="pvalue",
            operator=HighlightConditionOperator.LT,
            value=0.05,
        )
        assert condition.name == "pvalue"

    def test_highlight_link_by_name(self) -> None:
        """HighlightLink should support name-based references."""
        link = HighlightLink(
            highlight_name="upregulated",
            condition_name="pvalue",
            transform="inverse_log10",
        )
        assert link.highlight_name == "upregulated"
        assert link.condition_name == "pvalue"
        assert link.transform == "inverse_log10"

    def test_highlight_link_by_index(self) -> None:
        """HighlightLink should still support index-based references (legacy)."""
        link = HighlightLink(
            highlight_idx=0,
            condition_idx=1,
            transform="none",
        )
        assert link.highlight_idx == 0
        assert link.condition_idx == 1

    def test_negate_transform(self) -> None:
        """HighlightLink should support the 'negate' transform."""
        link = HighlightLink(
            highlight_name="downregulated",
            condition_name="fold_change",
            transform="negate",
        )
        assert link.transform == "negate"


# ============================================================================
# Test Linked Slider (requires customization models)
# ============================================================================


@requires_customization_models
class TestLinkedSlider:
    """Tests for reference line linked_slider field."""

    def test_refline_with_linked_slider(self) -> None:
        """ReferenceLineConfig should accept a linked_slider tag."""
        refline = ReferenceLineConfig(
            type=ReferenceLineType.HLINE,
            y=1.3,
            line_color="red",
            linked_slider="pvalue-slider",
        )
        assert refline.linked_slider == "pvalue-slider"

    def test_refline_without_linked_slider(self) -> None:
        """linked_slider should be optional."""
        refline = ReferenceLineConfig(
            type=ReferenceLineType.HLINE,
            y=0.05,
        )
        assert refline.linked_slider is None

    def test_refline_with_slider_and_highlights(self) -> None:
        """Reference line should support both linked_slider and linked_highlights."""
        refline = ReferenceLineConfig(
            type=ReferenceLineType.HLINE,
            y=1.3,
            linked_slider="pvalue-slider",
            linked_highlights=[
                HighlightLink(
                    highlight_name="upregulated",
                    condition_name="pvalue",
                    transform="inverse_log10",
                ),
            ],
        )
        assert refline.linked_slider == "pvalue-slider"
        assert refline.linked_highlights is not None
        assert len(refline.linked_highlights) == 1
        assert refline.linked_highlights[0].highlight_name == "upregulated"


# ============================================================================
# Test Preset Resolution (requires customization models)
# ============================================================================


@requires_customization_models
class TestPresetResolution:
    """Tests for FigureCustomizations preset system."""

    def test_preset_field(self) -> None:
        """FigureCustomizations should accept a preset field."""
        config = FigureCustomizations(preset="volcano")
        assert config.preset == "volcano"
        assert config.has_customizations()

    def test_resolve_volcano_preset(self) -> None:
        """Resolving volcano preset should produce reference lines and highlights."""
        config = FigureCustomizations(
            preset="volcano",
            preset_params={
                "significance_threshold": 0.05,
                "fold_change_threshold": 1.0,
            },
        )
        resolved = config.resolve_preset()
        assert resolved.reference_lines is not None
        assert len(resolved.reference_lines) >= 3  # p-value line + 2 FC lines
        assert resolved.highlights is not None
        assert len(resolved.highlights) >= 2  # up + down

    def test_resolve_threshold_preset(self) -> None:
        """Resolving threshold preset should produce a reference line."""
        config = FigureCustomizations(
            preset="threshold",
            preset_params={"threshold_value": 30, "axis": "y"},
        )
        resolved = config.resolve_preset()
        assert resolved.reference_lines is not None
        assert resolved.reference_lines[0].type == ReferenceLineType.HLINE

    def test_resolve_unknown_preset_raises(self) -> None:
        """Unknown preset should raise ValueError."""
        config = FigureCustomizations(preset="nonexistent")
        with pytest.raises(ValueError, match="Unknown preset"):
            config.resolve_preset()

    def test_resolve_no_preset_returns_self(self) -> None:
        """If no preset, resolve_preset should return self."""
        config = FigureCustomizations(
            reference_lines=[
                ReferenceLineConfig(type=ReferenceLineType.HLINE, y=0.05),
            ]
        )
        resolved = config.resolve_preset()
        assert resolved is config

    def test_preset_with_inline_overrides(self) -> None:
        """Inline fields should override preset defaults."""
        config = FigureCustomizations(
            preset="volcano",
            preset_params={"significance_threshold": 0.05},
            axes=AxesConfig(x=AxisConfig(title="Custom X Title")),
        )
        resolved = config.resolve_preset()
        assert resolved.axes is not None
        assert resolved.axes.x is not None
        assert resolved.axes.x.title == "Custom X Title"


# ============================================================================
# Test Compound Conditions (requires customization models)
# ============================================================================


@requires_customization_models
class TestCompoundConditions:
    """Tests for compound highlight conditions (numerical + categorical)."""

    def test_numerical_and_categorical_conditions(self) -> None:
        """Highlights should support mixing numerical and categorical conditions."""
        highlight = HighlightConfig(
            name="significant_treated",
            conditions=[
                HighlightCondition(
                    name="pvalue",
                    column="pvalue",
                    operator=HighlightConditionOperator.LT,
                    value=0.05,
                ),
                HighlightCondition(
                    name="condition",
                    column="condition",
                    operator=HighlightConditionOperator.EQ,
                    value="treated",
                ),
            ],
            logic="and",
            style=HighlightStyle(marker_color="red"),
            link_type=HighlightLinkType.DYNAMIC,
        )
        assert len(highlight.conditions) == 2
        assert highlight.conditions[0].operator == HighlightConditionOperator.LT
        assert highlight.conditions[1].operator == HighlightConditionOperator.EQ
        assert highlight.link_type == HighlightLinkType.DYNAMIC


# ============================================================================
# Test FigureCustomizations YAML Dict Methods (requires customization models)
# ============================================================================


@requires_customization_models
class TestFigureCustomizationsYAMLDict:
    """Tests for FigureCustomizations to_yaml_dict / from_yaml_dict."""

    def test_to_yaml_dict_with_named_highlights(self) -> None:
        """to_yaml_dict should include name fields."""
        config = FigureCustomizations(
            highlights=[
                HighlightConfig(
                    name="upregulated",
                    conditions=[
                        HighlightCondition(
                            name="pvalue",
                            column="pvalue",
                            operator=HighlightConditionOperator.LT,
                            value=0.05,
                        ),
                    ],
                    style=HighlightStyle(marker_color="red"),
                    link_type=HighlightLinkType.DYNAMIC,
                ),
            ],
        )
        yaml_dict = config.to_yaml_dict()
        assert yaml_dict["highlights"][0]["name"] == "upregulated"
        assert yaml_dict["highlights"][0]["conditions"][0]["name"] == "pvalue"
        assert yaml_dict["highlights"][0]["link_type"] == "dynamic"

    def test_from_yaml_dict_with_linked_slider(self) -> None:
        """from_yaml_dict should parse linked_slider correctly."""
        data = {
            "reference_lines": [
                {
                    "type": "hline",
                    "y": 1.3,
                    "linked_slider": "pvalue-slider",
                    "linked_highlights": [
                        {
                            "highlight_name": "sig",
                            "condition_name": "pval",
                            "transform": "inverse_log10",
                        }
                    ],
                }
            ],
        }
        config = FigureCustomizations.from_yaml_dict(data)
        assert config.reference_lines is not None
        refline = config.reference_lines[0]
        assert refline.linked_slider == "pvalue-slider"
        assert refline.linked_highlights is not None
        assert refline.linked_highlights[0].highlight_name == "sig"
