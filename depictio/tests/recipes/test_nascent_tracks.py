"""nascent's genome-track manifest: the strand bigWigs of every library, with its time point.

The manifest lists the plus and minus bigWig of each library of the hub in time order, each
plus strand above its minus strand, and carries the time point and its rank so the browser can colour
the tracks along a ramp (``color_scale``), the binned lanes of the Genome signal tab
wearing the same colours. Nothing here reads a real bigWig.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/nascent/2.3.0/template.yaml"
DASHBOARD = Path(__file__).parents[2] / "projects/nf-core/nascent/2.3.0/dashboards/base.yaml"

HUB = pl.DataFrame(
    {
        "sample": ["L_12h", "L_0h", "L_2h"],
        "time_point": ["12 h", "0 h", "2 h"],
        "time_order": [3, 1, 2],
    },
    schema_overrides={"time_order": pl.Int64},
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, **kwargs):
    return execute_recipe(
        "nf-core/nascent/tracks.py", root, extra_sources={"samples": HUB}, **kwargs
    )


def test_tracks_follow_the_time_course_and_carry_the_time_point(tmp_path: Path) -> None:
    for s in HUB["sample"]:
        _touch(tmp_path, f"coverage_graphs/{s}.plus.bigWig", f"coverage_graphs/{s}.minus.bigWig")
    df = _run(tmp_path)
    # In time order (12 h after 2 h, whatever the labels sort like), plus above minus.
    assert df["track_id"].to_list() == [
        "L_0h.plus",
        "L_0h.minus",
        "L_2h.plus",
        "L_2h.minus",
        "L_12h.plus",
        "L_12h.minus",
    ]
    assert df["time_point"].to_list()[::2] == ["0 h", "2 h", "12 h"]
    assert df["time_order"].to_list() == [1, 1, 2, 2, 3, 3]
    assert df["order"].to_list() == list(range(1, 7))
    assert df["format"].unique().to_list() == ["bigwig"]


def test_every_library_reads_down_in_time_order(tmp_path: Path) -> None:
    hub = pl.DataFrame(
        {
            "sample": [f"L_{h}h" for h in (8, 0, 4, 1, 2)],
            "time_point": [f"{h} h" for h in (8, 0, 4, 1, 2)],
            "time_order": [5, 1, 4, 2, 3],
        },
        schema_overrides={"time_order": pl.Int64},
    )
    for s in hub["sample"]:
        _touch(tmp_path, f"coverage_graphs/{s}.plus.bigWig", f"coverage_graphs/{s}.minus.bigWig")
    df = execute_recipe("nf-core/nascent/tracks.py", tmp_path, extra_sources={"samples": hub})
    assert df["track_id"].to_list() == [
        f"L_{h}h.{strand}" for h in (0, 1, 2, 4, 8) for strand in ("plus", "minus")
    ]


def test_read_in_place_lists_both_strands_of_every_library(tmp_path: Path) -> None:
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 6
    assert df["uri"].to_list()[0] == "coverage_graphs/L_0h.plus.bigWig"


def test_browser_opens_on_every_track() -> None:
    dash = yaml.safe_load(DASHBOARD.read_text())
    tab = next(t for t in dash["tabs"] if t["title"] == "Genome signal")
    browser = next(c for c in tab["components"] if c["component_type"] == "jbrowse")
    # Every bigWig open, the time course reading down the tile.
    assert browser["initial_tracks"] == browser["max_tracks"] >= 2 * 11


def _template(variables: dict[str, str]) -> dict:
    return substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)


def test_template_wires_the_tracks_collection() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    variables = {v["name"]: v for v in raw["template"]["variables"]}
    assert get_assembly_preset(variables["GENOME"]["default"]) is not None
    rules = [r for r in raw["template"]["conditional"] if r.get("if_var_present") == "TRACKS_URI"]
    assert rules[0]["override_dcs"][0]["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}

    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg38"})
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    config = DCGenomicTracksConfig(**tracks["config"]["dc_specific_properties"])
    assert config.assembly == "hg38"
    assert "time_point" in tracks["config"]["dc_specific_properties"]["columns_description"]


def test_browser_colours_the_tracks_along_the_time_course() -> None:
    dash = yaml.safe_load(DASHBOARD.read_text())
    tab = next(t for t in dash["tabs"] if t["title"] == "Genome signal")
    browser = next(c for c in tab["components"] if c["component_type"] == "jbrowse")
    assert browser["color_scale"] == {
        "column": "time_point",
        "order_by": "time_order",
        "scheme": "viridis",
    }
    assert "color_by" not in browser


def test_replicates_of_a_time_point_sit_together_by_name(tmp_path: Path) -> None:
    hub = pl.DataFrame(
        {
            "sample": ["L_0h_b", "L_0h_a", "L_2h_a", "L_2h_b"],
            "time_point": ["0 h", "0 h", "2 h", "2 h"],
            "time_order": [1, 1, 2, 2],
        },
        schema_overrides={"time_order": pl.Int64},
    )
    for s in hub["sample"]:
        _touch(tmp_path, f"coverage_graphs/{s}.plus.bigWig", f"coverage_graphs/{s}.minus.bigWig")
    df = execute_recipe("nf-core/nascent/tracks.py", tmp_path, extra_sources={"samples": hub})
    assert df["track_id"].to_list() == [
        "L_0h_a.plus",
        "L_0h_a.minus",
        "L_0h_b.plus",
        "L_0h_b.minus",
        "L_2h_a.plus",
        "L_2h_a.minus",
        "L_2h_b.plus",
        "L_2h_b.minus",
    ]
