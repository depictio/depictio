"""`indexed_file` data collections at ingest: which files go up, and where.

An indexed_file DC has no delta table. Ingest copies each sample's file and its
index sidecar to S3, then stamps the keys back onto the file documents, which is
what the presigned route signs later. The keys sit outside the ObjectId-shaped
prefixes orphan cleanup deletes, so that shape is pinned here as well.

No S3/MinIO or API is needed: the file listing, boto3 and the upsert call are
mocked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.deltatables import (
    plan_indexed_file_uploads,
    process_indexed_file_data_collection,
)
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections_types.indexed_file import (
    DCIndexedFileConfig,
    indexed_file_s3_key,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
BUCKET = "depictio-bucket"


@pytest.fixture
def cli_config() -> CLIConfig:
    return CLIConfig(  # type: ignore[call-arg]
        user={
            "email": "test@example.com",
            "is_admin": False,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
                "refresh_token": "refresh-token-example",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2025-12-31T23:59:59",
                "refresh_expire_datetime": "2025-12-31T23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        api_base_url="https://api.depictio.dev",
        s3_storage={
            "service_name": "minio",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "minio",
            "root_password": "minio123",
            "bucket": BUCKET,
        },
    )


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    # head_object raising means "not in the bucket yet", so every planned
    # upload actually runs unless a test says otherwise.
    client.head_object.side_effect = RuntimeError("404")
    monkeypatch.setattr("boto3.client", MagicMock(return_value=client))
    return client


class _FileDoc:
    """The subset of `File` the processor touches, writable like the real one."""

    def __init__(self, path: str, size: int = 1024):
        self.file_location = path
        self.filesize = size
        self.sample = None
        self.s3_key = None
        self.index_s3_key = None
        self.index_filesize = None


def _dc(properties: DCIndexedFileConfig) -> SimpleNamespace:
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="sarek_filtered_vcf",
        config=SimpleNamespace(type="indexed_file", dc_specific_properties=properties),
    )


def _registered(monkeypatch: pytest.MonkeyPatch, files) -> None:
    monkeypatch.setattr(deltatables, "fetch_file_data", lambda dc_id, CLI_config: files)


def _ok_upsert(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    response = MagicMock(status_code=200)
    created = MagicMock(return_value=response)
    monkeypatch.setattr(deltatables, "api_create_files", created)
    return created


def _vcf_pair(tmp_path, sample: str):
    vcf = tmp_path / f"{sample}.filtered.vcf.gz"
    vcf.write_bytes(b"\x1f\x8b" + b"0" * 32)
    (tmp_path / f"{sample}.filtered.vcf.gz.tbi").write_bytes(b"\x1f\x8b" + b"0" * 8)
    return vcf


class TestPlanUploads:
    def test_pairs_each_file_with_its_index(self, tmp_path):
        vcf = _vcf_pair(tmp_path, "NA12878")
        uploads, skipped = plan_indexed_file_uploads(
            [_FileDoc(str(vcf))], DC_ID, DCIndexedFileConfig(format="vcf")
        )
        assert skipped == []
        assert len(uploads) == 1
        assert uploads[0]["sample"] == "NA12878.filtered"
        assert uploads[0]["key"] == indexed_file_s3_key(
            DC_ID, "NA12878.filtered", "NA12878.filtered.vcf.gz"
        )
        assert uploads[0]["index_key"].endswith(".vcf.gz.tbi")
        assert uploads[0]["index_size"] > 0

    def test_sample_regex_names_the_sample(self, tmp_path):
        run = tmp_path / "variant_calling" / "haplotypecaller" / "HCC1395T"
        run.mkdir(parents=True)
        vcf = _vcf_pair(run, "HCC1395T")
        uploads, _ = plan_indexed_file_uploads(
            [_FileDoc(str(vcf))],
            DC_ID,
            DCIndexedFileConfig(
                format="vcf", sample_regex=r"variant_calling/[^/]+/(?P<sample>[^/]+)/"
            ),
        )
        assert uploads[0]["sample"] == "HCC1395T"

    def test_self_indexed_format_needs_no_sidecar(self, tmp_path):
        bw = tmp_path / "S1.bigWig"
        bw.write_bytes(b"0" * 16)
        uploads, skipped = plan_indexed_file_uploads(
            [_FileDoc(str(bw))], DC_ID, DCIndexedFileConfig(format="bigwig")
        )
        assert skipped == []
        assert uploads[0]["index_key"] is None

    def test_missing_index_is_skipped_not_uploaded(self, tmp_path):
        vcf = tmp_path / "S1.vcf.gz"
        vcf.write_bytes(b"0" * 16)
        uploads, skipped = plan_indexed_file_uploads(
            [_FileDoc(str(vcf))], DC_ID, DCIndexedFileConfig(format="vcf")
        )
        assert uploads == []
        assert ".tbi" in skipped[0]

    def test_file_above_the_cap_is_skipped(self, tmp_path):
        vcf = _vcf_pair(tmp_path, "big")
        uploads, skipped = plan_indexed_file_uploads(
            [_FileDoc(str(vcf), size=600 * 1024 * 1024)],
            DC_ID,
            DCIndexedFileConfig(format="vcf", max_file_size_mb=512),
        )
        assert uploads == []
        assert "cap" in skipped[0]

    def test_duplicate_sample_keeps_the_first_file(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        first = _vcf_pair(a, "S1")
        second = _vcf_pair(b, "S1")
        uploads, skipped = plan_indexed_file_uploads(
            [_FileDoc(str(first)), _FileDoc(str(second))], DC_ID, DCIndexedFileConfig(format="vcf")
        )
        assert len(uploads) == 1
        assert uploads[0]["file"].file_location == str(first)
        assert "already taken" in skipped[0]


class TestProcess:
    def test_uploads_file_and_index_then_records_the_keys(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        vcf = _vcf_pair(tmp_path, "NA12878")
        doc = _FileDoc(str(vcf))
        _registered(monkeypatch, [doc])
        created = _ok_upsert(monkeypatch)

        result = process_indexed_file_data_collection(
            _dc(DCIndexedFileConfig(format="vcf")), cli_config
        )

        assert result["result"] == "success"
        uploaded = {call.args[2] for call in s3_client.upload_file.call_args_list}
        assert uploaded == {
            f"indexed_files/{DC_ID}/NA12878.filtered/NA12878.filtered.vcf.gz",
            f"indexed_files/{DC_ID}/NA12878.filtered/NA12878.filtered.vcf.gz.tbi",
        }
        assert doc.sample == "NA12878.filtered"
        assert doc.s3_key.startswith("indexed_files/")
        assert doc.index_s3_key.endswith(".tbi")
        # The keys must reach Mongo, otherwise the presigned route finds nothing.
        assert created.call_args.kwargs["update"] is True

    def test_prefix_is_not_an_objectid_prefix(self):
        """Orphan cleanup deletes 24-hex top-level prefixes with no deltatable document."""
        assert indexed_file_s3_key(DC_ID, "S1", "S1.vcf.gz").split("/")[0] == "indexed_files"

    def test_existing_object_is_not_re_uploaded_without_overwrite(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        vcf = _vcf_pair(tmp_path, "S1")
        _registered(monkeypatch, [_FileDoc(str(vcf))])
        _ok_upsert(monkeypatch)
        s3_client.head_object.side_effect = None  # every key is already there

        result = process_indexed_file_data_collection(
            _dc(DCIndexedFileConfig(format="vcf")), cli_config
        )

        assert result["result"] == "success"
        s3_client.upload_file.assert_not_called()

    def test_overwrite_re_uploads(self, tmp_path, monkeypatch, cli_config, s3_client):
        vcf = _vcf_pair(tmp_path, "S1")
        _registered(monkeypatch, [_FileDoc(str(vcf))])
        _ok_upsert(monkeypatch)
        s3_client.head_object.side_effect = None

        process_indexed_file_data_collection(
            _dc(DCIndexedFileConfig(format="vcf")), cli_config, overwrite=True
        )

        assert s3_client.upload_file.call_count == 2

    def test_upload_failure_is_an_error_result(self, tmp_path, monkeypatch, cli_config, s3_client):
        vcf = _vcf_pair(tmp_path, "S1")
        _registered(monkeypatch, [_FileDoc(str(vcf))])
        _ok_upsert(monkeypatch)
        s3_client.upload_file.side_effect = RuntimeError("AccessDenied")

        result = process_indexed_file_data_collection(
            _dc(DCIndexedFileConfig(format="vcf")), cli_config
        )

        assert result["result"] == "error"
        assert "AccessDenied" in result["message"]

    def test_nothing_uploadable_is_an_error_result(
        self, tmp_path, monkeypatch, cli_config, s3_client
    ):
        lone = tmp_path / "S1.vcf.gz"
        lone.write_bytes(b"0" * 8)
        _registered(monkeypatch, [_FileDoc(str(lone))])
        _ok_upsert(monkeypatch)

        result = process_indexed_file_data_collection(
            _dc(DCIndexedFileConfig(format="vcf")), cli_config
        )

        assert result["result"] == "error"
        s3_client.upload_file.assert_not_called()
