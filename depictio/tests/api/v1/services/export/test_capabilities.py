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


class TestRegistryIsTheOnlyJsonGate:
    """A kind's JSON support must come from the registry, never from the table.

    ``AV_JSON_SOURCE`` used to name the ported kinds ``"python"`` outright, with
    a comment claiming the registry overrode it. It does not — it only upgrades
    ``client_only`` to ``"python"``. So a builder-package import failure (which
    ``figure_registry._ensure_loaded`` swallows deliberately) emptied the
    registry while the table went on advertising JSON: the request reached
    ``required_columns`` and died on a bare ``HTTPException(501, ...)`` with a
    plain-string detail, instead of degrading to ``format=html`` as documented
    in two places.
    """

    def test_every_python_kind_is_client_only_in_the_static_table(self) -> None:
        """The table is a floor. Anything above it has to be earned at runtime."""
        from depictio.api.v1.services.advanced_viz.figure_registry import supported_kinds

        offenders = sorted(k for k in supported_kinds() if AV_JSON_SOURCE.get(k) == "python")
        assert not offenders, (
            "these kinds declare 'python' in AV_JSON_SOURCE, so they would still "
            "advertise JSON with no builder registered: " + ", ".join(offenders)
        )

    def test_registered_builder_grants_json(self) -> None:
        from depictio.api.v1.services.advanced_viz.figure_registry import supported_kinds

        for kind in supported_kinds():
            assert advanced_viz_json_source(kind) == "python", kind
            assert ExportFormat.JSON in formats_for("advanced_viz", kind), kind

    def test_empty_registry_degrades_to_html(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The failure this whole change exists for: no builders, no JSON claim."""
        import depictio.api.v1.services.export.capabilities as cap

        monkeypatch.setattr(cap, "_python_builder_kinds", lambda: frozenset())

        assert cap.advanced_viz_json_source("volcano") == "client_only"
        assert cap.formats_for("advanced_viz", "volcano") == frozenset({ExportFormat.HTML})

        reason = cap.unsupported_reason("advanced_viz", "volcano")
        assert reason is not None
        assert "format=html" in reason

    def test_celery_kinds_are_unaffected_by_the_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Celery-built kinds have no Python builder and must not be downgraded."""
        import depictio.api.v1.services.export.capabilities as cap

        monkeypatch.setattr(cap, "_python_builder_kinds", lambda: frozenset())
        assert cap.advanced_viz_json_source("complex_heatmap") == "celery"
        assert ExportFormat.JSON in cap.formats_for("advanced_viz", "complex_heatmap")
