"""``GET /files/serve/image`` serves an image only to callers who may read it.

The route used to stream any object in the configured bucket to any caller,
private projects' images included — it had to be open because ``<img>`` tags
cannot send an Authorization header. Access now needs one of:

- a short-lived HMAC signature minted by ``POST /files/serve/image/sign``
  (the viewer exchanges its listing paths for signed URLs), or
- viewer access to a project whose image data collection covers the key;
  anonymous callers only get images of public projects.

An image key names no data collection, so coverage is resolved by prefix:
a project whose DC's ``s3_base_folder`` contains the key. No covering
project means denied, even for a signed-in user (fail closed).
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch
from urllib.parse import parse_qsl

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from depictio.api.v1.endpoints.files_endpoints import routes
from depictio.api.v1.services import signed_media
from depictio.api.v1.services.signed_media import SCOPE_SERVE_IMAGE
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import UserBase

BUCKET = routes.settings.s3.bucket


def _image_path(key: str = "images/cell_001.png") -> str:
    return f"s3://{BUCKET}/{key}"


def _image_project(base: str, *, is_public: bool = False, viewers=(), owners=()) -> dict:
    """A project whose one image-like DC stores under ``base``."""
    return {
        "_id": ObjectId(),
        "name": "Imaging",
        "project_type": "advanced",
        "is_public": is_public,
        "workflows": [
            {
                "_id": ObjectId(),
                "workflow_tag": "imaging",
                "data_collections": [
                    {
                        "_id": ObjectId(),
                        "tag": "images",
                        "config": {"dc_specific_properties": {"s3_base_folder": base}},
                    }
                ],
            }
        ],
        "permissions": {
            "owners": [{"_id": oid} for oid in owners],
            "editors": [],
            "viewers": [{"_id": oid} for oid in viewers],
        },
    }


@pytest.fixture
def database():
    db = mongomock.MongoClient()["t"]
    with (
        patch("depictio.api.v1.db.projects_collection", db["projects"]),
        patch("depictio.api.v1.db.groups_collection", db["groups"]),
    ):
        yield db


class _FakeS3Client:
    """Stands in for the boto3 client: serves bytes, knows its exceptions."""

    class exceptions:  # noqa: N801
        class NoSuchKey(Exception):
            pass

        class NoSuchBucket(Exception):
            pass

    body = b"image-bytes"

    def get_object(self, Bucket, Key):  # noqa: ANN001, ARG002
        body = self.body

        class _Body:
            def iter_chunks(self, chunk_size=8192):  # noqa: ANN001, ARG001
                return iter([body])

        return {"Body": _Body()}


def _serve(s3_path, current_user, exp=None, sig=None):
    with patch.object(routes, "s3_client", _FakeS3Client()):
        return asyncio.run(
            routes.serve_image(s3_path=s3_path, exp=exp, sig=sig, current_user=current_user)
        )


def _user(*, admin=False, anonymous=False) -> UserBase:
    user = UserBase(id=PyObjectId(), email="caller@example.com")
    user.is_admin = admin
    user.is_anonymous = anonymous
    return user


def _query_for(key: str) -> dict[str, str]:
    return dict(parse_qsl(signed_media.signed_query(SCOPE_SERVE_IMAGE, key)))


# ── the signed-URL path ────────────────────────────────────────────────────


def test_valid_signature_is_served_without_a_session(database):
    """The URL minted by the sign endpoint streams the image on its own."""
    auth = _query_for("images/cell_001.png")
    response = _serve(_image_path(), None, exp=auth["exp"], sig=auth["sig"])
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "image/png"


def test_signature_cannot_be_widened_to_another_image(database):
    """A sig minted for one key is rejected for any other key."""
    auth = _query_for("images/cell_001.png")
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path("images/other.png"), None, exp=auth["exp"], sig=auth["sig"])
    assert exc.value.status_code == 403


def test_expired_signature_is_rejected(database):
    key = "images/cell_001.png"
    sig = signed_media.sign(SCOPE_SERVE_IMAGE, key, 0)
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path(key), None, exp="0", sig=sig)
    assert exc.value.status_code == 403


def test_signature_for_another_scope_is_rejected(database):
    """A logo signature cannot be replayed against serve/image."""
    from depictio.api.v1.services.signed_media import SCOPE_DASHBOARD_LOGO

    auth = dict(parse_qsl(signed_media.signed_query(SCOPE_DASHBOARD_LOGO, "images/cell_001.png")))
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path(), None, exp=auth["exp"], sig=auth["sig"])
    assert exc.value.status_code == 403


# ── the session path ───────────────────────────────────────────────────────


def test_anonymous_caller_gets_public_project_images_only(database):
    """Anonymous callers keep the public/demo viewer: public projects serve,
    private ones do not."""
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/images/", is_public=True))
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/private_images/"))
    anonymous = _user(anonymous=True)
    assert isinstance(_serve(_image_path(), anonymous), StreamingResponse)
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path("private_images/cell_001.png"), anonymous)
    assert exc.value.status_code == 403


def test_signed_in_stranger_is_denied_a_private_project_image(database):
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/private_images/"))
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path("private_images/cell_001.png"), _user())
    assert exc.value.status_code == 403


def test_viewer_of_the_covering_project_is_served(database):
    viewer_id = ObjectId()
    database["projects"].insert_one(
        _image_project(f"s3://{BUCKET}/private_images/", viewers=[viewer_id])
    )
    viewer = UserBase(id=viewer_id, email="viewer@example.com")
    viewer.is_admin = False
    response = _serve(_image_path("private_images/cell_001.png"), viewer)
    assert isinstance(response, StreamingResponse)


def test_admin_is_served(database):
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/private_images/"))
    response = _serve(_image_path("private_images/cell_001.png"), _user(admin=True))
    assert isinstance(response, StreamingResponse)


def test_key_no_project_covers_fails_closed(database):
    """A signed-in caller cannot read a key no image DC covers."""
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/other/"))
    with pytest.raises(HTTPException) as exc:
        _serve(_image_path("private_images/cell_001.png"), _user())
    assert exc.value.status_code == 403


def test_other_bucket_is_still_rejected(database):
    """The bucket lock predates this hardening and stays in force."""
    with pytest.raises(HTTPException) as exc:
        _serve("s3://not-our-bucket/images/cell_001.png", _user(admin=True))
    assert exc.value.status_code == 403


# ── the signing endpoint ────────────────────────────────────────────────────


def _sign(payload, user, database):
    with patch.object(routes, "s3_client", _FakeS3Client()):
        return asyncio.run(routes.sign_serve_images(payload, current_user=user))


def test_sign_endpoint_mints_verifiable_urls_and_omits_denied_paths(database):
    """One request for a whole gallery: authorized paths in, denied paths out."""
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/images/", is_public=True))
    database["projects"].insert_one(_image_project(f"s3://{BUCKET}/private_images/"))
    payload = routes.SignServeImagesRequest(
        s3_paths=[
            _image_path(),
            _image_path("private_images/cell_001.png"),
            "not-an-s3-path",
        ]
    )
    answer = _sign(payload, _user(anonymous=True), database)
    assert list(answer["urls"]) == [_image_path()]
    # The minted URL verifies against the key it grants.
    query = dict(parse_qsl(answer["urls"][_image_path()].split("?", 1)[1]))
    assert signed_media.verify(SCOPE_SERVE_IMAGE, "images/cell_001.png", query["exp"], query["sig"])


def test_sign_endpoint_gives_a_viewer_its_private_images(database):
    viewer_id = ObjectId()
    database["projects"].insert_one(
        _image_project(f"s3://{BUCKET}/private_images/", viewers=[viewer_id])
    )
    viewer = UserBase(id=viewer_id, email="viewer@example.com")
    viewer.is_admin = False
    payload = routes.SignServeImagesRequest(s3_paths=[_image_path("private_images/cell_001.png")])
    answer = _sign(payload, viewer, database)
    assert _image_path("private_images/cell_001.png") in answer["urls"]


# ── static and serverless exports ───────────────────────────────────────────


def test_exports_do_not_depend_on_serve_image():
    """Exports embed image bytes at export time (S3 read, ``inline:`` blob
    keys), never the anonymous serve/image URL — tightening it must not
    break them, and it must stay that way."""
    import depictio.api.v1.services.export.embed as embed_module
    import depictio.serverless.producer_a as producer_module

    assert "serve/image" not in inspect.getsource(producer_module)
    assert "serve/image" not in inspect.getsource(embed_module)
