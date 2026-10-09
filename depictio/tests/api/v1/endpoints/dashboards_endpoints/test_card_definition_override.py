"""Drawing a component as a stored version defined it (``definition_version``).

The component-history modal and the ``?version=`` preview need two things at
once: a component's *definition* from a stored version, and the data from that
version's Delta commit. Applying today's chart config to yesterday's data would
answer a question nobody asked, and would do so without any visible sign.

Renders once took the definition itself from the request body
(``component_overrides``), filtered through per-type allow-lists. Those lists
let a figure's ``mode`` and ``code_content`` through, so any viewer of a
project, or visitor of a public one, could have the server run code of their
own. The body now names a *version*, and the server reads the definition from
the ledger: nothing a request carries can become part of a definition.
"""

from __future__ import annotations

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

API = "/depictio/api/v1/dashboards"


class _Anon:
    def __init__(self):
        self.id = str(ObjectId())
        self.email = "anonymous@depict.io"
        self.is_admin = False
        self.is_anonymous = True


class _User:
    def __init__(self, uid):
        self.id = uid
        self.email = "viewer@example.com"
        self.is_admin = False
        self.is_anonymous = False


class _DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True

    def exists(self, key):
        return key in self.store

    def delete_pattern(self, pattern):
        return 0


# Fixed, so parametrised test ids are the same on every xdist worker.
DID = ObjectId("6a0000000000000000000001")
CHILD = ObjectId("6a0000000000000000000002")
OTHER_FAMILY = ObjectId("6a0000000000000000000003")
PID = ObjectId("6a0000000000000000000004")
WF = ObjectId("6a0000000000000000000005")
DC = ObjectId("6a0000000000000000000006")
#: A collection of the same project the dashboard's components do not read.
DC_OTHER = ObjectId("6a0000000000000000000007")
#: A collection of no project at all.
DC_FOREIGN = ObjectId("6a0000000000000000000008")
VIEWER_ID = ObjectId("6a0000000000000000000009")

FIG = "fig-1"
CARD = "card-1"
TABLE = "table-1"


def _figure(index=FIG, **fields):
    return {
        "index": index,
        "component_type": "figure",
        "mode": "ui",
        "visu_type": "scatter",
        "dict_kwargs": {"x": "x", "y": "y"},
        "wf_id": WF,
        "dc_id": DC,
        **fields,
    }


def _card(index=CARD, **fields):
    return {
        "index": index,
        "component_type": "card",
        "aggregation": "count",
        "column_name": "x",
        "wf_id": WF,
        "dc_id": DC,
        **fields,
    }


def _stringified(component: dict) -> dict:
    """A component as a snapshot stores it: ObjectIds as strings."""
    return {k: str(v) if isinstance(v, ObjectId) else v for k, v in component.items()}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from depictio.api import cache as cache_module
    from depictio.api.v1 import db as db_module
    from depictio.api.v1 import deltatables_utils
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions, version_store
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    table = str(tmp_path / "delta")
    pl.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}).write_delta(table)
    dc_config = {"delta_location": table, "type": "table", "size_bytes": 0}

    secret = tmp_path / "server_secret.csv"
    secret.write_text("name,value\nTOPSECRET_SERVER_FILE_CONTENT,1\n")

    db = mongomock.MongoClient()["definition_version"]
    db["projects"].insert_one(
        {
            "_id": PID,
            "name": "public demo",
            "is_public": True,
            "permissions": {
                "owners": [{"_id": ObjectId()}],
                "editors": [],
                "viewers": [{"_id": VIEWER_ID}],
            },
            "workflows": [
                {
                    "_id": WF,
                    "workflow_tag": "wf",
                    "data_collections": [
                        {"_id": DC, "data_collection_tag": "dc", "config": {"type": "table"}},
                        {
                            "_id": DC_OTHER,
                            "data_collection_tag": "other",
                            "config": {"type": "table"},
                        },
                    ],
                }
            ],
        }
    )
    db["deltatables"].insert_one({"data_collection_id": DC, "delta_table_location": table})
    for doc in (
        {
            "_id": DID,
            "dashboard_id": DID,
            "project_id": PID,
            "is_main_tab": True,
            "title": "demo",
            "stored_metadata": [
                _figure(dc_config=dc_config),
                _card(dc_config=dc_config),
                {
                    "index": TABLE,
                    "component_type": "table",
                    "wf_id": WF,
                    "dc_id": DC,
                    "dc_config": dc_config,
                },
            ],
        },
        {
            "_id": CHILD,
            "dashboard_id": CHILD,
            "project_id": PID,
            "is_main_tab": False,
            "parent_dashboard_id": DID,
            "title": "child",
            "stored_metadata": [_figure("child-fig", dc_config=dc_config)],
        },
    ):
        db["dashboards"].insert_one(doc)

    monkeypatch.setattr(dash_routes, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(core_functions, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(db_module, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(deltatables_utils, "polars_s3_config", {})
    monkeypatch.setattr(deltatables_utils, "_get_aggregation_version", lambda _dc: "1")
    stub = _DictCache()
    monkeypatch.setattr(cache_module, "get_cache", lambda: stub)
    # Code mode is always offloaded to Celery; the worker runs the very same
    # build_figure_preview. Run it inline here.
    monkeypatch.setattr(dash_routes, "should_offload_render", lambda **_k: False)
    deltatables_utils.clear_memory_cache()

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    who = {"user": _Anon()}
    app.dependency_overrides[get_user_or_anonymous] = lambda: who["user"]
    return {
        "client": TestClient(app),
        "secret": str(secret),
        "who": who,
        "versions": db["dashboard_versions"],
        "dc_config": dc_config,
    }


def _version(env, *, main=None, child=None, family=DID) -> str:
    """Store a version of the family holding these components on each tab."""
    version_id = str(ObjectId())
    tabs = [{"dashboard_id": str(DID), "stored_metadata": [_stringified(c) for c in main or []]}]
    if child is not None:
        tabs.append(
            {"dashboard_id": str(CHILD), "stored_metadata": [_stringified(c) for c in child]}
        )
    env["versions"].insert_one(
        {"version_id": version_id, "family_id": str(family), "seq": 1, "tabs": tabs}
    )
    return version_id


def _render_figure(env, body, *, dashboard=DID, index=FIG):
    return env["client"].post(
        f"{API}/render_figure/{dashboard}/{index}", json={"filters": [], **body}
    )


def _trace_type(response) -> str | None:
    traces = (response.json().get("figure") or {}).get("data") or []
    return traces[0].get("type") if traces else None


def _cards(env, body):
    return env["client"].post(
        f"{API}/bulk_compute_cards/{DID}", json={"filters": [], "component_ids": [CARD], **body}
    )


# ── a view-only caller cannot hand the server a definition ─────────────────


def _code_payload(secret_path: str) -> dict:
    code = f"leak = pl.read_csv({secret_path!r})\nfig = px.bar(leak, x='name', y='value')"
    return {"component_overrides": {FIG: {"mode": "code", "code_content": code}}}


@pytest.mark.parametrize("who", ["anonymous_on_public_project", "project_viewer"])
def test_view_only_caller_cannot_execute_code(env, who):
    """The verifier's probe: a figure turned into code reading a server file."""
    if who == "project_viewer":
        env["who"]["user"] = _User(str(VIEWER_ID))

    response = _render_figure(env, _code_payload(env["secret"]))

    assert "TOPSECRET_SERVER_FILE_CONTENT" not in response.text
    assert response.status_code == 400, response.text


@pytest.mark.parametrize(
    "path",
    [
        f"render_figure/{DID}/{FIG}",
        f"render_table/{DID}/{TABLE}",
        f"bulk_compute_cards/{DID}",
        f"render_image_paths/{DID}/img-1",
        f"render_map/{DID}/map-1",
    ],
)
def test_component_overrides_is_refused_everywhere(env, path):
    """Refused, not ignored: an old client fails visibly instead of quietly
    drawing today's definition under a past label."""
    response = env["client"].post(
        f"{API}/{path}",
        json={"filters": [], "component_overrides": {FIG: {"title": "x"}}},
    )

    assert response.status_code == 400, response.text
    assert "definition_version" in response.json()["detail"]


# ── the version's definition is what is drawn ──────────────────────────────


def test_the_figure_is_drawn_as_the_version_defined_it(env):
    version = _version(env, main=[_figure(visu_type="bar")])

    live = _render_figure(env, {})
    past = _render_figure(env, {"definition_version": version})

    assert live.status_code == 200 and past.status_code == 200, past.text
    assert _trace_type(live).startswith("scatter")
    assert _trace_type(past) == "bar"


def test_the_card_is_computed_as_the_version_defined_it(env):
    version = _version(env, main=[_card(aggregation="sum")])

    live = _cards(env, {}).json()["values"][CARD]
    past = _cards(env, {"definition_version": version}).json()

    assert live == 3  # count of x
    assert past["values"][CARD] == 6  # sum of x
    assert "definition_errors" not in past


def test_a_text_tiles_values_are_computed_as_the_version_defined_them(env):
    """A text tile's live value is a card in all but name: its aggregation is
    part of the definition, so a past version computes it the past way too."""
    text = "text-1"

    def _text(aggregation):
        return {
            "index": text,
            "component_type": "text",
            "body": "{{n}}",
            "values": {"n": {"wf_id": WF, "dc_id": DC, "column": "x", "aggregation": aggregation}},
        }

    db = env["versions"].database
    db["dashboards"].update_one({"_id": DID}, {"$push": {"stored_metadata": _text("count")}})
    db["deltatables"].insert_one(
        {"data_collection_id": DC, "delta_table_location": env["dc_config"]["delta_location"]}
    )
    version = _version(env, main=[_text("sum")])

    def values(body):
        response = env["client"].post(
            f"{API}/bulk_compute_cards/{DID}", json={"filters": [], "component_ids": [text], **body}
        )
        return response.json()["values"][text]

    assert values({}) == {"n": 3}  # count of x
    assert values({"definition_version": version}) == {"n": 6}  # sum of x


def test_a_stale_version_is_400_with_the_detail_the_editor_matches(env):
    response = _render_figure(env, {"definition_version": "gone"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Version gone no longer exists."


def test_a_version_of_another_family_is_400(env):
    version = _version(env, main=[_figure(visu_type="bar")], family=OTHER_FAMILY)

    response = _render_figure(env, {"definition_version": version})

    assert response.status_code == 400
    assert response.json()["detail"] == f"Version {version} does not belong to this dashboard."


def test_definition_version_must_be_a_string(env):
    response = _render_figure(env, {"definition_version": 3})

    assert response.status_code == 400


def test_a_component_the_version_did_not_hold_is_404(env):
    version = _version(env, main=[])

    response = _render_figure(env, {"definition_version": version})

    assert response.status_code == 404
    assert "did not exist in version" in response.json()["detail"]


def test_a_version_reading_another_collection_is_409(env):
    """Its definition was written for other data: drawn over this collection's
    columns it would be a chart of nothing the version ever showed."""
    version = _version(env, main=[_figure(dc_id=DC_OTHER, visu_type="bar")])

    response = _render_figure(env, {"definition_version": version})

    assert response.status_code == 409
    assert "different data collection" in response.json()["detail"]


def test_the_collection_read_stays_the_live_ones(env):
    """``dc_config`` comes from the live component, never from the version."""
    version = _version(
        env,
        main=[_figure(visu_type="bar", dc_config={"delta_location": "/nowhere", "type": "table"})],
    )

    response = _render_figure(env, {"definition_version": version})

    assert response.status_code == 200, response.text
    assert _trace_type(response) == "bar"


def test_a_component_deleted_since_is_drawn_from_the_version(env):
    """The most valuable case for component history: it is no longer live."""
    version = _version(env, main=[_figure("gone-fig", visu_type="bar", dc_config={})])

    response = _render_figure(env, {"definition_version": version}, index="gone-fig")

    assert response.status_code == 200, response.text
    assert _trace_type(response) == "bar"
    # Without a version it is simply not there.
    assert _render_figure(env, {}, index="gone-fig").status_code == 404


def test_a_deleted_component_of_a_foreign_collection_is_404(env):
    """Only collections the dashboard's project holds are ever read."""
    version = _version(env, main=[_figure("gone-fig", dc_id=DC_FOREIGN)])

    response = _render_figure(env, {"definition_version": version}, index="gone-fig")

    assert response.status_code == 404
    assert "no longer holds" in response.json()["detail"]


def test_a_child_tab_component_is_found_on_its_own_tab(env):
    """Cross-tab components render under their owner tab's id: the version's
    tab is picked by that id, then the component by index."""
    version = _version(
        env, main=[_figure()], child=[_figure("child-fig", visu_type="bar", dc_config={})]
    )

    on_child = _render_figure(
        env, {"definition_version": version}, dashboard=CHILD, index="child-fig"
    )
    on_main = _render_figure(env, {"definition_version": version}, index="child-fig")

    assert on_child.status_code == 200, on_child.text
    assert _trace_type(on_child) == "bar"
    assert on_main.status_code == 404


# ── bulk: one card's problem is that card's ────────────────────────────────


def test_bulk_reports_a_card_that_cannot_be_drawn_and_computes_the_rest(env):
    version = _version(
        env,
        # card-2 was deleted since, and read a collection of no project.
        main=[_card(aggregation="sum"), _card("card-2", dc_id=DC_FOREIGN)],
    )

    response = env["client"].post(
        f"{API}/bulk_compute_cards/{DID}",
        json={"filters": [], "component_ids": [CARD, "card-2"], "definition_version": version},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["values"][CARD] == 6
    assert body["values"]["card-2"] is None
    assert body["definition_errors"]["card-2"]["status"] == 404


def test_bulk_reports_a_card_whose_collection_changed_as_409(env):
    version = _version(env, main=[_card(dc_id=DC_OTHER)])

    body = _cards(env, {"definition_version": version}).json()

    assert body["values"][CARD] is None
    assert body["definition_errors"][CARD]["status"] == 409


# ── a stored definition replaces the live one wholesale ────────────────────


def test_a_field_none_in_the_version_stays_none():
    """Merging would let today's value show through under the version's label."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _component_from_version

    live = _figure(dict_kwargs={"x": "x", "y": "y", "color": "species"}, title="Live")
    stored = _stringified(_figure(dict_kwargs=None, title=None))

    drawn = _component_from_version(
        {"stored_metadata": [stored]},
        live,
        FIG,
        "figure",
        project_id=PID,
        version_id="v",
        label="Figure",
    )

    assert drawn["dict_kwargs"] is None
    assert drawn["title"] is None
    assert drawn["dc_id"] == DC and isinstance(drawn["dc_id"], ObjectId)


def test_a_field_the_version_did_not_hold_is_absent():
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _component_from_version

    live = _figure(subtitle="added since")
    stored = _stringified(_figure())

    drawn = _component_from_version(
        {"stored_metadata": [stored]},
        live,
        FIG,
        "figure",
        project_id=PID,
        version_id="v",
        label="Figure",
    )

    assert "subtitle" not in drawn
