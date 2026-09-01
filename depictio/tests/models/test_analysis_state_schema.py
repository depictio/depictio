"""Pin the ``AnalysisState`` contract.

The committed JSON-schema snapshot must match what the Pydantic model
generates — any model change forces a deliberate snapshot regeneration, which
is the reviewable event for a contract change (the TypeScript mirror in
``packages/depictio-react-core/src/analysisState.ts`` validates against the
same snapshot).

Regenerate after an intentional model change with:

    uv run python -c "import json; from depictio.models.models.analysis_state import \
AnalysisState; open('depictio/models/models/analysis_state.schema.json','w').write(\
json.dumps(AnalysisState.model_json_schema(), indent=2, sort_keys=True) + '\\n')"
"""

import json
from pathlib import Path

from depictio.models.models.analysis_state import (
    ANALYSIS_STATE_VERSION,
    AnalysisState,
    NotebookExportRequest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "depictio" / "models" / "models" / "analysis_state.schema.json"


def test_schema_snapshot_matches_model():
    committed = json.loads(SCHEMA_PATH.read_text())
    generated = AnalysisState.model_json_schema()
    assert generated == committed, (
        "AnalysisState changed but depictio/models/models/analysis_state.schema.json was not "
        "regenerated — this snapshot is the contract shared with the viewer; regenerate it "
        "deliberately (see module docstring)."
    )


VIEWER_PAYLOAD = {
    "version": 1,
    "filters": [
        {
            "index": "filter-species",
            "value": ["Adelie", "Gentoo"],
            "column_name": "species",
            "interactive_component_type": "MultiSelect",
            "metadata": {"dc_id": "646b0f3c1e4a2d7f8e5b8ca1", "column_name": "species"},
        },
        {
            "index": "__depictio_group__:646b0f3c1e4a2d7f8e5b8ca1:individual_id",
            "value": ["N1A1", "N2A2"],
            "column_name": "individual_id",
            "interactive_component_type": "MultiSelect",
            "source": "group_filter",
            "metadata": {"dc_id": "646b0f3c1e4a2d7f8e5b8ca1"},
        },
    ],
    "groups": [
        {
            "id": "g1",
            "name": "Heavy Adelie",
            "color": "#e64980",
            "dc_id": "646b0f3c1e4a2d7f8e5b8ca1",
            "column_name": "individual_id",
            "values": ["N1A1", "N2A2"],
            "created_at": 1700000000000,
            "filter_active": True,
        }
    ],
    "color_by": {"kind": "groups"},
    "display_mode": "facet",
    "show_other": True,
    "show_overall": True,
    "compare_in_cards": False,
    "funnel": {"enabled": True, "stage_order": ["filter-species"]},
    "split_panels": [
        {
            "name": "Heavy Adelie",
            "color": "#e64980",
            "constraints": [
                {
                    "index": "__depictio_group__:panel:g1",
                    "value": ["N1A1", "N2A2"],
                    "column_name": "individual_id",
                    "interactive_component_type": "MultiSelect",
                    "source": "group_filter",
                    "metadata": {"dc_id": "646b0f3c1e4a2d7f8e5b8ca1"},
                }
            ],
        }
    ],
    "context": {"dashboard_id": "6824cb3b89d2b72169309738", "theme": "dark"},
}


def test_viewer_payload_round_trips():
    state = AnalysisState.model_validate(VIEWER_PAYLOAD)
    assert state.version == ANALYSIS_STATE_VERSION
    dumped = state.model_dump(mode="json")
    assert AnalysisState.model_validate(dumped) == state
    # The filters come back in the plain-dict shape the render endpoints read.
    payload = state.filters_as_payload()
    assert payload[0]["metadata"]["dc_id"] == "646b0f3c1e4a2d7f8e5b8ca1"
    assert payload[1]["source"] == "group_filter"


def test_minimal_state_defaults():
    state = AnalysisState.model_validate({"context": {"dashboard_id": "abc"}})
    assert state.filters == []
    assert state.funnel.enabled is True
    assert state.funnel.stage_order == []
    assert state.color_by.kind == "none"
    assert state.display_mode == "color"


def test_export_request_defaults_to_marimo():
    req = NotebookExportRequest.model_validate({"state": {"context": {"dashboard_id": "abc"}}})
    assert req.format == "marimo"
