"""rnafusion's genome-track manifest: one STAR alignment row per samplesheet sample.

The manifest is spelled out from the samplesheet and trimmed to the files the
run holds; read in place (``remote_base_uri``) every expected row is kept.
Nothing here reads a real track file: the megatest subset is tables only, so the
wiring is covered by these recipe and template tests alone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/rnafusion/4.1.3/template.yaml"
DASHBOARD = TEMPLATE.parent / "dashboards/base.yaml"

_SHEET = (
    "sample,fastq_1,fastq_2,strandedness\n"
    "S1,a_1.fq.gz,a_2.fq.gz,forward\n"
    "S2,b_1.fq.gz,b_2.fq.gz,forward\n"
    "S3,c_1.fq.gz,c_2.fq.gz,forward\n"
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / "samplesheet.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/rnafusion/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "star/S1.Aligned.sortedByCoord.out.bam",
        "star/S3.Aligned.sortedByCoord.out.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["S1.alignments", "S3.alignments"]
    assert df["sample"].to_list() == ["S1", "S3"]
    assert df["format"].to_list() == ["bam", "bam"]
    assert df["uri"].to_list() == [
        "star/S1.Aligned.sortedByCoord.out.bam",
        "star/S3.Aligned.sortedByCoord.out.bam",
    ]
    assert df["order"].to_list() == [1, 2]
    assert df["category"].to_list() == ["Alignments", "Alignments"]
    assert df["name"].to_list() == ["S1 reads", "S3 reads"]


def test_a_run_holding_none_lists_every_expected_file_in_sheet_order(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["S1.alignments", "S2.alignments", "S3.alignments"]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["format"].to_list() == ["bam"] * 3
    # No manifest colour: it would win over the dashboard's `category_colors`.
    assert "color" not in df.columns
    assert df["sample"].n_unique() == 3


def test_a_cram_run_is_listed_as_cram(tmp_path: Path) -> None:
    _touch(
        tmp_path, "star/S1.Aligned.sortedByCoord.out.cram", "star/S2.Aligned.sortedByCoord.out.bam"
    )
    df = _run(tmp_path)
    assert df["format"].to_list() == ["cram", "bam"]
    assert df["uri"].to_list()[0] == "star/S1.Aligned.sortedByCoord.out.cram"


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "star/S1.Aligned.sortedByCoord.out.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 3
    assert df["track_id"].to_list()[-1] == "S3.alignments"


def test_a_sample_listed_twice_gets_one_row(tmp_path: Path) -> None:
    df = _run(tmp_path, sheet=_SHEET + "S1,d_1.fq.gz,d_2.fq.gz,forward\n")
    assert df["track_id"].to_list() == ["S1.alignments", "S2.alignments", "S3.alignments"]


def _template(variables: dict[str, str]) -> dict:
    return substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)


def test_template_tracks_dc_validates_with_the_model() -> None:
    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg38"})
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    props = tracks["config"]["dc_specific_properties"]
    config = DCGenomicTracksConfig(**props)
    assert config.assembly == "hg38"
    assert get_assembly_preset("hg38") is not None
    assert set(config.display_defaults) == {"bam", "cram"}
    # The tile colours by `sample`, so the manifest declares no colour column.
    assert config.color_column is None
    assert (
        DCGenomicTracksConfig(
            **{**props, "remote_base_uri": "https://host/results"}
        ).remote_base_uri
        == "https://host/results/"
    )
    assert tracks["config"]["transform"]["source_overrides"]["samplesheet"]["path"] == (
        "/data/input/samplesheet.csv"
    )


def test_template_wires_the_overrides_and_the_links() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    variables = {v["name"]: v for v in raw["template"]["variables"]}
    assert variables["GENOME"]["default"] == "hg38"
    assert "TRACKS_URI" in variables
    rules = {r.get("if_var_present"): r for r in raw["template"]["conditional"]}

    override = rules["TRACKS_URI"]["override_dcs"][0]
    assert override["data_collection_tag"] == "tracks"
    assert override["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}

    # A user-supplied samplesheet moves the tracks manifest's source with the hub's.
    moved = {o["data_collection_tag"] for o in rules["SAMPLESHEET_FILE"]["override_dcs"]}
    assert {"samplesheet", "tracks"} <= moved

    links = {(link["source_dc_tag"], link["target_dc_tag"]) for link in raw["links"]}
    assert ("samplesheet", "tracks") in links
    assert ("tracks", "samplesheet") in links
    # The Fusion filter narrows the breakpoint table the browser frames from.
    assert ("fusion_consensus", "arriba_fusion_links") in links
    # A call picked on the ring opens the alignments of the sample that called it.
    assert ("arriba_fusion_links", "tracks") in links


def test_the_browser_colours_by_a_key_the_dashboard_declares() -> None:
    dash = yaml.safe_load(DASHBOARD.read_text())
    browser = next(
        c
        for tab in dash["tabs"]
        for c in tab.get("components", [])
        if c.get("component_type") == "jbrowse"
    )
    assert browser["color_by"] == "sample"
    assert "sample" in dash["main_dashboard"]["category_colors"]
    assert "ucsc_tracks" in browser
    # The calls open in the order of the ranked bars: the index, then the reads.
    assert browser["locus_from"]["sort_by"] == "rank_score"
    assert browser["locus_from"]["label_column"] == "label"
