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
