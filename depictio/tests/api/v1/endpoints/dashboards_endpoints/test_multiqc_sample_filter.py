"""Tests for ``_resolve_multiqc_sample_filter`` (issue #938).

Pins the corrected semantics:
- every active filter is an AND constraint — the result is the INTERSECTION
  of the per-filter sample sets, not their union;
- filters from *every* linked metadata DC contribute, not just the first one
  seen (the old behavior silently dropped later DCs, so the outcome depended
  on filter ordering);
- direct filters on the MultiQC DC are honored for any sample-column spelling
  (``sample``, ``sample_id``, ``sample_name``, ...), matching the frontend;
- return value distinguishes "no applicable filter" (``None``) from "active
  filters matched no sample" (``[]``).
"""

from unittest.mock import patch

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _resolve_multiqc_sample_filter,
)

MULTIQC_DC = str(ObjectId())
META_DC_A = str(ObjectId())
META_DC_B = str(ObjectId())
PROJECT_ID = ObjectId()
WF_ID = str(ObjectId())

MAPPINGS = {
    "S1": ["S1_R1"],
    "S2": ["S2_R1"],
    "S3": ["S3_R1"],
}


def _dashboard_data() -> dict:
    def meta(index: str, dc_id: str, column: str) -> dict:
        return {
            "index": index,
            "component_type": "interactive",
            "dc_id": dc_id,
            "wf_id": WF_ID,
            "column_name": column,
            "interactive_component_type": "MultiSelect",
            "dc_config": {"delta_location": f"memory://{dc_id}", "type": "table"},
        }

    return {
        "project_id": PROJECT_ID,
        "stored_metadata": [
            meta("direct-sample", MULTIQC_DC, "sample_name"),
            meta("habitat-a", META_DC_A, "habitat"),
            meta("depth-b", META_DC_B, "depth_zone"),
            {
                "index": "mqc-comp",
                "component_type": "multiqc",
                "dc_id": MULTIQC_DC,
                "wf_id": WF_ID,
            },
        ],
    }


def _component() -> dict:
    return {"index": "mqc-comp", "dc_id": MULTIQC_DC, "wf_id": WF_ID}


def _link(source_dc: str) -> dict:
    return {
        "id": str(ObjectId()),
        "source_dc_id": source_dc,
        "source_column": "sample",
        "target_dc_id": MULTIQC_DC,
        "target_type": "multiqc",
        "enabled": True,
        "link_config": {"resolver": "sample_mapping", "target_field": "sample_name"},
    }


@pytest.fixture
def patched_db():
    """Patch the DB collections and the Delta loader used by the resolver."""
    import mongomock

    client = mongomock.MongoClient()
    db = client.test_db
    db.multiqc.insert_one(
        {
            "data_collection_id": MULTIQC_DC,
            "metadata": {"sample_mappings": MAPPINGS},
        }
    )
    db.projects.insert_one(
        {
            "_id": PROJECT_ID,
            "links": [_link(META_DC_A), _link(META_DC_B)],
        }
    )

    # One frame per metadata DC: DC A narrows to S2+S3, DC B narrows to S1+S2.
    frames = {
        META_DC_A: pl.DataFrame({"sample": ["S2", "S3"], "habitat": ["w", "w"]}),
        META_DC_B: pl.DataFrame({"sample": ["S1", "S2"], "depth_zone": ["d", "d"]}),
    }

    def fake_load(workflow_id, data_collection_id, metadata=None, init_data=None, **kwargs):
        return frames[str(data_collection_id)]

    with (
        patch("depictio.api.v1.db.multiqc_collection", db.multiqc),
        patch("depictio.api.v1.db.projects_collection", db.projects),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", side_effect=fake_load),
    ):
        yield frames
        client.close()


def _filter(index: str, column: str, value) -> dict:
    return {
        "index": index,
        "value": value,
        "column_name": column,
        "interactive_component_type": "MultiSelect",
    }


def test_no_filters_returns_none(patched_db):
    assert _resolve_multiqc_sample_filter(_dashboard_data(), _component(), []) is None


def test_inapplicable_filters_return_none(patched_db):
    # A filter on the MultiQC DC but not on a sample-like column contributes
    # nothing — there is no sample filter to apply.
    dashboard = _dashboard_data()
    dashboard["stored_metadata"].append(
        {
            "index": "not-sample",
            "component_type": "interactive",
            "dc_id": MULTIQC_DC,
            "wf_id": WF_ID,
            "column_name": "module",
        }
    )
    filters = [_filter("not-sample", "module", ["fastqc"])]
    assert _resolve_multiqc_sample_filter(dashboard, _component(), filters) is None


def test_direct_filter_accepts_sample_name_spelling(patched_db):
    """The direct branch matches any allow-listed sample column, not just ``sample``."""
    filters = [_filter("direct-sample", "sample_name", ["S1"])]
    result = _resolve_multiqc_sample_filter(_dashboard_data(), _component(), filters)
    assert result is not None
    assert set(result) == {"S1", "S1_R1"}


def test_direct_and_indirect_filters_intersect(patched_db):
    """Direct S1+S2 ∩ metadata-A (S2+S3) must keep only S2 — never the union."""
    filters = [
        _filter("direct-sample", "sample_name", ["S1", "S2"]),
        _filter("habitat-a", "habitat", ["w"]),
    ]
    result = _resolve_multiqc_sample_filter(_dashboard_data(), _component(), filters)
    assert result is not None
    assert set(result) == {"S2", "S2_R1"}


def test_every_metadata_dc_contributes(patched_db):
    """DC A (S2+S3) ∩ DC B (S1+S2) = S2 — the second DC must not be dropped."""
    filters = [
        _filter("habitat-a", "habitat", ["w"]),
        _filter("depth-b", "depth_zone", ["d"]),
    ]
    result = _resolve_multiqc_sample_filter(_dashboard_data(), _component(), filters)
    assert result is not None
    assert set(result) == {"S2", "S2_R1"}


def test_metadata_dc_order_does_not_change_result(patched_db):
    filters_ab = [
        _filter("habitat-a", "habitat", ["w"]),
        _filter("depth-b", "depth_zone", ["d"]),
    ]
    filters_ba = list(reversed(filters_ab))
    dashboard = _dashboard_data()
    component = _component()
    assert _resolve_multiqc_sample_filter(
        dashboard, component, filters_ab
    ) == _resolve_multiqc_sample_filter(dashboard, component, filters_ba)


def test_empty_intersection_returns_empty_list_not_none(patched_db, monkeypatch):
    """Filters that match no sample must yield ``[]`` (render nothing)."""
    import depictio.api.v1.deltatables_utils as dtu

    monkeypatch.setattr(
        dtu,
        "load_deltatable_lite",
        lambda *a, **k: pl.DataFrame({"sample": [], "habitat": []}),
    )
    filters = [_filter("habitat-a", "habitat", ["nope"])]
    result = _resolve_multiqc_sample_filter(_dashboard_data(), _component(), filters)
    assert result == []


def test_unlinked_metadata_dc_is_skipped(patched_db):
    """A metadata DC without an enabled link is ignored, direct filters kept."""
    dashboard = _dashboard_data()
    unlinked_dc = str(ObjectId())
    dashboard["stored_metadata"].append(
        {
            "index": "unlinked",
            "component_type": "interactive",
            "dc_id": unlinked_dc,
            "wf_id": WF_ID,
            "column_name": "foo",
        }
    )
    filters = [
        _filter("direct-sample", "sample_name", ["S1"]),
        _filter("unlinked", "foo", ["bar"]),
    ]
    result = _resolve_multiqc_sample_filter(dashboard, _component(), filters)
    assert result is not None
    assert set(result) == {"S1", "S1_R1"}
