"""The export capability matrix must stay complete and honest.

The parametrised completeness tests are the highest-leverage ones here: adding a
component type or an advanced-viz kind without classifying it breaks CI, which is
the only reliable defence against the matrix silently going stale.
"""

from __future__ import annotations

from typing import get_args

import pytest

from depictio.api.v1.services.export.capabilities import (
    AV_JSON_SOURCE,
    COMPONENT_FORMATS,
    ExportFormat,
    advanced_viz_json_source,
    formats_for,
    resolve_viz_kind,
    unsupported_reason,
)
from depictio.models.components.types import AdvancedVizKind, ComponentType


@pytest.mark.parametrize("component_type", get_args(ComponentType))
def test_every_component_type_is_classified(component_type: str) -> None:
    assert component_type in COMPONENT_FORMATS, (
        f"{component_type!r} has no export classification — add it to COMPONENT_FORMATS."
    )


@pytest.mark.parametrize("viz_kind", get_args(AdvancedVizKind))
def test_every_viz_kind_is_classified(viz_kind: str) -> None:
    assert viz_kind in AV_JSON_SOURCE, (
        f"{viz_kind!r} has no JSON-source classification — add it to AV_JSON_SOURCE."
    )


def test_legacy_alias_resolves() -> None:
    """`ancombc_differentials` still appears in persisted metadata."""
    assert resolve_viz_kind("ancombc_differentials") == "da_barplot"
    assert advanced_viz_json_source("ancombc_differentials") is not None


def test_plotly_backed_types_support_both_formats() -> None:
    for component_type in ("figure", "map", "multiqc"):
        assert formats_for(component_type) == {ExportFormat.JSON, ExportFormat.HTML}


def test_non_plotly_types_are_html_only() -> None:
    for component_type in ("table", "card", "image", "interactive", "text"):
        assert formats_for(component_type) == {ExportFormat.HTML}
        reason = unsupported_reason(component_type)
        assert reason and "format=html" in reason


def test_jbrowse_supports_nothing() -> None:
    assert formats_for("jbrowse") == frozenset()
    reason = unsupported_reason("jbrowse")
    assert reason and "iframe" in reason


def test_server_side_advanced_viz_kinds_support_json() -> None:
    for kind in ("complex_heatmap", "upset_plot", "sankey"):
        assert ExportFormat.JSON in formats_for("advanced_viz", kind)
        assert advanced_viz_json_source(kind) == "celery"


def test_ported_advanced_viz_kinds_support_json() -> None:
    """Kinds with a Python builder are JSON-exportable without a matrix edit."""
    from depictio.api.v1.services.advanced_viz.figure_registry import supported_kinds

    ported = supported_kinds()
    assert ported, "expected at least one ported advanced_viz kind"
    for kind in ported:
        assert advanced_viz_json_source(kind) == "python"
        assert ExportFormat.JSON in formats_for("advanced_viz", kind)


def test_unported_advanced_viz_kind_is_html_only_and_says_why() -> None:
    from depictio.api.v1.services.advanced_viz.figure_registry import supported_kinds

    unported = [
        k
        for k, source in AV_JSON_SOURCE.items()
        if source == "client_only" and k not in supported_kinds()
    ]
    assert unported, "expected some kinds to still be client-only"
    kind = unported[0]
    assert formats_for("advanced_viz", kind) == {ExportFormat.HTML}
    reason = unsupported_reason("advanced_viz", kind)
    assert reason and "format=html" in reason and kind in reason


def test_unknown_inputs_do_not_raise() -> None:
    assert formats_for("not_a_type") == frozenset()
    assert advanced_viz_json_source("not_a_kind") is None
    assert "Unknown component type" in (unsupported_reason("not_a_type") or "")
    assert "Unknown advanced_viz kind" in (unsupported_reason("advanced_viz", "nope") or "")


# --- filter options ---------------------------------------------------------


class TestFilterOptionShapes:
    """The two shapes an external control needs, and the degradation contract.

    A manifest that 500s because one column could not be read is worse than one
    that omits its options, so every failure path here must return None.
    """

    def test_categorical_controls_are_classified_as_such(self) -> None:
        from depictio.api.v1.services.export.filter_options import (
            _CATEGORICAL_TYPES,
            _RANGE_TYPES,
        )

        assert {"Select", "MultiSelect", "SegmentedControl"} <= _CATEGORICAL_TYPES
        assert {"Slider", "RangeSlider", "DateRangePicker", "Timeline"} <= _RANGE_TYPES
        assert not (_CATEGORICAL_TYPES & _RANGE_TYPES), "a control is one or the other"

    def test_column_specs_reads_both_api_shapes(self) -> None:
        """`/deltatables/specs` returns a list; other call sites hand back a dict."""
        from depictio.api.v1.services.export.filter_options import _column_specs

        as_list = [{"name": "abundance", "specs": {"min": 0.0, "max": 1.0}}]
        assert _column_specs(as_list, "abundance") == {"min": 0.0, "max": 1.0}

        as_dict = {"abundance": {"specs": {"min": 0.0, "max": 1.0}}}
        assert _column_specs(as_dict, "abundance") == {"min": 0.0, "max": 1.0}

        assert _column_specs(as_list, "missing") == {}
        assert _column_specs(None, "abundance") == {}

    @pytest.mark.asyncio
    async def test_non_filter_components_have_no_options(self) -> None:
        from depictio.api.v1.services.export.filter_options import filter_options

        assert await filter_options({"component_type": "figure"}, None) is None
        assert (
            await filter_options(
                {"interactive_component_type": "MultiSelect", "column_name": None}, None
            )
            is None
        )


# --- per-component formats (views, GenomeSpy, interaction-driven kinds) -------


def _av_component(viz_kind: str, **config) -> dict:
    return {
        "component_type": "advanced_viz",
        "viz_kind": viz_kind,
        "config": {"viz_kind": viz_kind, **config},
    }


class TestComponentFormats:
    def test_the_view_decides_json_for_a_survivor(self) -> None:
        """dot_plot has no builder; its enrichment view has one."""
        from depictio.api.v1.services.export.capabilities import component_formats

        dotplot = _av_component("dot_plot")
        enrichment = _av_component("dot_plot", view="enrichment")
        assert ExportFormat.JSON not in component_formats(dotplot)
        assert ExportFormat.JSON in component_formats(enrichment)
        assert ExportFormat.JSON in component_formats(dotplot, {"view": "enrichment"})

    def test_retired_kind_exports_as_its_view(self) -> None:
        from depictio.api.v1.services.export.capabilities import component_formats

        assert ExportFormat.JSON in component_formats(_av_component("enrichment"))
        assert ExportFormat.JSON in component_formats(_av_component("roc_pr_curve"))

    @pytest.mark.parametrize(
        "kind",
        [
            "genome_view",
            "contact_map",
            "group_compare",
            "molecule_3d",
            "pae_matrix",
            "ramachandran",
        ],
    )
    def test_kinds_the_offline_bundle_cannot_serve_have_no_html(self, kind: str) -> None:
        from depictio.api.v1.services.export.capabilities import (
            component_formats,
            component_html_unavailable_reason,
        )

        component = _av_component(kind)
        assert ExportFormat.HTML not in component_formats(component)
        assert component_html_unavailable_reason(component)

    @pytest.mark.parametrize(
        "kind",
        [
            "molecule_3d",
            "msa",
            "sequence_track",
            "hmm_logo",
            "secondary_structure",
            "domain_architecture",
            "pae_matrix",
            "ramachandran",
        ],
    )
    def test_protein_kinds_are_drawn_in_the_browser_only(self, kind: str) -> None:
        from depictio.api.v1.services.export.capabilities import HTML_UNAVAILABLE_KINDS

        assert AV_JSON_SOURCE[kind] == "client_only"
        assert advanced_viz_json_source(kind) == "client_only"
        assert ExportFormat.JSON not in formats_for("advanced_viz", kind)
        reason = unsupported_reason("advanced_viz", kind)
        assert reason
        # The reason JSON is refused is the HTML one only when the bundle cannot serve the kind.
        if kind in HTML_UNAVAILABLE_KINDS:
            assert reason == HTML_UNAVAILABLE_KINDS[kind]
            assert ExportFormat.HTML not in formats_for("advanced_viz", kind)
        else:
            assert "format=html" in reason
            assert ExportFormat.HTML in formats_for("advanced_viz", kind)

    def test_ideogram_is_drawn_in_the_browser_and_embeds_as_html(self) -> None:
        """A hand-drawn SVG reading its own rows: no JSON spec, but the offline
        bundle carries the rows, so the HTML export renders it."""
        from depictio.api.v1.services.export.capabilities import (
            HTML_UNAVAILABLE_KINDS,
            component_formats,
        )

        assert AV_JSON_SOURCE["ideogram"] == "client_only"
        assert "ideogram" not in HTML_UNAVAILABLE_KINDS
        assert ExportFormat.JSON not in formats_for("advanced_viz", "ideogram")
        assert ExportFormat.HTML in formats_for("advanced_viz", "ideogram")
        assert ExportFormat.HTML in component_formats(_av_component("ideogram", mode="density"))

    def test_only_the_protein_kinds_that_fetch_a_file_lack_html(self) -> None:
        from depictio.api.v1.services.export.capabilities import HTML_UNAVAILABLE_KINDS

        protein = {
            "molecule_3d",
            "msa",
            "sequence_track",
            "hmm_logo",
            "secondary_structure",
            "domain_architecture",
            "pae_matrix",
            "ramachandran",
        }
        assert protein & set(HTML_UNAVAILABLE_KINDS) == {
            "molecule_3d",
            "pae_matrix",
            "ramachandran",
        }
        for kind in ("pae_matrix", "ramachandran"):
            assert "Open the dashboard instead" in HTML_UNAVAILABLE_KINDS[kind]

    def test_a_genomespy_view_has_no_html_but_the_plotly_view_does(self) -> None:
        from depictio.api.v1.services.export.capabilities import (
            component_formats,
            component_html_unavailable_reason,
        )

        locus = _av_component("coverage_track", view="locus")
        track = _av_component("coverage_track", view="track")
        assert ExportFormat.HTML not in component_formats(locus)
        assert "GenomeSpy" in (component_html_unavailable_reason(locus) or "")
        assert ExportFormat.HTML in component_formats(track)

    def test_highlight_exports_nothing_and_points_at_its_source(self) -> None:
        from depictio.api.v1.services.export.capabilities import (
            component_formats,
            component_html_unavailable_reason,
        )

        highlight = {"component_type": "highlight", "source_component": "fig-1"}
        assert component_formats(highlight) == frozenset()
        assert "source" in (component_html_unavailable_reason(highlight) or "")
