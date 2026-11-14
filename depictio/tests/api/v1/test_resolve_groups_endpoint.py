"""``POST /resolve_groups``: the guards and the hand-off to the link translation.

The translation itself (``resolve_group_defs_for_dc``) is covered with the
figure groups; what is checked here is what the endpoint adds: a required
``dc_id``, a data collection that must belong to the dashboard's project, and
the rewritten groups returned with one verdict per input group.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes

GROUP = {
    "name": "Group 1",
    "column_name": "guide",
    "values": ["ACG"],
    "color": "#ff0000",
    "dc_id": "dc-guide",
}


def _call(body: dict):
    return asyncio.run(
        routes.resolve_groups_endpoint("0" * 24, body, current_user=object(), access_token="t")
    )


@pytest.fixture
def project(monkeypatch):
    monkeypatch.setattr(routes, "_viewable_dashboard", lambda *_a: {"project_id": "p1"})
    monkeypatch.setattr(routes, "_project_collections", lambda _pid: {"dc-lib": {}, "dc-guide": {}})


def test_dc_id_is_required(project):
    with pytest.raises(HTTPException) as err:
        _call({"groups": [GROUP]})
    assert err.value.status_code == 400


def test_a_collection_of_another_project_is_a_404(project):
    with pytest.raises(HTTPException) as err:
        _call({"dc_id": "dc-elsewhere", "groups": [GROUP]})
    assert err.value.status_code == 404


def test_returns_the_rewritten_groups_and_one_verdict_each(project, monkeypatch):
    seen = {}

    def fake(group_defs, dc_id, project_id, token, component_type, target_columns=None):
        seen.update(dc_id=dc_id, project_id=project_id, component_type=component_type)
        return [{**group_defs[0], "column_name": "sample", "values": ["s1"]}], [
            {"status": "translated"}
        ]

    monkeypatch.setattr(routes, "_resolve_group_defs", fake)
    out = _call({"dc_id": "dc-lib", "groups": [GROUP]})
    assert out["groups"][0]["column_name"] == "sample"
    assert out["groups"][0]["values"] == ["s1"]
    assert out["status"] == [{"status": "translated"}]
    assert seen == {"dc_id": "dc-lib", "project_id": "p1", "component_type": "advanced_viz"}


def test_no_groups_resolves_to_nothing(project):
    assert _call({"dc_id": "dc-lib", "groups": []}) == {"groups": [], "status": []}


# ── groups of runs (the Overlay of "What's new") ────────────────────────────

NEW = {"name": "New: 2 runs", "column_name": "depictio_run_id", "values": ["b", "c"], "color": "#1"}
SEEN = {"name": "Seen before", "column_name": "depictio_run_id", "values": ["a"], "color": "#2"}
EMBEDDING = {
    "index": "emb",
    "dc_id": "dc-lib",
    "wf_id": "0" * 24,
    "config": {"sample_id_col": "sample_id", "dim_1_col": "x"},
}


@pytest.fixture
def frame(monkeypatch):
    import polars as pl

    from depictio.api.v1 import deltatables_utils

    state = {
        "frame": pl.DataFrame(
            {"sample_id": ["s1", "s2", "s3", "s4"], "depictio_run_id": ["a", "b", "c", None]}
        )
    }
    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", lambda *_a, **_k: state["frame"])
    return state


def test_run_groups_become_the_ids_of_the_component_marks(project, frame, monkeypatch):
    monkeypatch.setattr(
        routes,
        "_viewable_dashboard",
        lambda *_a: {"project_id": "p1", "stored_metadata": [EMBEDDING]},
    )
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [NEW, SEEN]})
    assert [(g["name"], g["column_name"], g["values"]) for g in out["groups"]] == [
        ("New: 2 runs", "sample_id", ["s2", "s3"]),
        ("Seen before", "sample_id", ["s1"]),
    ]
    assert [s["status"] for s in out["status"]] == ["runs", "runs"]


def test_ids_with_rows_of_both_sides_drop_every_run_group(project, frame, monkeypatch):
    import polars as pl

    # A feature tested once per run: its id is under both sides.
    frame["frame"] = pl.DataFrame(
        {"sample_id": ["f1", "f1", "f2", "f2"], "depictio_run_id": ["a", "b", "a", "c"]}
    )
    monkeypatch.setattr(
        routes,
        "_viewable_dashboard",
        lambda *_a: {"project_id": "p1", "stored_metadata": [EMBEDDING]},
    )
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [NEW, SEEN]})
    assert out["groups"] == []
    assert [s["status"] for s in out["status"]] == ["runs_ambiguous", "runs_ambiguous"]


def test_a_component_without_an_id_role_resolves_run_groups_as_before(project, frame, monkeypatch):
    bare = {**EMBEDDING, "config": {"abundance_col": "x"}}
    monkeypatch.setattr(
        routes, "_viewable_dashboard", lambda *_a: {"project_id": "p1", "stored_metadata": [bare]}
    )
    monkeypatch.setattr(
        routes,
        "_resolve_group_defs",
        lambda defs, *_a, **_k: (defs, [{"status": "applied"}] * len(defs)),
    )
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [NEW]})
    assert out["groups"][0]["column_name"] == "depictio_run_id"


def _with_embedding(monkeypatch, component=EMBEDDING):
    monkeypatch.setattr(
        routes,
        "_viewable_dashboard",
        lambda *_a: {"project_id": "p1", "stored_metadata": [component]},
    )


def _resolve_as_applied(monkeypatch):
    seen: list[list[str]] = []

    def fake(defs, *_a, **_k):
        seen.append([g["name"] for g in defs])
        return defs, [{"name": g["name"], "status": "applied"} for g in defs]

    monkeypatch.setattr(routes, "_resolve_group_defs", fake)
    return seen


def test_run_and_other_groups_come_back_in_the_order_asked(project, frame, monkeypatch):
    _with_embedding(monkeypatch)
    seen = _resolve_as_applied(monkeypatch)
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [GROUP, NEW, SEEN]})
    # Only the foreign group goes through the links; the runs are answered here.
    assert seen == [["Group 1"]]
    assert [g["name"] for g in out["groups"]] == ["Group 1", "New: 2 runs", "Seen before"]
    assert [s["status"] for s in out["status"]] == ["applied", "runs", "runs"]


def test_a_run_column_group_of_another_collection_goes_through_the_links(
    project, frame, monkeypatch
):
    _with_embedding(monkeypatch)
    seen = _resolve_as_applied(monkeypatch)
    captured = {**NEW, "dc_id": "dc-guide"}
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [captured, SEEN]})
    assert seen == [["New: 2 runs"]]
    assert [s["status"] for s in out["status"]] == ["applied", "runs"]


@pytest.mark.parametrize(
    "component, columns",
    [
        ({**EMBEDDING, "dc_id": "dc-guide"}, None),  # the component reads another collection
        (EMBEDDING, {"sample_id": ["s1"]}),  # its table has no run column
    ],
    ids=["other-collection", "no-run-column"],
)
def test_run_groups_fall_back_when_the_component_cannot_answer(
    project, frame, monkeypatch, component, columns
):
    import polars as pl

    if columns is not None:
        frame["frame"] = pl.DataFrame(columns)
    _with_embedding(monkeypatch, component)
    seen = _resolve_as_applied(monkeypatch)
    out = _call({"dc_id": "dc-lib", "component_id": "emb", "groups": [NEW, SEEN]})
    assert seen == [["New: 2 runs", "Seen before"]]
    assert [s["status"] for s in out["status"]] == ["applied", "applied"]
