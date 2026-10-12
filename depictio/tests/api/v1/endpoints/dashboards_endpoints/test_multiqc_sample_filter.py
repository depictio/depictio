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


# ── Filters declared on another tab of the family ──────────────────────────────
#
# A persistent filter section lives on the Overview and is rendered on every tab,
# so on the MultiQC tab its components are not in that tab's own stored_metadata.


ROUTES = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
OVERVIEW_ID = ObjectId()
MULTIQC_TAB_ID = ObjectId()


def _multiqc_tab() -> dict:
    """The MultiQC tab's own document: it holds the panel and nothing else."""
    return {
        "dashboard_id": MULTIQC_TAB_ID,
        "parent_dashboard_id": OVERVIEW_ID,
        "project_id": PROJECT_ID,
        "stored_metadata": [
            {
                "index": "mqc-comp",
                "component_type": "multiqc",
                "dc_id": MULTIQC_DC,
                "wf_id": WF_ID,
            }
        ],
    }


@pytest.fixture
def family_db(patched_db):
    """The Overview tab, which declares the pinned filters, in the dashboards collection."""
    import mongomock

    client = mongomock.MongoClient()
    coll = client.test_db.dashboards
    coll.insert_one(
        {
            "dashboard_id": OVERVIEW_ID,
            "project_id": PROJECT_ID,
            "stored_metadata": [
                {
                    "index": "pinned-habitat",
                    "component_type": "interactive",
                    "dc_id": META_DC_A,
                    "wf_id": WF_ID,
                    "column_name": "habitat",
                    "interactive_component_type": "MultiSelect",
                    "dc_config": {"delta_location": f"memory://{META_DC_A}", "type": "table"},
                }
            ],
        }
    )
    coll.insert_one(
        {
            "dashboard_id": MULTIQC_TAB_ID,
            "parent_dashboard_id": OVERVIEW_ID,
            "project_id": PROJECT_ID,
        }
    )
    with patch(f"{ROUTES}.dashboards_collection", coll):
        yield coll
    client.close()


def test_pinned_filter_from_another_tab_narrows_multiqc(family_db):
    """A filter declared on the Overview reaches the MultiQC panel through its link."""
    filters = [_filter("pinned-habitat", "habitat", ["w"])]
    result = _resolve_multiqc_sample_filter(_multiqc_tab(), _component(), filters)
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}


def test_pinned_and_local_filters_intersect(family_db):
    """A pinned filter and one of the MultiQC tab's own narrow together."""
    tab = _multiqc_tab()
    tab["stored_metadata"].append(
        {
            "index": "direct-sample",
            "component_type": "interactive",
            "dc_id": MULTIQC_DC,
            "wf_id": WF_ID,
            "column_name": "sample_name",
        }
    )
    filters = [
        _filter("pinned-habitat", "habitat", ["w"]),
        _filter("direct-sample", "sample_name", ["S1", "S2"]),
    ]
    result = _resolve_multiqc_sample_filter(tab, _component(), filters)
    assert result is not None
    assert set(result) == {"S2", "S2_R1"}


def test_filter_unknown_to_the_family_uses_the_metadata_the_viewer_sent(patched_db):
    """With no stored component anywhere, ``metadata.dc_id`` still names the collection."""
    tab = {"project_id": PROJECT_ID, "stored_metadata": []}
    filters = [
        {
            **_filter("floating", "habitat", ["w"]),
            "metadata": {"dc_id": META_DC_A, "column_name": "habitat"},
        }
    ]
    # The sent metadata carries no dc_config, so the Delta location is looked up
    # in the registry: give it an empty one rather than a real MongoDB.
    import mongomock

    with patch("depictio.api.v1.db.deltatables_collection", mongomock.MongoClient().db.dt):
        result = _resolve_multiqc_sample_filter(tab, _component(), filters)
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}


def test_unknown_filter_without_metadata_is_still_ignored(patched_db):
    """A filter nothing identifies stays a no-op, as before."""
    tab = {"project_id": PROJECT_ID, "stored_metadata": []}
    assert (
        _resolve_multiqc_sample_filter(tab, _component(), [_filter("ghost", "habitat", ["w"])])
        is None
    )


def test_family_lookup_failure_does_not_break_the_render(patched_db):
    """A failing read of the sibling tabs costs the foreign filters, not the request."""

    class Broken:
        def find(self, *a, **k):
            raise RuntimeError("mongo down")

    filters = [_filter("pinned-habitat", "habitat", ["w"])]
    with patch(f"{ROUTES}.dashboards_collection", Broken()):
        assert _resolve_multiqc_sample_filter(_multiqc_tab(), _component(), filters) is None


def test_own_tab_wins_a_collision_with_another_tab(family_db):
    """Two tabs sharing an index: the component on the rendered tab is the one used."""
    tab = _multiqc_tab()
    tab["stored_metadata"].append(
        {
            "index": "pinned-habitat",
            "component_type": "interactive",
            "dc_id": META_DC_B,
            "wf_id": WF_ID,
            "column_name": "depth_zone",
            "interactive_component_type": "MultiSelect",
            "dc_config": {"delta_location": f"memory://{META_DC_B}", "type": "table"},
        }
    )
    filters = [_filter("pinned-habitat", "depth_zone", ["d"])]
    result = _resolve_multiqc_sample_filter(tab, _component(), filters)
    assert result is not None
    # DC B (S1+S2), not the Overview's DC A (S2+S3).
    assert set(result) == {"S1", "S1_R1", "S2", "S2_R1"}


def test_family_is_not_read_when_every_active_filter_is_local(patched_db):
    """The common case costs no extra query."""

    class Spy:
        calls = 0

        def find(self, *a, **k):
            Spy.calls += 1
            return []

    tab = _multiqc_tab()
    tab["stored_metadata"].append(
        {
            "index": "direct-sample",
            "component_type": "interactive",
            "dc_id": MULTIQC_DC,
            "wf_id": WF_ID,
            "column_name": "sample_name",
        }
    )
    filters = [_filter("direct-sample", "sample_name", ["S1"])]
    with patch(f"{ROUTES}.dashboards_collection", Spy()):
        assert _resolve_multiqc_sample_filter(tab, _component(), filters) is not None
    assert Spy.calls == 0


def test_cleared_or_stale_filters_do_not_trigger_the_family_read(patched_db):
    """An empty control, or a filter of a deleted component, must not cost a query."""

    class Spy:
        calls = 0

        def find(self, *a, **k):
            Spy.calls += 1
            return []

    tab = _multiqc_tab()
    tab["stored_metadata"].append(
        {
            "index": "direct-sample",
            "component_type": "interactive",
            "dc_id": MULTIQC_DC,
            "wf_id": WF_ID,
            "column_name": "sample_name",
        }
    )
    filters = [
        _filter("direct-sample", "sample_name", ["S1"]),
        _filter("cleared", "habitat", []),
    ]
    with patch(f"{ROUTES}.dashboards_collection", Spy()):
        _resolve_multiqc_sample_filter(tab, _component(), filters)
    assert Spy.calls == 0


def test_foreign_filter_on_the_multiqc_sample_column_is_direct(patched_db):
    """A sent filter on the MultiQC DC's own sample column takes the direct branch."""
    tab = {"project_id": PROJECT_ID, "stored_metadata": []}
    filters = [
        {
            **_filter("pinned-sample", "sample_name", ["S1"]),
            "metadata": {"dc_id": MULTIQC_DC, "column_name": "sample_name"},
        }
    ]
    result = _resolve_multiqc_sample_filter(tab, _component(), filters)
    assert result is not None
    assert set(result) == {"S1", "S1_R1"}


class _Projects:
    """A projects collection holding one project with the given links."""

    def __init__(self, links: list[dict]):
        self.links = links

    def find_one(self, *args, **kwargs):
        return {"_id": PROJECT_ID, "links": self.links}


def _second_link(source_dc: str, column: str) -> dict:
    return {**_link(source_dc), "source_column": column}


def test_every_link_of_a_source_dc_contributes_its_column(patched_db):
    """One table linked twice (library id and sample name): the ids of both count."""
    patched_db[META_DC_A] = pl.DataFrame({"sample": ["S2"], "alias": ["S3"], "habitat": ["w"]})
    links = [_link(META_DC_A), _second_link(META_DC_A, "alias")]
    with patch("depictio.api.v1.db.projects_collection", _Projects(links)):
        result = _resolve_multiqc_sample_filter(
            _dashboard_data(), _component(), [_filter("habitat-a", "habitat", ["w"])]
        )
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}


def test_a_repeated_link_column_is_read_once(patched_db):
    links = [_link(META_DC_A), _link(META_DC_A)]
    with patch("depictio.api.v1.db.projects_collection", _Projects(links)):
        result = _resolve_multiqc_sample_filter(
            _dashboard_data(), _component(), [_filter("habitat-a", "habitat", ["w"])]
        )
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}


def test_a_link_column_missing_from_the_table_does_not_hide_the_others(patched_db):
    links = [_second_link(META_DC_A, "gone"), _link(META_DC_A)]
    with patch("depictio.api.v1.db.projects_collection", _Projects(links)):
        result = _resolve_multiqc_sample_filter(
            _dashboard_data(), _component(), [_filter("habitat-a", "habitat", ["w"])]
        )
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}


def test_a_null_in_a_link_column_is_not_a_sample_id(patched_db):
    patched_db[META_DC_A] = pl.DataFrame(
        {"sample": ["S2", "S3"], "alias": [None, None], "habitat": ["w", "w"]}
    )
    links = [_link(META_DC_A), _second_link(META_DC_A, "alias")]
    with patch("depictio.api.v1.db.projects_collection", _Projects(links)):
        result = _resolve_multiqc_sample_filter(
            _dashboard_data(), _component(), [_filter("habitat-a", "habitat", ["w"])]
        )
    assert result is not None
    assert set(result) == {"S2", "S2_R1", "S3", "S3_R1"}
