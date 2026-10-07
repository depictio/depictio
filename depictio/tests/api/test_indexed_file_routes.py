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
