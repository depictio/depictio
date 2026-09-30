"""Contract for the OME-Zarr store endpoints under ``/advanced_viz/bioimage``.

A browser zarr reader fetches ``.zattrs``, ``.zarray`` and then one request per
chunk, and treats a 404 as "empty chunk". So the chunk route must:

* gate on project access before touching storage (and cache that gate briefly);
* reject traversal in both the store name and the key;
* return 404 only for a genuine miss, S3 first, then the registered store on disk;
* authenticate from the Authorization header only (no ``?token=`` fallback);
* let metadata revalidate (``no-cache``) while chunks cache for an hour;
* keep one root per store name when two registered paths share it.

A zarr v3 (NGFF 0.5) store has ``zarr.json`` metadata and may shard its
chunks, which a reader fetches by byte range: the key route honours one Range,
like the OME-TIFF file route.

Per format: a SpatialData store is served from ``<store>/<image_path>`` on disk
(the upload holds that subtree only), and an OME-TIFF store is one file served
with HTTP Range. Remote stores are proxied only from allow-listed S3 buckets
(never the Depictio data bucket) and https hosts, with no redirects and a size
cap.

The router is mounted on a bare app; Mongo, S3, the remote https client and
token validation are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from depictio.api.v1.configs import config as config_module
from depictio.api.v1.configs.settings_models import BioimageConfig
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
        self.read_whole = False

    def read(self) -> bytes:
        if self.fail:
            raise ConnectionError("connection reset mid-read")
        self.read_whole = True
        return self.data

    def iter_chunks(self, chunk_size: int):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i : i + chunk_size]

    def close(self) -> None:
        self.closed = True


def no_such_key() -> ClientError:
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")


class Env:
    """Mocked projects/files collections, S3 client and token validation."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        permitted: bool = True,
        upload: bool = True,
        props: dict | None = None,
        scan_filename: str | None = None,
        bioimage: BioimageConfig | None = None,
        http_handler=None,
    ):
        self.tmp_path = tmp_path
        self.projects = MagicMock()
        self.files = MagicMock()
        self.s3 = MagicMock()
        self.s3.get_object.side_effect = no_such_key()
        self.s3.head_object.side_effect = no_such_key()
        self.file_docs: list[dict] = []
        config: dict = {
            "type": "bioimage",
            "dc_specific_properties": {"upload": upload, **(props or {})},
        }
        if scan_filename:
            config["scan"] = {"scan_parameters": {"filename": scan_filename}}
        self.dc_doc = {"_id": DC_ID, "config": config}
        self.bioimage = bioimage or BioimageConfig()
        self.http_requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            self.http_requests.append(request)
            if http_handler is None:
                return httpx.Response(500)
            return http_handler(request)

        self.http = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
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
            patch.object(routes, "_bioimage_http_client", lambda: self.http),
            patch.object(config_module.settings, "bioimage", self.bioimage),
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

    @pytest.mark.parametrize(
        "key", [".zattrs", ".zgroup", "0/.zarray", ".zmetadata", "zarr.json", "0/zarr.json"]
    )
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

        assert resp.json() == [
            {
                "name": "sample_C.zarr",
                "sample": "sample_C",
                "file_id": None,
                "format": "ome-zarr",
                "kind": "image",
                "remote": False,
            }
        ]

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
            {
                "name": "sample_A.zarr",
                "sample": "sample_A",
                "file_id": str(first_id),
                "format": "ome-zarr",
                "kind": "image",
                "remote": False,
            }
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


# ---------------------------------------------------------------------------
# OME-TIFF: one file per store, served whole or by byte range
# ---------------------------------------------------------------------------

TIFF = "sample_T.ome.tif"
TIFF_BYTES = bytes(range(256)) * 4  # 1024 bytes
TIFF_PROPS = {"format": "ome-tiff"}


def file_url(store: str = TIFF) -> str:
    return f"{PREFIX}/bioimage/{DC_ID}/{store}"


def make_tiff(parent: Path, name: str = TIFF) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / name
    path.write_bytes(TIFF_BYTES)
    return path


def disk_tiff_env(tmp_path: Path, **kwargs) -> Env:
    env = Env(tmp_path, upload=False, props=TIFF_PROPS, **kwargs)
    env.register(make_tiff(tmp_path))
    return env


class TestTiffOnDisk:
    def test_whole_file_without_range(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.content == TIFF_BYTES
        assert resp.headers["content-type"] == "image/tiff"
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.headers["cache-control"] == "private, max-age=3600"

    @pytest.mark.parametrize(
        ("spec", "start", "end"),
        [("bytes=2-5", 2, 5), ("bytes=1000-", 1000, 1023), ("bytes=-4", 1020, 1023)],
    )
    def test_one_range_is_a_206(self, tmp_path, spec, start, end):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": spec})

        assert resp.status_code == 206
        assert resp.content == TIFF_BYTES[start : end + 1]
        assert resp.headers["content-range"] == f"bytes {start}-{end}/1024"
        assert resp.headers["content-length"] == str(end - start + 1)
        assert resp.headers["accept-ranges"] == "bytes"

    def test_range_end_past_the_file_is_clamped(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=1020-5000"})

        assert resp.status_code == 206
        assert resp.headers["content-range"] == "bytes 1020-1023/1024"

    def test_head_returns_the_size(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.head(file_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-length"] == "1024"
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.content == b""

    @pytest.mark.parametrize(
        "spec", ["bytes=0-1,4-5", "bytes=5-2", "bytes=-0", "bytes=x-y", "bytes=" + "9" * 5000 + "-"]
    )
    def test_multi_or_malformed_range_is_416(self, tmp_path, spec):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": spec})

        assert resp.status_code == 416

    def test_range_past_the_end_is_416_with_the_size(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=1024-"})

        assert resp.status_code == 416
        assert resp.headers["content-range"] == "bytes */1024"

    def test_other_range_unit_is_ignored(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "items=0-1"})

        assert resp.status_code == 200
        assert resp.content == TIFF_BYTES

    def test_key_route_is_rejected_for_a_single_file_store(self, tmp_path):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(key_url(TIFF, ".zattrs"), headers=AUTH)

        assert resp.status_code == 400

    @pytest.mark.parametrize("store", ["sample_A.zarr", "plain.tif", "..", "stores.ome.tiff/x"])
    def test_names_not_of_the_format_are_rejected(self, tmp_path, store):
        with disk_tiff_env(tmp_path) as client:
            resp = client.get(file_url(store), headers=AUTH)

        assert resp.status_code in (400, 404)
        assert resp.status_code != 200

    def test_file_route_is_rejected_for_a_key_tree_store(self, tmp_path):
        env = Env(tmp_path, upload=False)
        env.register(make_store(tmp_path))
        with env as client:
            resp = client.get(file_url("sample_A.zarr"), headers=AUTH)

        assert resp.status_code == 400

    def test_denied_before_any_read(self, tmp_path):
        env = disk_tiff_env(tmp_path, permitted=False)
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=0-1"})

        assert resp.status_code == 404
        env.files.find.assert_not_called()

    def test_folder_of_tiffs_from_scan_parameters(self, tmp_path):
        folder = tmp_path / "images"
        make_tiff(folder, "a.ome.tif")
        make_tiff(folder, "b.ome.tiff")
        make_tiff(folder, "c.tif")
        (folder / "d.ome.tif").mkdir()
        env = Env(tmp_path, upload=False, props=TIFF_PROPS, scan_filename=str(folder))
        with env as client:
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()
            resp = client.get(file_url("b.ome.tiff"), headers={**AUTH, "Range": "bytes=0-1"})

        assert [s["name"] for s in listing] == ["a.ome.tif", "b.ome.tiff"]
        assert [s["sample"] for s in listing] == ["a", "b"]
        assert {s["format"] for s in listing} == {"ome-tiff"}
        assert resp.status_code == 206


class TestTiffOnS3:
    def test_range_is_forwarded_to_s3(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        body = Body(TIFF_BYTES[2:6])
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {
            "Body": body,
            "ContentLength": 4,
            "ContentRange": "bytes 2-5/1024",
        }
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=2-5"})

        assert resp.status_code == 206
        assert resp.content == TIFF_BYTES[2:6]
        assert resp.headers["content-range"] == "bytes 2-5/1024"
        kwargs = env.s3.get_object.call_args.kwargs
        assert kwargs["Key"] == f"bioimage/{DC_ID}/{TIFF}"
        assert kwargs["Range"] == "bytes=2-5"
        assert body.closed

    def test_whole_file_without_range(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(TIFF_BYTES), "ContentLength": 1024}
        with env as client:
            resp = client.get(file_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.content == TIFF_BYTES
        assert "Range" not in env.s3.get_object.call_args.kwargs

    def test_whole_file_over_the_cap_is_refused(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS, bioimage=BioimageConfig(remote_max_object_mb=1))
        body = Body(b"")
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": body, "ContentLength": 2 * 1024 * 1024}
        with env as client:
            resp = client.get(file_url(), headers=AUTH)

        assert resp.status_code == 413
        assert body.closed

    def test_head_uses_head_object(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        env.s3.head_object.side_effect = None
        env.s3.head_object.return_value = {"ContentLength": 1024}
        with env as client:
            resp = client.head(file_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-length"] == "1024"
        env.s3.get_object.assert_not_called()

    def test_s3_miss_falls_back_to_disk(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        env.register(make_tiff(tmp_path))
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=0-3"})

        assert resp.status_code == 206
        assert resp.content == TIFF_BYTES[:4]

    def test_genuine_miss_is_404_and_outage_is_502(self, tmp_path):
        with Env(tmp_path, props=TIFF_PROPS) as client:
            missing = client.get(file_url(), headers=AUTH)
        env = Env(tmp_path, props=TIFF_PROPS)
        env.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "SlowDown", "Message": "busy"}}, "GetObject"
        )
        with env as client:
            outage = client.get(file_url(), headers=AUTH)

        assert missing.status_code == 404
        assert outage.status_code == 502

    def test_s3_invalid_range_is_416(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        env.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "InvalidRange", "Message": "nope"}}, "GetObject"
        )
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=5000-"})

        assert resp.status_code == 416

    def test_s3_only_tiffs_are_listed_from_objects(self, tmp_path):
        env = Env(tmp_path, props=TIFF_PROPS)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": f"bioimage/{DC_ID}/{TIFF}"},
                    {"Key": f"bioimage/{DC_ID}/notes.txt"},
                ],
                "CommonPrefixes": [{"Prefix": f"bioimage/{DC_ID}/.uploads/"}],
            }
        ]
        env.s3.get_paginator.return_value = paginator
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert resp.json() == [
            {
                "name": TIFF,
                "sample": "sample_T",
                "file_id": None,
                "format": "ome-tiff",
                "kind": "image",
                "remote": False,
            }
        ]


# ---------------------------------------------------------------------------
# SpatialData: an OME-Zarr image at <store>/<image_path>
# ---------------------------------------------------------------------------

SD_STORE = "visium.zarr"
SD_PROPS = {"format": "spatialdata", "image_path": "images/he"}


def make_spatialdata(parent: Path) -> Path:
    store = parent / SD_STORE
    (store / "tables" / "table").mkdir(parents=True)
    (store / ".zattrs").write_text(json.dumps({"spatialdata_attrs": {"version": "0.1"}}))
    (store / "tables" / "table" / ".zattrs").write_text("{}")
    make_store(store / "images", "he")
    return store


class TestSpatialData:
    def test_disk_reads_join_the_image_path(self, tmp_path):
        env = Env(tmp_path, upload=False, props=SD_PROPS)
        env.register(make_spatialdata(tmp_path))
        with env as client:
            attrs = client.get(key_url(SD_STORE, ".zattrs"), headers=AUTH)
            chunk = client.get(key_url(SD_STORE, "0/0.0.0"), headers=AUTH)

        assert attrs.status_code == 200
        assert "multiscales" in attrs.json()
        assert chunk.content == b"\x01\x02\x03"

    def test_s3_reads_are_relative_to_the_image(self, tmp_path):
        env = Env(tmp_path, props=SD_PROPS)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"{}")}
        with env as client:
            resp = client.get(key_url(SD_STORE, ".zattrs"), headers=AUTH)

        assert resp.status_code == 200
        assert env.s3.get_object.call_args.kwargs["Key"] == f"bioimage/{DC_ID}/{SD_STORE}/.zattrs"

    @pytest.mark.parametrize("key", ["../../tables/table/.zattrs", "%2e%2e/%2e%2e/.zattrs"])
    def test_traversal_out_of_the_image_is_rejected(self, tmp_path, key):
        env = Env(tmp_path, upload=False, props=SD_PROPS)
        env.register(make_spatialdata(tmp_path))
        with env as client:
            resp = client.get(key_url(SD_STORE, key), headers=AUTH)

        assert resp.status_code in (400, 404)

    def test_symlink_out_of_the_store_is_not_served(self, tmp_path):
        store = make_spatialdata(tmp_path)
        secret = tmp_path / "secret.txt"
        secret.write_text("nope")
        (store / "images" / "he" / "leak").symlink_to(secret)
        env = Env(tmp_path, upload=False, props=SD_PROPS)
        env.register(store)
        with env as client:
            resp = client.get(key_url(SD_STORE, "leak"), headers=AUTH)

        assert resp.status_code == 404

    def test_listing_reports_the_format(self, tmp_path):
        env = Env(tmp_path, upload=False, props=SD_PROPS)
        env.register(make_spatialdata(tmp_path))
        with env as client:
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()

        assert listing == [
            {
                "name": SD_STORE,
                "sample": "visium",
                "file_id": str(FILE_ID),
                "format": "spatialdata",
                "kind": "image",
                "remote": False,
            }
        ]


# ---------------------------------------------------------------------------
# Remote stores: proxied, allow-listed, never followed through a redirect
# ---------------------------------------------------------------------------

HOST = "images.example.org"
REMOTE_ZARR = f"https://{HOST}/idr/sample_R.zarr"
ALLOW_HTTPS = BioimageConfig(remote_https_hosts=[HOST])


class TestRemoteHttps:
    def test_allowed_host_is_proxied(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(200, content=b"\x07\x08"),
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", "0/0.0.0"), headers=AUTH)

        assert resp.status_code == 200
        assert resp.content == b"\x07\x08"
        assert resp.headers["cache-control"] == "private, max-age=3600"
        assert str(env.http_requests[0].url) == f"{REMOTE_ZARR}/0/0.0.0"
        env.s3.get_object.assert_not_called()

    def test_host_not_allow_listed_is_403_but_still_listed(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=BioimageConfig(remote_https_hosts=["other.example.org"]),
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", ".zattrs"), headers=AUTH)
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Remote bioimage host not allowed"
        assert env.http_requests == []
        assert listing == [
            {
                "name": "sample_R.zarr",
                "sample": "sample_R",
                "file_id": None,
                "format": "ome-zarr",
                "kind": "image",
                "remote": True,
            }
        ]

    def test_redirect_is_not_followed(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(
                302, headers={"Location": "https://evil.example.com/x"}
            ),
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 502
        assert len(env.http_requests) == 1

    def test_upstream_404_is_a_404(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(404),
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", "0/9.9.9"), headers=AUTH)

        assert resp.status_code == 404

    def test_upstream_timeout_is_502(self, tmp_path):
        def timeout(req):
            raise httpx.ConnectTimeout("slow", request=req)

        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=ALLOW_HTTPS,
            http_handler=timeout,
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 502

    def test_body_over_the_cap_is_refused(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [REMOTE_ZARR]},
            bioimage=BioimageConfig(remote_https_hosts=[HOST], remote_max_object_mb=1),
            http_handler=lambda req: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)),
        )
        with env as client:
            resp = client.get(key_url("sample_R.zarr", "0/0.0.0"), headers=AUTH)

        assert resp.status_code == 413

    def test_spatialdata_remote_joins_the_image_path(self, tmp_path):
        env = Env(
            tmp_path,
            props={**SD_PROPS, "remote_stores": [f"https://{HOST}/sd/{SD_STORE}"]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(200, content=b"{}"),
        )
        with env as client:
            resp = client.get(key_url(SD_STORE, ".zattrs"), headers=AUTH)

        assert resp.status_code == 200
        assert str(env.http_requests[0].url) == f"https://{HOST}/sd/{SD_STORE}/images/he/.zattrs"

    def test_tiff_range_is_forwarded(self, tmp_path):
        def serve(req):
            assert req.headers["range"] == "bytes=2-5"
            return httpx.Response(
                206, content=TIFF_BYTES[2:6], headers={"Content-Range": "bytes 2-5/1024"}
            )

        env = Env(
            tmp_path,
            props={**TIFF_PROPS, "remote_stores": [f"https://{HOST}/t/{TIFF}"]},
            bioimage=ALLOW_HTTPS,
            http_handler=serve,
        )
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=2-5"})

        assert resp.status_code == 206
        assert resp.content == TIFF_BYTES[2:6]
        assert resp.headers["content-range"] == "bytes 2-5/1024"

    def test_tiff_range_ignored_upstream_is_sliced_here(self, tmp_path):
        env = Env(
            tmp_path,
            props={**TIFF_PROPS, "remote_stores": [f"https://{HOST}/t/{TIFF}"]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(200, content=TIFF_BYTES),
        )
        with env as client:
            resp = client.get(file_url(), headers={**AUTH, "Range": "bytes=-4"})

        assert resp.status_code == 206
        assert resp.content == TIFF_BYTES[-4:]
        assert resp.headers["content-range"] == "bytes 1020-1023/1024"

    def test_tiff_head_returns_the_remote_size(self, tmp_path):
        env = Env(
            tmp_path,
            props={**TIFF_PROPS, "remote_stores": [f"https://{HOST}/t/{TIFF}"]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(200, headers={"Content-Length": "1024"}),
        )
        with env as client:
            resp = client.head(file_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-length"] == "1024"
        assert env.http_requests[0].method == "HEAD"


class TestRemoteS3:
    URL = "s3://shared-images/project/sample_S.zarr"

    def test_allowed_bucket_is_read_on_the_server_endpoint(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [self.URL]},
            bioimage=BioimageConfig(remote_s3_buckets=["shared-images"]),
        )
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"{}")}
        with env as client:
            resp = client.get(key_url("sample_S.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 200
        kwargs = env.s3.get_object.call_args.kwargs
        assert kwargs["Bucket"] == "shared-images"
        assert kwargs["Key"] == "project/sample_S.zarr/.zattrs"

    def test_bucket_not_allow_listed_is_403(self, tmp_path):
        env = Env(tmp_path, props={"remote_stores": [self.URL]})
        with env as client:
            resp = client.get(key_url("sample_S.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 403
        env.s3.get_object.assert_not_called()

    def test_depictio_data_bucket_is_refused_even_if_listed(self, tmp_path):
        bucket = config_module.settings.s3.bucket
        env = Env(
            tmp_path,
            props={"remote_stores": [f"s3://{bucket}/{ObjectId()}/sample_S.zarr"]},
            bioimage=BioimageConfig(remote_s3_buckets=[bucket]),
        )
        with env as client:
            resp = client.get(key_url("sample_S.zarr", ".zattrs"), headers=AUTH)

        assert resp.status_code == 403
        env.s3.get_object.assert_not_called()

    def test_remote_miss_is_404(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [self.URL]},
            bioimage=BioimageConfig(remote_s3_buckets=["shared-images"]),
        )
        with env as client:
            resp = client.get(key_url("sample_S.zarr", "0/9.9.9"), headers=AUTH)

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# zarr v3 / NGFF 0.5: zarr.json metadata, sharded chunks read by byte range
# ---------------------------------------------------------------------------

V3_STORE = "sample_V.zarr"
SHARD_KEY = "0/c/0/0/0"
SHARD_BYTES = bytes(range(256)) * 2  # 512 bytes: chunks, then the shard index


def make_v3_store(parent: Path) -> Path:
    """A hand-built NGFF 0.5 store: the shard bytes are opaque to the API."""
    store = parent / V3_STORE
    (store / "0" / "c" / "0" / "0").mkdir(parents=True)
    root = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{"datasets": [{"path": "0"}]}]}},
    }
    (store / "zarr.json").write_text(json.dumps(root))
    array = {
        "zarr_format": 3,
        "node_type": "array",
        "codecs": [{"name": "sharding_indexed", "configuration": {"chunk_shape": [1, 8, 8]}}],
    }
    (store / "0" / "zarr.json").write_text(json.dumps(array))
    (store / SHARD_KEY).write_bytes(SHARD_BYTES)
    return store


def v3_disk_env(tmp_path: Path, **kwargs) -> Env:
    env = Env(tmp_path, upload=False, **kwargs)
    env.register(make_v3_store(tmp_path))
    return env


def shard_url(key: str = SHARD_KEY) -> str:
    return key_url(V3_STORE, key)


class TestZarrV3OnDisk:
    def test_zarr_json_is_served_as_revalidated_metadata(self, tmp_path):
        with v3_disk_env(tmp_path) as client:
            root = client.get(shard_url("zarr.json"), headers=AUTH)
            array = client.get(shard_url("0/zarr.json"), headers=AUTH)

        assert root.status_code == 200
        assert root.headers["content-type"] == "application/json"
        assert root.headers["cache-control"] == "no-cache"
        assert root.json()["attributes"]["ome"]["version"] == "0.5"
        assert array.json()["codecs"][0]["name"] == "sharding_indexed"

    def test_whole_shard_without_range_is_unchanged(self, tmp_path):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.content == SHARD_BYTES
        assert resp.headers["content-type"] == "application/octet-stream"
        assert resp.headers["cache-control"] == "private, max-age=3600"
        assert "content-range" not in resp.headers

    @pytest.mark.parametrize(
        ("spec", "start", "end"),
        [("bytes=16-31", 16, 31), ("bytes=500-", 500, 511), ("bytes=-16", 496, 511)],
    )
    def test_one_range_is_a_206(self, tmp_path, spec, start, end):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": spec})

        assert resp.status_code == 206
        assert resp.content == SHARD_BYTES[start : end + 1]
        assert resp.headers["content-range"] == f"bytes {start}-{end}/512"
        assert resp.headers["content-length"] == str(end - start + 1)
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.headers["cache-control"] == "private, max-age=3600"

    def test_range_end_past_the_shard_is_clamped(self, tmp_path):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=500-9999"})

        assert resp.status_code == 206
        assert resp.headers["content-range"] == "bytes 500-511/512"

    @pytest.mark.parametrize(
        "spec", ["bytes=0-1,4-5", "bytes=5-2", "bytes=-0", "bytes=x-y", "bytes=" + "9" * 5000 + "-"]
    )
    def test_multi_or_malformed_range_is_416(self, tmp_path, spec):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": spec})

        assert resp.status_code == 416

    def test_range_past_the_end_is_416_with_the_size(self, tmp_path):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=512-"})

        assert resp.status_code == 416
        assert resp.headers["content-range"] == "bytes */512"

    def test_ranged_read_of_a_missing_shard_is_404(self, tmp_path):
        """zarr reads a missing shard as empty, so it must stay a 404, not a 416."""
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url("0/c/9/9/9"), headers={**AUTH, "Range": "bytes=-16"})

        assert resp.status_code == 404

    def test_other_range_unit_is_ignored(self, tmp_path):
        with v3_disk_env(tmp_path) as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "items=0-1"})

        assert resp.status_code == 200
        assert resp.content == SHARD_BYTES

    def test_denied_before_any_read(self, tmp_path):
        env = v3_disk_env(tmp_path, permitted=False)
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-1,4-5"})

        assert resp.status_code == 404
        env.files.find.assert_not_called()

    def test_spatialdata_v3_image_is_read_by_range(self, tmp_path):
        sd = tmp_path / SD_STORE
        (sd / "images").mkdir(parents=True)
        (sd / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group"}))
        make_v3_store(sd / "images").rename(sd / "images" / "he")
        env = Env(tmp_path, upload=False, props=SD_PROPS)
        env.register(sd)
        with env as client:
            meta = client.get(key_url(SD_STORE, "zarr.json"), headers=AUTH)
            part = client.get(key_url(SD_STORE, SHARD_KEY), headers={**AUTH, "Range": "bytes=0-3"})

        assert meta.json()["attributes"]["ome"]["version"] == "0.5"
        assert part.status_code == 206
        assert part.content == SHARD_BYTES[:4]


class TestZarrV3OnS3:
    def test_range_is_forwarded_to_s3(self, tmp_path):
        env = Env(tmp_path)
        body = Body(SHARD_BYTES[16:32])
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {
            "Body": body,
            "ContentLength": 16,
            "ContentRange": "bytes 16-31/512",
        }
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=16-31"})

        assert resp.status_code == 206
        assert resp.content == SHARD_BYTES[16:32]
        assert resp.headers["content-range"] == "bytes 16-31/512"
        assert resp.headers["accept-ranges"] == "bytes"
        kwargs = env.s3.get_object.call_args.kwargs
        assert kwargs["Key"] == f"bioimage/{DC_ID}/{V3_STORE}/{SHARD_KEY}"
        assert kwargs["Range"] == "bytes=16-31"
        assert body.closed

    def test_suffix_range_is_forwarded_as_is(self, tmp_path):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {
            "Body": Body(SHARD_BYTES[-16:]),
            "ContentLength": 16,
            "ContentRange": "bytes 496-511/512",
        }
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=-16"})

        assert resp.status_code == 206
        assert env.s3.get_object.call_args.kwargs["Range"] == "bytes=-16"

    def test_whole_key_over_the_cap_is_streamed_not_refused(self, tmp_path):
        """A whole shard of the DC's own upload is served, but never held in memory."""
        env = Env(tmp_path, bioimage=BioimageConfig(remote_max_object_mb=1))
        data = b"x" * (3 * 1024 * 1024 + 1)
        body = Body(data)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": body, "ContentLength": len(data)}
        with env as client:
            resp = client.get(shard_url(), headers=AUTH)

        assert resp.status_code == 200
        assert resp.content == data
        assert resp.headers["content-length"] == str(len(data))
        assert "Range" not in env.s3.get_object.call_args.kwargs
        assert not body.read_whole
        assert body.closed

    def test_whole_key_under_the_cap_is_read_whole(self, tmp_path):
        """Small keys keep the whole read, so a mid-read failure is a 502."""
        env = Env(tmp_path)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b"x", fail=True), "ContentLength": 1}
        with env as client:
            resp = client.get(shard_url(), headers=AUTH)

        assert resp.status_code == 502

    def test_range_over_the_cap_is_refused(self, tmp_path):
        env = Env(tmp_path, bioimage=BioimageConfig(remote_max_object_mb=1))
        body = Body(b"")
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": body, "ContentLength": 2 * 1024 * 1024}
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-"})

        assert resp.status_code == 413
        assert body.closed

    def test_s3_miss_falls_back_to_disk_by_range(self, tmp_path):
        env = Env(tmp_path)
        env.register(make_v3_store(tmp_path))
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-3"})

        assert resp.status_code == 206
        assert resp.content == SHARD_BYTES[:4]

    def test_ranged_miss_is_404_and_outage_is_502(self, tmp_path):
        with Env(tmp_path) as client:
            missing = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-3"})
        env = Env(tmp_path)
        env.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "SlowDown", "Message": "busy"}}, "GetObject"
        )
        with env as client:
            outage = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-3"})

        assert missing.status_code == 404
        assert outage.status_code == 502

    def test_s3_invalid_range_is_416(self, tmp_path):
        env = Env(tmp_path)
        env.s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "InvalidRange", "Message": "nope"}}, "GetObject"
        )
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=5000-"})

        assert resp.status_code == 416


class TestZarrV3Remote:
    URL = f"https://{HOST}/idr/{V3_STORE}"

    def test_https_range_is_forwarded(self, tmp_path):
        def serve(req):
            assert req.headers["range"] == "bytes=-16"
            return httpx.Response(
                206, content=SHARD_BYTES[-16:], headers={"Content-Range": "bytes 496-511/512"}
            )

        env = Env(
            tmp_path,
            props={"remote_stores": [self.URL]},
            bioimage=ALLOW_HTTPS,
            http_handler=serve,
        )
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=-16"})

        assert resp.status_code == 206
        assert resp.content == SHARD_BYTES[-16:]
        assert resp.headers["content-range"] == "bytes 496-511/512"
        assert str(env.http_requests[0].url) == f"{self.URL}/{SHARD_KEY}"

    def test_https_range_ignored_upstream_is_sliced_here(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [self.URL]},
            bioimage=ALLOW_HTTPS,
            http_handler=lambda req: httpx.Response(200, content=SHARD_BYTES),
        )
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=16-31"})

        assert resp.status_code == 206
        assert resp.content == SHARD_BYTES[16:32]
        assert resp.headers["content-range"] == "bytes 16-31/512"

    def test_https_ranged_miss_is_404_and_zarr_json_is_metadata(self, tmp_path):
        def serve(req):
            if req.url.path.endswith("zarr.json"):
                return httpx.Response(200, content=b'{"zarr_format": 3}')
            return httpx.Response(404)

        env = Env(
            tmp_path,
            props={"remote_stores": [self.URL]},
            bioimage=ALLOW_HTTPS,
            http_handler=serve,
        )
        with env as client:
            meta = client.get(shard_url("zarr.json"), headers=AUTH)
            missing = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-3"})

        assert meta.headers["content-type"] == "application/json"
        assert meta.headers["cache-control"] == "no-cache"
        assert missing.status_code == 404

    def test_remote_s3_range_is_forwarded(self, tmp_path):
        env = Env(
            tmp_path,
            props={"remote_stores": [f"s3://shared-images/project/{V3_STORE}"]},
            bioimage=BioimageConfig(remote_s3_buckets=["shared-images"]),
        )
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {
            "Body": Body(SHARD_BYTES[:4]),
            "ContentLength": 4,
            "ContentRange": "bytes 0-3/512",
        }
        with env as client:
            resp = client.get(shard_url(), headers={**AUTH, "Range": "bytes=0-3"})

        assert resp.status_code == 206
        kwargs = env.s3.get_object.call_args.kwargs
        assert kwargs["Key"] == f"project/{V3_STORE}/{SHARD_KEY}"
        assert kwargs["Range"] == "bytes=0-3"


class TestLabelsStores:
    """A labels TIFF is registered as its mask file but served as the OME-Zarr
    key tree the CLI converted it to; the listing says it is a labels store and
    names its sample through the DC's ``sample_pattern``."""

    PROPS = {"format": "tiff", "kind": "labels", "sample_pattern": r"^(.+?)_mask\.tif$"}

    def _mask(self, parent: Path, name: str) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / name
        path.write_bytes(b"II*\x00")
        return path

    def test_listing_reports_kind_and_pattern_sample(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        env.register(self._mask(tmp_path / "seg", "s1_mask.tif"))
        with env as client:
            resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH)

        assert resp.json() == [
            {
                "name": "s1_mask.tif",
                "sample": "s1",
                "file_id": str(FILE_ID),
                "format": "tiff",
                "kind": "labels",
                "remote": False,
            }
        ]

    def test_folder_listing_keeps_mask_files(self, tmp_path):
        folder = tmp_path / "masks"
        self._mask(folder, "s1_mask.tif")
        self._mask(folder, "s2_mask.tiff")
        (folder / "s3_mask.tif").mkdir()
        env = Env(tmp_path, props=self.PROPS, scan_filename=str(folder))
        with env as client:
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()

        assert [s["name"] for s in listing] == ["s1_mask.tif", "s2_mask.tiff"]
        # The pattern names s1; s2_mask.tiff does not match it and keeps its stem.
        assert [s["sample"] for s in listing] == ["s1", "s2_mask"]

    def test_s3_only_masks_are_listed_from_prefixes(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"CommonPrefixes": [{"Prefix": f"bioimage/{DC_ID}/s1_mask.tif/"}]}
        ]
        env.s3.get_paginator.return_value = paginator
        with env as client:
            listing = client.get(f"{PREFIX}/bioimage/{DC_ID}/stores", headers=AUTH).json()

        assert [(s["name"], s["sample"], s["kind"]) for s in listing] == [
            ("s1_mask.tif", "s1", "labels")
        ]

    def test_keys_are_read_from_the_converted_prefix(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        env.register(self._mask(tmp_path, "s1_mask.tif"))
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {"Body": Body(b'{"multiscales": []}')}
        with env as client:
            resp = client.get(key_url("s1_mask.tif", ".zattrs"), headers=AUTH)

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        assert env.s3.get_object.call_args.kwargs["Key"] == f"bioimage/{DC_ID}/s1_mask.tif/.zattrs"

    def test_ranged_chunk_read(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        env.s3.get_object.side_effect = None
        env.s3.get_object.return_value = {
            "Body": Body(b"\x01\x02"),
            "ContentLength": 2,
            "ContentRange": "bytes 0-1/10",
        }
        with env as client:
            resp = client.get(
                key_url("s1_mask.tif", "0/0/0"), headers={**AUTH, "Range": "bytes=0-1"}
            )

        assert resp.status_code == 206
        assert env.s3.get_object.call_args.kwargs["Range"] == "bytes=0-1"

    def test_mask_file_on_disk_is_never_served_as_a_key(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        env.register(self._mask(tmp_path, "s1_mask.tif"))
        with env as client:
            resp = client.get(key_url("s1_mask.tif", ".zattrs"), headers=AUTH)
            file_resp = client.get(f"{PREFIX}/bioimage/{DC_ID}/s1_mask.tif", headers=AUTH)

        assert resp.status_code == 404
        assert file_resp.status_code == 400

    def test_image_store_names_are_not_labels_names(self, tmp_path):
        env = Env(tmp_path, props=self.PROPS)
        with env as client:
            resp = client.get(key_url("s1.zarr", ".zattrs"), headers=AUTH)
        assert resp.status_code == 400
