"""Text tiles' live values, formatted as the viewer's ``format.ts`` prints them."""

from __future__ import annotations

import pytest

from depictio.notebook.text import fill_text, format_number, format_text_value


@pytest.mark.parametrize(
    "value,fmt,expected",
    [
        (879737777, None, "879,737,777"),
        (3641.4, None, "3,641"),
        (907.12, None, "907.1"),
        (12.345, None, "12.35"),
        (0.012345, None, "0.0123"),
        (0.00032, None, "0.00032"),
        (0.41, "percent", "41%"),
        (0.047, "percent", "4.7%"),
        (0.00032, "percent", "0.032%"),
        (0, "percent", "0%"),
        (2.6, "integer", "3"),
        (214_300, "si", "214.3k"),
        (3_700_000, "si", "3.7M"),
        (7.1, "decimals:2", "7.10"),
        (7, "decimals:2", "7"),
    ],
)
def test_numbers_print_as_the_viewer_prints_them(value, fmt, expected):
    assert format_number(value, fmt) == expected


def test_missing_and_text_values():
    assert format_text_value(None) == "\N{EN DASH}"
    assert format_text_value(float("nan")) == "\N{EN DASH}"
    assert format_text_value("Proteobacteria") == "Proteobacteria"


def test_fill_text_replaces_every_placeholder():
    out = fill_text(
        "**{{share}}** of reads are {{top}} (run {{param:input}}), {{missing}} {{legend:x}}",
        {"share": 0.41, "top": "Bacteria", "param:input": "samplesheet.tsv"},
        formats={"share": "percent"},
        legends={"legend:x": "<span>key</span>"},
    )
    assert (
        out == "**41%** of reads are Bacteria (run samplesheet.tsv), \N{EN DASH} <span>key</span>"
    )
