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
from depictio.recipes import RecipeError, resolve_sources, validate_sources

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


# Values YAML would type on its own (booleans, dates, null) next to plain ones.
# Written as CSV, YAML and JSON, the three must read to the very same frame.
TRICKY_CSV = (
    "sample,flag,on_off,date,count,ratio,sci,padded,note\n"
    "s1,yes,on,2024-01-05,1,1.10,1e3,007,NA\n"
    "s2,no,Off,x,2,2.5,2e3,010,\n"
)
TRICKY_YAML = (
    "- {sample: s1, flag: yes, on_off: on, date: 2024-01-05, count: 1, ratio: 1.10,"
    " sci: 1e3, padded: 007, note: NA}\n"
    "- {sample: s2, flag: no, on_off: Off, date: x, count: 2, ratio: 2.5,"
    " sci: 2e3, padded: 010}\n"
)


def test_a_yaml_sheet_reads_exactly_as_the_same_csv():
    """No YAML typing: ``yes`` stays the text yes, a date stays text, as in a CSV."""
    frame = read_record_sheet(TRICKY_YAML.encode(), "sheet.yaml")
    expected = pl.read_csv(TRICKY_CSV.encode())
    assert frame.schema == expected.schema
    assert frame.equals(expected)
    assert frame["flag"].to_list() == ["yes", "no"]
    assert frame["on_off"].to_list() == ["on", "Off"]


def test_a_json_sheet_reads_exactly_as_the_same_csv():
    records = [
        {"sample": "s1", "ok": True, "n": 1, "x": 1.5, "note": None},
        {"sample": "s2", "ok": False, "n": 2, "x": 2.0, "note": "NA"},
    ]
    frame = read_record_sheet(json.dumps(records).encode(), "sheet.json")
    expected = pl.read_csv(b"sample,ok,n,x,note\ns1,true,1,1.5,\ns2,false,2,2.0,NA\n")
    assert frame.schema == expected.schema
    assert frame.equals(expected)


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


SCHEMA = {"sample": pl.Utf8, "fastq_1": pl.Utf8, "strandedness": pl.Utf8}


@pytest.mark.parametrize("name", RECORD_SHEETS)
def test_a_record_sheet_missing_a_key_names_it_a_key(tmp_path, cli_context, name):
    """A YAML/JSON sheet has keys, not columns: the error says so."""
    records = json.loads((FIXTURES / "samplesheet.json").read_text())
    for record in records:
        del record["strandedness"]
    sheet = tmp_path / name
    sheet.write_text(json.dumps(records))  # JSON is valid YAML too
    module = _module(path="input/samplesheet.csv", input_schema=SCHEMA)
    sources = resolve_sources(module, str(tmp_path), {"samplesheet": str(sheet)})
    with pytest.raises(RecipeError) as exc:
        validate_sources(module, sources, "demo")
    message = str(exc.value)
    assert "lacks input key(s) ['strandedness']" in message
    assert "Got keys: ['sample', 'fastq_1', 'fastq_2']" in message
    assert "column" not in message


def test_a_csv_sheet_missing_a_column_still_names_it_a_column(tmp_path, cli_context):
    (tmp_path / "sheet.csv").write_text("sample,fastq_1\ntest,r1.fq.gz\n")
    module = _module(path="sheet.csv", input_schema=SCHEMA)
    sources = resolve_sources(module, str(tmp_path))
    with pytest.raises(RecipeError, match=r"lacks input column\(s\) \['strandedness'\]"):
        validate_sources(module, sources, "demo")


@pytest.mark.parametrize(
    "fields",
    [{"path": "reports/stats.json"}, {"glob_pattern": "reports/*.json"}],
    ids=["path", "glob"],
)
def test_a_recipe_reading_its_own_json_keeps_its_csv_read(tmp_path, cli_context, fields):
    """Recipes (isoseq, crisprseq, pairgenomealign) read their ``.json`` outputs
    one line per row: only a CSV/TSV source *repointed* at a sheet changes."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "stats.json").write_text('{\n  "reads": 3\n}\n')
    module = _module(
        read_kwargs={"separator": "\x1f", "has_header": False, "new_columns": ["raw"]},
        **fields,
    )
    sources = resolve_sources(module, str(tmp_path))
    assert sources["samplesheet"]["raw"].to_list() == ["{", '  "reads": 3', "}"]


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


def test_a_raw_json_collection_with_a_separator_keeps_its_csv_read(tmp_path, cli_context):
    """bcl2fastq ``Stats.json``, simpleaf ``map_info.json``: declared TSV/CSV
    with a separator the file cannot hold, read one line per row as before."""
    report = tmp_path / "Stats.json"
    report.write_text('{\n  "Flowcell": "X"\n}\n')
    kwargs = {"separator": "\x1f", "has_header": False, "new_columns": ["raw"]}
    frame = deltatables._lazy_scan_path(str(report), "tsv", kwargs).collect()
    assert frame["raw"].to_list() == ["{", '  "Flowcell": "X"', "}"]


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
