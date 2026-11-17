"""The gene-name fallback of a filtered ``locus_from``.

A ``locus_from`` row without coordinates (nanoseq's isoform table, written
without the extended annotation) frames nothing in ``locus_from_rows``; the
gene its ``label_column`` names places the view instead, through the UCSC
search. The search is faked: no network.
"""

from __future__ import annotations

from depictio.api.v1.services.jbrowse.render import (
    centred_locus_from_rows,
    gene_fallback_locus,
    gene_names_from_rows,
    locus_from_rows,
    pad_locus,
)

SPEC = {
    "chrom_column": "chrom",
    "start_column": "start",
    "end_column": "end",
    "label_column": "gene_name",
    "padding": 500,
}
NO_COORDS = {"chrom": None, "start": None, "end": None}


class FakeSearch:
    """``search_genes`` stand-in: the hits per query, and the queries made."""

    def __init__(self, hits: dict[str, list[dict[str, str]]]):
        self.hits = hits
        self.calls: list[tuple[str, str]] = []

    def __call__(self, genome: str, query: str, limit: int):
        self.calls.append((genome, query))
        return self.hits.get(query, [])


def test_rows_without_coordinates_frame_nothing_but_name_a_gene():
    rows = [{**NO_COORDS, "gene_name": "TP53"}]
    assert locus_from_rows(rows, SPEC) is None
    search = FakeSearch({"TP53": [{"label": "TP53", "locus": "chr17:7668421-7687490"}]})
    assert gene_fallback_locus(rows, SPEC, "hg38", search) == "chr17:7667921-7687990"
    assert search.calls == [("hg38", "TP53")]


def test_a_symbol_needs_an_exact_label_not_the_first_hit():
    rows = [{**NO_COORDS, "gene_name": "TP53"}]
    search = FakeSearch({"TP53": [{"label": "TP53I3", "locus": "chr2:24077433-24084834"}]})
    assert gene_fallback_locus(rows, SPEC, "hg38", search) is None
    search = FakeSearch(
        {
            "TP53": [
                {"label": "TP53I3", "locus": "chr2:24077433-24084834"},
                {"label": "tp53", "locus": "chr17:7668421-7687490"},
            ]
        }
    )
    assert gene_fallback_locus(rows, SPEC, "hg38", search) == "chr17:7667921-7687990"


def test_an_ensembl_id_takes_the_first_hit():
    # UCSC labels the hit with the transcript's gene symbol or the id itself.
    rows = [{**NO_COORDS, "gene_name": "ENSG00000141510.18"}]
    search = FakeSearch(
        {"ENSG00000141510.18": [{"label": "TP53", "locus": "chr17:7668421-7687490"}]}
    )
    assert gene_fallback_locus(rows, SPEC, "hg38", search) == "chr17:7667921-7687990"


def test_no_genome_no_name_no_hit_is_none():
    search = FakeSearch({})
    rows = [{**NO_COORDS, "gene_name": "TP53"}]
    assert gene_fallback_locus(rows, SPEC, None, search) is None
    assert gene_fallback_locus([{**NO_COORDS}], SPEC, "hg38", search) is None
    assert (
        gene_fallback_locus(
            rows, {k: v for k, v in SPEC.items() if k != "label_column"}, "hg38", search
        )
        is None
    )
    assert gene_fallback_locus(rows, SPEC, "hg38", search) is None
    assert search.calls == [("hg38", "TP53")]


def test_a_failing_search_is_skipped_not_raised():
    def boom(genome, query, limit):
        raise RuntimeError("UCSC is down")

    assert gene_fallback_locus([{**NO_COORDS, "gene_name": "TP53"}], SPEC, "hg38", boom) is None


def test_names_are_distinct_clean_and_capped():
    rows = [
        {"gene_name": "TP53"},
        {"gene_name": "TP53"},
        {"gene_name": None},
        {"gene_name": "has space"},
        {"gene_name": "nan"},
        {"gene_name": "BRCA1"},
    ]
    assert gene_names_from_rows(rows, SPEC) == ["TP53", "BRCA1"]
    assert gene_names_from_rows(rows, {}) == []


def test_several_genes_are_framed_together_on_their_main_chromosome():
    rows = [{"gene_name": n} for n in ("A", "B", "C")]
    search = FakeSearch(
        {
            "A": [{"label": "A", "locus": "chr1:1000-2000"}],
            "B": [{"label": "B", "locus": "chr1:5000-6000"}],
            "C": [{"label": "C", "locus": "chr2:10-20"}],
        }
    )
    assert gene_fallback_locus(rows, SPEC, "hg38", search) == "chr1:500-6500"


def test_pad_locus_widens_both_sides_and_clamps_the_start():
    assert pad_locus("chr6:1000-2000", 500) == "chr6:500-2500"
    assert pad_locus("chr6:100-200", 500) == "chr6:1-700"
    assert pad_locus(None, 500) is None


def test_the_best_row_sits_in_the_middle_of_the_frame():
    rows = [
        {"chrom": "chr1", "start": 10_000, "end": 10_000},
        {"chrom": "chr1", "start": 12_000, "end": 12_000},
        {"chrom": "chr1", "start": 9_000, "end": 9_000},
        {"chrom": "chr2", "start": 1, "end": 1},
    ]
    # Half-width from the far side (12,000), padded; the other contig is ignored.
    assert centred_locus_from_rows(rows, SPEC) == "chr1:7500-12500"
    assert centred_locus_from_rows(rows[:1], SPEC) == "chr1:9500-10500"


def test_a_transcript_id_is_looked_up_before_the_gene_name():
    rows = [
        {**NO_COORDS, "gene_name": "ATP5F1D", "transcript_id": "ENST00000395633"},
        {**NO_COORDS, "gene_name": "TP53", "transcript_id": None},
    ]
    spec = {**SPEC, "locate_column": "transcript_id"}
    assert gene_names_from_rows(rows, spec) == ["ENST00000395633", "TP53"]
