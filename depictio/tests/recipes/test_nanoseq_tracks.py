"""nanoseq's genome-track manifest: one bigWig and one BAM row per samplesheet sample.

The manifest is spelled out from the validated samplesheet and trimmed to the
files the run holds; read in place (``remote_base_uri``) every expected row is
kept. Nothing here reads a real track file: the megatest subset is tables only,
so the wiring is covered by these recipe and template tests alone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/nanoseq/3.0.0/template.yaml"

_SHEET = (
    "sample,barcode,input_file,fasta,gtf,is_transcripts,nanopolish_fast5\n"
    "A_R1,,a1.fastq.gz,ref,,0,\n"
    "A_R2,,a2.fastq.gz,ref,,0,\n"
    "B_R1,,b1.fastq.gz,ref,,0,\n"
    "B_R2,,b2.fastq.gz,ref,,0,\n"
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "pipeline_info").mkdir(exist_ok=True)
    (root / "pipeline_info" / "samplesheet.valid.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/nanoseq/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "minimap2/bigwig/A_R1.bigWig",
        "minimap2/bigwig/B_R1.bigWig",
        "minimap2/A_R1.sorted.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["A_R1.coverage", "B_R1.coverage", "A_R1.alignments"]
    assert df["sample"].to_list() == ["A_R1", "B_R1", "A_R1"]
    assert df["format"].to_list() == ["bigwig", "bigwig", "bam"]
    assert df["uri"].to_list() == [
        "minimap2/bigwig/A_R1.bigWig",
        "minimap2/bigwig/B_R1.bigWig",
        "minimap2/A_R1.sorted.bam",
    ]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["category"].to_list() == ["Coverage", "Coverage", "Alignments"]


def test_a_run_holding_none_lists_every_file_light_tracks_first(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df.height == 8
    # Replicate 1 of every condition before replicate 2, the BAMs after every bigWig.
    assert df["track_id"].to_list() == [
        "A_R1.coverage",
        "B_R1.coverage",
        "A_R2.coverage",
        "B_R2.coverage",
        "A_R1.alignments",
        "B_R1.alignments",
        "A_R2.alignments",
        "B_R2.alignments",
    ]
    assert df["order"].to_list() == list(range(1, 9))
    assert df["format"].to_list() == ["bigwig"] * 4 + ["bam"] * 4


def test_graphmap2_is_used_when_the_run_has_no_minimap2_output(tmp_path: Path) -> None:
    _touch(tmp_path, "graphmap2/bigwig/A_R1.bigWig", "graphmap2/A_R1.sorted.bam")
    df = _run(tmp_path)
    assert df["uri"].to_list() == ["graphmap2/bigwig/A_R1.bigWig", "graphmap2/A_R1.sorted.bam"]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "minimap2/A_R1.sorted.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 8
    assert df["track_id"].to_list()[-1] == "B_R2.alignments"
    assert df["uri"].to_list()[0] == "minimap2/bigwig/A_R1.bigWig"


def test_colours_follow_the_condition(tmp_path: Path) -> None:
    df = _run(tmp_path)
    by_sample = dict(zip(df["sample"].to_list(), df["color"].to_list(), strict=True))
    assert by_sample["A_R1"] == by_sample["A_R2"]
    assert by_sample["B_R1"] == by_sample["B_R2"]
    assert by_sample["A_R1"] != by_sample["B_R1"]
    assert set(df["condition"].to_list()) == {"A", "B"}
    assert all(c.startswith("rgb(") for c in df["color"].to_list())


def test_a_sample_listed_twice_gets_one_row_per_file(tmp_path: Path) -> None:
    sheet = _SHEET + "A_R1,,a1b.fastq.gz,ref,,0,\n"
    df = _run(tmp_path, sheet=sheet)
    assert df["track_id"].is_unique().all()
    assert df.height == 8


def _template(variables: dict[str, str]) -> dict:
    return substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)


def _tracks_dc(resolved: dict) -> dict:
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    return next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")


def test_template_tracks_dc_validates_with_the_model() -> None:
    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg19"})
    props = _tracks_dc(resolved)["config"]["dc_specific_properties"]
    config = DCGenomicTracksConfig(**props)
    assert config.assembly == "hg19"
    assert get_assembly_preset("hg19") is not None
    assert config.order_column == "order"
    assert set(config.display_defaults) == {"bigwig", "bam"}

    # The TRACKS_URI override the template applies reads the run in place.
    config = DCGenomicTracksConfig(**{**props, "remote_base_uri": "s3://bucket/results"})
    assert config.remote_base_uri == "s3://bucket/results/"


def test_template_wires_the_genome_variable_and_the_tracks_override() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    variables = {v["name"]: v for v in raw["template"]["variables"]}
    assert variables["GENOME"]["default"] == "hg38"
    assert get_assembly_preset(variables["GENOME"]["default"]) is not None
    assert get_assembly_preset(raw["template"]["reference"]["vars"]["GENOME"]) is not None
    assert "TRACKS_URI" in variables
    assert "://" not in variables["TRACKS_URI"]["description"].replace("s3:// or https://", "")

    rules = [r for r in raw["template"]["conditional"] if r.get("if_var_present") == "TRACKS_URI"]
    assert len(rules) == 1
    override = rules[0]["override_dcs"][0]
    assert override["data_collection_tag"] == "tracks"
    assert override["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}


def test_template_links_hub_and_tracks_both_ways_and_the_locus_dc() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    links = {(link["source_dc_tag"], link["target_dc_tag"]) for link in raw["links"]}
    assert ("samples", "tracks") in links
    assert ("tracks", "samples") in links
    # The DC the browser takes its locus from is reachable from the DEXSeq pick.
    assert ("dexseq_results", "gtf_transcripts") in links
