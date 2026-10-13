"""`bulk_compute_cards` computes a text tile's live values and folds them under its index.

The values ride the card path as synthetic cards (`<text index>::<name>`), so
these tests check what comes back to the viewer: one plain object per text
tile, `{name: value, "param:KEY": text}`, next to the cards' own values; and
that the synthetic cards see the request's filters as a card does.

Against mongomock; the Delta scan is a Polars frame in memory.
"""

from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.users import UserBase

WF = ObjectId()
REL_DC = ObjectId()
FRAME = pl.DataFrame(
    {
        "Phylum": ["Firmicutes", "Bacteroidota", "Firmicutes", None, "Proteobacteria"],
        "reads": [10.0, 30.0, 15.0, 5.0, 40.0],
        "sample": ["s1", "s1", "s2", "s2", "s3"],
    }
)


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="viewer@example.com")
    u.is_admin = True
    u.is_anonymous = False
    return u


@pytest.fixture
def env():
    """Patched collections and a scan that records what it was asked for."""
    database = mongomock.MongoClient()["depictio_test"]
    scans: list[dict] = []

    def fake_scan(workflow_id, data_collection_id, metadata=None, init_data=None, **kw):
        scans.append({"dc": str(data_collection_id), "metadata": metadata, **kw})
        frame = FRAME
        for f in metadata or []:
            frame = frame.filter(pl.col(f["column_name"]).is_in(f["value"]))
        return frame.lazy()

    def fake_load(workflow_id, data_collection_id, metadata=None, **kw):
        return fake_scan(workflow_id, data_collection_id, metadata, **kw).collect()

    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(dash_routes, "check_project_permission", return_value=True),
        patch("depictio.api.v1.db.deltatables_collection", database["deltatables"]),
        patch("depictio.api.v1.deltatables_utils.open_deltatable_scan", side_effect=fake_scan),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", side_effect=fake_load),
    ):
        yield database, scans


def _spec(column, aggregation, dc_id=REL_DC, **extra):
    return {
        "dc": "rel_abundance",
        "column": column,
        "aggregation": aggregation,
        "dc_id": dc_id,
        "wf_id": WF if dc_id else None,
        **extra,
    }


def _dashboard(database, components) -> ObjectId:
    project_id = ObjectId()
    database["projects"].insert_one(
        {
            "_id": project_id,
            "template_origin": {
                "run_provenance": [
                    {"source": "software_versions", "key": "dada_ref_taxonomy", "value": "v0"},
                    {"source": "params", "key": "dada_ref_taxonomy", "value": "silva=138"},
                    {"source": "params", "key": "unset_param", "value": "null"},
                    {"source": "software_versions", "key": "DADA2", "value": "1.30.0"},
                ]
            },
        }
    )
    dashboard_id = ObjectId()
    database["dashboards"].insert_one(
        {"dashboard_id": dashboard_id, "project_id": project_id, "stored_metadata": components}
    )
    return dashboard_id


def _compute(dashboard_id, user, **request):
    return dash_routes.bulk_compute_cards(
        dashboard_id=dashboard_id, request=request, current_user=user, access_token=None
    )


TEXT = {
    "component_type": "text",
    "index": "findings",
    "body": (
        "- **{{share}}** of reads are {{top}} ({{n}} phyla)\n"
        "- {{gone}}; {{param:dada_ref_taxonomy}}, {{param:DADA2}}, "
        "{{param:unset_param}}, {{param:not_recorded}}"
    ),
    "values": {
        "top": _spec("Phylum", "top", weight="reads"),
        "share": _spec("Phylum", "top_share", weight="reads"),
        "n": _spec("Phylum", "nunique", filter_expr="col('reads') > 12"),
        "gone": _spec("x", "count", dc_id=None),
    },
}
CARD = {
    "component_type": "card",
    "index": "reads-card",
    "wf_id": WF,
    "dc_id": REL_DC,
    "column_name": "reads",
    "aggregation": "sum",
}


def test_values_come_back_folded_under_the_text_index(env, user):
    database, _ = env
    result = _compute(_dashboard(database, [CARD, TEXT]), user, filters=[])
    assert result["values"]["reads-card"] == pytest.approx(100.0)
    assert result["values"]["findings"] == {
        # Proteobacteria 40 > Bacteroidota 30 > Firmicutes 25 (two rows).
        "top": "Proteobacteria",
        "share": pytest.approx(0.4),
        # Rows with reads > 12: Bacteroidota, Firmicutes, Proteobacteria.
        "n": 3,
        "gone": None,
        "param:dada_ref_taxonomy": "silva=138",
        "param:DADA2": "1.30.0",
        "param:unset_param": None,
        "param:not_recorded": None,
    }
    assert not [k for k in result["values"] if "::" in k]


def test_a_text_only_request_is_computed(env, user):
    database, _ = env
    dashboard_id = _dashboard(database, [CARD, TEXT])
    result = _compute(dashboard_id, user, filters=[], component_ids=["findings"])
    assert set(result["values"]) == {"findings"}
    assert result["values"]["findings"]["top"] == "Proteobacteria"


def test_params_only_text_and_plain_text(env, user):
    database, _ = env
    params_only = {
        "component_type": "text",
        "index": "params",
        "body": "Reference: {{param:dada_ref_taxonomy}}",
    }
    plain = {"component_type": "text", "index": "plain", "body": "Nothing live."}
    result = _compute(_dashboard(database, [params_only, plain]), user, filters=[])
    assert result["values"] == {"params": {"param:dada_ref_taxonomy": "silva=138"}}


def test_text_values_follow_the_filters(env, user):
    database, scans = env
    dashboard_id = _dashboard(database, [TEXT])
    filters = [
        {
            "index": "sample-filter",
            "value": ["s1"],
            "column_name": "sample",
            "interactive_component_type": "MultiSelect",
            "metadata": {"dc_id": str(REL_DC), "column_name": "sample"},
        }
    ]
    with patch.object(
        dash_routes,
        "_resolve_link_filters_cached",
        side_effect=lambda filters, **kw: list(filters),
    ):
        result = _compute(dashboard_id, user, filters=filters)
    # s1 holds Firmicutes 10 and Bacteroidota 30.
    assert result["values"]["findings"]["top"] == "Bacteroidota"
    assert result["values"]["findings"]["share"] == pytest.approx(0.75)
    assert all(scan["metadata"] for scan in scans)
    # The weight column is projected in.
    assert any("reads" in (scan.get("select_columns") or []) for scan in scans)


def test_no_cards_and_no_texts_is_the_early_empty_answer(env, user):
    database, _ = env
    result = _compute(_dashboard(database, []), user, filters=[])
    assert result == {"values": {}, "filter_applied": False, "filter_count": 0}
