"""Sample / caller recovery for ``bcftools stats`` reports across nf-core layouts.

The three layouts a report is published under, plus the no-``ID``-line
fallback. Before this helper the ids came from a regex on the directory order,
which swapped them on sarek's documented layout and matched nothing on eager's.
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.bcftools import stats_summary, stats_tstv
from depictio.recipes.lib.bcftools_stats import sample_and_caller

SAREK_MEGATEST = (
    "reports/bcftools/haplotypecaller/NA12878_75M/"
    "NA12878_75M.haplotypecaller.filtered.bcftools_stats.txt"
)
SAREK_DOCS = "reports/bcftools/NA12878_200M/manta/NA12878_200M.manta.diploid_sv.bcftools_stats.txt"
EAGER_FLAT = "bcftools/stats/COD076.vcf.stats"
NO_ID_LINE = "reports/bcftools/strelka/S1/S1.strelka.variants.bcftools_stats.txt"


def _raw(rows: list[tuple[str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {"raw_line": [line for line, _ in rows], "source_path": [path for _, path in rows]}
    )


def _report(path: str, vcf: str | None, sn_records: int, ts: int, tv: int) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if vcf is not None:
        rows.append((f"ID\t0\t{vcf}", path))
    rows += [
        (f"SN\t0\tnumber of records:\t{sn_records}", path),
        (f"SN\t0\tnumber of SNPs:\t{sn_records - 10}", path),
        ("SN\t0\tnumber of indels:\t10", path),
        (f"TSTV\t0\t{ts}\t{tv}\t{ts / tv:.2f}\t{ts}\t{tv}\t{ts / tv:.2f}", path),
    ]
    return rows


RAW = _raw(
    _report(SAREK_MEGATEST, "NA12878_75M.haplotypecaller.filtered.vcf.gz", 1000, 600, 300)
    + _report(SAREK_DOCS, "NA12878_200M.manta.diploid_sv.vcf.gz", 200, 0, 1)
    + _report(EAGER_FLAT, "COD076.haplotypecaller.vcf.gz", 500, 300, 150)
    + _report(NO_ID_LINE, None, 50, 30, 15)
)


def test_ids_come_from_the_id_line_whatever_the_directory_order() -> None:
    ids = sample_and_caller(RAW).sort("source_path")
    by_path = {r["source_path"]: (r["sample"], r["caller"]) for r in ids.to_dicts()}
    assert by_path[SAREK_MEGATEST] == ("NA12878_75M", "haplotypecaller")
    assert by_path[SAREK_DOCS] == ("NA12878_200M", "manta")
    assert by_path[EAGER_FLAT] == ("COD076", "haplotypecaller")


def test_file_name_fallback_when_the_id_line_is_missing() -> None:
    ids = sample_and_caller(RAW).filter(pl.col("source_path") == NO_ID_LINE)
    assert ids.to_dicts() == [{"source_path": NO_ID_LINE, "sample": "S1", "caller": "strelka"}]


def test_single_token_name_falls_back_to_the_grandparent_directory() -> None:
    raw = _raw([("SN\t0\tnumber of records:\t1", "reports/bcftools/freebayes/S2/S2.txt")])
    assert sample_and_caller(raw).to_dicts() == [
        {
            "source_path": "reports/bcftools/freebayes/S2/S2.txt",
            "sample": "S2",
            "caller": "freebayes",
        }
    ]


def test_both_recipes_keep_one_row_per_sample_and_caller() -> None:
    summary = stats_summary.transform({"raw": RAW})
    tstv = stats_tstv.transform({"raw": RAW})
    for out in (summary, tstv):
        assert out.height == 4
        assert out.select(["sample", "caller"]).n_unique() == 4
        assert out.schema["sample"] == pl.Utf8 and out.schema["caller"] == pl.Utf8
    eager = summary.filter(pl.col("sample") == "COD076").to_dicts()[0]
    assert eager["caller"] == "haplotypecaller" and eager["n_records"] == 500
    manta = tstv.filter(pl.col("caller") == "manta").to_dicts()[0]
    assert manta["sample"] == "NA12878_200M" and manta["ts"] == 0
