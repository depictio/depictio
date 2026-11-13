"""Contract for the OME-Zarr store endpoints under ``/advanced_viz/bioimage``.

A browser zarr reader fetches ``.zattrs``, ``.zarray`` and then one request per
chunk, and treats a 404 as "empty chunk". So the chunk route must:

* gate on project access before touching storage (and cache that gate briefly);
* reject traversal in both the store name and the key;
* return 404 only for a genuine miss, S3 first, then the registered store on disk;
* authenticate from the Authorization header only (no ``?token=`` fallback);
* let metadata revalidate (``no-cache``) while chunks cache for an hour;
* keep one root per store name when two registered paths share it.

The router is mounted on a bare app; Mongo, S3 and token validation are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)

DC_ID = ObjectId()
FILE_ID = ObjectId()
PREFIX = "/depictio/api/v1/advanced_viz"
USER = MagicMock(is_admin=False, id=ObjectId())
OTHER_USER = MagicMock(is_admin=False, id=ObjectId())


def make_store(parent: Path, name: str = "sample_A.zarr") -> Path:
    store = parent / name
    (store / "0").mkdir(parents=True)
    (store / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4"}]}))
    (store / "0" / ".zarray").write_text(json.dumps({"zarr_format": 2}))
    (store / "0" / "0.0.0").write_bytes(b"\x01\x02\x03")
    return store


class Body:
    def __init__(self, data: bytes, fail: bool = False):
        self.data = data
        self.fail = fail
        self.closed = False

    def read(self) -> bytes:
        if self.fail:
            raise ConnectionError("connection reset mid-read")
        return self.data

    def close(self) -> None:
        self.closed = True


def no_such_key() -> ClientError:
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")


class Env:
    """Mocked projects/files collections, S3 client and token validation."""

    def __init__(self, tmp_path: Path, *, permitted: bool = True, upload: bool = True):
        self.tmp_path = tmp_path
        self.projects = MagicMock()
        self.files = MagicMock()
        self.s3 = MagicMock()
        self.s3.get_object.side_effect = no_such_key()
        self.file_docs: list[dict] = []
        self.dc_doc = {
            "_id": DC_ID,
            "config": {"type": "bioimage", "dc_specific_properties": {"upload": upload}},
        }
        self.permitted = permitted
        self.tokens: list[str | None] = []

        def find_one(query, projection=None):
            if "$or" in query and not self.permitted:
                return None
            return {"_id": ObjectId(), "workflows": [{"data_collections": [self.dc_doc]}]}

        self.projects.find_one.side_effect = find_one
        self.files.find.side_effect = lambda *a, **k: list(self.file_docs)

    def register(self, store: Path) -> None:
        self.file_docs.append({"_id": FILE_ID, "file_location": str(store)})

    def __enter__(self) -> TestClient:
        async def fake_user(token: str | None = Depends(oauth2_scheme_optional)):
            self.tokens.append(token)
            if token == "other":
                return OTHER_USER
            if token is None:
                raise HTTPException(status_code=401, detail="Invalid token")
            return USER

        routes._bioimage_access_cache.clear()
        routes._bioimage_store_cache.clear()
        self._patches = [
            patch("depictio.api.v1.db.projects_collection", self.projects),
            patch("depictio.api.v1.db.files_collection", self.files),
            patch.object(routes, "_bioimage_s3_client", lambda: self.s3),
        ]
        for p in self._patches:
            p.start()
        app = FastAPI()
        app.dependency_overrides[get_user_or_anonymous] = fake_user
        app.include_router(routes.advanced_viz_endpoint_router, prefix=PREFIX)
        return TestClient(app)

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        routes._bioimage_access_cache.clear()
        routes._bioimage_store_cache.clear()


AUTH = {"Authorization": "Bearer good"}


def key_url(store: str, key: str) -> str:
    return f"{PREFIX}/bioimage/{DC_ID}/{store}/{key}"


class TestAccessGate:
    def test_denied_before_any_storage_read(self, tmp_path):
        env = Env(tmp_path, permitted=False)
        with env as client:
            resp = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 404
        env.s3.get_object.assert_not_called()
        env.files.find.assert_not_called()

    def test_denied_on_the_stores_listing(self, tmp_path):
        env = Env(tmp_path, permitted=False)
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert resp.status_code == 404
        env.files.find.assert_not_called()

    def test_grant_is_cached_per_user(self, tmp_path):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = lambda **kw: {"Body": Body(b"x")}
        with env as client:
            for _ in range(3):
                assert (
                    client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH).status_code == 200
                )
            access_checks = [c for c in env.projects.find_one.call_args_list if "$or" in c.args[0]]
            assert len(access_checks) == 1

            client.get(
                key_url("sample_A.zarr", "0/0.0.0"), headers={"Authorization": "Bearer other"}
            )
            access_checks = [c for c in env.projects.find_one.call_args_list if "$or" in c.args[0]]
            assert len(access_checks) == 2

    def test_token_query_param_is_ignored(self, tmp_path):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"x")}
        with env as client:
            chunk = client.get(key_url("sample_A.zarr", ".zattrs") + "?token=good")
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores?token=good")
            with_header = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)

        assert chunk.status_code == 401
        assert listing.status_code == 401
        assert with_header.status_code == 200
        assert env.tokens == [None, None, "good"]
        env.s3.get_object.assert_called_once()


class TestTraversal:
    @pytest.mark.parametrize(
        ("store", "key"),
        [
            ("sample_A.zarr", "%2e%2e/other.zarr/.zattrs"),
            ("sample_A.zarr", "0/../../secret"),
            ("sample_A.zarr", "0//0.0.0"),
            ("sample_A.zarr", "0/%2e%2e/%2e%2e/secret"),
            ("..", ".zattrs"),
            ("not_a_store", ".zattrs"),
        ],
    )
    def test_rejected(self, tmp_path, store, key):
        env = Env(tmp_path)
        with env as client:
            resp = client.get(key_url(store, key), headers=AUTH)

        assert resp.status_code in (400, 404)
        env.s3.get_object.assert_not_called()

    @pytest.mark.parametrize(
        "key", ["../x", "0/../../x", "/etc/passwd", "0//0", "a\\b", "0/./0", ".", ""]
    )
    def test_key_normalisation_rejects(self, key):
        assert routes._normalize_zarr_key(key) is None

    @pytest.mark.parametrize("key", [".zattrs", "0/.zarray", "0/0.0.0.0.0", "0/0/0/0/0/0"])
    def test_key_normalisation_accepts_zarr_keys(self, key):
        assert routes._normalize_zarr_key(key) == key

    def test_symlink_out_of_the_store_is_not_served(self, tmp_path):
        store = make_store(tmp_path)
        secret = tmp_path / "secret.txt"
        secret.write_text("nope")
        (store / "leak").symlink_to(secret)
        env = Env(tmp_path, upload=False)
        env.register(store)
        with env as client:
            resp = client.get(key_url("sample_A.zarr", "leak"), headers=AUTH)

        assert resp.status_code == 404


class TestServing:
    def test_s3_object_is_served_with_zarr_content_types(self, tmp_path):
        env = Env(tmp_path)
        meta_body, chunk_body = Body(b'{"a": 1}'), Body(b"\x00\x01")
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": meta_body}
        with env as client:
            meta = client.get(key_url("sample_A.zarr", "0/.zarray"), headers=AUTH)
            env.s3.get_object.return_value = {"Body": chunk_body}
            chunk = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        assert meta.status_code == 200
        assert meta.headers["content-type"] == "application/json"
        assert meta.json() == {"a": 1}
        assert meta.headers["content-length"] == "8"
        assert chunk.content == b"\x00\x01"
        assert chunk.headers["content-type"] == "application/octet-stream"
        assert (
            env.s3.get_object.call_args.kwargs["Key"] == f"bioimage/{DC_ID}/sample_A.zarr/0/0.0.0"
        )
        assert meta_body.closed and chunk_body.closed

    @pytest.mark.parametrize("key", [".zattrs", ".zgroup", "0/.zarray", ".zmetadata"])
    def test_metadata_is_revalidated(self, tmp_path, key):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"{}")}
        with env as client:
            resp = client.get(key_url("sample_A.zarr", key), headers=AUTH)

        assert resp.headers["cache-control"] == "no-cache"

    def test_chunks_are_cached_on_s3_and_disk(self, tmp_path):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"\x00")}
        with env as client:
            s3_chunk = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        disk_env = Env(tmp_path, upload=False)
        disk_env.register(make_store(tmp_path))
        with disk_env as client:
            disk_chunk = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)
            disk_meta = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)

        assert s3_chunk.headers["cache-control"] == "private, max-age=3600"
        assert disk_chunk.headers["cache-control"] == "private, max-age=3600"
        assert disk_meta.headers["cache-control"] == "no-cache"

    def test_mid_read_s3_failure_is_502_and_closes_the_body(self, tmp_path):
        env = Env(tmp_path)
        body = Body(b"", fail=True)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": body}
        with env as client:
            resp = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        assert resp.status_code == 502
        assert body.closed

    def test_missing_chunk_is_404(self, tmp_path):
        env = Env(tmp_path)
        env.register(make_store(tmp_path))
        with env as client:
            resp = client.get(key_url("sample_A.zarr", "0/9.9.9"), headers=AUTH)

        assert resp.status_code == 404

    def test_disk_fallback_serves_the_registered_store(self, tmp_path):
        env = Env(tmp_path)
        env.register(make_store(tmp_path))
        with env as client:
            chunk = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)
            attrs = client.get(key_url("sample_A.zarr", ".zattrs"), headers=AUTH)

        assert chunk.status_code == 200
        assert chunk.content == b"\x01\x02\x03"
        assert attrs.headers["content-type"] == "application/json"
        assert "multiscales" in attrs.json()

    def test_reference_only_dc_skips_s3(self, tmp_path):
        env = Env(tmp_path, upload=False)
        env.register(make_store(tmp_path))
        with env as client:
            resp = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        assert resp.status_code == 200
        env.s3.get_object.assert_not_called()

    def test_s3_outage_without_disk_copy_is_not_a_404(self, tmp_path):
        """A 404 would make the reader draw an empty tile instead of failing."""
        env = Env(tmp_path)
        env.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "SlowDown", "Message": "busy"}}, "GetObject"
        )
        with env as client:
            resp = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        assert resp.status_code == 502


class TestStoresListing:
    def test_registered_stores_sorted_with_sample_names(self, tmp_path):
        env = Env(tmp_path)
        env.register(make_store(tmp_path, "sample_B.zarr"))
        env.file_docs.append({"_id": ObjectId(), "file_location": str(make_store(tmp_path))})
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert [s["name"] for s in body] == ["sample_A.zarr", "sample_B.zarr"]
        assert [s["sample"] for s in body] == ["sample_A", "sample_B"]
        assert body[1]["file_id"] == str(FILE_ID)

    def test_s3_only_stores_are_listed_from_prefixes(self, tmp_path):
        env = Env(tmp_path)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"CommonPrefixes": [{"Prefix": f"bioimage/{DC_ID}/sample_C.zarr/"}]}
        ]
        env.s3.get_paginator.return_value = paginator
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert resp.json() == [{"name": "sample_C.zarr", "sample": "sample_C", "file_id": None}]

    def test_upload_marker_folder_is_not_a_store(self, tmp_path):
        env = Env(tmp_path)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "CommonPrefixes": [
                    {"Prefix": f"bioimage/{DC_ID}/.uploads/"},
                    {"Prefix": f"bioimage/{DC_ID}/sample_C.zarr/"},
                ]
            }
        ]
        env.s3.get_paginator.return_value = paginator
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert [s["name"] for s in resp.json()] == ["sample_C.zarr"]

    def test_duplicate_store_names_keep_the_first_sorted_path(self, tmp_path, caplog):
        first = make_store(tmp_path / "run_1")
        second = make_store(tmp_path / "run_2")
        (second / "0" / "0.0.0").write_bytes(b"second")
        first_id = ObjectId()
        env = Env(tmp_path, upload=False)
        # Mongo order is not path order: the later path comes back first.
        env.file_docs.extend(
            [
                {"_id": ObjectId(), "file_location": str(second)},
                {"_id": first_id, "file_location": str(first)},
            ]
        )
        with env as client, caplog.at_level("WARNING", logger=routes.logger.name):
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()
            chunk = client.get(key_url("sample_A.zarr", "0/0.0.0"), headers=AUTH)

        assert listing == [
            {"name": "sample_A.zarr", "sample": "sample_A", "file_id": str(first_id)}
        ]
        assert chunk.content == b"\x01\x02\x03"
        assert "registered twice" in caplog.text
        assert str(second) in caplog.text

    def test_symlinked_path_to_the_same_store_is_not_a_clash(self, tmp_path, caplog):
        store = make_store(tmp_path / "real")
        (tmp_path / "link").symlink_to(tmp_path / "real")
        env = Env(tmp_path, upload=False)
        env.register(store)
        env.file_docs.append(
            {"_id": ObjectId(), "file_location": str(tmp_path / "link" / store.name)}
        )
        with env as client, caplog.at_level("WARNING", logger=routes.logger.name):
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert [s["name"] for s in resp.json()] == ["sample_A.zarr"]
        assert "registered twice" not in caplog.text
