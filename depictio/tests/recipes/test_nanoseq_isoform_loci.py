"""nanoseq's `isoform_loci`: the transcripts DEXSeq tested, spanned and ranked for the browser."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

RECIPE = "nf-core/nanoseq/isoform_loci.py"


def _dex() -> pl.DataFrame:
    # Two transcripts of G1 share the gene's q-value; G2 is less significant; G3 untested.
    rows = [
        ("T1", "G1", 2.0, 1e-10, True, "up"),
        ("T2", "G1", -3.0, 1e-10, True, "down"),
        ("T3", "G2", 0.5, 0.04, True, "up"),
        ("T4", "G3", 0.1, None, False, "not significant"),
        ("T5", "G4", 1.0, 0.0, True, "up"),
    ]
    return pl.DataFrame(
        rows,
        schema=["feature_id", "gene_id", "log2fc", "padj", "significant", "direction"],
        orient="row",
    )


def _blocks() -> pl.DataFrame:
    rows = [
        ("T1", "G1", "GENE1", "1", 100, 200, "exon", "+", "known"),
        ("T1", "G1", "GENE1", "1", 300, 400, "exon", "+", "known"),
        ("T1", "G1", "GENE1", "1", 100, 400, "CDS", "+", "known"),
        ("T2", "G1", "GENE1", "1", 100, 200, "exon", "+", "NNC"),
        ("T2", "G1", "GENE1", "1", 300, 450, "exon", "+", "NNC"),
        ("T3", "G2", "GENE2", "2", 10, 90, "exon", "-", "known"),
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
            "strand",
            "transcript_class",
        ],
        orient="row",
    )


@pytest.mark.no_db
def test_each_tested_transcript_gets_its_span_from_the_annotation():
    module = load_recipe(RECIPE)
    out = module.transform({"dex": _dex(), "blocks": _blocks()})
    validate_schema(out, module.OUTPUT_SCHEMA, "isoform_loci", None)
    assert out.height == 5
    t1 = out.filter(pl.col("transcript_id") == "T1").to_dicts()[0]
    # The CDS block is not an exon: the span runs over the exons only.
    assert (t1["chrom"], t1["start"], t1["end"], t1["n_exons"]) == ("1", 100, 400, 2)
    assert (t1["gene_name"], t1["strand"], t1["transcript_class"]) == ("GENE1", "+", "known")
    t5 = out.filter(pl.col("transcript_id") == "T5").to_dicts()[0]
    assert t5["chrom"] is None and t5["start"] is None  # tested, not in the annotation
    assert t5["gene_name"] == "G4"  # falls back to the gene id


@pytest.mark.no_db
def test_the_browser_opens_on_the_strongest_shift_and_the_effect_breaks_the_gene_tie():
    module = load_recipe(RECIPE)
    out = module.transform({"dex": _dex(), "blocks": _blocks()})
    # padj 0 is capped at 300; the gene's two transcripts tie on q-value and the larger effect leads.
    assert out["transcript_id"].to_list() == ["T5", "T2", "T1", "T3", "T4"]
    scores = dict(zip(out["transcript_id"].to_list(), out["rank_score"].to_list(), strict=True))
    assert scores["T5"] == pytest.approx(300.001)
    assert scores["T2"] == pytest.approx(10.003)
    assert scores["T1"] == pytest.approx(10.002)
    assert scores["T4"] == pytest.approx(0.0001)  # no q-value: last, never null


@pytest.mark.no_db
def test_without_the_extended_annotation_every_transcript_is_listed_with_no_span():
    module = load_recipe(RECIPE)
    for blocks in (None, _blocks().clear()):
        out = module.transform({"dex": _dex(), "blocks": blocks})
        validate_schema(out, module.OUTPUT_SCHEMA, "isoform_loci", None)
        assert out.height == 5
        assert out["chrom"].null_count() == 5
        assert out["start"].null_count() == 5
        assert out["rank_score"].null_count() == 0


@pytest.mark.no_db
def test_no_dexseq_rows_gives_an_empty_table_with_the_schema():
    module = load_recipe(RECIPE)
    out = module.transform({"dex": _dex().clear(), "blocks": _blocks()})
    assert out.is_empty()
    validate_schema(out, module.OUTPUT_SCHEMA, "isoform_loci", None)
