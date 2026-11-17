"""atacseq 1.2.2's genome-track manifest: bigWig, peak and BAM rows per merged library.

The manifest is spelled out from the design sheet and trimmed to the files the
run holds; read in place (``remote_base_uri``) every expected row is kept. The
template test checks that its ``tracks`` collection is a valid ``genomic_tracks``
configuration once the variables are substituted, and that every manifest
column it names is one the recipe writes.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/atacseq/tracks.py"
VERSION = "1.2.2"
TEMPLATE = Path(__file__).resolve().parents[2] / "projects/nf-core/atacseq/1.2.2/template.yaml"

# Two groups, two replicates each; the first group has two technical replicates.
_DESIGN = """sample_id,fastq_1,fastq_2
AA_R1_T1,a_1.fq.gz,a_2.fq.gz
AA_R1_T2,a2_1.fq.gz,a2_2.fq.gz
AA_R2_T1,b_1.fq.gz,b_2.fq.gz
BB_R1_T1,c_1.fq.gz,c_2.fq.gz
BB_R2_T1,d_1.fq.gz,d_2.fq.gz
"""


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, design: str = _DESIGN, **kwargs):
    (root / "pipeline_info").mkdir(exist_ok=True)
    (root / "pipeline_info" / "design_reads.csv").write_text(design, encoding="utf-8")
    return execute_recipe(RECIPE, root, pipeline_version=VERSION, **kwargs)


def _bigwig(m: str) -> str:
    return f"bwa/mergedLibrary/bigwig/{m}.mLb.clN.bigWig"


def _broad(m: str) -> str:
    return f"bwa/mergedLibrary/macs/broadPeak/{m}.mLb.clN_peaks.broadPeak"


def _bam(m: str) -> str:
    return f"bwa/mergedLibrary/{m}.mLb.clN.sorted.bam"


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("AA_R1"), _broad("AA_R1"), _bam("AA_R1"), _bigwig("BB_R1"))
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "AA_R1.mLb.clN.signal",
        "BB_R1.mLb.clN.signal",
        "AA_R1.mLb.clN.peaks",
        "AA_R1.mLb.clN.alignments",
    ]
    assert df["format"].to_list() == ["bigwig", "bigwig", "broadpeak", "bam"]
    assert df["uri"].to_list() == [
        _bigwig("AA_R1"),
        _bigwig("BB_R1"),
        _broad("AA_R1"),
        _bam("AA_R1"),
    ]
    assert df["order"].to_list() == [1, 2, 3, 4]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    # 4 merged libraries x (signal, peaks, alignments); technical replicates merge.
    assert df.height == 12
    assert df["kind"].to_list() == ["signal"] * 4 + ["peaks"] * 4 + ["alignments"] * 4
    assert df["sample"].unique(maintain_order=True).to_list()[:4] == [
        "AA_R1",
        "BB_R1",
        "AA_R2",
        "BB_R2",
    ]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("AA_R1"))
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 12
    assert df["track_id"].to_list()[-1] == "BB_R2.mLb.clN.alignments"


def test_signal_first_replicate_one_before_replicate_two_bams_last(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df["order"].to_list() == list(range(1, 13))
    assert df["sample_id"].to_list()[:4] == [
        "AA_R1.mLb.clN",
        "BB_R1.mLb.clN",
        "AA_R2.mLb.clN",
        "BB_R2.mLb.clN",
    ]
    assert df["format"].to_list()[-4:] == ["bam"] * 4
    assert set(df["category"].to_list()[:4]) == {"Signal"}
    assert df["name"].to_list()[0] == "AA_R1 signal"
    assert df["name"].to_list()[-1] == "BB_R2 reads"


def test_a_group_keeps_one_colour_across_replicates_and_kinds(tmp_path: Path) -> None:
    df = _run(tmp_path)
    by_group = df.group_by("group").agg(pl.col("color").n_unique().alias("n")).to_dicts()
    assert {row["group"]: row["n"] for row in by_group} == {"AA": 1, "BB": 1}
    assert df["color"].n_unique() == 2
    assert all(c.startswith("rgb(") for c in df["color"].to_list())


def test_narrow_peak_run_is_followed_when_it_holds_no_broad_file(tmp_path: Path) -> None:
    narrow = "bwa/mergedLibrary/macs/narrowPeak/AA_R1.mLb.clN_peaks.narrowPeak"
    _touch(tmp_path, narrow, _bigwig("AA_R1"))
    df = _run(tmp_path)
    peaks = df.filter(df["kind"] == "peaks")
    assert peaks["format"].to_list() == ["narrowpeak"]
    assert peaks["uri"].to_list() == [narrow]


def test_a_sample_off_the_group_replicate_convention_is_its_own_group(tmp_path: Path) -> None:
    df = _run(tmp_path, design="sample_id,fastq_1,fastq_2\nlone_T1,a.fq.gz,\n")
    assert df["group"].unique().to_list() == ["lone"]
    assert df["sample_id"].unique().to_list() == ["lone.mLb.clN"]


def _tracks_dc() -> tuple[dict, dict]:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    (dc,) = [
        dc
        for wf in template["workflows"]
        for dc in wf["data_collections"]
        if dc["data_collection_tag"] == "tracks"
    ]
    return template, dc


def test_template_tracks_collection_is_a_valid_genomic_tracks_config() -> None:
    template, dc = _tracks_dc()
    config = substitute_template_variables(dc["config"], {"DATA_ROOT": "/data", "GENOME": "hg38"})
    assert config["type"] == "genomic_tracks"
    props = DCGenomicTracksConfig.model_validate(config["dc_specific_properties"])
    assert props.assembly == "hg38"
    assert {"bigwig", "broadpeak"} <= set(props.display_defaults)

    # Every manifest column the template names is one the recipe writes.
    schema = load_recipe(RECIPE, VERSION).OUTPUT_SCHEMA
    for column in (
        props.uri_column,
        props.track_id_column,
        props.sample_column,
        props.format_column,
        props.name_column,
        props.color_column,
        props.category_column,
        props.order_column,
    ):
        assert column in schema

    # TRACKS_URI is declared, generic, and turned into remote_base_uri.
    variables = {v["name"]: v for v in template["template"]["variables"]}
    assert variables["TRACKS_URI"]["required"] is False
    assert "s3://nf-core" not in variables["TRACKS_URI"]["description"]
    (override,) = [
        c for c in template["template"]["conditional"] if c.get("if_var_present") == "TRACKS_URI"
    ]
    assert override["override_dcs"][0]["data_collection_tag"] == "tracks"
    assert override["override_dcs"][0]["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}


def test_template_links_the_hub_and_the_peaks_to_the_tracks() -> None:
    template, _ = _tracks_dc()
    links = {
        (link["source_dc_tag"], link["target_dc_tag"]): link["link_config"]
        for link in template["links"]
        if "tracks" in (link["source_dc_tag"], link["target_dc_tag"])
    }
    assert set(links) == {
        ("sample_design", "tracks"),
        ("tracks", "sample_design"),
        ("macs2_broad_peaks", "tracks"),
    }
    # The manifest is keyed on the merged-library spelling the peak calls use.
    assert links[("macs2_broad_peaks", "tracks")]["target_field"] == "sample_id"
    assert links[("tracks", "sample_design")]["target_field"] == "merged_library"
