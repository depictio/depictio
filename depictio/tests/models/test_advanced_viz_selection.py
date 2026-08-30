"""The advanced-viz selection opt-in stays off, and stays in step with the UI.

Two things can quietly break the "select on a clustering scatter or a variant
track, then save it as an analysis group" path:

1. A config growing a truthy default, which would hand every existing
   deployment a lasso and a cross-filter its dashboards never asked for.
2. A third viz kind declaring ``selection_enabled`` without being taught to the
   React side. ``advancedVizSelectionColumn`` in selection.ts is the single
   source of truth there: the renderers gate their Plotly handlers on it and
   the component chrome draws its "you can select here" marker from it, so a
   kind the switch does not name is a config field that validates, persists,
   and does nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter

from depictio.models.components.advanced_viz.configs import (
    EmbeddingConfig,
    ManhattanConfig,
    VizConfig,
)

REPO = Path(__file__).resolve().parents[3]
SELECTION_TS = REPO / "packages" / "depictio-react-core" / "src" / "selection.ts"

VIZ_CONFIG = TypeAdapter(VizConfig)


def _kinds_declaring_selection() -> set[str]:
    return {
        model.model_fields["viz_kind"].default
        for model in get_args(get_args(VizConfig)[0])
        if "selection_enabled" in model.model_fields
    }


def _kinds_handled_in_typescript() -> set[str]:
    src = SELECTION_TS.read_text()
    body = re.search(r"export function advancedVizSelectionColumn\(.*?\n\}", src, flags=re.DOTALL)
    assert body, "could not find advancedVizSelectionColumn in selection.ts"
    return set(re.findall(r"case '([a-z_0-9]+)':", body.group(0)))


def test_selection_is_off_by_default():
    for config in (EmbeddingConfig(), ManhattanConfig()):
        assert config.selection_enabled is False
        assert config.selection_column is None


def test_opted_in_configs_round_trip():
    """``extra="forbid"`` means a key with no field makes the component
    unloadable, so the shape a dashboard writes has to validate."""
    for blob in (
        {
            "viz_kind": "embedding",
            "sample_id_col": "sample",
            "selection_enabled": True,
            "selection_column": "sample",
        },
        {
            "viz_kind": "manhattan",
            "selection_enabled": True,
            "selection_column": "mutation_label",
        },
    ):
        parsed = VIZ_CONFIG.validate_python(blob)
        assert parsed.selection_enabled is True  # type: ignore[union-attr]


def test_every_kind_declaring_selection_is_handled_by_the_renderer_gate():
    assert _kinds_declaring_selection() == _kinds_handled_in_typescript()
