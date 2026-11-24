"""A column the dashboard colours shows its values as chips in a report table:
in the HTML (DataTables, read as HTML) and in the PDF (typst)."""

import polars as pl

from depictio.notebook import components
from depictio.notebook import typst as _typst

COLOURS = {
    "Kingdom": {"*": "auto", "Bacteria": "#1098ad", "Archaea": "#7048e8"},
    "reads": {"10": "#ff0000"},
    "{GROUP_COL}": "auto",
}


def _df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "Kingdom": ["Bacteria", "Archaea", "Viruses"],
            "name": ["<b>x</b>", "y", "z"],
            "reads": [10, 20, 30],
        }
    )


def test_only_pinned_colours_of_text_columns_count():
    chips = components.chip_columns(_df(), COLOURS)
    assert chips == {"Kingdom": {"Bacteria": "#1098ad", "Archaea": "#7048e8"}}


def test_the_html_table_draws_chips_and_escapes_the_rest(monkeypatch):
    monkeypatch.setitem(components._TABLES, "interactive", True)
    html = components.data_html(_df(), COLOURS)
    assert 'class="dpx-chip" style="--dpx-chip:#1098ad"' in html
    # A value without a colour stays text; other text cells are escaped.
    assert "--dpx-chip:#" not in html.split("Viruses")[0][-40:]
    assert "<b>x</b>" not in html


def test_no_colours_no_html_mode(monkeypatch):
    monkeypatch.setitem(components._TABLES, "interactive", True)
    assert "dpx-chip" not in components.data_html(_df(), None)


def test_the_pdf_table_draws_chips():
    chips = components.chip_columns(_df(), COLOURS)
    src = _typst.table(_df(), chips=chips)
    assert '(chip: "Bacteria", color: "#1098ad")' in src
    assert '"Viruses"' in src and '(chip: "Viruses"' not in src
