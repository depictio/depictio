"""`arriba/fusions.py`: the partner contigs split out of Arriba's breakpoints.

The call table gained `chrom_5p`, `chrom_3p` and `chrom_pair` so the same rows
can be read as a flow from the contig carrying the 5' partner to the contig
carrying the 3' partner. That is the only parsing in the recipe, and it is what
the `partner_chrom_sankey` render binds, so it is pinned here: the split itself,
the variant breakpoint spellings other callers write, and the missing-value case
Arriba writes as a bare dot.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.components.advanced_viz.configs import SankeyConfig
from depictio.recipes import execute_recipe

# Arriba's own column order and spelling. The first is commented out in the
# file, which is why it is `#gene1` rather than `gene1`.
HEADER = [
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


def _row(**over: object) -> list[str]:
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
    return [str(base[col]) for col in HEADER]


def _write_fusions(tmp_path: Path, rows: list[list[str]]) -> Path:
    run = tmp_path / "arriba"
    run.mkdir(parents=True, exist_ok=True)
    path = run / "sample_a.arriba.fusions.tsv"
    path.write_text("\t".join(HEADER) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n")
    return path


def test_both_breakpoints_yield_a_contig_and_a_pair(tmp_path: Path) -> None:
    _write_fusions(tmp_path, [_row(breakpoint1="chr8:127736231", breakpoint2="chr14:105586437")])
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
    _write_fusions(tmp_path, [_row(breakpoint1="chr4:1806934:+", breakpoint2="chr7:55019017:-")])
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
    _write_fusions(tmp_path, [_row(breakpoint1=".")])
    out = execute_recipe("arriba/fusions.py", tmp_path)

    row = out.row(0, named=True)
    assert row["chrom_5p"] == "unknown"
    assert row["chrom_pair"] == "unknown to chr4"


def test_the_contigs_bind_the_sankey_the_catalog_declares(tmp_path: Path) -> None:
    _write_fusions(tmp_path, [_row(), _row(breakpoint1="chr8:127736231", gene2="MYC")])
    out = execute_recipe("arriba/fusions.py", tmp_path)

    config = SankeyConfig(step_cols=["chrom_5p", "chrom_3p"], value_col="supporting_reads")
    assert config.step_cols == ["chrom_5p", "chrom_3p"]
    assert set(config.step_cols) <= set(out.columns)
    assert out["supporting_reads"].dtype == pl.Int64
