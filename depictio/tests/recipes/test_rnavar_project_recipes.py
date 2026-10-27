"""nf-core/rnavar pipeline recipes: the calls, the Genome navigator and the sample hub.

rnavar publishes each sample's calls twice (as called, and after
VariantFiltration), so the calls recipe must read one of them, the filtered one
when it exists; the navigator must keep to the primary contigs and name its
coordinates like the call track; the hub must survive every optional source
being absent and carry the design columns, or one constant group without a
design table.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

HEADER = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"


def _line(chrom: str, pos: int, ref: str, alt: str, filt: str, gt: str = "0/1") -> str:
    return f"{chrom}\t{pos}\t.\t{ref}\t{alt}\t100.0\t{filt}\tDP=20\tGT:AD:DP:GQ:PL\t{gt}:10,10:20:99:1,0,1"


def _raw(files: dict[str, list[str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [(line, path) for path, lines in files.items() for line in lines],
        schema=["raw_line", "source_path"],
        orient="row",
    )


CALLS = [
    _line("chr1", 100, "A", "G", "PASS"),
    _line("chr1", 200, "C", "T", "PASS", "1/1"),
    _line("chrUn_GL000220v1", 50, "A", "G", "PASS"),
]


def test_variants_prefer_the_filtered_vcf_of_a_sample(tmp_path: Path) -> None:
    raw = _raw(
        {
            "variant_calling/S1/S1.haplotypecaller.vcf.gz": [
                _line("chr1", 100, "A", "G", "."),
                _line("chr1", 200, "C", "T", "."),
            ],
            "variant_calling/S1/S1.haplotypecaller.filtered.vcf.gz": [
                _line("chr1", 100, "A", "G", "PASS"),
                _line("chr1", 200, "C", "T", "QD"),
            ],
            # A run that skipped VariantFiltration: only the unfiltered VCF.
            "variant_calling/S2/S2.haplotypecaller.vcf.gz": [_line("chr2", 300, "G", "A", ".")],
        }
    )
    df = execute_recipe("nf-core/rnavar/variants.py", tmp_path, extra_sources={"raw": raw})
    assert df.group_by("sample").len().sort("sample").rows() == [("S1", 2), ("S2", 1)]
    s1 = df.filter(pl.col("sample") == "S1")
    assert s1["stage"].unique().to_list() == ["filtered"]
    assert s1["filter_status"].to_list() == ["PASS", "QD"]
    assert s1["is_pass"].to_list() == [True, False]
    s2 = df.filter(pl.col("sample") == "S2").row(0, named=True)
    assert s2["stage"] == "raw" and s2["caller"] == "haplotypecaller" and s2["is_pass"]


def test_variants_keep_the_catalog_vcf_columns_first(tmp_path: Path) -> None:
    from depictio.recipes.lib.vcf import CORE_COLUMNS

    raw = _raw({"x/S1.haplotypecaller.filtered.vcf.gz": CALLS})
    df = execute_recipe("nf-core/rnavar/variants.py", tmp_path, extra_sources={"raw": raw})
    assert df.columns == [*CORE_COLUMNS, "stage"]


def test_variant_windows_count_the_cohort_on_primary_contigs(tmp_path: Path) -> None:
    raw = _raw(
        {
            "a/S1.haplotypecaller.filtered.vcf.gz": CALLS,
            "a/S2.haplotypecaller.filtered.vcf.gz": [
                CALLS[0],
                _line("chr1", 1_500_000, "G", "T", "PASS"),
            ],
        }
    )
    calls = execute_recipe("nf-core/rnavar/variants.py", tmp_path, extra_sources={"raw": raw})
    win = execute_recipe(
        "nf-core/rnavar/variant_windows.py", tmp_path, extra_sources={"variants": calls}
    )
    assert win.columns == ["chrom", "pos", "end", "variants", "calls", "samples", "snv_pct"]
    rows = {(r["chrom"], r["pos"]): r for r in win.iter_rows(named=True)}
    assert set(rows) == {("chr1", 0), ("chr1", 1_000_000)}  # the unplaced contig is out
    first = rows[("chr1", 0)]
    assert first["variants"] == 2 and first["calls"] == 3 and first["samples"] == 2
    assert first["end"] == 1_000_000 and first["snv_pct"] == 100.0


@pytest.fixture()
def hub_sources() -> dict[str, pl.DataFrame]:
    star = pl.DataFrame(
        {
            "sample": ["S1", "S2"],
            "input_reads": [1000, 2000],
            "uniquely_mapped_pct": [84.0, 80.0],
            "multimapped_pct": [10.0, 12.0],
            "unmapped_pct": [5.0, 7.0],
            "mismatch_rate_pct": [0.5, 0.4],
            "splices_annotated_pct": [99.0, 98.0],
        }
    )
    junctions = pl.DataFrame(
        {
            "sample": ["S1", "S1", "S2"],
            "annotation": ["annotated", "novel", "annotated"],
            "junctions": [99, 1, 50],
        }
    )
    dups = pl.DataFrame({"sample": ["S1", "S2"], "percent_duplication": [0.5, 0.25]})
    stats = pl.DataFrame(
        {
            "sample": ["S1", "S1", "S1", "S1"],
            "section": ["SN", "COV", "COV", "COV"],
            "bin": [None, 1.0, 5.0, 20.0],
            "n_bases": [None, 50.0, 25.0, 25.0],
        }
    )
    idx = pl.DataFrame(
        {
            "sample": ["S1"] * 4,
            "contig_class": ["autosome", "mitochondrion", "Y", "other"],
            "mapped_pct": [80.0, 5.0, 1.0, 14.0],
        }
    )
    callset = pl.DataFrame(
        {
            "sample": ["S1"],
            "pass_calls": [40],
            "snvs": [35],
            "indels": [5],
            "pass_pct": [88.0],
            "ts_tv": [2.6],
            "het_hom_ratio": [1.5],
            "median_dp": [20.0],
        }
    )
    return {
        "star": star,
        "junctions": junctions,
        "dups": dups,
        "stats": stats,
        "idxstats": idx,
        "callset": callset,
    }


def test_hub_joins_every_source_and_the_design(tmp_path: Path, hub_sources: dict) -> None:
    design = pl.DataFrame(
        {"sample": ["S1", "S2"], "cell line": ["A", "B"], "replicate": ["1", "1"]}
    )
    df = execute_recipe(
        "nf-core/rnavar/samples.py",
        tmp_path,
        extra_sources={**hub_sources, "metadata": design},
        pipeline_version="1.3.0",
    )
    assert df.columns[:3] == ["sample", "cell_line", "replicate"]  # Delta-safe factor names
    s1 = df.filter(pl.col("sample") == "S1").row(0, named=True)
    assert s1["novel_junction_pct"] == pytest.approx(1.0)
    assert s1["duplication_pct"] == pytest.approx(50.0)
    assert s1["bases_10x_pct"] == pytest.approx(25.0)
    assert s1["mito_reads_pct"] == pytest.approx(5.0)
    assert s1["other_contig_reads_pct"] == pytest.approx(14.0)
    assert s1["pass_calls"] == 40 and s1["ts_tv"] == pytest.approx(2.6)
    s2 = df.filter(pl.col("sample") == "S2").row(0, named=True)
    assert s2["pass_calls"] is None and s2["bases_10x_pct"] is None  # missing, not 0


def test_hub_without_design_or_optional_sources_keeps_one_group(
    tmp_path: Path, hub_sources: dict
) -> None:
    df = execute_recipe(
        "nf-core/rnavar/samples.py",
        tmp_path,
        extra_sources={"star": hub_sources["star"]},
        pipeline_version="1.3.0",
    )
    assert df["__no_group__"].unique().to_list() == ["All samples"]
    assert df["sample"].to_list() == ["S1", "S2"]
    assert df["duplication_pct"].null_count() == 2


def test_hub_of_a_run_started_from_bam_keys_on_the_callset(
    tmp_path: Path, hub_sources: dict
) -> None:
    """A BAM, CRAM or VCF start skips STAR: the callset names the samples."""
    df = execute_recipe(
        "nf-core/rnavar/samples.py",
        tmp_path,
        extra_sources={"callset": hub_sources["callset"]},
        pipeline_version="1.3.0",
    )
    assert df["sample"].to_list() == ["S1"]
    row = df.row(0, named=True)
    assert row["pass_calls"] == 40 and row["input_reads"] is None
