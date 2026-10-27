"""oncoanalyser's genome-track manifest: PURPLE's VCFs and the tumor and normal BAMs per group.

The manifest is spelled out from the samplesheet and trimmed to the files (and
indexes) the run holds; read in place (``remote_base_uri``) every expected row
is kept. Every row of a group is keyed on the group's tumor DNA sample.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).resolve().parents[2] / "projects/nf-core/oncoanalyser/3.0.0/template.yaml"

_HEADER = "group_id,subject_id,sample_id,sample_type,sequence_type,filetype,filepath\n"
_SHEET = (
    _HEADER
    + "G1,P1,G1.tumor_dna,tumor,dna,fastq,a\n"
    + "G1,P1,G1.tumor_dna,tumor,dna,fastq,b\n"
    + "G1,P1,G1.normal_dna,normal,dna,fastq,c\n"
    + "G1,P1,G1.tumor_rna,tumor,rna,fastq,d\n"
    + "G2,P2,G2.tumor_dna,tumor,dna,bam,e\n"
)


def _touch(root: Path, *rel_paths: str, index: bool = True) -> None:
    """Create each file and, unless ``index`` is off, its ``.tbi`` / ``.bai``."""
    for rel in rel_paths:
        paths = [rel, rel + (".bai" if rel.endswith(".bam") else ".tbi")] if index else [rel]
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / "samplesheet.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/oncoanalyser/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "G1/purple/G1.tumor_dna.purple.somatic.vcf.gz",
        "G1/purple/G1.tumor_dna.purple.sv.vcf.gz",
        "G2/purple/G2.tumor_dna.purple.somatic.vcf.gz",
        "G1/alignments/G1.normal_dna/G1.normal_dna.redux.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "G1.tumor_dna.somatic",
        "G1.tumor_dna.sv",
        "G2.tumor_dna.somatic",
        "G1.tumor_dna.normal_reads",
    ]
    assert df["format"].to_list() == ["vcf", "vcf", "vcf", "bam"]
    assert df["uri"].to_list() == [
        "G1/purple/G1.tumor_dna.purple.somatic.vcf.gz",
        "G1/purple/G1.tumor_dna.purple.sv.vcf.gz",
        "G2/purple/G2.tumor_dna.purple.somatic.vcf.gz",
        "G1/alignments/G1.normal_dna/G1.normal_dna.redux.bam",
    ]
    assert df["order"].to_list() == [1, 2, 3, 4]
    assert df["category"].to_list() == [
        "Small variants",
        "Structural variants",
        "Small variants",
        "Alignments",
    ]


def test_a_file_without_its_index_is_left_out_of_an_upload(tmp_path: Path) -> None:
    _touch(tmp_path, "G1/purple/G1.tumor_dna.purple.somatic.vcf.gz")
    _touch(tmp_path, "G1/purple/G1.tumor_dna.purple.sv.vcf.gz", index=False)
    assert _run(tmp_path)["track_id"].to_list() == ["G1.tumor_dna.somatic"]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    # G1 has a normal: 4 VCFs and 2 BAMs. G2 has none: 2 VCFs and 1 BAM.
    assert df.height == 9
    assert df["uri"].to_list()[:4] == [
        "G1/purple/G1.tumor_dna.purple.somatic.vcf.gz",
        "G1/purple/G1.tumor_dna.purple.sv.vcf.gz",
        "G1/purple/G1.tumor_dna.purple.germline.vcf.gz",
        "G1/purple/G1.tumor_dna.purple.sv.germline.vcf.gz",
    ]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "G1/purple/G1.tumor_dna.purple.somatic.vcf.gz")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/outdir"})
    assert df.height == 9


def test_vcfs_come_first_and_the_bams_last_tumor_before_normal(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df["format"].to_list() == ["vcf"] * 6 + ["bam"] * 3
    assert df["kind"].to_list()[6:] == ["tumor_reads", "normal_reads", "tumor_reads"]
    assert df["order"].to_list() == list(range(1, 10))
    assert df["track_id"].n_unique() == df.height


def test_every_row_is_keyed_on_the_tumor_and_names_its_own_sample(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert set(df["sample_id"].to_list()) == {"G1.tumor_dna", "G2.tumor_dna"}
    normal = df.filter(df["kind"] == "normal_reads")
    assert normal["sample_id"].to_list() == ["G1.tumor_dna"]
    assert normal["source_sample"].to_list() == ["G1.normal_dna"]
    assert normal["group_id"].to_list() == ["G1"]
    assert normal["name"].to_list() == ["G1.normal_dna normal reads"]


def test_a_tumor_only_group_has_no_germline_and_no_normal_alignment(tmp_path: Path) -> None:
    df = _run(tmp_path)
    g2 = df.filter(df["group_id"] == "G2")
    assert g2["kind"].to_list() == ["somatic", "sv", "tumor_reads"]


def test_the_tumor_rna_alignment_is_not_listed(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert not any("rna" in uri for uri in df["uri"].to_list())


def test_a_tab_separated_sheet_is_read(tmp_path: Path) -> None:
    df = _run(tmp_path, sheet=_SHEET.replace(",", "\t"))
    assert df.height == 9


def test_a_sheet_without_a_tumor_dna_sample_is_an_error(tmp_path: Path) -> None:
    sheet = _HEADER + "G1,P1,G1.tumor_rna,tumor,rna,fastq,a\n"
    with pytest.raises(ValueError, match="oncoanalyser tracks"):
        _run(tmp_path, sheet=sheet)


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
    assert set(config.display_defaults) == {"bam", "vcf"}
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
            override["dc_properties"], {"TRACKS_URI": "s3://bucket/outdir"}
        ),
    }
    assert DCGenomicTracksConfig(**props).remote_base_uri == "s3://bucket/outdir/"
    assert "TRACKS_URI" in {v["name"] for v in template["template"]["variables"]}
