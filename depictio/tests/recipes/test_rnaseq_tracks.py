"""rnaseq's genome-track manifest: both strands and the BAM of every samplesheet sample.

The manifest is spelled out from the samplesheet and trimmed to the files the run
holds; read in place (``remote_base_uri``) every expected row is kept. Nothing here
reads a real track file: the megatest subset is tables only, so the wiring is covered
by these recipe and template tests alone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe

TEMPLATE_DIR = Path(__file__).parents[2] / "projects/nf-core/rnaseq/3.26.0"
TEMPLATE = TEMPLATE_DIR / "template.yaml"
BASE = TEMPLATE_DIR / "dashboards/base.yaml"

_SHEET = (
    "sample,fastq_1,fastq_2,strandedness\n"
    "A_REP1,a1_1.fastq.gz,a1_2.fastq.gz,auto\n"
    "A_REP2,a2_1.fastq.gz,a2_2.fastq.gz,auto\n"
    "B_REP1,b1_1.fastq.gz,b1_2.fastq.gz,auto\n"
    "B_REP2,b2_1.fastq.gz,b2_2.fastq.gz,auto\n"
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / "samplesheet.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/rnaseq/tracks.py", root, **kwargs)


def test_a_run_holding_none_lists_every_file_first_replicates_first(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df.height == 12
    # Replicate 1 of every condition before replicate 2; per sample both strands
    # then the BAM, so the opening tracks hold the reads the splice arcs come from.
    assert df["track_id"].to_list() == [
        f"{s}.{kind}"
        for s in ("A_REP1", "B_REP1", "A_REP2", "B_REP2")
        for kind in ("coverage_forward", "coverage_reverse", "alignments")
    ]
    assert df["format"].to_list() == ["bigwig", "bigwig", "bam"] * 4
    assert df["order"].to_list() == list(range(1, 13))
    assert df["uri"].to_list()[:3] == [
        "star_salmon/bigwig/A_REP1.forward.bigWig",
        "star_salmon/bigwig/A_REP1.reverse.bigWig",
        "star_salmon/A_REP1.markdup.sorted.bam",
    ]


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "star_salmon/bigwig/A_REP1.forward.bigWig",
        "star_salmon/bigwig/B_REP1.reverse.bigWig",
        "star_salmon/A_REP1.markdup.sorted.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "A_REP1.coverage_forward",
        "A_REP1.alignments",
        "B_REP1.coverage_reverse",
    ]
    assert df["order"].to_list() == [1, 2, 3]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "star_salmon/A_REP1.markdup.sorted.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 12


def test_the_manifest_writes_no_colour_the_condition_colours_the_tracks(tmp_path: Path) -> None:
    """A manifest colour wins over color_by + category_colors, so there is none."""
    df = _run(tmp_path)
    assert "color" not in df.columns
    assert set(df["condition"].to_list()) == {"A", "B"}
    by_sample = dict(zip(df["sample"].to_list(), df["condition"].to_list(), strict=True))
    assert by_sample["A_REP1"] == by_sample["A_REP2"] != by_sample["B_REP1"]


def test_a_sample_listed_twice_gets_one_row_per_file(tmp_path: Path) -> None:
    df = _run(tmp_path, sheet=_SHEET + "A_REP1,a1b_1.fastq.gz,a1b_2.fastq.gz,auto\n")
    assert df["track_id"].is_unique().all()
    assert df.height == 12


def _tracks_dc(variables: dict[str, str]) -> dict:
    resolved = substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    return next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")


def test_template_tracks_dc_validates_with_the_model_and_sets_no_colour_column() -> None:
    props = _tracks_dc({"DATA_ROOT": "/data"})["config"]["dc_specific_properties"]
    config = DCGenomicTracksConfig(**props)
    assert config.color_column is None
    assert config.order_column == "order"
    assert set(config.display_defaults) == {"bigwig", "bam"}
    schema = load_recipe("nf-core/rnaseq/tracks.py").OUTPUT_SCHEMA
    for column in (
        props["uri_column"],
        props["track_id_column"],
        props["sample_column"],
        props["format_column"],
        props["name_column"],
        props["category_column"],
        props["order_column"],
    ):
        assert column in schema, column

    config = DCGenomicTracksConfig(**{**props, "remote_base_uri": "s3://bucket/results"})
    assert config.remote_base_uri == "s3://bucket/results/"


def test_the_browser_colours_by_a_manifest_column_the_main_tab_declares() -> None:
    doc = yaml.safe_load(BASE.read_text())
    explorer = next(t for t in doc["tabs"] if t["title"] == "Gene Explorer")
    browser = next(c for c in explorer["components"] if c["component_type"] == "jbrowse")
    schema = load_recipe("nf-core/rnaseq/tracks.py").OUTPUT_SCHEMA
    assert browser["color_by"] in schema
    assert browser["color_by"] in doc["main_dashboard"]["category_colors"]
    # The opening tracks cover four conditions with their reads (junction arcs).
    assert browser["initial_tracks"] >= 12
    assert browser["show_junctions"] is True
