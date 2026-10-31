"""viralrecon's genome-track manifest: one VCF and one BAM row per summary sample.

The manifest is spelled out from the MultiQC summary and trimmed to the files
the run holds; read in place (``remote_base_uri``) every expected row is kept.
It holds no colour column (the tile colours the tracks by ``lineage``, through the
dashboard's ``category_colors``) and opens on the sample of the best supported call.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/viralrecon/3.0.0/template.yaml"

_SUMMARY = "Sample,# Mapped reads,Pangolin lineage\nS1,1000,B.1\nS2,2000,A.2\n"


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, summary: str = _SUMMARY, variants: pl.DataFrame | None = None, **kwargs):
    (root / "multiqc").mkdir(exist_ok=True)
    (root / "multiqc" / "summary_variants_metrics_mqc.csv").write_text(summary, encoding="utf-8")
    extra = {"variants": variants} if variants is not None else None
    return execute_recipe("nf-core/viralrecon/tracks.py", root, extra_sources=extra, **kwargs)


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


def test_no_colour_column_and_the_lineage_the_tile_colours_by(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert "color" not in df.columns
    assert df["lineage"].to_list() == ["B.1", "B.1", "A.2", "A.2"]


def test_a_sample_without_lineage_is_unassigned(tmp_path: Path) -> None:
    summary = "Sample,# Mapped reads,Pangolin lineage\nS1,1000,NA\nS2,2000,\nS3,10,B.1\n"
    df = _run(tmp_path, summary=summary)
    by_sample = dict(zip(df["sample_id"].to_list(), df["lineage"].to_list(), strict=True))
    assert by_sample == {"S1": "Unassigned", "S2": "Unassigned", "S3": "B.1"}


def test_a_summary_without_a_lineage_column_still_lists_the_tracks(tmp_path: Path) -> None:
    df = _run(tmp_path, summary="Sample,# Mapped reads\nS1,1000\n")
    assert df["lineage"].unique().to_list() == ["Unassigned"]


def test_rows_open_on_the_sample_of_the_best_supported_call(tmp_path: Path) -> None:
    variants = pl.DataFrame(
        {"sample": ["S1", "S2", "S2"], "call_score": [5.0e9, 1.0e10 + 40, -9.0e10]}
    )
    df = _run(tmp_path, variants=variants)
    assert df["track_id"].to_list() == [
        "S2.variants",
        "S2.alignments",
        "S1.variants",
        "S1.alignments",
    ]
    assert df["order"].to_list() == [1, 2, 3, 4]


def test_a_variant_table_without_the_score_falls_back_on_the_allele_frequency(
    tmp_path: Path,
) -> None:
    variants = pl.DataFrame({"sample": ["S1", "S2"], "AF": [0.4, 0.9]})
    assert _run(tmp_path, variants=variants)["sample_id"].to_list()[0] == "S2"


def test_template_tracks_dc_validates_with_the_model() -> None:
    resolved = substitute_template_variables(
        yaml.safe_load(TEMPLATE.read_text()), {"DATA_ROOT": "/data"}
    )
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    props = tracks["config"]["dc_specific_properties"]
    assert "color_column" not in props
    config = DCGenomicTracksConfig(**props)
    assert config.assembly == "wuhCor1"
    assert set(config.display_defaults) == {"bam", "vcf"}
    # The recipe reads variants_long (dc_ref): it is declared first.
    tags = [dc["data_collection_tag"] for dc in dcs]
    assert tags.index("variants_long") < tags.index("tracks")
