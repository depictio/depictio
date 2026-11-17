"""The instance storage interface (#1358): registry, locations, factory, S3 backend.

No store is reached: the S3 backend runs on a fake boto3 client, except for the
presigner, which boto3 computes offline.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.exceptions import ClientError

from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options
from depictio.models.storage import (
    ObjectInfo,
    S3Backend,
    StorageBackend,
    StorageError,
    StorageNotFound,
    backend_class,
    backend_names,
    instance_storage,
    is_object_url,
    object_schemes,
    object_url,
    register_backend,
    split_object_url,
)
from depictio.models.storage import registry as registry_module


def _cfg(**overrides) -> S3DepictioCLIConfig:
    values = dict(
        service_name="s3",
        service_port=9000,
        external_host="files.example.org",
        external_port=443,
        external_protocol="https",
        root_user="key",
        root_password="secret-secret-secret",
        bucket="depictio-bucket",
    )
    values.update(overrides)
    return S3DepictioCLIConfig(**values)


def _error(code: str, op: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)  # type: ignore[arg-type]


def _backend(client: MagicMock | None = None, **cfg) -> S3Backend:
    backend = S3Backend(_cfg(**cfg))
    backend._client = client or MagicMock()
    return backend


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


class TestRegistry:
    def test_s3_is_registered_and_its_scheme_accepted(self):
        assert "s3" in backend_names()
        assert backend_class("s3") is S3Backend
        assert "s3" in object_schemes()

    def test_an_unknown_backend_names_the_known_ones(self):
        with pytest.raises(ValueError, match=r"unknown storage backend 'nope' \(known: .*s3"):
            backend_class("nope")

    def test_a_new_backend_brings_its_scheme(self, monkeypatch):
        """What adding Azure (or anything) amounts to: register, and the scheme is accepted."""
        monkeypatch.setattr(registry_module, "_BACKENDS", dict(registry_module._BACKENDS))

        @register_backend
        class FakeBackend:
            name = "fake"
            scheme = "fk"

        assert backend_class("fake") is FakeBackend
        assert "fk" in object_schemes()
        assert is_object_url("fk://bucket/key")
        assert split_object_url("fk://bucket/a/b") == ("fk", "bucket", "a/b")

    def test_two_backends_cannot_share_a_name_or_a_scheme(self, monkeypatch):
        monkeypatch.setattr(registry_module, "_BACKENDS", dict(registry_module._BACKENDS))

        with pytest.raises(ValueError, match="already registered"):
            register_backend(type("Other", (), {"name": "s3", "scheme": "zz"}))
        with pytest.raises(ValueError, match="already served"):
            register_backend(type("Other", (), {"name": "other", "scheme": "s3"}))


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------


class TestLocations:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("s3://bucket/a/b.parquet", ("s3", "bucket", "a/b.parquet")),
            ("S3://bucket/key", ("s3", "bucket", "key")),
            ("s3://bucket", ("s3", "bucket", "")),
            ("s3://bucket/", ("s3", "bucket", "")),
            ("  s3://bucket/k  ", ("s3", "bucket", "k")),
        ],
    )
    def test_split(self, url, expected):
        assert split_object_url(url) == expected

    @pytest.mark.parametrize(
        "url", ["s3://", "s3:///key", "/data/x", "https://host/x", "file:///x", "", None, 3]
    )
    def test_not_object_urls(self, url):
        assert not is_object_url(url)

    def test_split_refuses_with_the_accepted_schemes(self):
        with pytest.raises(ValueError, match=r"s3://"):
            split_object_url("ftp://bucket/key")

    def test_schemes_can_be_narrowed(self):
        assert not is_object_url("s3://bucket/key", ("gs",))

    def test_object_url(self):
        assert object_url("s3", "b", "dc") == "s3://b/dc"
        assert object_url("s3", "b", "/dc/x") == "s3://b/dc/x"
        assert object_url("s3", "b") == "s3://b"


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


class TestFactory:
    def test_server_settings_give_the_s3_backend(self):
        from depictio.api.v1.configs.config import settings

        backend = instance_storage(settings)
        assert isinstance(backend, S3Backend)
        assert backend.config is settings.s3
        assert backend.bucket == settings.s3.bucket

    def test_a_cli_config_gives_its_s3_storage(self):
        cfg = _cfg(bucket="cli-bucket")
        backend = instance_storage(SimpleNamespace(s3_storage=cfg))
        assert isinstance(backend, S3Backend) and backend.bucket == "cli-bucket"

    def test_a_bare_section_is_accepted(self):
        assert instance_storage(_cfg(bucket="bare")).bucket == "bare"

    def test_a_stand_in_config_is_read_as_a_cli_config(self):
        """Tests hand MagicMock CLI configs around: the CLI attribute must win."""
        cli = MagicMock()
        cli.s3_storage = _cfg(bucket="mocked")
        assert instance_storage(cli).bucket == "mocked"

    def test_the_backend_comes_from_the_configuration(self):
        with pytest.raises(ValueError, match="unknown storage backend 'nope'"):
            instance_storage(SimpleNamespace(storage_backend="nope", s3_storage=_cfg()))
        with pytest.raises(ValueError, match="unknown storage backend 'nope'"):
            instance_storage(SimpleNamespace(storage=SimpleNamespace(backend="nope"), s3=_cfg()))

    def test_a_config_without_the_backend_section_is_refused(self):
        with pytest.raises(ValueError, match="no 's3' storage section"):
            instance_storage(SimpleNamespace())


# --------------------------------------------------------------------------
# S3 backend
# --------------------------------------------------------------------------


class TestS3Backend:
    def test_it_fulfils_the_protocol(self):
        assert isinstance(S3Backend(_cfg()), StorageBackend)

    def test_storage_options_are_the_ones_polars_got_before(self):
        cfg = _cfg()
        before = turn_S3_config_into_polars_storage_options(cfg).model_dump(exclude_none=True)
        assert S3Backend(cfg).storage_options() == before
        assert before["AWS_S3_ALLOW_UNSAFE_RENAME"] == "true"

    def test_url_and_key_of(self):
        backend = S3Backend(_cfg(bucket="b"))
        assert backend.url("dc1") == "s3://b/dc1"
        assert backend.url() == "s3://b"
        assert backend.key_of("s3://b/dc1/x") == "dc1/x"
        assert backend.key_of("S3://b/dc1") == "dc1"
        assert backend.key_of("s3://other/dc1") is None
        assert backend.key_of("/local/dc1") is None

    def test_the_client_carries_the_instance_settings(self, monkeypatch):
        import boto3

        seen: list[dict] = []
        monkeypatch.setattr(boto3, "client", lambda service, **kw: seen.append(kw) or MagicMock())
        cfg = _cfg(verify_tls=False)
        S3Backend(cfg).client

        (kwargs,) = seen
        assert kwargs["endpoint_url"] == cfg.endpoint_url
        assert kwargs["aws_access_key_id"] == "key"
        assert kwargs["aws_secret_access_key"] == "secret-secret-secret"
        assert kwargs["verify"] is False
        assert kwargs["region_name"] == "us-east-1"
        assert kwargs["config"] is None

    def test_fail_fast_shortens_timeouts(self, monkeypatch):
        import boto3

        seen: list[dict] = []
        monkeypatch.setattr(boto3, "client", lambda service, **kw: seen.append(kw) or MagicMock())
        S3Backend(_cfg(), fail_fast=True).client
        config = seen[0]["config"]
        assert config.connect_timeout == 3
        assert config.retries == {"total_max_attempts": 2}

    def test_the_client_is_built_once(self, monkeypatch):
        import boto3

        calls = []
        monkeypatch.setattr(boto3, "client", lambda *a, **k: calls.append(1) or MagicMock())
        backend = S3Backend(_cfg())
        assert backend.client is backend.client
        assert len(calls) == 1

    def test_list_objects_pages_lazily(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "dc/a", "Size": 3, "ETag": '"e1"'}]},
            {},
            {"Contents": [{"Key": "dc/b", "Size": 4}]},
        ]
        listed = list(_backend(client).list_objects("dc/"))
        assert listed == [ObjectInfo("dc/a", 3, "e1"), ObjectInfo("dc/b", 4, "")]
        client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="depictio-bucket", Prefix="dc/"
        )

    def test_a_listing_error_is_a_storage_error(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.side_effect = _error("AccessDenied")
        with pytest.raises(StorageError) as exc:
            list(_backend(client).list_objects("dc/"))
        assert exc.value.code == "AccessDenied"
        assert not isinstance(exc.value, StorageNotFound)

    def test_head(self):
        client = MagicMock()
        client.head_object.return_value = {"ContentLength": 12, "ETag": '"x"'}
        assert _backend(client).head("k") == ObjectInfo("k", 12, "x")

        client.head_object.side_effect = _error("404", "HeadObject")
        assert _backend(client).head("k") is None

    def test_read_bytes_and_a_missing_key(self):
        client = MagicMock()
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"abc")}
        assert _backend(client).read_bytes("k") == b"abc"

        client.get_object.side_effect = _error("NoSuchKey", "GetObject")
        with pytest.raises(StorageNotFound):
            _backend(client).read_bytes("k")
        with pytest.raises(FileNotFoundError):
            _backend(client).read_bytes("k")

    def test_read_range_is_end_exclusive(self):
        client = MagicMock()
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b"bcd")}
        assert _backend(client).read_range("k", 1, 4) == b"bcd"
        assert client.get_object.call_args.kwargs["Range"] == "bytes=1-3"
        assert _backend(client).read_range("k", 4, 4) == b""

    def test_writes(self, tmp_path: Path):
        client = MagicMock()
        backend = _backend(client)
        backend.put_bytes("k", b"x", content_type="application/json")
        client.put_object.assert_called_once_with(
            Bucket="depictio-bucket", Key="k", Body=b"x", ContentType="application/json"
        )
        path = tmp_path / "f.bin"
        path.write_bytes(b"1")
        backend.upload_file("k2", path)
        client.upload_file.assert_called_once_with(str(path), "depictio-bucket", "k2")

    def test_delete_prefix_lists_then_deletes_in_bulk(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": f"dc/{i}"} for i in range(3)]}
        ]
        client.delete_objects.return_value = {}
        assert _backend(client).delete_prefix("dc") == 3
        objects = client.delete_objects.call_args.kwargs["Delete"]["Objects"]
        assert [o["Key"] for o in objects] == ["dc/0", "dc/1", "dc/2"]

    def test_delete_prefix_with_nothing_there_deletes_nothing(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [{}]
        assert _backend(client).delete_prefix("dc") == 0
        client.delete_objects.assert_not_called()

    def test_delete_falls_back_to_single_deletes(self):
        """A store without DeleteObjects (GCS's XML API) still gets cleaned up."""
        client = MagicMock()
        client.delete_objects.side_effect = _error("NotImplemented", "DeleteObjects")
        _backend(client).delete_keys(["a", "b"])
        assert [c.kwargs["Key"] for c in client.delete_object.call_args_list] == ["a", "b"]

    def test_bucket(self):
        client = MagicMock()
        backend = _backend(client)
        assert backend.bucket_exists()
        assert backend.ensure_bucket() is False
        client.create_bucket.assert_not_called()

        client.head_bucket.side_effect = _error("404", "HeadBucket")
        assert not backend.bucket_exists()
        assert backend.ensure_bucket() is True
        client.create_bucket.assert_called_once_with(Bucket="depictio-bucket")

        client.create_bucket.side_effect = _error("BucketAlreadyOwnedByYou", "CreateBucket")
        assert backend.ensure_bucket() is False

        client.head_bucket.side_effect = _error("403", "HeadBucket")
        with pytest.raises(StorageError):
            backend.bucket_exists()

    def test_presigned_urls_are_signed_for_the_browser_endpoint(self):
        """Computed offline by boto3: the host is the public one, not ``s3:9000``."""
        backend = S3Backend(_cfg(bucket="b"))
        url = urlparse(backend.presign_get("dc/x.vcf.gz", 900))
        assert url.hostname == "files.example.org"
        assert url.path == "/b/dc/x.vcf.gz"
        query = parse_qs(url.query)
        assert query["X-Amz-Expires"] == ["900"]
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]

    def test_filesystem_is_s3fs_on_the_endpoint(self):
        fs = S3Backend(_cfg()).filesystem()
        assert "s3" in fs.protocol
        assert fs.client_kwargs.get("endpoint_url") or fs.endpoint_url


# --------------------------------------------------------------------------
# Modularity guard
# --------------------------------------------------------------------------

_DEPICTIO = Path(__file__).resolve().parents[2]
_STORAGE = _DEPICTIO / "models" / "storage"


def test_no_code_outside_the_storage_package_names_a_backend_class():
    """Callers get a backend from ``instance_storage`` and use its methods.

    Naming a backend class outside ``depictio/models/storage`` is how
    ``if gcs / if azure`` creeps back in.
    """
    pattern = re.compile(r"\b(S3Backend|GCSBackend|ObstoreBackend|AzureBackend)\b")
    offenders = [
        f"{path.relative_to(_DEPICTIO)}:{lineno}: {line.strip()}"
        for path in _DEPICTIO.rglob("*.py")
        if _STORAGE not in path.parents and "tests" not in path.relative_to(_DEPICTIO).parts
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


# --------------------------------------------------------------------------
# GCS backend (no store reached; the emulator and live suites are in tests/storage)
# --------------------------------------------------------------------------


class TestGCSBackend:
    def _gcs(self, **cfg):
        from depictio.api.v1.configs.settings_models import GCSConfig
        from depictio.models.storage import GCSBackend

        return GCSBackend(GCSConfig(bucket="instance-bucket", **cfg))

    def test_it_is_registered_with_its_scheme(self):
        from depictio.models.storage import GCSBackend

        assert backend_class("gcs") is GCSBackend
        assert "gs" in object_schemes()
        assert split_object_url("gs://b/k/x") == ("gs", "b", "k/x")
        assert isinstance(self._gcs(), StorageBackend)

    def test_locations_are_gs_urls(self):
        backend = self._gcs()
        assert backend.url("dc1") == "gs://instance-bucket/dc1"
        assert backend.key_of("gs://instance-bucket/dc1/x") == "dc1/x"
        assert backend.key_of("s3://instance-bucket/dc1") is None

    def test_under_adc_polars_and_deltars_read_the_environment(self):
        """Workload Identity / gcloud ADC: no option at all, and nothing AWS."""
        assert self._gcs().storage_options() == {}

    def test_a_key_file(self):
        options = self._gcs(service_account_path="/var/run/sa.json").storage_options()
        assert options == {"google_service_account": "/var/run/sa.json"}

    def test_anonymous(self):
        assert self._gcs(anonymous=True).storage_options() == {"google_skip_signature": "true"}

    def test_an_emulator_gets_a_no_oauth_key_and_plain_http(self):
        import json

        options = self._gcs(endpoint_url="http://localhost:4443/").storage_options()
        assert options["allow_http"] == "true"
        key = json.loads(options["google_service_account_key"])
        assert key["gcs_base_url"] == "http://localhost:4443"
        assert key["disable_oauth"] is True

    def test_buckets_are_not_created(self, monkeypatch):
        """A GCS bucket needs a project and a location: the operator's choice."""
        backend = self._gcs()
        monkeypatch.setattr(backend, "bucket_exists", lambda: False)
        with pytest.raises(StorageNotFound, match="create it before starting"):
            backend.ensure_bucket()

    def test_check_names_what_failed(self, monkeypatch):
        backend = self._gcs()
        monkeypatch.setattr(backend, "bucket_exists", lambda: False)
        with pytest.raises(StorageError, match="does not exist"):
            backend.check(["bucket"])


class TestInstanceSelection:
    def _settings(self, backend: str, **gcs):
        from depictio.api.v1.configs.settings_models import GCSConfig, StorageConfig

        return SimpleNamespace(
            storage=StorageConfig(backend=backend),
            s3=_cfg(bucket="s3-bucket"),
            gcs=GCSConfig(**gcs),
        )

    def test_the_server_picks_gcs_from_its_settings(self):
        from depictio.models.storage import GCSBackend

        backend = instance_storage(self._settings("gcs", bucket="g"))
        assert isinstance(backend, GCSBackend) and backend.bucket == "g"

    def test_cli_configs_built_by_the_server_carry_the_backend(self):
        from depictio.models.storage import cli_storage_fields

        assert cli_storage_fields(self._settings("s3")) == {"storage_backend": "s3"}
        fields = cli_storage_fields(self._settings("gcs", bucket="g"), dump=True)
        assert fields["storage_backend"] == "gcs"
        assert fields["gcs_storage"]["bucket"] == "g"

    def test_a_cli_config_with_gcs_storage(self):
        from depictio.api.v1.configs.settings_models import GCSConfig
        from depictio.models.storage import GCSBackend

        cli = SimpleNamespace(
            storage_backend="gcs", gcs_storage=GCSConfig(bucket="g"), s3_storage=_cfg()
        )
        assert isinstance(instance_storage(cli), GCSBackend)

    def test_cli_delta_options_follow_the_backend(self):
        from depictio.models.storage import BackendStorageOptions, instance_polars_options

        s3_options = instance_polars_options(SimpleNamespace(s3_storage=_cfg()))
        assert s3_options.model_dump()["AWS_S3_ALLOW_UNSAFE_RENAME"] == "true"
        gcs_options = instance_polars_options(
            SimpleNamespace(storage_backend="gcs", gcs_storage=self._settings("gcs").gcs)
        )
        assert isinstance(gcs_options, BackendStorageOptions)
        assert gcs_options.aws_access_key_id is None
        assert gcs_options.model_dump() == {}

    def test_s3_only_features_refuse_another_backend(self):
        from depictio.models.storage import require_s3_instance

        require_s3_instance(self._settings("s3"), "Project migration")
        with pytest.raises(StorageError, match="Project migration needs the instance bucket on S3"):
            require_s3_instance(self._settings("gcs", bucket="g"), "Project migration")


class TestServerSettings:
    def _settings(self, monkeypatch, **env):
        from depictio.api.v1.configs.settings_models import Settings

        # The secret checks run on a server boot outside single-user mode only:
        # other tests in the same worker may have left either in the environment.
        for name in (
            "DEPICTIO_S3_ROOT_PASSWORD",
            "DEPICTIO_MINIO_ROOT_PASSWORD",
            "DEPICTIO_AUTH_SINGLE_USER_MODE",
            "DEPICTIO_AUTH_UNAUTHENTICATED_MODE",
            "DEPICTIO_STORAGE_BACKEND",
            "DEPICTIO_GCS_BUCKET",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return Settings(context="server")

    def test_an_instance_on_gcs_needs_no_s3_secret(self, monkeypatch):
        settings = self._settings(
            monkeypatch, DEPICTIO_STORAGE_BACKEND="gcs", DEPICTIO_GCS_BUCKET="g"
        )
        assert settings.storage.backend == "gcs"
        assert settings.gcs.bucket == "g"

    def test_an_instance_on_gcs_names_its_bucket(self, monkeypatch):
        with pytest.raises(ValueError, match="DEPICTIO_GCS_BUCKET"):
            self._settings(monkeypatch, DEPICTIO_STORAGE_BACKEND="gcs")

    def test_an_instance_on_s3_still_needs_its_secret(self, monkeypatch):
        with pytest.raises(ValueError, match="DEPICTIO_S3_ROOT_PASSWORD"):
            self._settings(monkeypatch)
