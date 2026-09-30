"""`arriba/fusion_links.py`: Arriba's fusion calls as plottable breakpoint pairs.

The recipe exists for one reason: Arriba writes each breakpoint as a single
``chr:pos`` string, which no coordinate-bound viz can read. These tests pin the
split (including the variant forms other callers write), the evidence sum, and
the fact that an unparsable breakpoint is dropped rather than placed at the start
of a chromosome.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.components.advanced_viz.configs import GenomeChordConfig
from depictio.models.components.advanced_viz.schemas import validate_binding
from depictio.recipes import execute_recipe

# The columns the recipe reads, in Arriba's own order and spelling (the first is
# commented out, which is why it is `#gene1` and not `gene1`).
HEADER = [
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


def _write_fusions(tmp_path: Path, rows: list[list[str]]) -> Path:
    run = tmp_path / "arriba"
    run.mkdir(parents=True, exist_ok=True)
    path = run / "sample_a.arriba.fusions.tsv"
    path.write_text(
        "\t".join(HEADER) + "\n" + "\n".join("\t".join(str(v) for v in r) for r in rows) + "\n"
    )
    return path


def _row(**over: object) -> list[str]:
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
    return [str(base[col]) for col in HEADER]


def _polars_schema_name(df: pl.DataFrame) -> dict[str, str]:
    return {name: str(dtype) for name, dtype in df.schema.items()}


def test_breakpoints_become_four_bindable_columns(tmp_path: Path) -> None:
    _write_fusions(tmp_path, [_row()])
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
    _write_fusions(tmp_path, [_row(breakpoint1="chr4:1806934:+", breakpoint2="chr7:55019017:-")])
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.row(0, named=True)["pos_a"] == 1806934
    assert out.row(0, named=True)["pos_b"] == 55019017


def test_an_unparsable_breakpoint_is_dropped_not_placed_at_zero(tmp_path: Path) -> None:
    _write_fusions(
        tmp_path,
        [_row(), _row(**{"#gene1": "BAD", "breakpoint2": "not-a-locus"})],
    )
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.height == 1
    assert "BAD" not in out["label"].to_list()


def test_missing_read_counts_read_as_zero_rather_than_null(tmp_path: Path) -> None:
    """Arriba writes `.` for a value it has no number for, and a null weight
    would make the chord width undefined."""
    _write_fusions(tmp_path, [_row(discordant_mates=".", split_reads2=".")])
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    assert out.row(0, named=True)["weight"] == 90
    assert out["weight"].null_count() == 0


def test_the_output_binds_to_genome_chord(tmp_path: Path) -> None:
    _write_fusions(
        tmp_path,
        [
            _row(),
            _row(
                **{
                    "#gene1": "HOOK3",
                    "gene2": "RET",
                    "breakpoint1": "chr8:42968214",
                    "breakpoint2": "chr10:43116584",
                    "type": "translocation",
                }
            ),
        ],
    )
    out = execute_recipe("arriba/fusion_links.py", tmp_path)
    config = GenomeChordConfig(label_col="label", weight_col="weight", category_col="category")
    assert validate_binding(config, _polars_schema_name(out)) == []
    # A translocation and an intra-chromosomal event in one frame: the renderer's
    # `intra_chromosomal` toggle has something to remove.
    assert set(out["category"].to_list()) == {"duplication", "translocation"}
