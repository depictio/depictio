"""nanoseq's isoform junctions: intron chains of the extended annotation, weighted by counts."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

RECIPE = "nf-core/nanoseq/junctions.py"


def _blocks() -> pl.DataFrame:
    rows = [
        # T1: three exons, two introns. T2: two exons sharing T1's first intron.
        # T3: one exon, no intron. T4: two blocks that touch, no intron.
        ("T1", "G1", "GENE1", "1", 100, 200, "exon", "known"),
        ("T1", "G1", "GENE1", "1", 300, 400, "exon", "known"),
        ("T1", "G1", "GENE1", "1", 500, 600, "exon", "known"),
        ("T1", "G1", "GENE1", "1", 100, 600, "CDS", "known"),
        ("T2", "G1", "GENE1", "1", 100, 200, "exon", "NNC"),
        ("T2", "G1", "GENE1", "1", 300, 450, "exon", "NNC"),
        ("T3", "G2", "GENE2", "2", 10, 90, "exon", "known"),
        ("T4", "G3", "GENE3", "3", 10, 20, "exon", "known"),
        ("T4", "G3", "GENE3", "3", 21, 40, "exon", "known"),
    ]
    return pl.DataFrame(
        rows,
        schema=[
            "transcript_id",
            "gene_id",
            "gene_name",
            "chrom",
            "start",
            "end",
            "feature",
            "transcript_class",
        ],
        orient="row",
    )


def _counts() -> pl.DataFrame:
    rows = []
    for sample, condition in [("A_R1", "A"), ("A_R2", "A"), ("B_R1", "B")]:
        for tx, n in [("T1", 10.0), ("T2", 4.0), ("T3", 7.0), ("T4", 1.0)]:
            rows.append((sample, condition, tx, n * (3 if condition == "B" else 1)))
    return pl.DataFrame(
        rows, schema=["sample", "condition", "transcript_id", "count"], orient="row"
    )


@pytest.mark.no_db
def test_one_arc_per_intron_of_each_transcript_and_condition():
    module = load_recipe(RECIPE)
    out = module.transform({"blocks": _blocks(), "counts": _counts()})
    validate_schema(out, module.OUTPUT_SCHEMA, "isoform_junctions", None)

    # T1 has two introns, T2 one; T3 and T4 have none. Two conditions each.
    assert out.height == (2 + 1) * 2
    assert set(out["transcript_id"].to_list()) == {"T1", "T2"}
    t1 = out.filter(pl.col("transcript_id") == "T1").sort(["start", "condition"])
    assert t1["start"].to_list() == [200, 200, 400, 400]
    assert t1["end"].to_list() == [300, 300, 500, 500]


@pytest.mark.no_db
def test_reads_are_the_transcript_mean_over_the_libraries_of_a_condition():
    module = load_recipe(RECIPE)
    out = module.transform({"blocks": _blocks(), "counts": _counts()})
    row = {
        (r["transcript_id"], r["condition"]): r["reads"]
        for r in out.filter(pl.col("start") == 200).to_dicts()
    }
    assert row[("T1", "A")] == pytest.approx(10.0)  # 20 reads over 2 libraries
    assert row[("T1", "B")] == pytest.approx(30.0)
    assert row[("T2", "A")] == pytest.approx(4.0)


@pytest.mark.no_db
def test_a_transcript_outside_the_reference_is_novel():
    module = load_recipe(RECIPE)
    out = module.transform({"blocks": _blocks(), "counts": _counts()})
    by_tx = dict(zip(out["transcript_id"].to_list(), out["annotation"].to_list(), strict=True))
    assert by_tx == {"T1": "known", "T2": "novel"}


@pytest.mark.no_db
def test_no_extended_annotation_gives_an_empty_table_with_the_schema():
    module = load_recipe(RECIPE)
    for blocks in (None, _blocks().clear()):
        out = module.transform({"blocks": blocks, "counts": _counts()})
        assert out.is_empty()
        validate_schema(out, module.OUTPUT_SCHEMA, "isoform_junctions", None)


@pytest.mark.no_db
def test_a_transcript_never_counted_has_no_arc():
    module = load_recipe(RECIPE)
    counts = _counts().filter(pl.col("transcript_id") != "T2")
    out = module.transform({"blocks": _blocks(), "counts": counts})
    assert set(out["transcript_id"].to_list()) == {"T1"}
