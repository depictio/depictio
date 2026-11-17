"""viralrecon's variant table: the catalog transform plus the ``call_score`` ranking.

The genome browser opens on the highest-scoring call and the Gene picker starts on
the gene holding it. Sorting on the allele frequency alone left ties at 1.0 and
could land on an intergenic call, which carries no protein change.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

_HEADER = "SAMPLE,CHROM,POS,REF,ALT,FILTER,DP,REF_DP,ALT_DP,AF,GENE,AA,EFFECT\n"


def _run(tmp_path: Path, rows: list[str]) -> pl.DataFrame:
    folder = tmp_path / "variants" / "ivar"
    folder.mkdir(parents=True)
    (folder / "variants_long_table.csv").write_text(_HEADER + "\n".join(rows) + "\n")
    return execute_recipe("nf-core/viralrecon/variants_long.py", tmp_path)


def _ranked(df: pl.DataFrame) -> list[str]:
    return df.sort("call_score", descending=True)["mutation_label"].to_list()


def test_the_catalog_columns_are_kept_and_the_score_added(tmp_path: Path) -> None:
    df = _run(tmp_path, ["S1,c,10,A,T,PASS,50,0,50,0.9,S,p.X1X,missense_variant"])
    assert {"sample", "mutation_label", "AF", "DP", "GENE", "call_score"} <= set(df.columns)
    assert df.schema["call_score"] == pl.Float64


def test_ties_at_full_frequency_are_broken_by_depth(tmp_path: Path) -> None:
    df = _run(
        tmp_path,
        [
            "S1,c,10,A,T,PASS,40,0,40,1.0,S,p.X1X,missense_variant",
            "S1,c,20,A,T,PASS,900,0,900,1.0,N,p.X1X,missense_variant",
            "S1,c,30,A,T,PASS,300,0,300,1.0,M,p.X1X,synonymous_variant",
        ],
    )
    assert _ranked(df) == ["N:A20T", "M:A30T", "S:A10T"]


def test_frequency_comes_before_depth(tmp_path: Path) -> None:
    df = _run(
        tmp_path,
        [
            "S1,c,10,A,T,PASS,5000,0,5000,0.80,S,p.X1X,missense_variant",
            "S1,c,20,A,T,PASS,30,0,30,0.99,N,p.X1X,missense_variant",
        ],
    )
    assert _ranked(df) == ["N:A20T", "S:A10T"]


def test_intergenic_calls_rank_last_whatever_their_support(tmp_path: Path) -> None:
    df = _run(
        tmp_path,
        [
            "S1,c,10,A,T,PASS,9000,0,9000,1.0,CHR_START-orf1ab,p.X1X,intergenic_region",
            "S1,c,20,A,T,PASS,10,0,10,0.3,orf1ab,p.X1X,missense_variant",
            "S1,c,30,A,T,PASS,9000,0,9000,1.0,ORF8-N,p.X1X,intergenic_region",
        ],
    )
    ranked = _ranked(df)
    assert ranked[0] == "orf1ab:A20T"
    assert set(ranked[1:]) == {"CHR_START-orf1ab:A10T", "ORF8-N:A30T"}


def test_a_gene_picker_ranking_by_max_score_skips_the_intergenic_pseudo_gene(
    tmp_path: Path,
) -> None:
    df = _run(
        tmp_path,
        [
            "S1,c,10,A,T,PASS,100,0,100,1.0,CHR_START-orf1ab,p.X1X,intergenic_region",
            "S1,c,20,A,T,PASS,60,0,60,0.8,S,p.X1X,missense_variant",
        ],
    )
    top_gene = (
        df.group_by("GENE").agg(pl.col("call_score").max()).sort("call_score", descending=True)
    )
    assert top_gene["GENE"][0] == "S"


def test_missing_depth_or_frequency_does_not_break_the_score(tmp_path: Path) -> None:
    df = _run(tmp_path, ["S1,c,10,A,T,PASS,,0,0,,S,p.X1X,missense_variant"])
    assert df["call_score"].null_count() == 0
