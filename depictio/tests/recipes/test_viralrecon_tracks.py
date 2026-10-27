"""viralrecon's genome-track manifest: one VCF and one BAM row per summary sample.

The manifest is spelled out from the MultiQC summary and trimmed to the files
the run holds; read in place (``remote_base_uri``) every expected row is kept.
"""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe

_SUMMARY = "Sample,# Mapped reads,Pangolin lineage\nS1,1000,B.1\nS2,2000,A.2\n"


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, summary: str = _SUMMARY, **kwargs):
    (root / "multiqc").mkdir(exist_ok=True)
    (root / "multiqc" / "summary_variants_metrics_mqc.csv").write_text(summary, encoding="utf-8")
    return execute_recipe("nf-core/viralrecon/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variants/ivar/S1.vcf.gz",
        "variants/bowtie2/S1.ivar_trim.sorted.bam",
        "variants/ivar/S2.vcf.gz",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["S1.variants", "S1.alignments", "S2.variants"]
    assert df["sample_id"].to_list() == ["S1", "S1", "S2"]
    assert df["format"].to_list() == ["vcf", "bam", "vcf"]
    assert df["uri"].to_list() == [
        "variants/ivar/S1.vcf.gz",
        "variants/bowtie2/S1.ivar_trim.sorted.bam",
        "variants/ivar/S2.vcf.gz",
    ]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["category"].to_list() == ["Variants", "Alignments", "Variants"]
    assert df["name"].to_list() == ["S1 variants", "S1 reads", "S2 variants"]


def test_snpeff_vcf_is_preferred_over_the_plain_one(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variants/ivar/S1.vcf.gz",
        "variants/ivar/snpeff/S1.snpeff.vcf.gz",
        "variants/bcftools/S2.vcf.gz",
        "variants/bcftools/snpeff/S2.snpeff.vcf.gz",
    )
    df = _run(tmp_path)
    assert df["uri"].to_list() == [
        "variants/ivar/snpeff/S1.snpeff.vcf.gz",
        "variants/bcftools/snpeff/S2.snpeff.vcf.gz",
    ]


def test_plain_vcf_is_used_when_the_run_has_no_snpeff_output(tmp_path: Path) -> None:
    _touch(tmp_path, "variants/ivar/S1.vcf.gz", "variants/bcftools/S2.vcf.gz")
    df = _run(tmp_path)
    assert df["uri"].to_list() == ["variants/ivar/S1.vcf.gz", "variants/bcftools/S2.vcf.gz"]


def test_variants_fall_back_to_bcftools_then_nanopore(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variants/bcftools/S1.vcf.gz",
        "artic_minion/S2.pass.vcf.gz",
        "artic_minion/S2.primertrimmed.rg.sorted.bam",
    )
    df = _run(tmp_path)
    assert df["uri"].to_list() == [
        "variants/bcftools/S1.vcf.gz",
        "artic_minion/S2.pass.vcf.gz",
        "artic_minion/S2.primertrimmed.rg.sorted.bam",
    ]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df.height == 4
    assert df["uri"].to_list() == [
        "variants/ivar/snpeff/S1.snpeff.vcf.gz",
        "variants/bowtie2/S1.ivar_trim.sorted.bam",
        "variants/ivar/snpeff/S2.snpeff.vcf.gz",
        "variants/bowtie2/S2.ivar_trim.sorted.bam",
    ]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "variants/ivar/S1.vcf.gz")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 4
    assert df["track_id"].to_list()[-1] == "S2.alignments"


def test_a_bom_on_the_summary_header_is_ignored(tmp_path: Path) -> None:
    df = _run(tmp_path, summary="﻿" + _SUMMARY)
    assert df["sample_id"].unique(maintain_order=True).to_list() == ["S1", "S2"]
