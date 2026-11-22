"""``GET /dashboards/logo/{id}`` serves a logo only to callers who may read it.

The route used to be unauthenticated: anyone could read the logo of any
dashboard, private projects' included. Access now needs one of:

- a short-lived HMAC signature minted by ``POST /dashboards/logo/sign``
  (the viewer swaps the stored logo URL for a signed one, since ``<img>``
  tags cannot send an Authorization header), or
- viewer access to the dashboard's project; anonymous callers are served
  only when that project is public, which keeps the public/demo viewer
  working.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import patch
from urllib.parse import parse_qsl

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.services import branding, signed_media
from depictio.api.v1.services.signed_media import SCOPE_DASHBOARD_LOGO
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import UserBase

LOGO_BYTES = b"png-logo-bytes"


@pytest.fixture
def database():
    db = mongomock.MongoClient()["t"]
    with (
        patch.object(routes, "dashboards_collection", db["dashboards"]),
        patch.object(routes, "projects_collection", db["projects"]),
        patch("depictio.api.v1.db.groups_collection", db["groups"]),
        patch.object(branding, "branding_assets_collection", db["branding_assets"]),
    ):
        yield db


def _user(*, admin=False, anonymous=False) -> UserBase:
    user = UserBase(id=PyObjectId(), email="caller@example.com")
    user.is_admin = admin
    user.is_anonymous = anonymous
    return user


def _setup(database, *, is_public: bool, viewers=()):
    """A project with one dashboard whose logo is stored; returns its id."""
    project_id = ObjectId()
    database["projects"].insert_one(
        {
            "_id": project_id,
            "name": "P",
            "project_type": "advanced",
            "is_public": is_public,
            "permissions": {
                "owners": [],
                "editors": [],
                "viewers": [{"_id": oid} for oid in viewers],
            },
        }
    )
    dashboard_id = PyObjectId()
    database["dashboards"].insert_one({"dashboard_id": dashboard_id, "project_id": project_id})
    database["branding_assets"].insert_one(
        {
            "_id": branding.dashboard_logo_key(dashboard_id),
            "content_type": "image/png",
            "data_b64": base64.b64encode(LOGO_BYTES).decode("ascii"),
        }
    )
    return dashboard_id


def _logo(dashboard_id, current_user, exp=None, sig=None):
    return asyncio.run(
        routes.get_dashboard_logo(
            dashboard_id=dashboard_id, exp=exp, sig=sig, current_user=current_user
        )
    )


# ── the session path ────────────────────────────────────────────────────────


def test_anonymous_caller_gets_public_project_logos_only(database):
    public_id = _setup(database, is_public=True)
    private_id = _setup(database, is_public=False)
    anonymous = _user(anonymous=True)
    assert _logo(public_id, anonymous).body == LOGO_BYTES
    with pytest.raises(HTTPException) as exc:
        _logo(private_id, anonymous)
    assert exc.value.status_code == 403


def test_no_user_is_401(database):
    dashboard_id = _setup(database, is_public=True)
    with pytest.raises(HTTPException) as exc:
        _logo(dashboard_id, None)
    assert exc.value.status_code == 401


def test_viewer_of_a_private_project_is_served(database):
    viewer_id = ObjectId()
    dashboard_id = _setup(database, is_public=False, viewers=[viewer_id])
    viewer = UserBase(id=viewer_id, email="viewer@example.com")
    viewer.is_admin = False
    assert _logo(dashboard_id, viewer).body == LOGO_BYTES


def test_signed_in_stranger_is_denied_a_private_project_logo(database):
    dashboard_id = _setup(database, is_public=False)
    with pytest.raises(HTTPException) as exc:
        _logo(dashboard_id, _user())
    assert exc.value.status_code == 403


def test_missing_logo_is_404_even_when_authorized(database):
    dashboard_id = _setup(database, is_public=True)
    database["branding_assets"].delete_one({"_id": branding.dashboard_logo_key(dashboard_id)})
    with pytest.raises(HTTPException) as exc:
        _logo(dashboard_id, _user(anonymous=True))
    assert exc.value.status_code == 404


# ── the signed-URL path ────────────────────────────────────────────────────


def _signature_for(dashboard_id) -> dict[str, str]:
    return dict(parse_qsl(signed_media.signed_query(SCOPE_DASHBOARD_LOGO, str(dashboard_id))))


def test_valid_signature_serves_without_a_session(database):
    dashboard_id = _setup(database, is_public=False)
    auth = _signature_for(dashboard_id)
    response = _logo(dashboard_id, None, exp=auth["exp"], sig=auth["sig"])
    assert response.body == LOGO_BYTES


def test_signature_cannot_be_widened_to_another_dashboard(database):
    granted_id = _setup(database, is_public=True)
    other_id = _setup(database, is_public=False)
    auth = _signature_for(granted_id)
    with pytest.raises(HTTPException) as exc:
        _logo(other_id, None, exp=auth["exp"], sig=auth["sig"])
    assert exc.value.status_code == 401


def test_expired_signature_is_rejected(database):
    dashboard_id = _setup(database, is_public=True)
    sig = signed_media.sign(SCOPE_DASHBOARD_LOGO, str(dashboard_id), 0)
    with pytest.raises(HTTPException) as exc:
        _logo(dashboard_id, None, exp="0", sig=sig)
    assert exc.value.status_code == 401


# ── the signing endpoint ────────────────────────────────────────────────────


def _sign(dashboard_ids, user, database):
    return asyncio.run(
        routes.sign_dashboard_logos({"dashboard_ids": dashboard_ids}, current_user=user)
    )


def test_sign_endpoint_omits_denied_and_unknown_ids(database):
    """Authorized ids in, denied and unparseable ids out."""
    public_id = _setup(database, is_public=True)
    private_id = _setup(database, is_public=False)
    answer = _sign([str(public_id), str(private_id), "not-an-id"], _user(anonymous=True), database)
    assert list(answer["urls"]) == [str(public_id)]
    # The minted URL verifies for the dashboard it grants.
    query = dict(parse_qsl(answer["urls"][str(public_id)].split("?", 1)[1]))
    assert signed_media.verify(SCOPE_DASHBOARD_LOGO, str(public_id), query["exp"], query["sig"])
    # The base of the minted URL is the stored (cache-busted) logo URL.
    assert answer["urls"][str(public_id)].split("?")[0].endswith(f"/dashboards/logo/{public_id}")


def test_sign_endpoint_serves_a_viewer_its_private_logo(database):
    viewer_id = ObjectId()
    dashboard_id = _setup(database, is_public=False, viewers=[viewer_id])
    viewer = UserBase(id=viewer_id, email="viewer@example.com")
    viewer.is_admin = False
    answer = _sign([str(dashboard_id)], viewer, database)
    assert str(dashboard_id) in answer["urls"]


def test_sign_endpoint_rejects_a_bad_payload(database):
    with pytest.raises(HTTPException) as exc:
        _sign(None, _user(admin=True), database)
    assert exc.value.status_code == 400


# ── the stored document keeps the unsigned URL ──────────────────────────────


def test_write_paths_strip_the_short_lived_signature():
    """The upload response's logo URL is signed, and the editor round-trips
    what it loaded back through /save and /appearance: the document must keep
    the stable unsigned URL, never a signature that expires."""
    theme = {
        "logo_url": "/depictio/api/v1/dashboards/logo/abc?exp=123&sig=456&v=7",
        "logo_url_dark": "/depictio/api/v1/dashboards/logo/abc?v=7",
    }
    routes._strip_logo_signatures(theme)
    assert theme["logo_url"] == "/depictio/api/v1/dashboards/logo/abc?v=7"
    assert theme["logo_url_dark"] == "/depictio/api/v1/dashboards/logo/abc?v=7"

    # Both write paths run the strip on the client-echoed theme.
    import inspect

    assert "_strip_logo_signatures" in inspect.getsource(routes.save_dashboard)
    assert "_strip_logo_signatures" in inspect.getsource(routes.update_dashboard_appearance)
