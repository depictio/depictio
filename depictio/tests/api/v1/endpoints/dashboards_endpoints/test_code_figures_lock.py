"""With the lock on, non-admins cannot add figure code, and existing figures keep working."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest
import yaml
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import code_figures
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.figure_endpoints import routes as figure_routes

STORED = "fig = px.scatter(df, x='a', y='b')"
NEW = "fig = px.bar(df, x='a', y='b')"
PARTICIPANT = SimpleNamespace(is_admin=False, is_anonymous=False)
ADMIN = SimpleNamespace(is_admin=True, is_anonymous=False)


def _figure(code: str, mode: str = "code") -> dict:
    return {"component_type": "figure", "mode": mode, "code_content": code}


@pytest.fixture()
def locked(monkeypatch):
    collection = mongomock.MongoClient().db.dashboards
    collection.insert_one({"stored_metadata": [_figure(STORED)]})
    monkeypatch.setattr(code_figures, "dashboards_collection", collection)
    monkeypatch.setattr(code_figures.settings.viewer, "code_figures_locked", True)


@pytest.mark.usefixtures("locked")
def test_new_code_is_refused():
    with pytest.raises(HTTPException) as exc:
        code_figures.refuse_new_figure_code([_figure(NEW)], PARTICIPANT)
    assert exc.value.status_code == 403


@pytest.mark.usefixtures("locked")
def test_code_already_on_a_dashboard_passes():
    code_figures.refuse_new_figure_code([_figure(STORED)], PARTICIPANT)


@pytest.mark.usefixtures("locked")
def test_catalogue_code_passes():
    assert code_figures._catalog_code()
    code = next(iter(code_figures._catalog_code()))
    code_figures.refuse_new_figure_code([_figure(code)], PARTICIPANT)


@pytest.mark.usefixtures("locked")
def test_an_admin_may_write_code():
    code_figures.refuse_new_figure_code([_figure(NEW)], ADMIN)


@pytest.mark.usefixtures("locked")
def test_a_ui_figure_is_not_code():
    code_figures.refuse_new_figure_code([_figure(NEW, mode="ui")], PARTICIPANT)


@pytest.mark.usefixtures("locked")
def test_code_nested_in_tabs_is_found():
    document = {"tabs": [{"components": [_figure(NEW)]}]}
    with pytest.raises(HTTPException):
        code_figures.refuse_new_figure_code(document, PARTICIPANT)


def test_nothing_is_refused_when_the_lock_is_off(monkeypatch):
    monkeypatch.setattr(code_figures.settings.viewer, "code_figures_locked", False)
    code_figures.refuse_new_figure_code([_figure(NEW)], PARTICIPANT)


@pytest.mark.usefixtures("locked")
def test_the_preview_route_refuses_new_code(monkeypatch):
    monkeypatch.setattr(figure_routes, "_authorize_preview_dc", lambda *_args: None)
    request = {"metadata": {**_figure(NEW), "wf_id": "w", "dc_id": "d"}}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(figure_routes.preview_figure(MagicMock(), request, PARTICIPANT))
    assert exc.value.status_code == 403


@pytest.mark.usefixtures("locked")
def test_the_save_route_refuses_new_code_before_writing(monkeypatch):
    collection = MagicMock()
    collection.find_one.return_value = None
    monkeypatch.setattr(dash_routes, "dashboards_collection", collection)
    data = SimpleNamespace(mongo=lambda: {"stored_metadata": [_figure(NEW)]})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dash_routes.save_dashboard("id", data, current_user=PARTICIPANT))
    assert exc.value.status_code == 403
    collection.insert_one.assert_not_called()
    collection.update_one.assert_not_called()


@pytest.mark.usefixtures("locked")
def test_the_yaml_import_route_refuses_new_code():
    content = yaml.safe_dump({"title": "t", "components": [_figure(NEW)]})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dash_routes.import_dashboard_from_yaml(content, current_user=PARTICIPANT))
    assert exc.value.status_code == 403


@pytest.mark.usefixtures("locked")
def test_the_json_import_route_refuses_new_code():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            dash_routes.import_dashboard_from_json(
                {"stored_metadata": [_figure(NEW)]}, current_user=PARTICIPANT
            )
        )
    assert exc.value.status_code == 403
