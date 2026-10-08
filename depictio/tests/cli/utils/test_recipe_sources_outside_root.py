"""A recipe source a template variable points outside the data root.

``source_overrides: {samplesheet: {path: "{SAMPLESHEET_FILE}"}}`` (the nf-core
rnaseq, riboseq, differentialabundance and mhcquant templates) makes the source
whatever the variable holds: a path under the root, the auto-detected
``{DATA_ROOT}/input/samplesheet.csv``, or ``--var SAMPLESHEET_FILE=`` an
absolute path or a URL somewhere else. Each must be read where it is: never
re-rooted under the data root, and on a server never read off its own disk
unless the local-data policy allows it.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import polars as pl
import pytest

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.data_root import LocalDataRoot, relative_to_root
from depictio.cli.cli.utils.template_preview import _preview_recipe_dc
from depictio.models.models.transforms import RecipeSource
from depictio.recipes import RecipeError, resolve_sources

from ..s3_stubs import S3_ROOT, s3_data_root


def _module(**source_fields) -> ModuleType:
    module = MagicMock(spec=ModuleType)
    module.SOURCES = [RecipeSource(ref="samplesheet", format="csv", **source_fields)]
    return module


@pytest.fixture()
def run(tmp_path) -> Path:
    """A run folder with its own samplesheet, and another one outside it."""
    root = tmp_path / "run42"
    (root / "input").mkdir(parents=True)
    (root / "input" / "samplesheet.csv").write_text("sample,group\nIN1,a\n")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "sheet.csv").write_text("sample,group\nOUT1,b\n")
    return root


@pytest.fixture()
def cli_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")


@pytest.fixture()
def server_context(monkeypatch):
    """A shared server: local folders off."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


def _samples(sources) -> list[str]:
    return sources["samplesheet"]["sample"].to_list()


# ── relative_to_root ─────────────────────────────────────────────────────────


def test_only_an_absolute_path_or_a_url_can_lie_outside(run):
    root = LocalDataRoot(str(run))
    assert relative_to_root(root, "input/samplesheet.csv") == "input/samplesheet.csv"
    assert relative_to_root(root, str(run / "input" / "samplesheet.csv")) == (
        "input/samplesheet.csv"
    )
    assert relative_to_root(root, str(run.parent / "elsewhere" / "sheet.csv")) is None
    assert relative_to_root(root, "https://data.example.org/sheet.csv") is None
    # Relative to the root by definition, so the root's reads answer for it.
    assert relative_to_root(root, "../elsewhere/sheet.csv") == "../elsewhere/sheet.csv"


# ── under the root ───────────────────────────────────────────────────────────


def test_a_relative_source_is_read_under_the_root(run, cli_context):
    sources = resolve_sources(_module(path="input/samplesheet.csv"), str(run))
    assert _samples(sources) == ["IN1"]


def test_an_absolute_path_under_the_root_is_read_through_it(run, server_context):
    """The auto-detected ``{DATA_ROOT}/input/samplesheet.csv``: it used to be
    re-rooted to ``<root>/<root>/input/samplesheet.csv`` and never found."""
    module = _module(path="input/samplesheet.csv", source_path="file")
    overrides = {"samplesheet": str(run / "input" / "samplesheet.csv")}
    sources = resolve_sources(module, LocalDataRoot(str(run)), overrides)
    assert _samples(sources) == ["IN1"]
    assert sources["samplesheet"]["file"].to_list() == ["input/samplesheet.csv"]


def test_an_s3_url_under_an_s3_root_is_read_through_the_root(monkeypatch, cli_context):
    root = s3_data_root(monkeypatch, {"input/samplesheet.csv": b"sample\nS1\n"})
    reads: list[str] = []

    def scan_csv(location, **_kwargs):
        reads.append(location)
        return pl.DataFrame({"sample": ["S1"]}).lazy()

    monkeypatch.setattr(pl, "scan_csv", scan_csv)
    overrides = {"samplesheet": f"{S3_ROOT}/input/samplesheet.csv"}
    sources = resolve_sources(_module(path="input/samplesheet.csv"), root, overrides)
    assert _samples(sources) == ["S1"]
    assert reads == [f"{S3_ROOT}/input/samplesheet.csv"]


# ── a local path outside the root ────────────────────────────────────────────


def test_the_cli_reads_an_absolute_path_outside_the_root_as_it_is(run, cli_context):
    outside = str(run.parent / "elsewhere" / "sheet.csv")
    module = _module(path="input/samplesheet.csv", source_path="file")
    sources = resolve_sources(module, str(run), {"samplesheet": outside})
    assert _samples(sources) == ["OUT1"]
    # No path relative to the root to give: the full location.
    assert sources["samplesheet"]["file"].to_list() == [outside]


def test_the_cli_passes_none_for_an_absent_optional_source_outside(run, cli_context):
    module = _module(path="input/samplesheet.csv", optional=True)
    gone = str(run.parent / "elsewhere" / "gone.csv")
    assert resolve_sources(module, str(run), {"samplesheet": gone})["samplesheet"] is None


def test_the_cli_names_a_missing_required_source_outside(run, cli_context):
    gone = str(run.parent / "elsewhere" / "gone.csv")
    with pytest.raises(RecipeError, match="file not found") as exc:
        resolve_sources(_module(path="input/samplesheet.csv"), str(run), {"samplesheet": gone})
    assert gone in str(exc.value)


@pytest.mark.parametrize("name", ["sheet.csv", "gone.csv"])
def test_a_server_refuses_a_path_outside_the_root_without_a_policy(run, server_context, name):
    """Refused alike whether the file exists or not: no read, and no oracle."""
    outside = str(run.parent / "elsewhere" / name)
    module = _module(path="input/samplesheet.csv", optional=True)
    with pytest.raises(RecipeError, match="outside the data root") as exc:
        resolve_sources(module, LocalDataRoot(str(run)), {"samplesheet": outside})
    assert "not in a folder this server may read" in str(exc.value)


def test_a_server_reads_a_path_outside_the_root_its_policy_allows(run, monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(run.parent))
    outside = str(run.parent / "elsewhere" / "sheet.csv")
    sources = resolve_sources(
        _module(path="input/samplesheet.csv"), LocalDataRoot(str(run)), {"samplesheet": outside}
    )
    assert _samples(sources) == ["OUT1"]


# ── a URL outside the root ───────────────────────────────────────────────────


@pytest.fixture()
def http_sheet(tmp_path, monkeypatch):
    """A samplesheet served over loopback, which the CLI reads directly."""
    served = tmp_path / "served"
    served.mkdir()
    (served / "sheet.csv").write_text("sample,group\nURL1,c\n")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/sheet.csv"
    server.shutdown()


def test_an_http_url_outside_the_root_is_read_as_it_is(run, cli_context, http_sheet):
    module = _module(path="input/samplesheet.csv", source_path="file")
    sources = resolve_sources(module, str(run), {"samplesheet": http_sheet})
    assert _samples(sources) == ["URL1"]
    assert sources["samplesheet"]["file"].to_list() == [http_sheet]


def test_an_s3_url_outside_the_root_goes_through_the_remote_reader(monkeypatch, run, cli_context):
    """The reader every ``url`` collection uses, handed the URL verbatim and the
    configuration the root was built with, so its read target is the URL's own."""
    config = object()
    seen: list[tuple] = []

    def remote_reader(url, file_format, polars_kwargs, CLI_config=None):
        seen.append((url, file_format, polars_kwargs, CLI_config))
        return pl.DataFrame({"sample": ["S3OUT"]}).lazy()

    monkeypatch.setattr(deltatables, "_read_remote_file_lazy", remote_reader)
    module = _module(path="input/samplesheet.csv", read_kwargs={"infer_schema_length": 10})
    url = "s3://another-bucket/sheets/sheet.tsv"
    sources = resolve_sources(module, LocalDataRoot(str(run), config), {"samplesheet": url})

    assert _samples(sources) == ["S3OUT"]
    # The recipe declared CSV, so the reader may not pick tabs from the name.
    assert seen == [(url, "csv", {"infer_schema_length": 10, "separator": ","}, config)]


# ── the preview counts the same way ──────────────────────────────────────────


def _recipe_dc(path: str) -> dict:
    return {
        "source": "transformed",
        "transform": {
            "recipe": "nf-core/rnaseq/samplesheet.py",
            "source_overrides": {"samplesheet": {"path": path}},
        },
    }


def test_the_preview_finds_an_absolute_path_under_the_root(run, server_context):
    row = _preview_recipe_dc(
        "samplesheet",
        _recipe_dc(str(run / "input" / "samplesheet.csv")),
        LocalDataRoot(str(run)),
        False,
    )
    assert (row.status, row.matched) == ("ok", 1)


def test_the_preview_finds_a_path_outside_the_root_in_the_cli(run, cli_context):
    outside = str(run.parent / "elsewhere" / "sheet.csv")
    row = _preview_recipe_dc("samplesheet", _recipe_dc(outside), LocalDataRoot(str(run)), False)
    assert (row.status, row.matched) == ("ok", 1)


def test_the_preview_reports_a_path_a_server_may_not_read_missing(run, server_context):
    outside = str(run.parent / "elsewhere" / "sheet.csv")
    row = _preview_recipe_dc("samplesheet", _recipe_dc(outside), LocalDataRoot(str(run)), False)
    assert row.status == "missing"
    assert row.missing_sources == [outside]


def test_the_preview_does_not_report_a_url_outside_the_root_missing(run, cli_context):
    url = "https://data.example.org/sheet.csv"
    row = _preview_recipe_dc("samplesheet", _recipe_dc(url), LocalDataRoot(str(run)), False)
    assert (row.status, row.matched, row.missing_sources) == ("ok", 0, [])
