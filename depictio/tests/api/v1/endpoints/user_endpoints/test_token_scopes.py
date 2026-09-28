"""REST enforcement of token scopes, the token API, and refresh behaviour."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from depictio.api.main import app
from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
from depictio.api.v1.endpoints.user_endpoints import scope_gate
from depictio.api.v1.endpoints.user_endpoints.scope_gate import (
    DENIED_READS,
    EXPLICIT_DENY,
    READ_METHODS,
    READ_ONLY_POSTS,
    WRITE_SCOPES,
    api_relative_path,
    enforce_token_scopes,
    required_scope,
)
from depictio.api.v1.endpoints.user_endpoints.token_scopes import current_token_scopes
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenData

API = "/depictio/api/v1"


# ---------------------------------------------------------------------------
# Route coverage: every write route needs an explicit decision
# ---------------------------------------------------------------------------


def _optional_routes_app() -> FastAPI:
    """The feature-gated routers, mounted as ``routers.py`` would mount them."""
    from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
    from depictio.api.v1.endpoints.analytics_data_endpoints.routes import (
        router as analytics_data_router,
    )
    from depictio.api.v1.endpoints.analytics_endpoints.routes import router as analytics_router
    from depictio.api.v1.endpoints.events_endpoints.routes import events_router
    from depictio.api.v1.endpoints.jbrowse_endpoints.routes import jbrowse_endpoints_router
    from depictio.api.v1.endpoints.monitoring_endpoints.routes import (
        monitoring_endpoint_router,
    )

    extra = FastAPI()
    for sub, prefix in (
        (jbrowse_endpoints_router, "/jbrowse"),
        (monitoring_endpoint_router, "/monitoring"),
        (analytics_router, "/analytics"),
        (analytics_data_router, "/analytics-data"),
        (ai_endpoint_router, "/ai"),
        (events_router, "/events"),
    ):
        extra.include_router(sub, prefix=API + prefix)
    return extra


def _api_route_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for routes in (app.routes, _optional_routes_app().routes):
        for ctx in iter_route_contexts(routes):
            if not isinstance(ctx.original_route, APIRoute) or not ctx.path:
                continue
            if not ctx.path.startswith(API + "/"):
                continue
            for method in ctx.methods or ():
                keys.add((method, api_relative_path(ctx.path)))
    return keys


ROUTE_KEYS = _api_route_keys()


def test_route_walk_found_the_api():
    assert ("GET", "/dashboards/list") in ROUTE_KEYS
    assert ("POST", "/ai/analyze") in ROUTE_KEYS  # optional routers included


def test_every_write_route_has_a_scope_decision():
    """A new write route must be added to one table, or scoped tokens get 403."""
    decided = READ_ONLY_POSTS | set(WRITE_SCOPES) | EXPLICIT_DENY
    undecided = sorted(k for k in ROUTE_KEYS if k[0] not in READ_METHODS and k not in decided)
    assert not undecided, (
        "Write routes without a scope decision; add them to READ_ONLY_POSTS, "
        f"WRITE_SCOPES or EXPLICIT_DENY in scope_gate.py: {undecided}"
    )


def test_scope_tables_are_disjoint():
    write = set(WRITE_SCOPES)
    assert not READ_ONLY_POSTS & write
    assert not READ_ONLY_POSTS & EXPLICIT_DENY
    assert not write & EXPLICIT_DENY


def test_scope_tables_have_no_stale_entries():
    """Renamed or removed routes must be dropped from the tables too."""
    stale = sorted((READ_ONLY_POSTS | set(WRITE_SCOPES) | EXPLICIT_DENY) - ROUTE_KEYS)
    assert not stale, f"Scope table entries without a route: {stale}"
    get_paths = {path for method, path in ROUTE_KEYS if method == "GET"}
    assert not DENIED_READS - get_paths


def test_every_api_route_carries_the_gate():
    missing = []
    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.original_route, APIRoute) or not ctx.path.startswith(API + "/"):
            continue
        calls = [dep.call for dep in ctx.dependant.dependencies] if ctx.dependant else []
        if enforce_token_scopes not in calls:
            missing.append(ctx.path)
    assert not missing


# ---------------------------------------------------------------------------
# Decision table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/dashboards/list", "read"),
        ("HEAD", "/dashboards/list", "read"),
        ("GET", "/auth/list_tokens", None),
        ("GET", "/utils/drop_all_collections", None),
        ("POST", "/dashboards/bulk_compute_cards/{dashboard_id}", "read"),
        ("POST", "/comments/threads", "annotate"),
        ("POST", "/comments/threads/{thread_id}/comments", "annotate"),
        ("POST", "/comments/threads/{thread_id}/review", None),
        ("POST", "/ai/analyze", "report"),
        ("POST", "/dashboards/save/{dashboard_id}", "edit_dashboard"),
        ("POST", "/projects/from_run", "ingest"),
        ("DELETE", "/projects/delete", None),
        ("POST", "/auth/me/tokens", None),
        ("POST", "/some/future/route", None),
    ],
)
def test_required_scope(method, path, expected):
    assert required_scope(method, path) == expected


def test_api_relative_path():
    assert api_relative_path("/depictio/api/v1/dashboards/list") == "/dashboards/list"
    assert api_relative_path("/depictio/api/v1") == "/"
    assert api_relative_path("/health") == "/health"


# ---------------------------------------------------------------------------
# Allow/deny matrix through a real router tree
# ---------------------------------------------------------------------------


def _stub_app() -> FastAPI:
    """Nested routers under the API prefix, gated like ``routers.py``."""

    async def ok() -> dict:
        return {"ok": True}

    dashboards = APIRouter()
    dashboards.add_api_route("/list", ok, methods=["GET"])
    dashboards.add_api_route("/render_figure/{dashboard_id}/{component_id}", ok, methods=["POST"])
    dashboards.add_api_route("/save/{dashboard_id}", ok, methods=["POST"])
    comments = APIRouter()
    comments.add_api_route("/threads", ok, methods=["POST"])
    comments.add_api_route("/threads/{thread_id}/review", ok, methods=["POST"])
    auth = APIRouter()
    auth.add_api_route("/me/tokens", ok, methods=["POST"])
    auth.add_api_route("/list_tokens", ok, methods=["GET"])
    projects = APIRouter()
    projects.add_api_route("/delete", ok, methods=["DELETE"])

    api = APIRouter(dependencies=[Depends(enforce_token_scopes)])
    api.include_router(dashboards, prefix="/dashboards")
    api.include_router(comments, prefix="/comments")
    api.include_router(auth, prefix="/auth")
    api.include_router(projects, prefix="/projects")
    stub = FastAPI()
    stub.include_router(api, prefix=API)
    return stub


def _token_doc(scopes):
    doc = MagicMock()
    doc.id = PydanticObjectId()
    doc.scopes = scopes
    return doc


READ_ONLY = ["read"]
AGENT = ["read", "annotate", "report"]
LEGACY = None

MATRIX = [
    # method, path, allowed for (read-only, agent, legacy)
    ("GET", "/dashboards/list", (True, True, True)),
    ("POST", "/dashboards/render_figure/d1/c1", (True, True, True)),
    ("POST", "/dashboards/save/d1", (False, False, True)),
    ("POST", "/comments/threads", (False, True, True)),
    ("POST", "/comments/threads/t1/review", (False, False, True)),
    ("POST", "/auth/me/tokens", (False, False, True)),
    ("GET", "/auth/list_tokens", (False, False, True)),
    ("DELETE", "/projects/delete", (False, False, True)),
]


@pytest.mark.parametrize(("method", "path", "allowed"), MATRIX)
@pytest.mark.parametrize("token_index", [0, 1, 2], ids=["read-only", "agent", "legacy"])
def test_allow_deny_matrix(method, path, allowed, token_index):
    scopes = (READ_ONLY, AGENT, LEGACY)[token_index]
    client = TestClient(_stub_app())
    with patch.object(
        scope_gate.TokenBeanie, "find_one", AsyncMock(return_value=_token_doc(scopes))
    ):
        response = client.request(method, API + path, headers={"Authorization": "Bearer tok"})
    expected = 200 if allowed[token_index] else 403
    assert response.status_code == expected, response.text


def test_unauthenticated_request_is_not_gated():
    client = TestClient(_stub_app())
    find_one = AsyncMock()
    with patch.object(scope_gate.TokenBeanie, "find_one", find_one):
        response = client.post(API + "/dashboards/save/d1")
    assert response.status_code == 200
    find_one.assert_not_called()


def test_unknown_token_is_left_to_route_auth():
    client = TestClient(_stub_app())
    with patch.object(scope_gate.TokenBeanie, "find_one", AsyncMock(return_value=None)):
        response = client.post(
            API + "/dashboards/save/d1", headers={"Authorization": "Bearer nope"}
        )
    assert response.status_code == 200


def test_token_lookup_failure_fails_closed():
    client = TestClient(_stub_app())
    with patch.object(
        scope_gate.TokenBeanie, "find_one", AsyncMock(side_effect=RuntimeError("db down"))
    ):
        response = client.get(API + "/dashboards/list", headers={"Authorization": "Bearer tok"})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# The real app
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/me/tokens"),
        ("GET", "/auth/list_tokens"),
        ("DELETE", "/projects/delete"),
        ("POST", "/comments/threads/abc/review"),
        ("POST", "/backup/create"),
    ],
)
def test_real_app_refuses_scoped_token(method, path):
    client = TestClient(app)
    with patch.object(
        scope_gate.TokenBeanie, "find_one", AsyncMock(return_value=_token_doc(AGENT))
    ):
        response = client.request(method, API + path, headers={"Authorization": "Bearer tok"})
    assert response.status_code == 403, response.text


def test_real_app_passes_legacy_token_to_route_auth():
    """A legacy token goes through untouched; route auth then rejects the fake JWT."""
    client = TestClient(app)
    with patch.object(
        scope_gate.TokenBeanie, "find_one", AsyncMock(return_value=_token_doc(LEGACY))
    ):
        response = client.post(
            API + "/auth/me/tokens",
            json={"name": "x"},
            headers={"Authorization": "Bearer tok"},
        )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Token API and refresh
# ---------------------------------------------------------------------------


def _user():
    user = MagicMock()
    user.id = PydanticObjectId()
    user.is_admin = False
    return user


@pytest.mark.asyncio
async def test_create_my_token_stores_scopes():
    added = MagicMock()
    with (
        patch.object(user_routes.TokenBeanie, "find_one", AsyncMock(return_value=None)),
        patch.object(user_routes, "_add_token", AsyncMock(return_value=added)) as add_token,
    ):
        result = await user_routes.create_my_token(
            user_routes._CreateMeTokenRequest(
                name="agent", scopes=["report", "annotate", "report"]
            ),
            current_user=_user(),
        )
    assert result is added
    token_data: TokenData = add_token.call_args[0][0]
    assert token_data.scopes == ["annotate", "report"]
    assert token_data.token_lifetime == "long-lived"


@pytest.mark.asyncio
async def test_create_my_token_without_scopes_keeps_full_access():
    with (
        patch.object(user_routes.TokenBeanie, "find_one", AsyncMock(return_value=None)),
        patch.object(user_routes, "_add_token", AsyncMock(return_value=MagicMock())) as add_token,
    ):
        await user_routes.create_my_token(
            user_routes._CreateMeTokenRequest(name="cli"), current_user=_user()
        )
    assert add_token.call_args[0][0].scopes is None


@pytest.mark.asyncio
async def test_create_my_token_rejects_empty_scopes():
    with pytest.raises(HTTPException) as exc:
        await user_routes.create_my_token(
            user_routes._CreateMeTokenRequest(name="x", scopes=[]), current_user=_user()
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_scoped_token_cannot_mint_tokens():
    reset = current_token_scopes.set(["read", "annotate"])
    try:
        with pytest.raises(HTTPException) as exc:
            await user_routes.create_my_token(
                user_routes._CreateMeTokenRequest(name="wider"), current_user=_user()
            )
    finally:
        current_token_scopes.reset(reset)
    assert exc.value.status_code == 403


def _refresh_patches(scopes):
    doc = MagicMock()
    doc.name = "agent"
    doc.user_id = PydanticObjectId()
    doc.scopes = scopes
    doc.save = AsyncMock()
    create = AsyncMock(return_value=("new-access", datetime.now() + timedelta(hours=1)))
    return create, (
        patch.object(user_routes.TokenBeanie, "find_one", AsyncMock(return_value=doc)),
        patch.object(user_routes.UserBeanie, "find_one", AsyncMock(return_value=_user())),
        patch.object(user_routes, "create_access_token", create),
        patch.object(user_routes, "_rearm_temporary_user_expiry", AsyncMock()),
        patch.object(user_routes, "_is_valid_internal_api_key", return_value=True),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [["read", "annotate"], None])
async def test_refresh_browser_keeps_scopes(scopes):
    create, patches = _refresh_patches(scopes)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        await user_routes.refresh_token_browser({"refresh_token": "r"})
    assert create.call_args[0][0].scopes == scopes


@pytest.mark.asyncio
async def test_refresh_endpoint_keeps_scopes():
    create, patches = _refresh_patches(["read"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        await user_routes.refresh_token_endpoint({"refresh_token": "r"}, api_key="k")
    assert create.call_args[0][0].scopes == ["read"]


@pytest.mark.asyncio
async def test_jwt_payload_carries_scopes():
    from depictio.api.v1.endpoints.user_endpoints.utils import create_access_token

    data = TokenData(sub=PyObjectId(str(PydanticObjectId())), scopes=["read", "report"])
    with patch("depictio.api.v1.endpoints.user_endpoints.utils.jwt.encode") as encode:
        encode.return_value = "jwt"
        await create_access_token(data)
    assert encode.call_args[0][0]["scopes"] == ["read", "report"]
