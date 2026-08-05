"""Tests for the remote data manifest models and remote-URL support.

Covers:
- depictio.models.models.manifest: ManifestEntry, DataManifest (CSV/JSON parsing),
  is_remote_url / validate_remote_url_syntax
- depictio.models.models.data_collections: ScanURL and Scan mode "url"
- depictio.models.models.files: File accepting remote URLs and the -1 filesize sentinel
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import Scan, ScanURL
from depictio.models.models.files import File
from depictio.models.models.manifest import (
    DataManifest,
    ManifestEntry,
    is_remote_url,
    validate_remote_url_syntax,
)
from depictio.models.models.users import Permission, UserBase


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    """Set DEPICTIO_CONTEXT for all tests in the module."""
    monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "server")
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "server")


@pytest.fixture(autouse=True)
def no_http_allowed(monkeypatch):
    """Ensure the http:// opt-in env var is unset unless a test sets it."""
    monkeypatch.delenv("DEPICTIO_REMOTE_ALLOW_HTTP", raising=False)


class TestRemoteUrlSyntax:
    """Test suite for is_remote_url / validate_remote_url_syntax."""

    def test_s3_url_accepted(self):
        url = "s3://bucket/prefix/data.parquet"
        assert is_remote_url(url)
        assert validate_remote_url_syntax(url) == url

    def test_https_url_accepted(self):
        url = "https://example.org/data.csv"
        assert is_remote_url(url)
        assert validate_remote_url_syntax(url) == url

    def test_http_url_rejected_by_default(self):
        url = "http://example.org/data.csv"
        assert not is_remote_url(url)
        with pytest.raises(ValueError, match="URL scheme not allowed"):
            validate_remote_url_syntax(url)

    def test_http_url_accepted_when_env_opt_in(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        url = "http://example.org/data.csv"
        assert is_remote_url(url)
        assert validate_remote_url_syntax(url) == url

    @pytest.mark.parametrize("env_value", ["1", "yes", "TRUE"])
    def test_http_opt_in_env_value_variants(self, monkeypatch, env_value):
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", env_value)
        assert is_remote_url("http://example.org/x")

    def test_http_opt_in_falsey_env_value(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "false")
        assert not is_remote_url("http://example.org/x")

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="URL cannot be empty"):
            validate_remote_url_syntax("")

    def test_ftp_url_rejected(self):
        assert not is_remote_url("ftp://example.org/data.csv")
        with pytest.raises(ValueError, match="URL scheme not allowed"):
            validate_remote_url_syntax("ftp://example.org/data.csv")

    def test_local_path_is_not_remote(self):
        assert not is_remote_url("/path/to/local/file.csv")


class TestManifestEntry:
    """Test suite for the ManifestEntry model."""

    def test_valid_entry(self):
        entry = ManifestEntry(
            id="sample1", type="counts", url="s3://bucket/sample1.parquet", run="run_A"
        )
        assert entry.id == "sample1"
        assert entry.run == "run_A"
        assert entry.extra == {}

    def test_run_defaults_to_none(self):
        entry = ManifestEntry(id="s1", type="counts", url="https://example.org/s1.csv")
        assert entry.run is None

    def test_id_and_type_stripped(self):
        entry = ManifestEntry(id="  s1  ", type=" counts ", url="s3://b/x")
        assert entry.id == "s1"
        assert entry.type == "counts"

    @pytest.mark.parametrize("field", ["id", "type"])
    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_id_or_type_rejected(self, field, value):
        data = {"id": "s1", "type": "counts", "url": "s3://b/x"}
        data[field] = value
        with pytest.raises(ValidationError, match="Field cannot be empty"):
            ManifestEntry(**data)

    def test_bad_url_scheme_rejected(self):
        with pytest.raises(ValidationError, match="URL scheme not allowed"):
            ManifestEntry(id="s1", type="counts", url="ftp://example.org/x")

    def test_unknown_key_rejected(self):
        """The schema is closed — extra is the only open field."""
        with pytest.raises(ValidationError):
            ManifestEntry(id="s1", type="counts", url="s3://b/x", batch="b1")  # type: ignore[call-arg]


class TestDataManifestCsv:
    """Test suite for DataManifest.from_csv."""

    def test_happy_path_with_extra_column(self):
        text = (
            "id,type,url,run,condition\n"
            "s1,counts,s3://bucket/s1.parquet,run_A,treated\n"
            "s2,counts,https://example.org/s2.parquet,run_A,control\n"
            "s3,metadata,s3://bucket/s3.csv,,\n"
        )
        manifest = DataManifest.from_csv(text, source="s3://bucket/manifest.csv")
        assert manifest.version == "1"
        assert manifest.source == "s3://bucket/manifest.csv"
        assert len(manifest.entries) == 3

        s1 = manifest.entries[0]
        assert s1.id == "s1"
        assert s1.type == "counts"
        assert s1.url == "s3://bucket/s1.parquet"
        assert s1.run == "run_A"
        # Unknown column is folded into extra
        assert s1.extra == {"condition": "treated"}

        # Empty run cell becomes None
        assert manifest.entries[2].run is None

    def test_missing_required_column_raises(self):
        text = "id,url\ns1,s3://bucket/s1.parquet\n"
        with pytest.raises(ValueError, match="missing required column"):
            DataManifest.from_csv(text)

    def test_blank_lines_tolerated(self):
        text = (
            "id,type,url\n"
            "\n"
            "s1,counts,s3://bucket/s1.parquet\n"
            ",,\n"
            "s2,counts,s3://bucket/s2.parquet\n"
            "\n"
        )
        manifest = DataManifest.from_csv(text)
        assert [entry.id for entry in manifest.entries] == ["s1", "s2"]

    def test_source_defaults_to_none(self):
        manifest = DataManifest.from_csv("id,type,url\ns1,counts,s3://b/x\n")
        assert manifest.source is None

    def test_invalid_row_url_raises(self):
        text = "id,type,url\ns1,counts,ftp://example.org/x\n"
        with pytest.raises(ValidationError, match="URL scheme not allowed"):
            DataManifest.from_csv(text)

    def test_types_and_entries_for_type(self):
        text = "id,type,url\ns1,counts,s3://b/s1\ns2,counts,s3://b/s2\ns3,metadata,s3://b/s3\n"
        manifest = DataManifest.from_csv(text)
        assert manifest.types() == {"counts", "metadata"}
        counts_entries = manifest.entries_for_type("counts")
        assert [entry.id for entry in counts_entries] == ["s1", "s2"]
        assert manifest.entries_for_type("unknown_tag") == []


class TestDataManifestJson:
    """Test suite for DataManifest.from_json."""

    def test_object_form_with_entries(self):
        text = (
            '{"version": "1", "entries": ['
            '{"id": "s1", "type": "counts", "url": "s3://b/s1.parquet"},'
            '{"id": "s2", "type": "counts", "url": "https://example.org/s2.parquet", "run": "r1"}'
            "]}"
        )
        manifest = DataManifest.from_json(text, source="https://example.org/manifest.json")
        assert manifest.version == "1"
        assert manifest.source == "https://example.org/manifest.json"
        assert len(manifest.entries) == 2
        assert manifest.entries[1].run == "r1"

    def test_bare_list_form(self):
        text = '[{"id": "s1", "type": "counts", "url": "s3://b/s1.parquet"}]'
        manifest = DataManifest.from_json(text)
        assert len(manifest.entries) == 1
        assert manifest.entries[0].id == "s1"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            DataManifest.from_json("{not json")

    @pytest.mark.parametrize("text", ['"a string"', "42", "true", "null"])
    def test_non_object_non_list_raises(self, text):
        with pytest.raises(ValueError, match="must be an object or a list"):
            DataManifest.from_json(text)

    def test_unknown_entry_key_rejected(self):
        text = '[{"id": "s1", "type": "counts", "url": "s3://b/x", "batch": "b1"}]'
        with pytest.raises(ValidationError):
            DataManifest.from_json(text)

    def test_unknown_top_level_key_rejected(self):
        text = '{"entries": [], "owner": "someone"}'
        with pytest.raises(ValidationError):
            DataManifest.from_json(text)

    def test_unsupported_version_rejected(self):
        text = '{"version": "2", "entries": []}'
        with pytest.raises(ValidationError, match="Unsupported manifest version"):
            DataManifest.from_json(text)

    def test_source_in_payload_preserved_when_arg_omitted(self):
        text = '{"entries": [], "source": "s3://b/manifest.json"}'
        manifest = DataManifest.from_json(text)
        assert manifest.source == "s3://b/manifest.json"


class TestScanURL:
    """Test suite for ScanURL and Scan mode 'url'."""

    def test_scan_url_valid(self):
        scan_url = ScanURL(url="https://example.org/data.parquet")
        assert scan_url.url == "https://example.org/data.parquet"

    def test_scan_url_s3_valid(self):
        scan_url = ScanURL(url="s3://bucket/data.parquet")
        assert scan_url.url == "s3://bucket/data.parquet"

    def test_scan_url_bad_scheme_raises(self):
        with pytest.raises(ValidationError, match="URL scheme not allowed"):
            ScanURL(url="ftp://example.org/data.parquet")

    def test_scan_url_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ScanURL(url="s3://bucket/data.parquet", other="x")  # type: ignore[call-arg]

    def test_scan_mode_url_dispatches_dict(self):
        scan = Scan(mode="url", scan_parameters={"url": "https://example.org/data.parquet"})
        assert scan.mode == "url"
        assert isinstance(scan.scan_parameters, ScanURL)
        assert scan.scan_parameters.url == "https://example.org/data.parquet"

    def test_scan_mode_url_with_instance(self):
        scan = Scan(mode="url", scan_parameters=ScanURL(url="s3://bucket/data.parquet"))
        assert isinstance(scan.scan_parameters, ScanURL)

    def test_scan_mode_url_bad_scheme_raises(self):
        with pytest.raises(ValidationError):
            Scan(mode="url", scan_parameters={"url": "ftp://example.org/data.parquet"})

    def test_scan_unknown_mode_rejected(self):
        with pytest.raises(ValidationError, match="mode must be one of"):
            Scan(mode="crawl", scan_parameters={"url": "https://example.org/data.parquet"})


class TestFileRemoteLocation:
    """Test suite for File accepting remote URLs and the filesize sentinel."""

    @pytest.fixture
    def sample_permissions(self):
        return Permission(
            owners=[
                UserBase(
                    id=PyObjectId(),
                    email="test@example.com",
                    is_admin=True,
                )
            ]
        )

    @pytest.fixture
    def remote_file_data(self, sample_permissions):
        return {
            "filename": "x.csv",
            "file_location": "https://example.org/x.csv",
            "creation_time": "2025-01-01 10:00:00",
            "modification_time": "2025-01-01 11:00:00",
            "run_id": PyObjectId(),
            "data_collection_id": PyObjectId(),
            "filesize": -1,
            "file_hash": "a" * 64,
            "permissions": sample_permissions,
        }

    def test_remote_url_location_with_unknown_size(self, remote_file_data):
        file_instance = File(**remote_file_data)  # type: ignore[missing-argument]
        assert file_instance.file_location == "https://example.org/x.csv"
        assert file_instance.filesize == -1

    def test_s3_url_location(self, remote_file_data):
        remote_file_data["file_location"] = "s3://bucket/x.csv"
        remote_file_data["filesize"] = 1024
        file_instance = File(**remote_file_data)  # type: ignore[missing-argument]
        assert file_instance.file_location == "s3://bucket/x.csv"

    def test_remote_url_skips_local_checks_in_cli_context(self, remote_file_data, monkeypatch):
        """Remote URLs bypass the CLI-context filesystem existence checks."""
        monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")
        file_instance = File(**remote_file_data)  # type: ignore[missing-argument]
        assert file_instance.file_location == "https://example.org/x.csv"

    def test_zero_filesize_rejected(self, remote_file_data):
        remote_file_data["filesize"] = 0
        with pytest.raises(ValidationError, match="File size cannot be zero"):
            File(**remote_file_data)  # type: ignore[missing-argument]

    def test_filesize_below_sentinel_rejected(self, remote_file_data):
        remote_file_data["filesize"] = -2
        with pytest.raises(ValidationError, match="File size cannot be negative"):
            File(**remote_file_data)  # type: ignore[missing-argument]
