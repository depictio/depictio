"""S3-compatibility shims for stores that are not AWS: Google Cloud Storage's XML API.

GCS serves the S3 protocol at ``https://storage.googleapis.com`` with HMAC keys, but
has no multi-object delete (``DeleteObjects``) and rejects the CRC checksums boto3
>= 1.36 sends by default. See ``docs/google-cloud-storage.md``.
"""

import os
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from depictio.api.v1.configs import settings_models
from depictio.models.s3_utils import delete_keys


def _client_error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class _FakeS3:
    def __init__(self, bulk_error: str | None = None, single_error: str | None = None):
        self.bulk_error = bulk_error
        self.single_error = single_error
        self.bulk_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    def delete_objects(self, Bucket, Delete):
        keys = [o["Key"] for o in Delete["Objects"]]
        self.bulk_calls.append(keys)
        if self.bulk_error:
            raise _client_error(self.bulk_error, "DeleteObjects")
        return {"Deleted": [{"Key": k} for k in keys]}

    def delete_object(self, Bucket, Key):
        if self.single_error:
            raise _client_error(self.single_error, "DeleteObject")
        self.single_calls.append(Key)
        return {}


class TestDeleteKeys:
    def test_bulk_delete_in_batches_of_1000(self):
        s3 = _FakeS3()
        keys = [f"dc/{i}.parquet" for i in range(2500)]

        assert delete_keys(s3, "bucket", keys) == []

        assert [len(b) for b in s3.bulk_calls] == [1000, 1000, 500]
        assert s3.single_calls == []

    def test_no_keys_makes_no_call(self):
        s3 = _FakeS3()
        assert delete_keys(s3, "bucket", []) == []
        assert s3.bulk_calls == [] and s3.single_calls == []

    def test_falls_back_to_one_delete_per_key_when_bulk_is_unsupported(self):
        s3 = _FakeS3(bulk_error="NotImplemented")
        keys = [f"dc/{i}" for i in range(1500)]

        assert delete_keys(s3, "bucket", keys) == []

        # One failed bulk attempt, then every key one by one, no second bulk try.
        assert len(s3.bulk_calls) == 1
        assert s3.single_calls == keys

    def test_a_real_error_still_raises_after_the_fallback(self):
        s3 = _FakeS3(bulk_error="AccessDenied", single_error="AccessDenied")
        with pytest.raises(ClientError):
            delete_keys(s3, "bucket", ["dc/a"])

    def test_partial_bulk_errors_are_returned(self):
        class _Partial(_FakeS3):
            def delete_objects(self, Bucket, Delete):
                return {"Errors": [{"Key": "dc/a", "Code": "InternalError"}]}

        assert delete_keys(_Partial(), "bucket", ["dc/a", "dc/b"]) == [
            {"Key": "dc/a", "Code": "InternalError"}
        ]


class TestChecksumDefault:
    VARS = ("AWS_REQUEST_CHECKSUM_CALCULATION", "AWS_RESPONSE_CHECKSUM_VALIDATION")

    def test_defaults_to_when_required(self, monkeypatch):
        for var in self.VARS:
            monkeypatch.delenv(var, raising=False)

        settings_models.default_s3_checksums_when_required()

        assert all(os.environ[var] == "when_required" for var in self.VARS)

    def test_an_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("AWS_REQUEST_CHECKSUM_CALCULATION", "when_supported")
        monkeypatch.delenv("AWS_RESPONSE_CHECKSUM_VALIDATION", raising=False)

        settings_models.default_s3_checksums_when_required()

        assert os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] == "when_supported"
        assert os.environ["AWS_RESPONSE_CHECKSUM_VALIDATION"] == "when_required"

    def test_boto3_clients_pick_it_up(self, monkeypatch):
        import boto3

        for var in self.VARS:
            monkeypatch.delenv(var, raising=False)
        settings_models.default_s3_checksums_when_required()

        client = boto3.client(
            "s3",
            endpoint_url="https://storage.googleapis.com",
            aws_access_key_id="GOOG1EXAMPLE",
            aws_secret_access_key="secret",
            region_name="us-east-1",
        )
        assert client.meta.config.request_checksum_calculation == "when_required"
        assert client.meta.config.response_checksum_validation == "when_required"

    def test_set_once_settings_are_imported(self):
        # Every S3 client in the API and CLI imports the settings module first.
        assert os.environ.get("AWS_REQUEST_CHECKSUM_CALCULATION")
        assert os.environ.get("AWS_RESPONSE_CHECKSUM_VALIDATION")


class TestPrerenderPrefixDelete:
    def test_falls_back_to_per_file_delete(self):
        from depictio.api.v1.services import multiqc_s3_prerender

        removed: list[str] = []

        class _FakeFS:
            def exists(self, path):
                return True

            def find(self, path):
                return ["b/dc/prerender/a.json", "b/dc/prerender/b.json"]

            def rm(self, paths):
                raise OSError("NotImplemented: DeleteObjects")

            def rm_file(self, path):
                removed.append(path)

        with (
            patch(
                "depictio.api.v1.services.multiqc.figures._get_s3_filesystem",
                return_value=_FakeFS(),
            ),
            patch("depictio.api.cache.get_cache"),
        ):
            assert multiqc_s3_prerender.delete_dc_prefix("dc") == 2

        assert removed == ["b/dc/prerender/a.json", "b/dc/prerender/b.json"]
