"""POST /projects/run_file_preview: the start of one file of a run folder.

The run folder is opened as ``POST /projects/from_run`` opens it, with the same
refusals; the file has to lie below it. A table shows its first rows, a text
its first lines, anything else why it is not shown. Every read is bounded.

No network: S3 is the shared stub (``depictio/tests/cli/s3_stubs.py``).
"""

import gzip
import json
import os

import polars as pl
import pytest
from bson import ObjectId
from starlette.requests import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.projects_endpoints import routes, run_file_preview
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.endpoints.projects_endpoints.run_file_preview import (
    RunFilePreviewRequest,
)
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    install_s3_listing,
    write_tree,
)

CSV = b"sample,reads,group\nS1,100,a\nS2,200,b\nS3,300,a\n"
TSV = b"sample\treads\nS1\t100\nS2\t200\n"
MQC = b"# id: 'custom_table'\n# plot_type: 'table'\nSample;Reads;Ratio\nS1;100;0.5\nS2;200;0.25\n"
FEATURE_TABLE = b"# Constructed from biom file\n#OTU ID\tS1\tS2\nASV_1\t3\t0\nASV_2\t1\t7\n"
YAML = b"Workflow:\n  nf-core/ampliseq: v2.16.0\n  Nextflow: 25.10.0\n"


def _user(is_admin: bool = True) -> UserBase:
    return UserBase(id=ObjectId(), email="me@example.com", is_admin=is_admin)


def _request(host: str = "localhost:8058") -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"host", host.encode())]}
    )


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, no bucket listed, local folders off, unless a test says otherwise."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    for name in (
        "DEPICTIO_LOCAL_DATA_ROOTS",
        "DEPICTIO_AUTH_SINGLE_USER_MODE",
        "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS",
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def run(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, a run folder at ``home/run42``."""
    home = tmp_path / "home"
    (home / "depictio-local").mkdir(parents=True)
    write_tree(
        home / "run42",
        {
            "input/samplesheet.csv": CSV,
            "input/metadata.tsv": TSV,
            "multiqc/custom_mqc.txt": MQC,
            "qiime2/feature-table.txt": FEATURE_TABLE,
            "qiime2/abundance.tsv.gz": gzip.compress(TSV),
            "pipeline_info/versions.yml": YAML,
            "pipeline_info/notes.txt": b"one line of notes\nand another\n",
            "pipeline_info/execution_report.html": b"<html>" + b"x" * 5000 + b"</html>",
            "pipeline_info/blob.bin": b"\x00\x01\x02\x03",
        },
    )
    write_tree(tmp_path / "outside", {"stolen.csv": CSV})
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home / "depictio-local"))
    return home / "run42"


def _preview(run, rel: str, *, data_root=None, user=None, request=None, **fields):
    payload = RunFilePreviewRequest(
        data_root=str(data_root or run),
        location=rel if rel.startswith(("/", "s3://")) else str(run / rel),
        **fields,
    )
    return run_file_preview.preview_run_file(
        payload, request=request or _request(), current_user=user or _user()
    )


def _refusal(run, rel: str, **kwargs) -> CodedHTTPException:
    with pytest.raises(CodedHTTPException) as exc:
        _preview(run, rel, **kwargs)
    return exc.value


# ── tables ───────────────────────────────────────────────────────────────────


def test_a_csv_is_a_table_of_text_cells(run):
    preview = _preview(run, "input/samplesheet.csv")
    assert (preview.format, preview.name, preview.size) == ("table", "samplesheet.csv", len(CSV))
    assert preview.location == os.path.join(os.path.realpath(run), "input/samplesheet.csv")
    assert preview.columns == ["sample", "reads", "group"]
    assert preview.rows == [["S1", "100", "a"], ["S2", "200", "b"], ["S3", "300", "a"]]
    assert (preview.columns_total, preview.rows_total, preview.truncated) == (3, 3, False)


def test_only_the_rows_asked_for_are_shown_and_all_are_counted(run):
    preview = _preview(run, "input/samplesheet.csv", max_rows=1)
    assert preview.rows == [["S1", "100", "a"]]
    assert (preview.rows_total, preview.truncated) == (3, True)


def test_a_tsv_is_split_on_tabs(run):
    preview = _preview(run, "input/metadata.tsv")
    assert (preview.format, preview.columns) == ("table", ["sample", "reads"])
    assert preview.rows == [["S1", "100"], ["S2", "200"]]


def test_a_plain_text_table_has_its_separator_sniffed_past_its_comments(run):
    preview = _preview(run, "multiqc/custom_mqc.txt")
    assert (preview.format, preview.columns) == ("table", ["Sample", "Reads", "Ratio"])
    assert preview.rows == [["S1", "100", "0.5"], ["S2", "200", "0.25"]]


def test_a_commented_header_as_wide_as_the_data_is_the_header(run):
    preview = _preview(run, "qiime2/feature-table.txt")
    assert (preview.format, preview.columns) == ("table", ["#OTU ID", "S1", "S2"])
    assert preview.rows == [["ASV_1", "3", "0"], ["ASV_2", "1", "7"]]


def test_a_plain_text_of_one_column_is_a_text(run):
    preview = _preview(run, "pipeline_info/notes.txt")
    assert (preview.format, preview.text) == ("text", "one line of notes\nand another\n")


def test_a_gzipped_tsv_is_decompressed_and_read_as_its_inner_suffix(run):
    preview = _preview(run, "qiime2/abundance.tsv.gz")
    assert (preview.format, preview.columns) == ("table", ["sample", "reads"])
    assert preview.rows_total == 2
    assert preview.size == len(gzip.compress(TSV))


def test_a_table_past_the_head_shows_its_start_whole_lines_only(run):
    rows = "".join(f"S{index},{index * 10}\n" for index in range(20_000))
    (run / "input" / "big.csv").write_text(f"sample,reads\n{rows}")
    preview = _preview(run, "input/big.csv", max_rows=50)
    assert preview.format == "table"
    assert len(preview.rows) == 50
    # Not read whole: no row count, and said to be cut.
    assert (preview.rows_total, preview.truncated) == (None, True)
    assert preview.size == (run / "input" / "big.csv").stat().st_size


def test_wide_tables_show_their_first_columns_and_long_cells_are_cut(run):
    header = ",".join(f"c{index}" for index in range(40))
    cells = ",".join(["y" * 300] + ["1"] * 39)
    (run / "input" / "wide.csv").write_text(f"{header}\n{cells}\n")
    preview = _preview(run, "input/wide.csv")
    assert len(preview.columns) == run_file_preview.MAX_PREVIEW_COLUMNS
    assert preview.columns_total == 40
    assert preview.rows[0][0] == "y" * run_file_preview.MAX_CELL_CHARS + "..."
    assert preview.truncated is True


def test_a_parquet_file_shows_its_first_rows_and_counts_them_all(run):
    frame = pl.DataFrame({f"c{index}": list(range(100)) for index in range(35)})
    frame.write_parquet(run / "multiqc" / "multiqc.parquet")

    preview = _preview(run, "multiqc/multiqc.parquet", max_rows=5)

    assert preview.format == "table"
    assert preview.columns == [f"c{index}" for index in range(30)]
    assert preview.rows[1][:3] == ["1", "1", "1"]
    assert len(preview.rows) == 5
    assert (preview.columns_total, preview.rows_total, preview.truncated) == (35, 100, True)


def test_a_parquet_file_that_is_not_one_says_so(run):
    (run / "multiqc" / "broken.parquet").write_bytes(b"PAR1 not really")
    preview = _preview(run, "multiqc/broken.parquet")
    assert (preview.format, preview.reason) == ("none", "This parquet file could not be read.")


def test_a_parquet_file_past_the_cap_is_not_opened(run, monkeypatch):
    pl.DataFrame({"a": [1, 2]}).write_parquet(run / "multiqc" / "multiqc.parquet")
    monkeypatch.setattr(run_file_preview, "MAX_PARQUET_BYTES", 10)
    monkeypatch.setattr(
        pl, "scan_parquet", lambda *_a, **_k: pytest.fail("a parquet over the cap was opened")
    )
    preview = _preview(run, "multiqc/multiqc.parquet")
    assert preview.format == "none" and "larger than" in preview.reason


# ── text and what is not shown ───────────────────────────────────────────────


def test_a_yaml_file_is_a_text(run):
    preview = _preview(run, "pipeline_info/versions.yml")
    assert (preview.format, preview.text, preview.truncated) == ("text", YAML.decode(), False)


def test_a_long_text_shows_its_first_lines(run):
    (run / "pipeline_info" / "run.log").write_text("".join(f"line {i}\n" for i in range(500)))
    preview = _preview(run, "pipeline_info/run.log")
    assert preview.format == "text"
    assert preview.text.splitlines() == [
        f"line {i}" for i in range(run_file_preview.MAX_TEXT_LINES)
    ]
    assert preview.truncated is True


def test_an_html_report_is_not_shown_and_says_why(run):
    preview = _preview(run, "pipeline_info/execution_report.html")
    assert (preview.format, preview.reason) == ("none", "An HTML report, open it in a browser.")
    assert preview.size == len(b"<html>" + b"x" * 5000 + b"</html>")
    assert (preview.text, preview.rows) == (None, [])


def test_a_binary_file_of_unknown_kind_is_not_shown(run):
    preview = _preview(run, "pipeline_info/blob.bin")
    assert (preview.format, preview.reason) == ("none", run_file_preview.BINARY)


def test_a_gzipped_file_of_a_binary_kind_is_not_decompressed(run):
    (run / "pipeline_info" / "report.html.gz").write_bytes(gzip.compress(b"<html></html>"))
    preview = _preview(run, "pipeline_info/report.html.gz")
    assert (preview.format, preview.reason) == ("none", "An HTML report, open it in a browser.")


def test_a_gz_file_that_is_not_gzip_says_so(run):
    (run / "input" / "fake.tsv.gz").write_bytes(b"not gzip at all")
    preview = _preview(run, "input/fake.tsv.gz")
    assert (preview.format, preview.reason) == ("none", "This file could not be decompressed.")


# ── refusals ─────────────────────────────────────────────────────────────────


def test_a_location_outside_the_run_folder_is_refused(run):
    refused = _refusal(run, str(run.parent.parent / "outside" / "stolen.csv"))
    assert (refused.status_code, refused.code) == (422, "location_outside_run")
    refused = _refusal(run, "s3://bucket/run42/input/samplesheet.csv")
    assert (refused.status_code, refused.code) == (422, "location_outside_run")


def test_a_link_out_of_the_run_folder_is_outside_it(run):
    (run / "input" / "escape.csv").symlink_to(run.parent.parent / "outside" / "stolen.csv")
    refused = _refusal(run, "input/escape.csv")
    assert refused.code == "location_outside_run"


def test_a_file_that_is_not_there_is_a_404(run):
    refused = _refusal(run, "input/nope.csv")
    assert (refused.status_code, refused.code) == (404, "run_file_missing")
    refused = _refusal(run, "input")
    assert refused.code == "run_file_missing"


def test_a_hidden_file_of_the_run_folder_is_refused_by_the_policy(run):
    write_tree(run, {".secrets/token.csv": CSV})
    refused = _refusal(run, ".secrets/token.csv")
    assert (refused.status_code, refused.code) == (422, "local_path_outside")


def test_a_run_folder_off_the_policy_is_refused_as_from_run_refuses_it(run):
    outside = run.parent.parent / "outside"
    refused = _refusal(run, str(outside / "stolen.csv"), data_root=outside)
    assert (refused.status_code, refused.code) == (422, "local_path_outside")


def test_local_folders_off_refuse_a_local_run_folder(run, monkeypatch):
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS")
    refused = _refusal(run, "input/samplesheet.csv")
    assert (refused.status_code, refused.code) == (422, "local_folders_off")


def test_a_local_read_is_for_an_administrator_on_this_machine(run):
    assert _refusal(run, "input/samplesheet.csv", user=_user(is_admin=False)).code == (
        "local_admin_only"
    )
    refused = _refusal(run, "input/samplesheet.csv", request=_request("evil.example:8058"))
    assert (refused.status_code, refused.code) == (403, "non_loopback_host")


# ── an s3:// run folder ──────────────────────────────────────────────────────


def test_an_s3_file_is_read_with_one_ranged_request(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)
    monkeypatch.setattr(settings.s3, "bucket", "instance-data")
    client = install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)

    preview = run_file_preview.preview_run_file(
        RunFilePreviewRequest(data_root=S3_ROOT, location=f"{S3_ROOT}/input/Metadata_full.tsv"),
        request=_request(),
        current_user=_user(is_admin=False),
    )

    assert (preview.format, preview.columns) == ("table", ["sample", "habitat", "treatment"])
    assert preview.rows == [["S1", "soil", "control"]]
    assert client.get_object_calls == [f"{S3_KEY_PREFIX}input/Metadata_full.tsv"]
    assert client.get_object_ranges == [f"bytes=0-{run_file_preview.MAX_HEAD_BYTES - 1}"]


def test_an_unlisted_bucket_is_refused_as_from_run_refuses_it(monkeypatch):
    from depictio.models.s3_access import S3AccessRefused

    with pytest.raises(S3AccessRefused):
        run_file_preview.preview_run_file(
            RunFilePreviewRequest(data_root=S3_ROOT, location=f"{S3_ROOT}/input/samplesheet.csv"),
            request=_request(),
            current_user=_user(),
        )


# ── the route ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_route_answers_a_refusal_with_detail_and_code(run):
    payload = RunFilePreviewRequest(data_root=str(run), location="/etc/hosts")
    response = await routes.post_run_file_preview(payload, _request(), current_user=_user())
    assert response.status_code == 422
    assert json.loads(response.body)["code"] == "location_outside_run"


@pytest.mark.asyncio
async def test_the_route_is_closed_to_non_admins_in_public_mode(run, monkeypatch):
    """The gate of POST /projects/from_run: the preview is a step of creating a project."""
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    public = MagicMock()
    public.auth.is_public_mode = True
    monkeypatch.setattr(routes, "settings", public)
    monkeypatch.setattr(
        routes, "preview_run_file", lambda *_a, **_k: pytest.fail("the file was read")
    )
    payload = RunFilePreviewRequest(data_root=str(run), location=str(run / "input/metadata.tsv"))
    with pytest.raises(HTTPException) as exc:
        await routes.post_run_file_preview(payload, _request(), current_user=_user(is_admin=False))
    assert exc.value.status_code == 403
    assert "public/demo mode" in str(exc.value.detail)
