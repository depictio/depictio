"""Tests for `depictio manifest from-table`.

The pivot itself is simple; what matters is that it refuses to emit a manifest
the ingestion layer would reject (local paths), and that auto-detection does not
mistake a label column for a file column.
"""

import json

from typer.testing import CliRunner

from depictio.cli.depictio_cli import app
from depictio.models.models.manifest import DataManifest, ManifestEntry

runner = CliRunner()

SAMPLESHEET = (
    "sample,fastq_1,fastq_2,condition\n"
    "s1,s1_R1.fastq.gz,s1_R2.fastq.gz,control\n"
    "s2,s2_R1.fastq.gz,s2_R2.fastq.gz,treated\n"
    "s3,s3_R1.fastq.gz,,treated\n"
)


def _write(tmp_path, text, name="samplesheet.csv"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_pivots_wide_to_long_and_prefixes_relative_paths(tmp_path):
    table = _write(tmp_path, SAMPLESHEET)
    out = tmp_path / "manifest.json"
    result = runner.invoke(
        app,
        [
            "manifest",
            "from-table",
            str(table),
            "--base-url",
            "s3://my-bucket/run42",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    entries = json.loads(out.read_text())
    # 3 rows x 2 file columns, minus s3's empty fastq_2 cell.
    assert len(entries) == 5
    assert {e["type"] for e in entries} == {"fastq_1", "fastq_2"}
    assert entries[0] == {
        "id": "s1",
        "type": "fastq_1",
        "url": "s3://my-bucket/run42/s1_R1.fastq.gz",
    }


def test_output_validates_against_the_manifest_model(tmp_path):
    table = _write(tmp_path, SAMPLESHEET)
    out = tmp_path / "manifest.json"
    runner.invoke(
        app,
        ["manifest", "from-table", str(table), "--base-url", "s3://b/r", "-o", str(out)],
    )
    manifest = DataManifest(entries=[ManifestEntry(**e) for e in json.loads(out.read_text())])
    assert sorted(manifest.types()) == ["fastq_1", "fastq_2"]
    assert len(manifest.entries_for_type("fastq_1")) == 3
    assert len(manifest.entries_for_type("fastq_2")) == 2


def test_label_columns_are_not_mistaken_for_files(tmp_path):
    """`condition` holds labels, not paths — it must not become a DC type."""
    table = _write(tmp_path, SAMPLESHEET)
    out = tmp_path / "manifest.json"
    result = runner.invoke(
        app,
        ["manifest", "from-table", str(table), "--base-url", "s3://b/r", "-o", str(out)],
    )
    assert "condition" not in {e["type"] for e in json.loads(out.read_text())}
    assert "condition" not in result.output.split("file columns:")[1].split("\n")[0]


def test_local_paths_without_base_url_are_refused(tmp_path):
    """A manifest entry must be a remote URL; emitting local paths would only
    fail later, at ingestion, with a far less obvious message."""
    table = _write(tmp_path, SAMPLESHEET)
    out = tmp_path / "manifest.json"
    result = runner.invoke(app, ["manifest", "from-table", str(table), "-o", str(out)])
    assert result.exit_code == 1
    assert "--base-url" in result.output
    assert not out.exists()


def test_already_remote_urls_are_left_alone(tmp_path):
    table = _write(
        tmp_path,
        "sample,reads\ns1,https://host/s1.csv\ns2,s3://bucket/s2.csv\n",
    )
    out = tmp_path / "manifest.json"
    result = runner.invoke(
        app,
        ["manifest", "from-table", str(table), "--base-url", "s3://ignored", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    urls = [e["url"] for e in json.loads(out.read_text())]
    assert urls == ["https://host/s1.csv", "s3://bucket/s2.csv"]


def test_run_column_becomes_the_manifest_run(tmp_path):
    table = _write(tmp_path, "sample,reads,batch\ns1,a.csv,b1\ns2,b.csv,b2\n")
    out = tmp_path / "manifest.json"
    runner.invoke(
        app,
        [
            "manifest",
            "from-table",
            str(table),
            "--base-url",
            "s3://b/r",
            "--run-col",
            "batch",
            "-o",
            str(out),
        ],
    )
    assert [e["run"] for e in json.loads(out.read_text())] == ["b1", "b2"]


def test_tsv_is_read_with_the_right_delimiter(tmp_path):
    table = _write(tmp_path, "sample\treads\ns1\ta.csv\n", name="sheet.tsv")
    out = tmp_path / "manifest.json"
    result = runner.invoke(
        app,
        ["manifest", "from-table", str(table), "--base-url", "s3://b/r", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text()) == [{"id": "s1", "type": "reads", "url": "s3://b/r/a.csv"}]


def test_explicit_file_cols_must_exist(tmp_path):
    table = _write(tmp_path, SAMPLESHEET)
    result = runner.invoke(
        app,
        [
            "manifest",
            "from-table",
            str(table),
            "--file-cols",
            "nope",
            "--base-url",
            "s3://b/r",
        ],
    )
    assert result.exit_code != 0
    assert "nope" in result.output


def test_csv_output_format(tmp_path):
    table = _write(tmp_path, "sample,reads\ns1,a.csv\n")
    out = tmp_path / "manifest.csv"
    result = runner.invoke(
        app,
        ["manifest", "from-table", str(table), "--base-url", "s3://b/r", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.read_text().splitlines()[0] == "id,type,url,run"
