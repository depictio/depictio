"""cutandrun 3.2.2's genome-track manifest: bigWig, peak and BAM rows per sample.

The manifest is spelled out from the validated samplesheet and trimmed to the
files the run holds; read in place (``remote_base_uri``) every expected row is
kept. The template test checks that its ``tracks`` collection is a valid
``genomic_tracks`` configuration once the variables are substituted, and that
every manifest column it names is one the recipe writes.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/cutandrun/tracks.py"
VERSION = "3.2.2"
TEMPLATE = Path(__file__).resolve().parents[2] / "projects/nf-core/cutandrun/3.2.2/template.yaml"

# One mark in two replicates (two libraries for the first) and an IgG control.
_SHEET = """id,group,replicate,control,single_end,fastq_1,fastq_2,is_control
mark_R1_T1,mark,1,igg_1,0,a_1.fq.gz,a_2.fq.gz,0
mark_R1_T2,mark,1,igg_1,0,a2_1.fq.gz,a2_2.fq.gz,0
mark_R2_T1,mark,2,igg_2,0,b_1.fq.gz,b_2.fq.gz,0
igg_R1_T1,igg,1,,0,c_1.fq.gz,c_2.fq.gz,1
"""

_CALLS = "03_peak_calling/04_called_peaks"
_ALIGN = "02_alignment/bowtie2/target"


def _touch(root: Path, *rel_paths: str, data: bytes = b"x") -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "pipeline_info").mkdir(exist_ok=True)
    (root / "pipeline_info" / "samplesheet.valid.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe(RECIPE, root, pipeline_version=VERSION, **kwargs)


def _bigwig(s: str) -> str:
    return f"03_peak_calling/03_bed_to_bigwig/{s}.bigWig"


def _seacr(s: str) -> str:
    return f"{_CALLS}/seacr/{s}.seacr.peaks.stringent.bed"


def _macs2(s: str) -> str:
    return f"{_CALLS}/macs2/{s}.macs2_peaks.narrowPeak"


def _bam(s: str) -> str:
    return f"{_ALIGN}/markdup/{s}.target.markdup.sorted.bam"


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    # 3 samples x (signal, alignments) + 2 targets x (SEACR, MACS2): controls have no peaks.
    assert df.height == 10
    assert df["kind"].to_list() == (
        ["signal"] * 3 + ["peaks_seacr"] * 2 + ["peaks_macs2"] * 2 + ["alignments"] * 3
    )
    assert df["sample_id"].to_list()[:3] == ["igg_R1", "mark_R1", "mark_R2"]
    assert df["order"].to_list() == list(range(1, 11))
    assert df["format"].to_list()[-3:] == ["bam"] * 3
    assert df["name"].to_list()[0] == "igg_R1 signal"


def test_present_files_only_in_the_order_signal_peaks_bam(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        _bam("mark_R1"),
        _seacr("mark_R1"),
        _bigwig("mark_R2"),
        _bigwig("mark_R1"),
        _macs2("mark_R1"),
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "mark_R1.signal",
        "mark_R2.signal",
        "mark_R1.peaks_seacr",
        "mark_R1.peaks_macs2",
        "mark_R1.alignments",
    ]
    assert df["uri"].to_list()[2] == _seacr("mark_R1")
    assert df["order"].to_list() == [1, 2, 3, 4, 5]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("mark_R1"))
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 10
    assert df["uri"].to_list()[-1] == _bam("mark_R2")


def test_an_empty_peak_file_is_dropped_but_not_in_place(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("mark_R1"), _seacr("mark_R1"))
    _touch(tmp_path, _seacr("mark_R2"), data=b"")
    df = _run(tmp_path)
    assert "mark_R2.peaks_seacr" not in df["track_id"].to_list()
    assert "mark_R1.peaks_seacr" in df["track_id"].to_list()
    in_place = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert "mark_R2.peaks_seacr" in in_place["track_id"].to_list()


def test_other_layouts_are_followed_when_the_first_candidate_is_absent(tmp_path: Path) -> None:
    linear = f"{_ALIGN}/linear_dedup/mark_R1.target.linear_dedup.sorted.bam"
    igv_bw = "04_reporting/igv/mark_R1.bigWig"
    igv_bed = "04_reporting/igv/mark_R1.seacr.peaks.stringent.bed"
    _touch(tmp_path, linear, igv_bw, igv_bed)
    df = _run(tmp_path)
    by_kind = dict(zip(df["kind"].to_list(), df["uri"].to_list(), strict=True))
    assert by_kind == {
        "signal": igv_bw,
        "peaks_seacr": igv_bed,
        "alignments": linear,
    }
    # The marked-duplicate BAM wins when both are there.
    _touch(tmp_path, _bam("mark_R1"))
    df = _run(tmp_path)
    assert df.filter(pl.col("kind") == "alignments")["uri"].to_list() == [_bam("mark_R1")]


def test_a_group_keeps_one_colour_and_the_control_its_own(tmp_path: Path) -> None:
    df = _run(tmp_path)
    colours = df.group_by("target").agg(pl.col("color").n_unique().alias("n")).to_dicts()
    assert {row["target"]: row["n"] for row in colours} == {"mark": 1, "igg": 1}
    assert df["color"].n_unique() == 2
    assert all(c.startswith("rgb(") for c in df["color"].to_list())


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
    config = substitute_template_variables(dc["config"], {"DATA_ROOT": "/data", "GENOME": "mm10"})
    assert config["type"] == "genomic_tracks"
    props = DCGenomicTracksConfig.model_validate(config["dc_specific_properties"])
    assert props.assembly == "mm10"
    assert {"bigwig", "bed", "narrowpeak"} <= set(props.display_defaults)

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


def test_template_links_the_hub_and_the_seacr_peaks_to_the_tracks() -> None:
    template, _ = _tracks_dc()
    links = {
        (link["source_dc_tag"], link["target_dc_tag"]): link["link_config"]
        for link in template["links"]
        if "tracks" in (link["source_dc_tag"], link["target_dc_tag"])
    }
    assert set(links) == {
        ("samples", "tracks"),
        ("tracks", "samples"),
        ("seacr_peaks", "tracks"),
    }
    # The manifest is keyed on the GROUP_R<n> spelling the peak calls use.
    assert all(cfg["target_field"] == "sample_id" for cfg in links.values())


def test_tracks_is_declared_after_the_hub_it_links_to() -> None:
    template, _ = _tracks_dc()
    tags = [dc["data_collection_tag"] for dc in template["workflows"][0]["data_collections"]]
    assert tags.index("samples") < tags.index("tracks")
