"""Genomic tracks DCs at ingest: which local files are uploaded, and where.

The manifest becomes a Delta table like any table DC; the files its rows point
at are uploaded under the DC's S3 folder at the same relative path, which is
where the API's track proxy resolves them. Remote rows are read in place, and
a missing index fails the DC before anything is registered.

No S3/MinIO or API is needed: the file listing and boto3 are mocked.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli.utils import deltatables, genomic_tracks_ingest
from depictio.cli.cli.utils.genomic_tracks_ingest import (
    TrackPathError,
    bucket_relative,
    check_sequence_names,
    sample_sequence_names,
    upload_genomic_track_files,
)
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.data_collections_types.genomic_tracks import (
    CustomAssembly,
    DCGenomicTracksConfig,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
BUCKET = "depictio-bucket"
PREFIX = f"genomic_tracks/{DC_ID}/"


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
    client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
    monkeypatch.setattr("boto3.client", MagicMock(return_value=client))
    return client


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """HEAD probes of https tracks are recorded, never sent."""
    probed: list[str] = []

    def _head(url, **kwargs):
        probed.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("httpx.head", _head)
    return probed


def _dc(**props) -> SimpleNamespace:
    return SimpleNamespace(
        id=DC_ID,
        data_collection_tag="sv_tracks",
        config=SimpleNamespace(
            type="genomic_tracks",
            dc_specific_properties=DCGenomicTracksConfig(format="tsv", **props),
        ),
    )


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _manifest(path: Path, rows: list[dict[str, str]]) -> SimpleNamespace:
    columns = list(rows[0])
    lines = ["\t".join(columns)] + ["\t".join(r.get(c, "") for c in columns) for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return SimpleNamespace(file_location=str(path))


def _uploaded(s3_client: MagicMock) -> dict[str, str]:
    """key → local path of every upload_file call."""
    calls = s3_client.upload_file.call_args_list
    assert all(c.args[1] == BUCKET for c in calls)
    return {c.args[2]: c.args[0] for c in calls}


class TestUpload:
    def test_relative_tracks_and_indexes_go_under_the_dc_folder(
        self, tmp_path, cli_config, s3_client, no_network
    ):
        _touch(tmp_path / "cells" / "c1.bw")
        _touch(tmp_path / "cells" / "c1.bam")
        _touch(tmp_path / "cells" / "c1.bam.bai")
        _touch(tmp_path / "sv.vcf.gz")
        _touch(tmp_path / "sv.vcf.gz.tbi")
        _touch(tmp_path / "calls.bed", b"chr1\t1\t10\n")
        manifest = _manifest(
            tmp_path / "tracks.tsv",
            [
                {"uri": "cells/c1.bw", "cell": "C1"},
                {"uri": "cells/c1.bam", "cell": "C1"},
                {"uri": "sv.vcf.gz", "cell": "C2"},
                {"uri": "calls.bed", "cell": "C2"},
                {"uri": "https://tracks.example.org/r.bw", "cell": "C3"},
                {"uri": "s3://public-genomes/x.bw", "cell": "C3"},
            ],
        )

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success", result["message"]
        assert _uploaded(s3_client) == {
            PREFIX + "cells/c1.bw": str(tmp_path / "cells" / "c1.bw"),
            PREFIX + "cells/c1.bam": str(tmp_path / "cells" / "c1.bam"),
            PREFIX + "cells/c1.bam.bai": str(tmp_path / "cells" / "c1.bam.bai"),
            PREFIX + "sv.vcf.gz": str(tmp_path / "sv.vcf.gz"),
            PREFIX + "sv.vcf.gz.tbi": str(tmp_path / "sv.vcf.gz.tbi"),
            PREFIX + "calls.bed": str(tmp_path / "calls.bed"),
        }
        assert result["uploaded"] == 6
        assert result["remote"] == 2
        assert no_network == ["https://tracks.example.org/r.bw"]

    def test_missing_bam_index_fails_with_the_file_listed(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "c1.bam")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "c1.bam"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert str(tmp_path / "c1.bam.bai") in result["message"]
        assert "samtools index" in result["message"]
        s3_client.upload_file.assert_not_called()

    def test_missing_tabix_index_fails(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "calls.bed.gz")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "calls.bed.gz"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert "calls.bed.gz.tbi" in result["message"]

    def test_missing_track_file_fails(self, tmp_path, cli_config, s3_client):
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "gone.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert str(tmp_path / "gone.bw") in result["message"]

    def test_remote_only_manifest_uploads_nothing(self, tmp_path, cli_config, s3_client):
        manifest = _manifest(
            tmp_path / "tracks.tsv",
            [{"uri": "https://h.org/a.bam"}, {"uri": "s3://b/c.bw"}],
        )

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success"
        assert result["remote"] == 2
        s3_client.upload_file.assert_not_called()

    def test_https_probe_failure_only_warns(self, tmp_path, cli_config, s3_client, monkeypatch):
        def _boom(url, **kwargs):
            raise OSError("down")

        monkeypatch.setattr("httpx.head", _boom)
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "https://h.org/a.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success"

    def test_explicit_relative_index_column(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "bams" / "c1.bam")
        _touch(tmp_path / "idx" / "c1.csi")
        manifest = _manifest(
            tmp_path / "tracks.tsv", [{"uri": "bams/c1.bam", "index_uri": "idx/c1.csi"}]
        )

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success", result["message"]
        assert set(_uploaded(s3_client)) == {PREFIX + "bams/c1.bam", PREFIX + "idx/c1.csi"}

    def test_remote_explicit_index_is_not_uploaded(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "c1.bam")
        manifest = _manifest(
            tmp_path / "tracks.tsv", [{"uri": "c1.bam", "index_uri": "https://h.org/c1.bai"}]
        )

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success", result["message"]
        assert set(_uploaded(s3_client)) == {PREFIX + "c1.bam"}

    def test_tracks_base_path(self, tmp_path, cli_config, s3_client):
        data = tmp_path / "data"
        _touch(data / "c1.bw")
        manifest = _manifest(tmp_path / "meta" / "tracks.tsv", [{"uri": "c1.bw"}])

        result = upload_genomic_track_files(
            _dc(tracks_base_path=str(data)), cli_config, files=[manifest]
        )

        assert result["result"] == "success", result["message"]
        assert _uploaded(s3_client) == {PREFIX + "c1.bw": str(data / "c1.bw")}

    def test_relative_tracks_base_path_is_relative_to_the_manifest(
        self, tmp_path, cli_config, s3_client
    ):
        _touch(tmp_path / "data" / "c1.bw")
        manifest = _manifest(tmp_path / "meta" / "tracks.tsv", [{"uri": "c1.bw"}])

        result = upload_genomic_track_files(
            _dc(tracks_base_path="../data"), cli_config, files=[manifest]
        )

        assert result["result"] == "success", result["message"]
        assert PREFIX + "c1.bw" in _uploaded(s3_client)

    def test_each_manifest_resolves_against_its_own_directory(
        self, tmp_path, cli_config, s3_client
    ):
        _touch(tmp_path / "run1" / "a.bw")
        _touch(tmp_path / "run2" / "b.bw")
        m1 = _manifest(tmp_path / "run1" / "tracks.tsv", [{"uri": "a.bw"}])
        m2 = _manifest(tmp_path / "run2" / "tracks.tsv", [{"uri": "b.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[m1, m2])

        assert result["result"] == "success", result["message"]
        assert _uploaded(s3_client) == {
            PREFIX + "a.bw": str(tmp_path / "run1" / "a.bw"),
            PREFIX + "b.bw": str(tmp_path / "run2" / "b.bw"),
        }

    def test_path_escaping_the_folder_is_an_error(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "x.bw")
        manifest = _manifest(tmp_path / "meta" / "tracks.tsv", [{"uri": "../x.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert "tracks_base_path" in result["message"]
        s3_client.upload_file.assert_not_called()

    def test_existing_keys_are_skipped_unless_overwrite(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        _touch(tmp_path / "b.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}, {"uri": "b.bw"}])
        s3_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": PREFIX + "a.bw"}]}
        ]

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert (result["uploaded"], result["skipped"]) == (1, 1)
        assert set(_uploaded(s3_client)) == {PREFIX + "b.bw"}
        s3_client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket=BUCKET, Prefix=PREFIX
        )

        s3_client.upload_file.reset_mock()
        result = upload_genomic_track_files(_dc(), cli_config, overwrite=True, files=[manifest])
        assert result["uploaded"] == 2

    def test_upload_failure_is_an_error_result(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])
        s3_client.upload_file.side_effect = RuntimeError("AccessDenied")

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"

    def test_duplicate_rows_upload_once(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}, {"uri": "./a.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["uploaded"] == 1

    def test_custom_s3_base_folder(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])

        result = upload_genomic_track_files(
            _dc(s3_base_folder=f"s3://{BUCKET}/{PREFIX}run1"), cli_config, files=[manifest]
        )

        assert result["result"] == "success", result["message"]
        assert set(_uploaded(s3_client)) == {PREFIX + "run1/a.bw"}

    def test_custom_folder_outside_the_dc_in_own_bucket_is_refused(
        self, tmp_path, cli_config, s3_client
    ):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])

        result = upload_genomic_track_files(
            _dc(s3_base_folder=f"s3://{BUCKET}/shared"), cli_config, files=[manifest]
        )

        assert result["result"] == "error"
        s3_client.upload_file.assert_not_called()

    def test_custom_fasta_assembly_files(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "ref" / "genome.fa.gz")
        _touch(tmp_path / "ref" / "genome.fa.gz.fai")
        _touch(tmp_path / "ref" / "genome.fa.gz.gzi")
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])
        assembly = CustomAssembly(name="v", fasta_uri="ref/genome.fa.gz")

        result = upload_genomic_track_files(_dc(assembly=assembly), cli_config, files=[manifest])

        assert result["result"] == "success", result["message"]
        assert set(_uploaded(s3_client)) == {
            PREFIX + "a.bw",
            PREFIX + "ref/genome.fa.gz",
            PREFIX + "ref/genome.fa.gz.fai",
            PREFIX + "ref/genome.fa.gz.gzi",
        }

    def test_custom_assembly_missing_fai_fails(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "genome.fa")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "https://h.org/a.bw"}])
        assembly = CustomAssembly(name="v", fasta_uri="genome.fa")

        result = upload_genomic_track_files(_dc(assembly=assembly), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert "genome.fa.fai" in result["message"]

    def test_remote_custom_assembly_is_left_alone(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])
        assembly = CustomAssembly(name="v", twobit_uri="https://h.org/v.2bit")

        result = upload_genomic_track_files(_dc(assembly=assembly), cli_config, files=[manifest])

        assert result["result"] == "success"
        assert set(_uploaded(s3_client)) == {PREFIX + "a.bw"}

    def test_manifest_without_uri_column(self, tmp_path, cli_config, s3_client):
        manifest = _manifest(tmp_path / "tracks.tsv", [{"path": "a.bw"}])

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "error"
        assert "uri_column" in result["message"]

    def test_files_are_fetched_when_not_given(self, tmp_path, cli_config, s3_client, monkeypatch):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw"}])
        monkeypatch.setattr(deltatables, "fetch_file_data", lambda dc_id, cfg: [manifest])

        result = upload_genomic_track_files(_dc(), cli_config)

        assert result["result"] == "success"


class TestSequenceNames:
    def test_bucket_relative(self):
        assert bucket_relative("./a//b.bw") == "a/b.bw"
        assert bucket_relative("/abs/a.bw") == "abs/a.bw"
        with pytest.raises(TrackPathError):
            bucket_relative("a/../../b.bw")

    def test_sample_skips_headers_and_reads_gzip(self, tmp_path):
        vcf = tmp_path / "sv.vcf.gz"
        with gzip.open(vcf, "wt") as fh:
            fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\nchr1\t10\n2\t20\n")
        assert sample_sequence_names(vcf) == {"chr1", "2"}

    def test_sample_is_bounded(self, tmp_path):
        bed = _touch(tmp_path / "a.bed", b"".join(f"s{i}\t1\t2\n".encode() for i in range(500)))
        assert len(sample_sequence_names(bed, max_lines=200)) == 200

    def test_mixed_prefixes_warn(self, tmp_path):
        bed = _touch(tmp_path / "a.bed", b"track name=x\nchr1\t1\t2\n1\t1\t2\n")
        (warning,) = check_sequence_names([bed], "hg38", None)
        assert "chr" in warning and "a.bed" in warning

    def test_consistent_names_do_not_warn(self, tmp_path):
        bed = _touch(tmp_path / "a.bed", b"chr1\t1\t2\nchrX\t1\t2\n")
        assert check_sequence_names([bed], "hg38", None) == []

    def test_names_missing_from_a_custom_fai_warn(self, tmp_path):
        bed = _touch(tmp_path / "a.bed", b"chr1\t1\t2\n")
        fai = _touch(tmp_path / "ref.fa.fai", b"1\t100\t3\t60\t61\n")
        assembly = CustomAssembly(name="v", fasta_uri="ref.fa")
        (warning,) = check_sequence_names([bed], assembly, fai)
        assert "refname_aliases_uri" in warning

    def test_aliases_silence_the_fai_check(self, tmp_path):
        bed = _touch(tmp_path / "a.bed", b"chr1\t1\t2\n")
        fai = _touch(tmp_path / "ref.fa.fai", b"1\t100\t3\t60\t61\n")
        assembly = CustomAssembly(name="v", fasta_uri="ref.fa", refname_aliases_uri="al.txt")
        assert check_sequence_names([bed], assembly, fai) == []

    def test_mixed_names_warn_but_do_not_fail_ingest(
        self, tmp_path, cli_config, s3_client, monkeypatch
    ):
        _touch(tmp_path / "a.bed", b"chr1\t1\t2\n1\t1\t2\n")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bed"}])
        warnings: list[str] = []
        monkeypatch.setattr(
            genomic_tracks_ingest,
            "rich_print_checked_statement",
            lambda msg, mode: warnings.append(msg) if mode == "warning" else None,
        )

        result = upload_genomic_track_files(_dc(), cli_config, files=[manifest])

        assert result["result"] == "success"
        assert any("mixes" in w for w in warnings)


class TestAggregateRouting:
    """The manifest takes the table path; the upload runs before the upsert."""

    @pytest.fixture
    def table_path(self, tmp_path, monkeypatch):
        from depictio.cli.cli.utils.rich_utils import add_rich_display_to_polars

        add_rich_display_to_polars()
        _touch(tmp_path / "a.bw")
        manifest = _manifest(tmp_path / "tracks.tsv", [{"uri": "a.bw", "cell": "C1"}])
        written: list = []
        upserts: list = []
        monkeypatch.setattr(
            deltatables, "read_delta_table", lambda *a, **k: {"result": "error", "message": ""}
        )
        monkeypatch.setattr(deltatables, "fetch_file_data", lambda dc_id, cfg: [manifest])
        monkeypatch.setattr(
            deltatables,
            "write_delta_table",
            lambda aggregated_df, **k: written.append(aggregated_df) or {"result": "success"},
        )

        def _upsert(**kwargs):
            upserts.append(kwargs)
            return SimpleNamespace(status_code=200, json=lambda: {"result": "success"})

        monkeypatch.setattr(deltatables, "api_upsert_deltatable", _upsert)
        dc = DataCollection(
            id=DC_ID,  # type: ignore[arg-type]
            data_collection_tag="sv_tracks",
            config={  # type: ignore[arg-type]
                "type": "genomic_tracks",
                "scan": {"mode": "single", "scan_parameters": {"filename": manifest.file_location}},
                "dc_specific_properties": {"format": "tsv", "sample_column": "cell"},
            },
        )
        return SimpleNamespace(written=written, upserts=upserts, manifest=manifest, dc=dc)

    def test_manifest_is_written_then_files_uploaded(
        self, table_path, cli_config, s3_client, monkeypatch
    ):
        calls = []
        real = genomic_tracks_ingest.upload_genomic_track_files
        monkeypatch.setattr(
            genomic_tracks_ingest,
            "upload_genomic_track_files",
            lambda dc, cfg, overwrite, files=None: (
                calls.append((overwrite, files)) or real(dc, cfg, overwrite, files=files)
            ),
        )

        result = deltatables.client_aggregate_data(table_path.dc, cli_config, {"overwrite": True})

        assert result["result"] == "success", result["message"]
        (df,) = table_path.written
        assert df.columns[:2] == ["uri", "cell"]
        assert calls == [(True, [table_path.manifest])]
        assert PREFIX + "a.bw" in _uploaded(s3_client)
        assert len(table_path.upserts) == 1

    def test_upload_error_skips_the_upsert(self, table_path, cli_config, monkeypatch):
        monkeypatch.setattr(
            genomic_tracks_ingest,
            "upload_genomic_track_files",
            lambda *a, **k: {"result": "error", "message": "missing index"},
        )

        result = deltatables.client_aggregate_data(table_path.dc, cli_config, {"overwrite": True})

        assert result == {"result": "error", "message": "missing index"}
        assert table_path.upserts == []


class TestRemoteBaseUri:
    def test_relative_rows_are_read_in_place(self, tmp_path, cli_config, s3_client, monkeypatch):
        _touch(tmp_path / "a.bw")
        manifest = _manifest(
            tmp_path / "tracks.tsv",
            [{"uri": "a.bw"}, {"uri": "gone.bam"}, {"uri": "https://h.org/x.bw"}],
        )
        messages: list[str] = []
        monkeypatch.setattr(
            genomic_tracks_ingest,
            "rich_print_checked_statement",
            lambda msg, mode: messages.append(msg),
        )
        assembly = CustomAssembly(name="v", fasta_uri="ref/genome.fa")

        result = upload_genomic_track_files(
            _dc(remote_base_uri="s3://results/run1", assembly=assembly),
            cli_config,
            files=[manifest],
        )

        assert result["result"] == "success", result["message"]
        assert result["in_place"] == 2
        assert result["remote"] == 1
        s3_client.upload_file.assert_not_called()
        assert "2 track(s) read in place under s3://results/run1/" in messages


class TestRecipeManifests:
    def test_single_run_resolves_against_data_dir(self, tmp_path):
        import polars as pl

        df = pl.DataFrame({"uri": ["a.bw"], "depictio_run_id": ["r1"]})
        ((rows, base),) = genomic_tracks_ingest.manifests_from_frame(df, tmp_path, [])
        assert base == tmp_path.resolve()
        assert rows == [{"uri": "a.bw", "depictio_run_id": "r1"}]

    def test_multi_run_rows_resolve_against_their_run(self, tmp_path):
        import polars as pl

        r1, r2 = tmp_path / "run1", tmp_path / "run2"
        df = pl.DataFrame(
            {"uri": ["a.bw", "b.bw", "c.bw"], "depictio_run_id": ["run1", "run2", "run1"]}
        )
        groups = dict(
            (base, [r["uri"] for r in rows])
            for rows, base in genomic_tracks_ingest.manifests_from_frame(df, r1, [str(r1), str(r2)])
        )
        assert groups == {r1.resolve(): ["a.bw", "c.bw"], r2.resolve(): ["b.bw"]}

    def test_missing_ok_warns_and_uploads_the_rest(self, tmp_path, cli_config, s3_client):
        _touch(tmp_path / "a.bw")
        _touch(tmp_path / "r.bam")
        rows = [{"uri": "a.bw"}, {"uri": "gone.bw"}, {"uri": "r.bam"}]

        result = upload_genomic_track_files(
            _dc(), cli_config, manifests=[(rows, tmp_path)], missing_ok=True
        )

        assert result["result"] == "success", result["message"]
        assert result["missing"] == 2  # gone.bw and the r.bam index
        assert set(_uploaded(s3_client)) == {PREFIX + "a.bw", PREFIX + "r.bam"}

    def test_recipe_path_uploads_after_the_delta_write(
        self, tmp_path, cli_config, s3_client, monkeypatch
    ):
        import polars as pl

        import depictio.recipes as recipes

        _touch(tmp_path / "bigwig" / "s1.bw")
        manifest_df = pl.DataFrame(
            {"uri": ["bigwig/s1.bw", "bigwig/s2.bw"], "sample": ["s1", "s2"]}
        )
        monkeypatch.setattr(recipes, "load_recipe", lambda *a, **k: SimpleNamespace(SOURCES=[]))
        monkeypatch.setattr(recipes, "execute_recipe", lambda *a, **k: manifest_df)
        written: list = []
        upserts: list = []
        monkeypatch.setattr(
            deltatables,
            "write_delta_table",
            lambda aggregated_df, **k: written.append(aggregated_df) or {"result": "success"},
        )
        monkeypatch.setattr(
            deltatables,
            "api_upsert_deltatable",
            lambda **k: (
                upserts.append(k)
                or SimpleNamespace(status_code=200, json=lambda: {"result": "success"})
            ),
        )
        dc = DataCollection(
            id=DC_ID,  # type: ignore[arg-type]
            data_collection_tag="bigwig_tracks",
            config={  # type: ignore[arg-type]
                "type": "genomic_tracks",
                "source": "transformed",
                "transform": {"recipe": "nf-core/cutandrun/tracks.py"},
                "dc_specific_properties": {"format": "tsv", "sample_column": "sample"},
            },
        )
        workflow = SimpleNamespace(
            version=None,
            data_collections=[dc],
            data_location=SimpleNamespace(locations=[str(tmp_path)], structure="flat"),
        )

        result = deltatables.client_aggregate_data(
            dc, cli_config, {"overwrite": True}, workflow=workflow
        )

        assert result["result"] == "success", result["message"]
        assert len(written) == 1 and len(upserts) == 1
        assert _uploaded(s3_client) == {PREFIX + "bigwig/s1.bw": str(tmp_path / "bigwig" / "s1.bw")}
