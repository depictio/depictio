"""Karyotype order of contigs shared by the recipes (``depictio.recipes.lib.contigs``)."""

from __future__ import annotations

import polars as pl

from depictio.recipes.lib.contigs import sort_contigs


def _order(names: list[str]) -> list[str]:
    return sort_contigs(pl.DataFrame({"chrom": names}), "chrom").get_column("chrom").to_list()


def test_numbers_sort_as_numbers_not_text():
    assert _order(["chr10", "chr2", "chr1", "chr22", "chr3"]) == [
        "chr1",
        "chr2",
        "chr3",
        "chr10",
        "chr22",
    ]


def test_sex_mito_others_and_total_follow_the_numbered_contigs():
    shuffled = ["total", "chrM", "chrUn_KI270302v1", "chrY", "chrX", "chr21", "chr9"]
    assert _order(shuffled) == ["chr9", "chr21", "chrX", "chrY", "chrM", "chrUn_KI270302v1", "total"]


def test_ensembl_names_sort_like_ucsc_ones():
    assert _order(["MT", "Y", "X", "10", "2", "1"]) == ["1", "2", "10", "X", "Y", "MT"]


def test_by_columns_come_first():
    df = pl.DataFrame({"sample": ["b", "a", "a"], "chrom": ["chr1", "chr10", "chr2"]})
    out = sort_contigs(df, "chrom", "sample")
    assert out.rows() == [("a", "chr2"), ("a", "chr10"), ("b", "chr1")]
