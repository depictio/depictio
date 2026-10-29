"""sarek's genome-track manifest: one VCF row per caller and sample, one CRAM per sample.

The manifest is spelled out from sarek's own csv/ manifests and trimmed to the
files (and indexes) the run holds; read in place (``remote_base_uri``) every
expected row is kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).resolve().parents[2] / "projects/nf-core/sarek/3.10.0/template.yaml"

_RECALIBRATED = (
    "patient,sex,status,sample,cram,crai\nP1,NA,0,S1,x.cram,x.crai\nP2,NA,0,S2,y.cram,y.crai\n"
)
_CALLED = (
    "patient,sample,variantcaller,vcf\n"
    "P1,S1,deepvariant,a\n"
    "P1,S1,manta,b\n"
    "P1,S1,haplotypecaller,c\n"
    "P2,S2,haplotypecaller,d\n"
)


def _touch(root: Path, *rel_paths: str, index: bool = True) -> None:
    """Create each file and, unless ``index`` is off, its ``.tbi`` / ``.crai``."""
    for rel in rel_paths:
        paths = [rel, rel + (".crai" if rel.endswith(".cram") else ".tbi")] if index else [rel]
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")


def _run(root: Path, manifests: dict[str, str] | None = None, **kwargs):
    manifests = {"recalibrated": _RECALIBRATED, "variantcalled": _CALLED, **(manifests or {})}
    (root / "csv").mkdir(exist_ok=True)
    for name, text in manifests.items():
        (root / "csv" / f"{name}.csv").write_text(text, encoding="utf-8")
    return execute_recipe("nf-core/sarek/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz",
        "variant_calling/haplotypecaller/S2/S2.haplotypecaller.vcf.gz",
        "preprocessing/recalibrated/S1/S1.recal.cram",
    )
    df = _run(tmp_path)
    # The first sample's caller and its reads lead, then the rest.
    assert df["track_id"].to_list() == ["S1.deepvariant", "S1.alignments", "S2.haplotypecaller"]
    assert df["sample_id"].to_list() == ["S1", "S1", "S2"]
    assert df["format"].to_list() == ["vcf", "cram", "vcf"]
    assert df["uri"].to_list() == [
        "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz",
        "preprocessing/recalibrated/S1/S1.recal.cram",
        "variant_calling/haplotypecaller/S2/S2.haplotypecaller.vcf.gz",
    ]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["caller"].to_list() == ["deepvariant", None, "haplotypecaller"]
    assert df["category"].to_list() == ["Small variants", "Alignments", "Small variants"]
    assert df["name"].to_list() == ["S1 deepvariant", "S1 reads", "S2 haplotypecaller"]


def test_a_file_without_its_index_is_left_out_of_an_upload(tmp_path: Path) -> None:
    _touch(tmp_path, "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz")
    _touch(tmp_path, "variant_calling/manta/S1/S1.manta.diploid_sv.vcf.gz", index=False)
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["S1.deepvariant"]


def test_the_snpeff_twin_is_preferred_and_a_filtered_vcf_comes_first(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variant_calling/haplotypecaller/S1/S1.haplotypecaller.vcf.gz",
        "variant_calling/haplotypecaller/S1/S1.haplotypecaller.filtered.vcf.gz",
        "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz",
        "annotation/deepvariant/S1/S1.deepvariant_snpEff.ann.vcf.gz",
    )
    df = _run(tmp_path)
    assert df["uri"].to_list() == [
        "variant_calling/haplotypecaller/S1/S1.haplotypecaller.filtered.vcf.gz",
        "annotation/deepvariant/S1/S1.deepvariant_snpEff.ann.vcf.gz",
    ]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df.height == 6
    assert df["uri"].to_list() == [
        "annotation/haplotypecaller/S1/S1.haplotypecaller.filtered_snpEff.ann.vcf.gz",
        "annotation/deepvariant/S1/S1.deepvariant_snpEff.ann.vcf.gz",
        "preprocessing/recalibrated/S1/S1.recal.cram",
        "annotation/manta/S1/S1.manta.diploid_sv_snpEff.ann.vcf.gz",
        "annotation/haplotypecaller/S2/S2.haplotypecaller.filtered_snpEff.ann.vcf.gz",
        "preprocessing/recalibrated/S2/S2.recal.cram",
    ]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "variant_calling/deepvariant/S1/S1.deepvariant.vcf.gz")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 6
    assert df["track_id"].to_list()[-1] == "S2.alignments"


def test_the_opening_tracks_are_every_caller_of_the_first_sample_and_its_reads(
    tmp_path: Path,
) -> None:
    df = _run(tmp_path)
    # A caller comparison with the reads under it, then the structural-variant caller of
    # the first sample, the other samples' callers and their CRAMs.
    assert df["track_id"].to_list() == [
        "S1.haplotypecaller",
        "S1.deepvariant",
        "S1.alignments",
        "S1.manta",
        "S2.haplotypecaller",
        "S2.alignments",
    ]
    assert df["kind"].to_list() == [
        "variants",
        "variants",
        "alignments",
        "sv",
        "variants",
        "alignments",
    ]
    assert df["category"].to_list()[3] == "Structural variants"
    assert df["order"].to_list() == list(range(1, 7))
    assert df["track_id"].n_unique() == df.height


def test_order_is_assigned_after_the_filter(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variant_calling/haplotypecaller/S2/S2.haplotypecaller.filtered.vcf.gz",
        "preprocessing/recalibrated/S1/S1.recal.cram",
    )
    df = _run(tmp_path)
    assert df["order"].to_list() == [1, 2]


def test_somatic_pairs_have_no_row_and_the_markduplicates_cram_is_the_fallback(
    tmp_path: Path,
) -> None:
    called = _CALLED + "P1,S1_vs_S3,strelka,e\n"
    marked = "patient,sex,status,sample,cram,crai\nP1,NA,0,S1,x.cram,x.crai\n"
    df = _run(
        tmp_path,
        manifests={"variantcalled": called, "recalibrated": marked},
    )
    assert not any("_vs_" in s for s in df["sample_id"].to_list())
    # A sample only the markduplicates manifest lists has its md.cram.
    (tmp_path / "csv" / "recalibrated.csv").unlink()
    (tmp_path / "csv" / "markduplicates.csv").write_text(marked, encoding="utf-8")
    df = execute_recipe("nf-core/sarek/tracks.py", tmp_path)
    assert df.filter(df["kind"] == "alignments")["uri"].to_list() == [
        "preprocessing/markduplicates/S1/S1.md.cram"
    ]


def test_a_run_with_no_manifest_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "other.csv").write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sarek tracks"):
        execute_recipe("nf-core/sarek/tracks.py", tmp_path)


def _tracks_properties(variables: dict[str, str]) -> dict:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    dcs = template["workflows"][0]["data_collections"]
    dc = next(d for d in dcs if d["data_collection_tag"] == "tracks")
    assert dc["config"]["type"] == "genomic_tracks"
    return substitute_template_variables(dc["config"]["dc_specific_properties"], variables)


def test_the_template_tracks_collection_validates() -> None:
    config = DCGenomicTracksConfig(**_tracks_properties({"GENOME": "hg38"}))
    assert config.assembly == "hg38"
    assert config.order_column == "order"
    assert set(config.display_defaults) == {"cram", "vcf"}
    assert config.remote_base_uri is None


def test_the_tracks_uri_override_names_a_valid_remote_base() -> None:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    rules = [
        r for r in template["template"]["conditional"] if r.get("if_var_present") == "TRACKS_URI"
    ]
    (override,) = rules[0]["override_dcs"]
    assert override["data_collection_tag"] == "tracks"
    props = {
        **_tracks_properties({"GENOME": "hg38"}),
        **substitute_template_variables(
            override["dc_properties"], {"TRACKS_URI": "s3://bucket/results"}
        ),
    }
    assert DCGenomicTracksConfig(**props).remote_base_uri == "s3://bucket/results/"
    assert "TRACKS_URI" in {v["name"] for v in template["template"]["variables"]}
