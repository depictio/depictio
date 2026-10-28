"""YAML and JSON samplesheets: a list of records with the columns a CSV/TSV sheet has.

The fixtures are the two sheets of issue #1280, and ``SAMPLESHEET_CSV`` the CSV
they stand for. A YAML or JSON sheet must read to the very frame the CSV does,
wherever a CSV samplesheet is read: a recipe source (under the root, outside it, over HTTP, on
S3), a plain ``Table`` collection, the ``input/`` auto-detection, and
``depictio manifest from-table``.
"""

from __future__ import annotations

import http.server
import json
import shutil
import threading
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import polars as pl
import pytest
from typer.testing import CliRunner

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.record_sheets import (
    RecordSheetError,
    is_record_sheet,
    read_record_sheet,
)
from depictio.cli.cli.utils.templates import _pick_input_samplesheet
from depictio.cli.depictio_cli import app
from depictio.models.models.transforms import RecipeSource
from depictio.recipes import RecipeError, resolve_sources

from ..s3_stubs import S3_ROOT, install_s3_listing, s3_cli_config, s3_data_root

FIXTURES = Path(__file__).parent.parent / "fixtures" / "samplesheets"
RECORD_SHEETS = ["samplesheet.yaml", "samplesheet.json"]
READS = "https://github.com/nf-core/test-datasets/raw/rnafusion/testdata/human"
# The CSV both fixtures stand for (inline: the repository ignores ``*.csv``).
SAMPLESHEET_CSV = (
    "sample,fastq_1,fastq_2,strandedness\n"
    f"test,{READS}/reads_1.fq.gz,{READS}/reads_2.fq.gz,forward\n"
)


def _csv_frame() -> pl.DataFrame:
    return pl.read_csv(SAMPLESHEET_CSV.encode())


def _module(fmt: str = "csv", **source_fields) -> ModuleType:
    module = MagicMock(spec=ModuleType)
    module.SOURCES = [RecipeSource(ref="samplesheet", format=fmt, **source_fields)]
    return module


@pytest.fixture()
def cli_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")


@pytest.fixture()
def run(tmp_path) -> Path:
    """A run folder holding the issue's sheets under ``input/``."""
    (tmp_path / "input").mkdir()
    for name in RECORD_SHEETS:
        shutil.copy(FIXTURES / name, tmp_path / "input" / name)
    return tmp_path


# ── the reader itself ────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_record_sheet_reads_to_the_frame_its_csv_reads_to(name):
    frame = read_record_sheet((FIXTURES / name).read_bytes(), name)
    assert frame.columns == ["sample", "fastq_1", "fastq_2", "strandedness"]
    assert frame.to_dicts() == _csv_frame().to_dicts()
    assert frame.to_dicts()[0]["fastq_1"] == f"{READS}/reads_1.fq.gz"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("sheet.yaml", True),
        ("sheet.YML", True),
        ("/data/sheet.json", True),
        ("s3://bucket/run/input/sheet.json", True),
        ("https://host/sheet.yaml?raw=1", True),
        ("sheet.csv", False),
        ("sheet.tsv", False),
        ("yaml", False),
    ],
)
def test_a_record_sheet_is_told_by_its_extension(location, expected):
    assert is_record_sheet(location) is expected


def test_records_with_missing_keys_take_the_union_of_columns():
    text = "- {sample: a, fastq_1: a.fq}\n- {sample: b, strandedness: reverse}\n"
    frame = read_record_sheet(text.encode(), "sheet.yaml")
    assert frame.columns == ["sample", "fastq_1", "strandedness"]
    assert frame.to_dicts() == [
        {"sample": "a", "fastq_1": "a.fq", "strandedness": None},
        {"sample": "b", "fastq_1": None, "strandedness": "reverse"},
    ]


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("sheet.yaml", "sample: test\n", "a list of records"),
        ("sheet.json", '{"sample": "test"}', "a list of records"),
        ("sheet.yaml", "- test\n", "record 1 is not a mapping"),
        ("sheet.json", '[{"sample": "a", "reads": ["r1", "r2"]}]', "'reads' of record 1"),
        ("sheet.json", "[{", "not valid JSON"),
        ("sheet.yaml", "- sample: [unclosed\n", "not valid YAML"),
    ],
)
def test_a_sheet_that_is_not_a_list_of_flat_records_is_refused(name, body, message):
    with pytest.raises(RecordSheetError, match=message) as exc:
        read_record_sheet(body.encode(), name)
    assert name in str(exc.value)


# ── recipe sources ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", RECORD_SHEETS)
@pytest.mark.parametrize("fmt", ["csv", "tsv"])
def test_a_recipe_reads_a_record_sheet_under_the_root(run, cli_context, name, fmt):
    """``--var SAMPLESHEET_FILE=input/samplesheet.yaml`` on a recipe declaring CSV/TSV."""
    sources = resolve_sources(
        _module(fmt, path="input/samplesheet.csv", source_path="file"),
        str(run),
        {"samplesheet": f"input/{name}"},
    )
    frame = sources["samplesheet"]
    assert frame.drop("file").to_dicts() == _csv_frame().to_dicts()
    assert frame["file"].to_list() == [f"input/{name}"]


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_recipe_reads_a_record_sheet_outside_the_root(tmp_path, cli_context, name):
    root = tmp_path / "run"
    root.mkdir()
    sources = resolve_sources(
        _module(path="input/samplesheet.csv"), str(root), {"samplesheet": str(FIXTURES / name)}
    )
    assert sources["samplesheet"].to_dicts() == _csv_frame().to_dicts()


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_recipe_reads_a_record_sheet_on_an_s3_root(monkeypatch, cli_context, name):
    root = s3_data_root(monkeypatch, {f"input/{name}": (FIXTURES / name).read_bytes()})
    sources = resolve_sources(
        _module(path="input/samplesheet.csv"), root, {"samplesheet": f"{S3_ROOT}/input/{name}"}
    )
    assert sources["samplesheet"].to_dicts() == _csv_frame().to_dicts()


def test_a_recipe_refuses_a_malformed_record_sheet(run, cli_context):
    (run / "input" / "bad.yaml").write_text("sample: test\n")
    with pytest.raises(RecipeError, match="a list of records"):
        resolve_sources(
            _module(path="input/samplesheet.csv"), str(run), {"samplesheet": "input/bad.yaml"}
        )


@pytest.fixture()
def http_sheets(monkeypatch):
    """The fixtures served over loopback, which the CLI reads directly."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FIXTURES), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_recipe_reads_a_record_sheet_over_http(tmp_path, cli_context, http_sheets, name):
    sources = resolve_sources(
        _module(path="input/samplesheet.csv"),
        str(tmp_path),
        {"samplesheet": f"{http_sheets}/{name}"},
    )
    assert sources["samplesheet"].to_dicts() == _csv_frame().to_dicts()


# ── plain Table collections ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", RECORD_SHEETS)
@pytest.mark.parametrize("fmt", ["csv", "tsv"])
def test_a_table_collection_declared_csv_reads_a_record_sheet(cli_context, name, fmt):
    """rnafusion's ``samplesheet`` collection, repointed by ``SAMPLESHEET_FILE``."""
    frame = deltatables._lazy_scan_path(str(FIXTURES / name), fmt, {}).collect()
    assert frame.to_dicts() == _csv_frame().to_dicts()


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_remote_s3_record_sheet_is_read_whole(monkeypatch, cli_context, name):
    client = install_s3_listing(monkeypatch, {f"run/{name}": (FIXTURES / name).read_bytes()})
    url = f"s3://lab-bucket/run/{name}"
    frame = deltatables._read_remote_file_lazy(url, "csv", {}, s3_cli_config()).collect()
    assert frame.to_dicts() == _csv_frame().to_dicts()
    assert client.get_object_calls == [f"run/{name}"]


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_remote_http_record_sheet_is_read(cli_context, http_sheets, name):
    frame = deltatables._read_remote_file_lazy(f"{http_sheets}/{name}", "csv", {}).collect()
    assert frame.to_dicts() == _csv_frame().to_dicts()


# ── input/ auto-detection ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_record_samplesheet_is_auto_detected(tmp_path, name):
    (tmp_path / "input").mkdir()
    shutil.copy(FIXTURES / name, tmp_path / "input" / name)
    root = LocalDataRoot(str(tmp_path))
    assert _pick_input_samplesheet(root) == str(tmp_path / "input" / name)


def test_a_csv_samplesheet_still_wins_over_a_record_one(tmp_path):
    """Detection of a run that ships a CSV sheet does not move: CSV/TSV first."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(SAMPLESHEET_CSV)
    for name in RECORD_SHEETS:
        shutil.copy(FIXTURES / name, tmp_path / "input" / name)
    # A record sheet that sorts first must not take the CSV's place.
    shutil.copy(FIXTURES / "samplesheet.json", tmp_path / "input" / "a_samplesheet.json")
    root = LocalDataRoot(str(tmp_path))
    assert _pick_input_samplesheet(root) == str(tmp_path / "input" / "samplesheet.csv")


# ── depictio manifest from-table ─────────────────────────────────────────────


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_manifest_from_table_pivots_a_record_sheet(tmp_path, name):
    out = tmp_path / "manifest.json"
    result = CliRunner().invoke(
        app, ["manifest", "from-table", str(FIXTURES / name), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text()) == [
        {"id": "test", "type": "fastq_1", "url": f"{READS}/reads_1.fq.gz"},
        {"id": "test", "type": "fastq_2", "url": f"{READS}/reads_2.fq.gz"},
    ]
