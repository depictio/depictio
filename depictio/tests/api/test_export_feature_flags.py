"""The offline exports ship switched off, and switched off they are absent.

The suite's conftest turns both on (`DEPICTIO_NOTEBOOK_EXPORT_ENABLED`,
`DEPICTIO_STATIC_EXPORT_ENABLED`) because it exercises them; these tests read
the shipped defaults with those variables unset, and check that every
`/serverless` route answers 404 while the static export is off.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from depictio.api.v1.configs.settings_models import NotebookExportConfig, StaticExportConfig
from depictio.api.v1.endpoints.serverless_endpoints import routes as routes_mod


def test_both_exports_are_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEPICTIO_NOTEBOOK_EXPORT_ENABLED", raising=False)
    monkeypatch.delenv("DEPICTIO_STATIC_EXPORT_ENABLED", raising=False)
    assert NotebookExportConfig().enabled is False
    assert StaticExportConfig().enabled is False


def test_the_env_turns_them_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPICTIO_NOTEBOOK_EXPORT_ENABLED", "true")
    monkeypatch.setenv("DEPICTIO_STATIC_EXPORT_ENABLED", "true")
    assert NotebookExportConfig().enabled is True
    assert StaticExportConfig().enabled is True


def _serverless_routes() -> list[tuple[str, str]]:
    out = []
    for route in routes_mod.serverless_endpoint_router.routes:
        if isinstance(route, APIRoute):
            path = route.path.replace("{dashboard_id}", "6824cb3b89d2b72169309737").replace(
                "{job_id}", "job-1"
            )
            out.extend((method, path) for method in route.methods)
    return out


def test_every_serverless_route_is_behind_the_switch() -> None:
    """Router-wide, so a route added later cannot escape the gate."""
    assert all(
        any(
            getattr(dep.call, "__name__", "") == "_require_static_export_enabled"
            for dep in route.dependant.dependencies
        )
        for route in routes_mod.serverless_endpoint_router.routes
        if isinstance(route, APIRoute)
    )


@pytest.mark.parametrize(("method", "path"), _serverless_routes())
def test_switched_off_every_serverless_route_is_404(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.setattr(routes_mod.settings.static_export, "enabled", False)
    app = FastAPI()
    app.include_router(routes_mod.serverless_endpoint_router, prefix="/serverless")
    response = TestClient(app).request(method, f"/serverless{path}", json={})
    assert response.status_code == 404
    assert response.json()["detail"] == "Static export is disabled."
