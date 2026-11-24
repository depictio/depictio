"""MultiQC's General Statistics in a report reads as on the dashboard: one row
per sample (the mean of its reads), values with their units, each over the
data bar the server drew for it, in the HTML and in the PDF."""

import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

from depictio.api.v1.services.notebook_export.render import quarto_binary
from depictio.notebook import components
from depictio.notebook import typst as _typst

ASSETS = Path(components.__file__).parents[1] / "api/v1/services/notebook_export/assets"


def _bar(col: str, lo: float, hi: float | None, colour: str, share: float) -> dict:
    query = f"{{{col}}} >= {lo}" + (f" && {{{col}}} < {hi}" if hi is not None else "")
    return {
        "if": {"filter_query": query, "column_id": col},
        "backgroundImage": (
            f"linear-gradient(90deg, {colour} 0%, {colour} {share}%, transparent {share}%, "
            "transparent 100%)"
        ),
    }


MODE = {
    "table_columns": [
        {"id": "Sample Name", "type": "text", "format": None},
        {
            "id": "Seqs (M)",
            "type": "numeric",
            "format": {"precision": 2, "suffix": " M", "group": True},
        },
        {
            "id": "Avg len (bp)",
            "type": "numeric",
            "format": {"precision": 0, "suffix": " bp", "group": True},
        },
    ],
    "table_styles": [
        _bar("Seqs (M)", 0.0, 0.1, "#9ecae1", 40.0),
        _bar("Seqs (M)", 0.1, None, "#3182bd", 90.0),
        {
            "if": {"filter_query": "{Avg len \\(bp\\)} >= 0", "column_id": "Avg len (bp)"},
            "backgroundColor": "#fff",
        },
    ],
    "table_data": [
        {"Sample Name": "S1", "Seqs (M)": 0.0993, "Avg len (bp)": 244.9},
        {"Sample Name": "S2", "Seqs (M)": 0.1322, "Avg len (bp)": 1243.2},
    ],
}
PAYLOAD = {"is_paired_end": True, "modes": {"all": {"table_data": []}, "mean": MODE}}


def test_the_report_opens_on_the_mean_as_the_dashboard_does():
    assert components.MultiQCGeneralStatsComponent._mode(PAYLOAD) is MODE


def test_values_carry_the_columns_units():
    fmt = MODE["table_columns"][2]["format"]
    assert components.gs_format(1243.2, fmt) == "1,243 bp"
    assert components.gs_format(0.0993, MODE["table_columns"][1]["format"]) == "0.10 M"
    assert components.gs_format(None, fmt) == ""


def test_each_value_finds_its_bin_and_a_style_that_is_no_bar_is_skipped():
    bars = components.gs_bars(MODE["table_styles"])
    assert set(bars) == {"Seqs (M)"}
    assert components.gs_bar_for(bars["Seqs (M)"], 0.05) == ("#9ecae1", 40.0)
    assert components.gs_bar_for(bars["Seqs (M)"], 0.13) == ("#3182bd", 90.0)
    assert components.gs_bar_for(bars["Seqs (M)"], None) is None


def _component() -> components.MultiQCGeneralStatsComponent:
    comp = components.MultiQCGeneralStatsComponent.__new__(components.MultiQCGeneralStatsComponent)
    comp._gs_mode = MODE
    return comp


def test_the_html_table_draws_units_and_bars():
    html = _component()._gs_html(pl.DataFrame(MODE["table_data"]))
    assert "<td>1,243 bp</td>" in html
    assert "linear-gradient(90deg,#3182bd 0%,#3182bd 90%,transparent 90%)" in html
    assert '<td class="dpx-gs-name">S1</td>' in html


def test_the_pdf_table_draws_units_and_bars():
    comp = _component()
    df = pl.DataFrame(MODE["table_data"])
    formats, bars = comp._gs_cells(df)
    src = _typst.table(
        df,
        text={c: (lambda v, f=f: components.gs_format(v, f)) for c, f in formats.items()},
        bars={c: (lambda v, b=b: components.gs_bar_for(b, v)) for c, b in bars.items()},
    )
    assert '(bar: 0.9000, color: "#3182bd", text: "0.13 M")' in src
    assert '"1,243 bp"' in src


def test_the_bar_table_compiles(tmp_path):
    quarto = quarto_binary()
    if not quarto or not shutil.which(quarto) and not Path(quarto).exists():
        pytest.skip("Quarto is not installed")
    df = pl.DataFrame(MODE["table_data"])
    comp = _component()
    formats, bars = comp._gs_cells(df)
    src = _typst.table(
        df,
        text={c: (lambda v, f=f: components.gs_format(v, f)) for c, f in formats.items()},
        bars={c: (lambda v, b=b: components.gs_bar_for(b, v)) for c, b in bars.items()},
    )
    body = src.split("````{=typst}", 1)[1].rsplit("````", 1)[0]
    doc = tmp_path / "t.typ"
    doc.write_text(
        "#let dpx-muted = luma(130)\n#let dpx-ink = luma(20)\n#let dpx-hair = luma(220)\n"
        + (ASSETS / "definitions.typ").read_text()
        + "\n"
        + body
    )
    run = subprocess.run(
        [quarto, "typst", "compile", str(doc), str(tmp_path / "t.pdf")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr[-800:]
