"""Presigned URLs for `indexed_file` data collections.

The bytes never pass through the API: a file-backed track reads the object
straight from storage with HTTP range requests, and what the API hands out is a
short-lived presigned URL plus the manifest saying which samples exist. Three
things have to hold for that to work at all, and they are what this file pins:

1. the URL is signed against the *browser-reachable* endpoint, not the
   in-cluster one (SigV4 signs the host);
2. the key is rebuilt from the path parameters, so a caller-supplied sample or
   file name cannot reach outside the DC's own prefix;
3. the object must be registered for that DC, so access to one collection does
   not turn into key-guessing in another.

No MinIO and no Mongo: boto3's presigner is exercised against a throwaway
client, and the collections are monkeypatched.
"""

import os
from types import SimpleNamespace

import pytest
from bson import ObjectId

os.environ.setdefault("DEPICTIO_MINIO_ROOT_PASSWORD", "test-secret-for-unit-tests")

from depictio.api.v1.endpoints.files_endpoints import routes  # noqa: E402
from depictio.models.models.data_collections_types.indexed_file import (  # noqa: E402
    indexed_file_s3_key,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
DC_OID = ObjectId(DC_ID)


@pytest.fixture(autouse=True)
def _reset_presign_client():
    routes._presign_client = None
    yield
    routes._presign_client = None


@pytest.fixture
def allow_access(monkeypatch):
    """Grant the project-level read check, which has its own tests elsewhere."""
    import depictio.api.v1.endpoints.advanced_viz_endpoints.routes as av

    monkeypatch.setattr(av, "_assert_dc_access", lambda dc_oid, user: None)


class _FakeFiles:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        return list(self.docs)

    def find_one(self, query, projection=None):
        """Only the `$or` over s3_key / index_s3_key the route actually issues."""
        for doc in self.docs:
            for clause in query.get("$or", []):
                ((field, value),) = clause.items()
                if doc.get(field) == value:
                    return doc
        return None


def _doc(sample="NA12878", name="NA12878.vcf.gz", size=4096):
    return {
        "sample": sample,
        "filename": name,
        "filesize": size,
        "s3_key": indexed_file_s3_key(DC_ID, sample, name),
        "index_s3_key": indexed_file_s3_key(DC_ID, sample, f"{name}.tbi"),
        "index_filesize": 128,
    }


class TestPresigning:
    def test_url_is_signed_for_the_browser_endpoint(self):
        """A URL signed for http://minio:9000 is useless in a browser."""
        from depictio.api.v1.configs.config import settings

        url = routes.presign_indexed_file(indexed_file_s3_key(DC_ID, "S1", "S1.vcf.gz"))
        assert url.startswith(settings.minio.external_url)
        assert settings.minio.internal_url not in url

    def test_url_carries_a_signature_and_an_expiry(self):
        url = routes.presign_indexed_file(indexed_file_s3_key(DC_ID, "S1", "S1.vcf.gz"))
        assert "X-Amz-Signature=" in url
        assert f"X-Amz-Expires={routes.INDEXED_FILE_URL_TTL_SECONDS}" in url

    def test_ttl_is_fifteen_minutes(self):
        assert routes.INDEXED_FILE_URL_TTL_SECONDS == 15 * 60


class TestIndexSuffixResolution:
    def test_explicit_suffix_wins(self):
        assert routes._effective_index_suffix({"format": "vcf", "index_suffix": ".csi"}) == ".csi"

    def test_empty_suffix_is_kept(self):
        assert routes._effective_index_suffix({"format": "vcf", "index_suffix": ""}) == ""

    def test_falls_back_to_the_format_default(self):
        assert routes._effective_index_suffix({"format": "bam"}) == ".bai"
        assert routes._effective_index_suffix({"format": "bigwig"}) == ""

    def test_unknown_format_has_no_index(self):
        assert routes._effective_index_suffix({"format": "cram"}) == ""


@pytest.mark.asyncio
class TestManifestRoute:
    async def test_lists_one_entry_per_registered_file(self, monkeypatch, allow_access):
        monkeypatch.setattr(
            routes, "_indexed_file_dc_properties", lambda oid: {"format": "vcf", "assembly": "hg38"}
        )
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc(), _doc("NA12891")]))

        payload = await routes.list_indexed_files(DC_ID, current_user=SimpleNamespace(id=1))

        assert payload["format"] == "vcf"
        assert payload["assembly"] == "hg38"
        assert payload["index_suffix"] == ".tbi"
        assert payload["expires_in"] == routes.INDEXED_FILE_URL_TTL_SECONDS
        assert [f["sample"] for f in payload["files"]] == ["NA12878", "NA12891"]
        assert all(f["url"].startswith("http") for f in payload["files"])
        assert all(f["index_url"] for f in payload["files"])

    async def test_self_indexed_format_reports_no_index_url(self, monkeypatch, allow_access):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "bigwig"})
        doc = _doc("S1", "S1.bigWig")
        doc["index_s3_key"] = None
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([doc]))

        payload = await routes.list_indexed_files(DC_ID, current_user=SimpleNamespace(id=1))

        assert payload["index_suffix"] == ""
        assert payload["files"][0]["index_url"] is None

    async def test_non_indexed_file_dc_is_404(self, monkeypatch, allow_access):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {})
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([]))

        with pytest.raises(Exception) as exc:
            await routes.list_indexed_files(DC_ID, current_user=SimpleNamespace(id=1))
        assert getattr(exc.value, "status_code", None) == 404

    async def test_bad_object_id_is_400(self, allow_access):
        with pytest.raises(Exception) as exc:
            await routes.list_indexed_files("not-an-id", current_user=SimpleNamespace(id=1))
        assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
class TestFileUrlRoute:
    async def test_returns_a_presigned_url_for_a_registered_object(self, monkeypatch, allow_access):
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc()]))

        payload = await routes.get_indexed_file_url(
            DC_ID, "NA12878", "NA12878.vcf.gz", current_user=SimpleNamespace(id=1)
        )

        assert "X-Amz-Signature=" in payload["url"]
        assert payload["expires_in"] == routes.INDEXED_FILE_URL_TTL_SECONDS
        assert payload["size_bytes"] == 4096

    async def test_index_sidecar_reports_its_own_size(self, monkeypatch, allow_access):
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc()]))

        payload = await routes.get_indexed_file_url(
            DC_ID, "NA12878", "NA12878.vcf.gz.tbi", current_user=SimpleNamespace(id=1)
        )

        assert payload["size_bytes"] == 128

    @pytest.mark.parametrize(
        ("sample", "name"),
        [
            ("..", "x.vcf.gz"),
            ("NA12878", ".."),
            ("NA12878", ""),
        ],
    )
    async def test_traversal_is_rejected(self, monkeypatch, allow_access, sample, name):
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc()]))

        with pytest.raises(Exception) as exc:
            await routes.get_indexed_file_url(
                DC_ID, sample, name, current_user=SimpleNamespace(id=1)
            )
        assert getattr(exc.value, "status_code", None) == 400

    async def test_unregistered_object_is_404(self, monkeypatch, allow_access):
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc()]))

        with pytest.raises(Exception) as exc:
            await routes.get_indexed_file_url(
                DC_ID, "OTHER", "secret.vcf.gz", current_user=SimpleNamespace(id=1)
            )
        assert getattr(exc.value, "status_code", None) == 404

    async def test_access_check_runs_before_any_lookup(self, monkeypatch):
        from fastapi import HTTPException

        import depictio.api.v1.endpoints.advanced_viz_endpoints.routes as av

        def _deny(dc_oid, user):
            raise HTTPException(
                status_code=404, detail="Data collection not found or access denied."
            )

        monkeypatch.setattr(av, "_assert_dc_access", _deny)
        monkeypatch.setattr(routes, "files_collection", _FakeFiles([_doc()]))

        with pytest.raises(Exception) as exc:
            await routes.get_indexed_file_url(
                DC_ID, "NA12878", "NA12878.vcf.gz", current_user=SimpleNamespace(id=1)
            )
        assert getattr(exc.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# DEPICTIO_S3_BROWSER_ACCESS=proxy: the API streams the object (#1420)
# ---------------------------------------------------------------------------

PDB = b"HEADER    TEST PROTEIN\nATOM      1  N   MET A   1\nEND\n"
READER_ID = ObjectId()


class _FakeUsers:
    def __init__(self, docs):
        self.docs = {d["_id"]: d for d in docs}

    def find_one(self, query, projection=None):
        return self.docs.get(query.get("_id"))


@pytest.fixture
def proxy(monkeypatch):
    """Proxy mode, one registered structure, its bytes served from memory."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import depictio.api.v1.db as db_module
    import depictio.api.v1.endpoints.advanced_viz_endpoints.routes as av
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.services import remote_read

    monkeypatch.setattr(settings.s3, "browser_access", "proxy")
    pdb = _doc("P1", "P1.pdb", size=len(PDB))
    pdb["index_s3_key"] = None
    monkeypatch.setattr(routes, "files_collection", _FakeFiles([pdb]))
    monkeypatch.setattr(
        db_module,
        "users_collection",
        _FakeUsers([{"_id": READER_ID, "is_admin": False}]),
        raising=False,
    )
    readers: set[str] = {str(READER_ID)}

    def access(dc_oid, user):
        if str(user.id) not in readers:
            raise routes.HTTPException(status_code=404, detail="no access")

    monkeypatch.setattr(av, "_assert_dc_access", access)
    keys: list[str] = []
    monkeypatch.setattr(remote_read, "source_size", lambda src: keys.append(src.key) or len(PDB))
    monkeypatch.setattr(
        remote_read, "open_range", lambda src, rng: iter([PDB[rng.start : rng.end + 1]])
    )
    app = FastAPI()
    app.include_router(routes.files_endpoint_router, prefix="/depictio/api/v1/files")
    return SimpleNamespace(client=TestClient(app), readers=readers, keys=keys, doc=pdb)


def _manifest_url(proxy_env) -> str:
    import asyncio

    payload = asyncio.run(
        routes.list_indexed_files(DC_ID, current_user=SimpleNamespace(id=READER_ID))
    )
    return payload["files"][0]["url"]


class TestProxyMode:
    def test_the_manifest_hands_out_signed_api_urls(self, proxy, monkeypatch):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "pdb"})
        url = _manifest_url(proxy)
        path, _, query = url.partition("?")
        assert path == f"/depictio/api/v1/files/indexed/{DC_ID}/object/P1/P1.pdb"
        assert f"uid={READER_ID}" in query and "sig=" in query and "exp=" in query
        assert "X-Amz" not in url

    def test_the_presigned_mode_is_unchanged(self, proxy, monkeypatch):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.s3, "browser_access", "presigned")
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "pdb"})
        assert "X-Amz-Signature=" in _manifest_url(proxy)

    def test_a_signed_url_serves_the_object_and_its_byte_ranges(self, proxy, monkeypatch):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "pdb"})
        url = _manifest_url(proxy)

        whole = proxy.client.get(url)
        assert (whole.status_code, whole.content) == (200, PDB)
        assert whole.headers["accept-ranges"] == "bytes"

        part = proxy.client.get(url, headers={"Range": "bytes=10-16"})
        assert (part.status_code, part.content) == (206, PDB[10:17])
        assert part.headers["content-range"] == f"bytes 10-16/{len(PDB)}"

        head = proxy.client.head(url)
        assert (head.status_code, head.headers["content-length"]) == (200, str(len(PDB)))
        # The object read is the one the DC registered, rebuilt server side.
        assert set(proxy.keys) == {proxy.doc["s3_key"]}

    def test_a_signature_grants_one_object_only(self, proxy, monkeypatch):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "pdb"})
        url = _manifest_url(proxy)
        other = url.replace("/P1/P1.pdb?", "/P1/P2.pdb?")
        assert proxy.client.get(other).status_code == 401
        tampered = url.replace(f"uid={READER_ID}", f"uid={ObjectId()}")
        assert proxy.client.get(tampered).status_code == 401
        assert proxy.client.get(url.partition("?")[0]).status_code == 401

    def test_a_reader_who_lost_access_is_refused(self, proxy, monkeypatch):
        monkeypatch.setattr(routes, "_indexed_file_dc_properties", lambda oid: {"format": "pdb"})
        url = _manifest_url(proxy)
        proxy.readers.clear()
        assert proxy.client.get(url).status_code == 404

    def test_an_unregistered_object_is_404(self, proxy, monkeypatch):
        from depictio.api.v1.services.jbrowse import signing

        key = indexed_file_s3_key(DC_ID, "P1", "secret.pdb")
        exp = 2_000_000_000
        sig = signing.sign("indexed", DC_ID, key, "object", str(READER_ID), exp)
        url = (
            f"/depictio/api/v1/files/indexed/{DC_ID}/object/P1/secret.pdb"
            f"?uid={READER_ID}&exp={exp}&sig={sig}"
        )
        assert proxy.client.get(url).status_code == 404
