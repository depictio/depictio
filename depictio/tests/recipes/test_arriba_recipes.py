"""Arriba recipes: `arriba/fusions.py` (partner contigs) and `arriba/fusion_links.py` (breakpoint pairs).

Both read Arriba's `chr:pos` breakpoint strings. The tests pin the parsing edge cases: the
variant spellings other callers write (a trailing strand field), the bare-dot missing value,
unparsable breakpoints and the evidence sum.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

# Arriba's own column order and spelling. The first is commented out in the
# file, which is why it is `#gene1` rather than `gene1`.
FUSIONS_HEADER = [
    "#gene1",
    "gene2",
    "breakpoint1",
    "breakpoint2",
    "site1",
    "site2",
    "type",
    "split_reads1",
    "split_reads2",
    "discordant_mates",
    "coverage1",
    "coverage2",
    "confidence",
    "reading_frame",
    "tags",
    "retained_protein_domains",
]


def _fusions_row(**over: object) -> list[str]:
    base: dict[str, object] = {
        "#gene1": "FGFR3",
        "gene2": "TACC3",
        "breakpoint1": "chr4:1806934",
        "breakpoint2": "chr4:1727977",
        "site1": "CDS/splice-site",
        "site2": "CDS",
        "type": "duplication",
        "split_reads1": "90",
        "split_reads2": "104",
        "discordant_mates": "300",
        "coverage1": "245",
        "coverage2": "425",
        "confidence": "high",
        "reading_frame": "in-frame",
        "tags": ".",
        "retained_protein_domains": ".",
    }
    base.update(over)
    return [str(base[col]) for col in FUSIONS_HEADER]


def _write_fusions_table(tmp_path: Path, rows: list[list[str]]) -> Path:
    run = tmp_path / "arriba"
    run.mkdir(parents=True, exist_ok=True)
    path = run / "sample_a.arriba.fusions.tsv"
    path.write_text("\t".join(FUSIONS_HEADER) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n")
    return path


def test_both_breakpoints_yield_a_contig_and_a_pair(tmp_path: Path) -> None:
    _write_fusions_table(
        tmp_path, [_fusions_row(breakpoint1="chr8:127736231", breakpoint2="chr14:105586437")]
    )
    out = execute_recipe("arriba/fusions.py", tmp_path)

    row = out.row(0, named=True)
    assert row["chrom_5p"] == "chr8"
    assert row["chrom_3p"] == "chr14"
    # One label, so a translocation and a local rearrangement separate in a
    # filter without the reader having to compare two columns by eye.
    assert row["chrom_pair"] == "chr8 to chr14"
    assert out.schema["chrom_5p"] == pl.Utf8
    assert out.schema["chrom_pair"] == pl.Utf8


def test_a_trailing_strand_field_does_not_reach_the_contig(tmp_path: Path) -> None:
    """Some callers append a strand: `chr4:1806934:+`. Only the contig is taken."""
    _write_fusions_table(
        tmp_path, [_fusions_row(breakpoint1="chr4:1806934:+", breakpoint2="chr7:55019017:-")]
    )
    out = execute_recipe("arriba/fusions.py", tmp_path)

    row = out.row(0, named=True)
    assert row["chrom_5p"] == "chr4"
    assert row["chrom_3p"] == "chr7"
    assert row["chrom_pair"] == "chr4 to chr7"


def test_a_missing_breakpoint_is_named_rather_than_left_blank(tmp_path: Path) -> None:
    """Arriba writes `.` for a missing value, which the source reads as null.

    A blank contig would become a nameless sankey node that the reader cannot
    tell from a rendering fault, so it is labelled instead.
    """
    _write_fusions_table(tmp_path, [_fusions_row(breakpoint1=".")])
    out = execute_recipe("arriba/fusions.py", tmp_path)

    row = out.row(0, named=True)
    assert row["chrom_5p"] == "unknown"
    assert row["chrom_pair"] == "unknown to chr4"


# The columns the recipe reads, in Arriba's own order and spelling (the first is
# commented out, which is why it is `#gene1` and not `gene1`).
LINKS_HEADER = [
    "#gene1",
    "gene2",
    "breakpoint1",
    "breakpoint2",
    "type",
    "split_reads1",
    "split_reads2",
    "discordant_mates",
    "coverage1",
    "coverage2",
    "confidence",
]


def _write_links_table(tmp_path: Path, rows: list[list[str]]) -> Path:
    run = tmp_path / "arriba"
    run.mkdir(parents=True, exist_ok=True)
    path = run / "sample_a.arriba.fusions.tsv"
    path.write_text(
        "\t".join(LINKS_HEADER)
        + "\n"
        + "\n".join("\t".join(str(v) for v in r) for r in rows)
        + "\n"
    )
    return path


def _links_row(**over: object) -> list[str]:
    base = {
        "#gene1": "FGFR3",
        "gene2": "TACC3",
        "breakpoint1": "chr4:1806934",
        "breakpoint2": "chr4:1727977",
        "type": "duplication",
        "split_reads1": "90",
        "split_reads2": "104",
        "discordant_mates": "300",
        "coverage1": "500",
        "coverage2": "400",
        "confidence": "high",
    }
    base.update(over)
    return [str(base[col]) for col in LINKS_HEADER]


def test_breakpoints_become_four_bindable_columns(tmp_path: Path) -> None:
    _write_links_table(tmp_path, [_links_row()])
    out = execute_recipe("arriba/fusion_links.py", tmp_path)

    assert out.height == 1
    row = out.row(0, named=True)
    assert row["chrom_a"] == "chr4"
    assert row["pos_a"] == 1806934
    assert row["chrom_b"] == "chr4"
    assert row["pos_b"] == 1727977
    assert row["label"] == "FGFR3--TACC3"
    # Split reads on both sides plus the discordant mates, which is what a chord
    # width has to be: one number per link.
    assert row["weight"] == 90 + 104 + 300
    assert row["category"] == "duplication"
    assert row["confidence"] == "high"
    assert out.schema["pos_a"] == pl.Int64


def test_a_third_breakpoint_field_does_not_corrupt_the_position(tmp_path: Path) -> None:
    """Some callers append a strand: `chr4:1806934:+`. The position must survive."""
    _write_links_table(
        tmp_path, [_links_row(breakpoint1="chr4:1806934:+", breakpoint2="chr7:55019017:-")]
    )
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.row(0, named=True)["pos_a"] == 1806934
    assert out.row(0, named=True)["pos_b"] == 55019017


def test_an_unparsable_breakpoint_is_dropped_not_placed_at_zero(tmp_path: Path) -> None:
    _write_links_table(
        tmp_path,
        [_links_row(), _links_row(**{"#gene1": "BAD", "breakpoint2": "not-a-locus"})],
    )
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.height == 1
    assert "BAD" not in out["label"].to_list()


def test_missing_read_counts_read_as_zero_rather_than_null(tmp_path: Path) -> None:
    """Arriba writes `.` for a value it has no number for, and a null weight
    would make the chord width undefined."""
    _write_links_table(tmp_path, [_links_row(discordant_mates=".", split_reads2=".")])
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.row(0, named=True)["weight"] == 90
    assert out["weight"].null_count() == 0
