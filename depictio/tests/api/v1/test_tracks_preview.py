"""`GET /jbrowse/preview/{dc_id}` draws a track collection without a dashboard."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.jbrowse_endpoints import routes
from depictio.api.v1.services.jbrowse import render
from depictio.api.v1.services.jbrowse.tracks import TracksNotIngested

TDC = SimpleNamespace(project_id="p1")
USER = SimpleNamespace(id="u1", is_anonymous=False)


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.jbrowse, "enabled", True)
    monkeypatch.setattr(routes, "find_tracks_dc", lambda dc_id: TDC)
    monkeypatch.setattr(routes, "user_can_read_project", lambda project_id, uid: True)


def test_builds_the_view_from_the_collection_alone(enabled, monkeypatch: pytest.MonkeyPatch):
    seen = {}

    def build(component, tdc, filtered_rows, **kwargs):
        seen.update(component=component, filtered_rows=filtered_rows, uid=kwargs["uid"])
        return {"tracks": []}

    monkeypatch.setattr(render, "build_jbrowse_payload", build)

    assert routes.preview_tracks_collection("dc1", current_user=USER) == {"tracks": []}
    assert seen == {"component": {"dc_id": "dc1"}, "filtered_rows": None, "uid": "u1"}


def test_a_project_the_caller_cannot_read_is_a_404(enabled, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(routes, "user_can_read_project", lambda project_id, uid: False)

    with pytest.raises(HTTPException) as caught:
        routes.preview_tracks_collection("dc1", current_user=USER)

    assert caught.value.status_code == 404


def test_a_collection_of_another_type_is_a_404(enabled, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(routes, "find_tracks_dc", lambda dc_id: None)

    with pytest.raises(HTTPException) as caught:
        routes.preview_tracks_collection("dc1", current_user=USER)

    assert caught.value.status_code == 404


def test_a_collection_without_data_says_so(enabled, monkeypatch: pytest.MonkeyPatch):
    def empty(*args, **kwargs):
        raise TracksNotIngested("none")

    monkeypatch.setattr(render, "build_jbrowse_payload", empty)

    with pytest.raises(HTTPException) as caught:
        routes.preview_tracks_collection("dc1", current_user=USER)

    assert (caught.value.status_code, caught.value.detail) == (
        404,
        "This collection holds no tracks.",
    )
