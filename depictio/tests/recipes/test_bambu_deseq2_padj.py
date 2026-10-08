"""A DESeq2 ``NA`` padj is an absent verdict, not the most significant one.

DESeq2 writes ``NA`` for the adjusted p-value of every gene its independent
filtering set aside. ``-log10`` of a null is null, and a null must never fall
through to the underflow cap, which would draw those genes at the very top of
every volcano built on ``deseq2_on_bambu``.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes.lib.bambu import NEG_LOG10_CAP, deseq2_on_bambu


def _raw(padj: list[str]) -> pl.DataFrame:
    """The raw ``deseq2.results.txt`` scan: every column text, ``NA`` verbatim."""
    n = len(padj)
    return pl.DataFrame(
        {
            "": [f"gene{i}" for i in range(n)],
            "baseMean": ["100.0"] * n,
            "log2FoldChange": ["2.5"] * n,
            "lfcSE": ["0.1"] * n,
            "pvalue": ["0.001"] * n,
            "padj": padj,
        }
    )


def test_a_null_padj_stays_null_and_is_not_significant() -> None:
    out = deseq2_on_bambu(_raw(["NA", "0.01", "0"]), "all").sort("gene_id")

    assert out["neg_log10_padj"].to_list()[0] is None
    assert out["significant"].to_list()[0] is False
    assert out["direction"].to_list()[0] == "not significant"
    # The other two branches are untouched: a real padj is -log10'd and an
    # underflowed one is capped.
    assert out["neg_log10_padj"].to_list()[1] == pytest.approx(2.0)
    assert out["neg_log10_padj"].to_list()[2] == NEG_LOG10_CAP
