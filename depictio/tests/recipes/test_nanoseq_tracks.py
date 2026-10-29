"""nanoseq's genome-track manifest: one bigWig and one BAM row per sample of the hub.

The manifest is spelled out from the ``samples`` hub and trimmed to the files the
run holds; read in place (``remote_base_uri``) every expected row is kept. It
carries the hub's condition under the name the dashboard's ``category_colors``
keys it by and no colour of its own. Nothing here reads a real track file: the
megatest subset is tables only, so the wiring is covered by these recipe and
template tests alone.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/nanoseq/3.0.0/template.yaml"

# The hub, sorted by sample id as samples.py writes it.
_HUB = pl.DataFrame(
    {
        "sample_id": ["A_R1", "A_R2", "B_R1", "B_R2"],
        "condition": ["A", "A", "B", "B"],
        "replicate": [1, 2, 1, 2],
    }
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, hub: pl.DataFrame = _HUB, **kwargs):
    return execute_recipe("nf-core/nanoseq/tracks.py", root, extra_sources={"hub": hub}, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "minimap2/bigwig/A_R1.bigWig",
        "minimap2/bigwig/B_R1.bigWig",
        "minimap2/A_R1.sorted.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == ["A_R1.alignments", "A_R1.coverage", "B_R1.coverage"]
    assert df["sample"].to_list() == ["A_R1", "A_R1", "B_R1"]
    assert df["format"].to_list() == ["bam", "bigwig", "bigwig"]
    assert df["uri"].to_list() == [
        "minimap2/A_R1.sorted.bam",
        "minimap2/bigwig/A_R1.bigWig",
        "minimap2/bigwig/B_R1.bigWig",
    ]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["category"].to_list() == ["Alignments", "Coverage", "Coverage"]


def test_a_run_holding_none_lists_every_file_alignments_before_coverage(tmp_path: Path) -> None:
    df = _run(tmp_path)
    assert df.height == 8
    # Replicate 1 of every condition before replicate 2; a sample's BAM before its
    # bigWig, so the opening tracks hold the reads the splice arcs are read from.
    assert df["track_id"].to_list() == [
        "A_R1.alignments",
        "A_R1.coverage",
        "B_R1.alignments",
        "B_R1.coverage",
        "A_R2.alignments",
        "A_R2.coverage",
        "B_R2.alignments",
        "B_R2.coverage",
    ]
    assert df["order"].to_list() == list(range(1, 9))
    assert df["format"].to_list() == ["bam", "bigwig"] * 4


def test_graphmap2_is_used_when_the_run_has_no_minimap2_output(tmp_path: Path) -> None:
    _touch(tmp_path, "graphmap2/bigwig/A_R1.bigWig", "graphmap2/A_R1.sorted.bam")
    df = _run(tmp_path)
    assert df["uri"].to_list() == ["graphmap2/A_R1.sorted.bam", "graphmap2/bigwig/A_R1.bigWig"]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "minimap2/A_R1.sorted.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 8
    assert df["track_id"].to_list()[-1] == "B_R2.coverage"
    assert df["uri"].to_list()[0] == "minimap2/A_R1.sorted.bam"


def test_the_manifest_writes_the_hubs_condition_and_no_colour(tmp_path: Path) -> None:
    # A colour column would win over color_by + category_colors in the browser.
    df = _run(tmp_path)
    assert "color" not in df.columns
    by_sample = dict(zip(df["sample"].to_list(), df["condition"].to_list(), strict=True))
    assert by_sample == {"A_R1": "A", "A_R2": "A", "B_R1": "B", "B_R2": "B"}


def test_the_condition_is_the_hubs_not_the_one_in_the_name(tmp_path: Path) -> None:
    # A design table can give the condition a factor the sample name does not spell.
    hub = _HUB.with_columns(pl.Series("condition", ["treated", "treated", "control", "control"]))
    df = _run(tmp_path, hub=hub)
    assert set(df["condition"].to_list()) == {"treated", "control"}
    # Replicate 1 of every condition opens first, the conditions in the hub's order.
    assert df["sample"].to_list()[:4] == ["A_R1", "A_R1", "B_R1", "B_R1"]


def test_a_sample_listed_twice_gets_one_row_per_file(tmp_path: Path) -> None:
    hub = pl.concat([_HUB, _HUB.head(1)])
    df = _run(tmp_path, hub=hub)
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
    # ... and so is the collection the browser opens on, written on every run.
    assert ("dexseq_results", "isoform_loci") in links


def test_template_tracks_dc_has_no_colour_column_and_keeps_the_condition() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg19"})
    props = _tracks_dc(resolved)["config"]["dc_specific_properties"]
    assert "color_column" not in props
    assert "color" not in props["columns_description"]
    assert "condition" in props["columns_description"]
    # The recipe's columns are the ones the DC documents.
    assert raw["template"]["conditional"][0]["remove_dc_tags"] == ["metadata", "design"]
