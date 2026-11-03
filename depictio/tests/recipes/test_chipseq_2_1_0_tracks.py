"""`nf-core/chipseq/tracks.py` at 2.1.0: the genome-track manifest of a 2.x run.

The manifest is spelled out from the `design` hub (merged libraries `<sample>_REP<n>`) and
trimmed to the files the run holds; read in place (`remote_base_uri`) every expected row is
kept. The aligner and the MACS3 peak folder are read off the files DATA_ROOT holds. The
template test checks that its `tracks` collection is a valid `genomic_tracks`
configuration once the variables are substituted and that every manifest column it names
is one the recipe writes. Nothing here reads a real bigWig, peak or BAM.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/chipseq/tracks.py"
VERSION = "2.1.0"
TEMPLATE = Path(__file__).resolve().parents[2] / "projects/nf-core/chipseq/2.1.0/template.yaml"

# One antibody in two conditions, two replicates each, and two inputs.
_HUB = pl.DataFrame(
    {
        "sample_id": [
            "ABX_WT_REP1",
            "ABX_WT_REP2",
            "ABX_KO_REP1",
            "ABX_KO_REP2",
            "INPUT_REP1",
            "INPUT_REP2",
        ],
        "role": ["ChIP"] * 4 + ["input control"] * 2,
        "is_control": [False] * 4 + [True] * 2,
        "antibody": ["ABX"] * 6,
        "condition": ["ABX_WT", "ABX_WT", "ABX_KO", "ABX_KO", "ABX_WT", "ABX_WT"],
    }
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, hub: pl.DataFrame = _HUB, **kwargs):
    return execute_recipe(
        RECIPE, root, extra_sources={"design": hub}, pipeline_version=VERSION, **kwargs
    )


def _bigwig(s: str, aligner: str = "bwa") -> str:
    return f"{aligner}/merged_library/bigwig/{s}.mLb.clN.bigWig"


def _peaks(s: str, aligner: str = "bwa", peak_type: str = "narrow_peak") -> str:
    suffix = "narrowPeak" if peak_type == "narrow_peak" else "broadPeak"
    return f"{aligner}/merged_library/macs3/{peak_type}/{s}_peaks.{suffix}"


def _bam(s: str, aligner: str = "bwa") -> str:
    return f"{aligner}/merged_library/{s}.mLb.clN.sorted.bam"


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("ABX_WT_REP1"), _peaks("ABX_WT_REP1"), _bam("ABX_WT_REP1"))
    _touch(tmp_path, _bigwig("INPUT_REP1"), _bigwig("ABX_KO_REP1"))
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "ABX_KO_REP1.signal",
        "ABX_WT_REP1.signal",
        "ABX_WT_REP1.peaks",
        "INPUT_REP1.input",
        "ABX_WT_REP1.alignments",
    ]
    assert df["format"].to_list() == ["bigwig", "bigwig", "narrowpeak", "bigwig", "bam"]
    assert df["order"].to_list() == [1, 2, 3, 4, 5]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    df = _run(tmp_path)
    # 4 ChIPs x (signal, peaks, alignments) + 2 inputs.
    assert df.height == 14
    assert (
        df["kind"].to_list() == ["signal"] * 4 + ["peaks"] * 4 + ["input"] * 2 + ["alignments"] * 4
    )
    assert df["uri"].to_list()[0] == _bigwig("ABX_KO_REP1")


def test_replicate_one_of_every_condition_before_replicate_two_bams_last(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df["order"].to_list() == list(range(1, 15))
    assert df["sample_id"].to_list()[:4] == [
        "ABX_KO_REP1",
        "ABX_WT_REP1",
        "ABX_KO_REP2",
        "ABX_WT_REP2",
    ]
    assert df["format"].to_list()[-4:] == ["bam"] * 4
    assert df["name"].to_list()[0] == "ABX_KO_REP1 signal"
    assert df["category"].to_list()[:1] == ["Signal"]


def test_sample_ids_are_the_hub_spelling_the_peak_calls_use(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert set(df["sample_id"]) == set(_HUB["sample_id"])
    assert not any(".mLb" in s for s in df["sample_id"])


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, _bigwig("ABX_WT_REP1"))
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 14
    assert df["track_id"].to_list()[-1] == "ABX_WT_REP2.alignments"


def test_the_aligner_and_peak_type_are_read_off_the_files_the_run_holds(tmp_path: Path) -> None:
    # A tables-only tree: the peak calls are there, the bigWigs and BAMs are not.
    _touch(tmp_path, _peaks("ABX_WT_REP1", "bowtie2", "broad_peak"))
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    peaks = df.filter(df["kind"] == "peaks")
    assert peaks["format"].unique().to_list() == ["broadpeak"]
    assert peaks["uri"].to_list()[0] == _peaks("ABX_KO_REP1", "bowtie2", "broad_peak")
    assert df.filter(df["kind"] == "signal")["uri"].to_list()[0] == _bigwig(
        "ABX_KO_REP1", "bowtie2"
    )
    assert df.filter(df["kind"] == "alignments")["uri"].to_list()[0] == _bam(
        "ABX_KO_REP1", "bowtie2"
    )


def test_a_run_with_no_file_falls_back_on_the_params_then_the_defaults(tmp_path: Path) -> None:
    (tmp_path / "pipeline_info").mkdir()
    (tmp_path / "pipeline_info" / "params_2026-01-01.json").write_text(
        '{"aligner": "star", "narrow_peak": false}'
    )
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.filter(df["kind"] == "peaks")["uri"].to_list()[0] == _peaks(
        "ABX_KO_REP1", "star", "broad_peak"
    )
    assert df["uri"].to_list()[0].startswith("star/merged_library/bigwig/")


def test_inputs_are_grey_and_one_antibody_is_coloured_by_condition(tmp_path: Path) -> None:
    df = _run(tmp_path)
    inputs = df.filter(df["kind"] == "input")
    assert inputs["color"].n_unique() == 1
    chips = df.filter(df["kind"] != "input")
    by_sample = dict(zip(chips["sample_id"], chips["color"], strict=True))
    assert by_sample["ABX_WT_REP1"] == by_sample["ABX_WT_REP2"]
    assert by_sample["ABX_WT_REP1"] != by_sample["ABX_KO_REP1"]
    assert inputs["color"][0] not in set(chips["color"])


def test_several_antibodies_are_coloured_by_antibody_and_each_has_its_inputs(
    tmp_path: Path,
) -> None:
    hub = pl.DataFrame(
        {
            "sample_id": ["A_REP1", "B_REP1", "IN_A_REP1", "IN_B_REP1"],
            "role": ["ChIP", "ChIP", "input control", "input control"],
            "is_control": [False, False, True, True],
            "antibody": ["AA", "BB", "AA", "BB"],
            "condition": ["A", "B", "A", "B"],
        }
    )
    df = _run(tmp_path, hub)
    chips = df.filter(df["kind"] == "signal")
    assert chips["color"].n_unique() == 2
    # One block per antibody: its signal, its peaks, its input; the BAMs close the manifest.
    assert df["track_id"].to_list() == [
        "A_REP1.signal",
        "A_REP1.peaks",
        "IN_A_REP1.input",
        "B_REP1.signal",
        "B_REP1.peaks",
        "IN_B_REP1.input",
        "A_REP1.alignments",
        "B_REP1.alignments",
    ]


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
    assert {"bigwig", "narrowpeak", "broadpeak"} <= set(props.display_defaults)

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

    # The manifest follows the hub: it is declared after it.
    tags = [
        d["data_collection_tag"] for wf in template["workflows"] for d in wf["data_collections"]
    ]
    assert tags.index("design") < tags.index("tracks")


def test_template_gates_the_tracks_on_the_assembly_and_reads_them_in_place() -> None:
    template, _ = _tracks_dc()
    variables = {v["name"]: v for v in template["template"]["variables"]}
    assert variables["TRACKS_URI"]["required"] is False
    assert "s3://nf-core" not in variables["TRACKS_URI"]["description"]
    rules = template["template"]["conditional"]
    (in_place,) = [c for c in rules if c.get("if_var_present") == "TRACKS_URI"]
    assert in_place["override_dcs"][0]["data_collection_tag"] == "tracks"
    assert in_place["override_dcs"][0]["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}
    # Without an assembly the browser has nothing to draw on: the collection goes.
    (gate,) = [c for c in rules if c.get("if_var_absent") == "GENOME"]
    assert gate["remove_dc_tags"] == ["tracks"]


def test_template_links_the_hub_and_the_peaks_to_the_tracks() -> None:
    template, _ = _tracks_dc()
    links = {
        (link["source_dc_tag"], link["target_dc_tag"]): link["link_config"]
        for link in template["links"]
        if "tracks" in (link["source_dc_tag"], link["target_dc_tag"])
    }
    assert set(links) == {
        ("design", "tracks"),
        ("tracks", "design"),
        ("macs2_peaks", "tracks"),
    }
    # The manifest is keyed on the merged-library spelling the peak calls use.
    assert links[("macs2_peaks", "tracks")]["target_field"] == "sample_id"
    assert links[("tracks", "design")]["target_field"] == "sample_id"
