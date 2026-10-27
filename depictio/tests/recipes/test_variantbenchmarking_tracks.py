"""variantbenchmarking's genome-track manifest: FP, FN and TP files of every callset.

The manifest is spelled out from the aggregated rtg-tools (germline) and Truvari
(structural) summary tables and trimmed to the files (and indexes) the run holds;
read in place (``remote_base_uri``) every expected row is kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

RECIPE = "nf-core/variantbenchmarking/tracks.py"
TEMPLATE = (
    Path(__file__).resolve().parents[2] / "projects/nf-core/variantbenchmarking/1.4.0/template.yaml"
)

_RTG = (
    "Tool,File,Caller,Threshold,TP_base,TP_comp,FP,FN,Precision,Recall,F1\n"
    "cs2,cs2.TRUTH.callerb.summary.txt,callerb,None,10,10,1,1,0.9,0.9,0.9\n"
    "cs2,cs2.TRUTH.callerb.summary.txt,callerb,30.0,9,9,0,2,1.0,0.8,0.9\n"
    "cs1,cs1.TRUTH.callera.summary.txt,callera,None,10,10,1,5,0.9,0.7,0.8\n"
)
_TRUVARI = (
    "Tool,File,Caller,TP_base,TP_comp,FP,FN,Precision,Recall,F1\n"
    "sv1,sv1.TRUTH.manta.summary.json,manta,0,0,0,10,0.0,0.0,0.0\n"
)

_RTG_PATH = "small/summary/tables/rtgtools/rtgtools.summary.csv"
_TRUVARI_PATH = "structural/summary/tables/truvari/truvari.summary.csv"


def _stage(root: Path, rel: str, text: str = "") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _touch(root: Path, *rel_paths: str, index: bool = True) -> None:
    for rel in rel_paths:
        for path in [rel, rel + ".tbi"] if index else [rel]:
            _stage(root, path)


def test_germline_callsets_list_fp_fn_tp_each(tmp_path: Path) -> None:
    _stage(tmp_path, _RTG_PATH, _RTG)
    df = execute_recipe(RECIPE, tmp_path)
    # One block per callset, in the table's order, the threshold sweep collapsed.
    assert df["track_id"].to_list() == [
        "rtgtools.cs2.TRUTH.callerb.fp",
        "rtgtools.cs2.TRUTH.callerb.fn",
        "rtgtools.cs2.TRUTH.callerb.tp",
        "rtgtools.cs1.TRUTH.callera.fp",
        "rtgtools.cs1.TRUTH.callera.fn",
        "rtgtools.cs1.TRUTH.callera.tp",
    ]
    assert df["uri"].to_list()[:3] == [
        "small/cs2/benchmarks/rtgtools/cs2.TRUTH.callerb.fp.vcf.gz",
        "small/cs2/benchmarks/rtgtools/cs2.TRUTH.callerb.fn.vcf.gz",
        "small/cs2/benchmarks/rtgtools/cs2.TRUTH.callerb.tp.vcf.gz",
    ]
    assert df["sample_id"].to_list() == ["cs2"] * 3 + ["cs1"] * 3
    assert df["caller"].to_list()[:1] == ["callerb"]
    assert df["truth_set"].unique().to_list() == ["TRUTH"]
    assert df["kind"].to_list()[:3] == ["fp", "fn", "tp"]
    assert df["name"].to_list()[:3] == [
        "cs2 false positives",
        "cs2 false negatives",
        "cs2 true positives",
    ]
    assert df["format"].unique().to_list() == ["vcf"]
    assert df["order"].to_list() == list(range(1, 7))
    assert df["track_id"].n_unique() == df.height


def test_structural_callsets_use_truvari_names(tmp_path: Path) -> None:
    _stage(tmp_path, _TRUVARI_PATH, _TRUVARI)
    df = execute_recipe(RECIPE, tmp_path)
    assert df["uri"].to_list() == [
        "structural/sv1/benchmarks/truvari/sv1.TRUTH.manta.fp.vcf.gz",
        "structural/sv1/benchmarks/truvari/sv1.TRUTH.manta.fn.vcf.gz",
        "structural/sv1/benchmarks/truvari/sv1.TRUTH.manta.tp-comp.vcf.gz",
    ]
    assert df["kind"].to_list() == ["fp", "fn", "tp"]
    assert df["tool"].unique().to_list() == ["truvari"]


def test_a_truth_set_with_dots_keeps_its_name(tmp_path: Path) -> None:
    sheet = "Tool,File,Caller\ncs1,cs1.GIAB_v1.00.callera.summary.txt,callera\n"
    _stage(tmp_path, _RTG_PATH, sheet)
    df = execute_recipe(RECIPE, tmp_path)
    assert df["truth_set"].unique().to_list() == ["GIAB_v1.00"]
    assert (
        df["uri"].to_list()[0] == "small/cs1/benchmarks/rtgtools/cs1.GIAB_v1.00.callera.fp.vcf.gz"
    )


def test_both_routes_in_one_data_root_are_listed_in_order(tmp_path: Path) -> None:
    _stage(tmp_path, _RTG_PATH, _RTG)
    _stage(tmp_path, _TRUVARI_PATH, _TRUVARI)
    df = execute_recipe(RECIPE, tmp_path)
    assert df["tool"].to_list() == ["rtgtools"] * 6 + ["truvari"] * 3
    assert df["order"].to_list() == list(range(1, 10))


def test_files_that_are_missing_or_without_index_are_left_out_of_an_upload(tmp_path: Path) -> None:
    _stage(tmp_path, _RTG_PATH, _RTG)
    _touch(tmp_path, "small/cs1/benchmarks/rtgtools/cs1.TRUTH.callera.fp.vcf.gz")
    _touch(tmp_path, "small/cs1/benchmarks/rtgtools/cs1.TRUTH.callera.fn.vcf.gz", index=False)
    df = execute_recipe(RECIPE, tmp_path)
    assert df["uri"].to_list() == ["small/cs1/benchmarks/rtgtools/cs1.TRUTH.callera.fp.vcf.gz"]
    assert df["order"].to_list() == [1]


def test_a_run_holding_none_lists_every_expected_file(tmp_path: Path) -> None:
    _stage(tmp_path, _RTG_PATH, _RTG)
    assert execute_recipe(RECIPE, tmp_path).height == 6


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _stage(tmp_path, _RTG_PATH, _RTG)
    _touch(tmp_path, "small/cs1/benchmarks/rtgtools/cs1.TRUTH.callera.fp.vcf.gz")
    df = execute_recipe(RECIPE, tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 6


def test_a_run_without_either_summary_is_an_error(tmp_path: Path) -> None:
    _stage(tmp_path, "indel/summary/tables/rtgtools/rtgtools.summary.csv", _RTG)
    with pytest.raises(ValueError, match="variantbenchmarking tracks"):
        execute_recipe(RECIPE, tmp_path)


def _tracks_properties(variables: dict[str, str]) -> dict:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    dcs = template["workflows"][0]["data_collections"]
    dc = next(d for d in dcs if d["data_collection_tag"] == "tracks")
    assert dc["config"]["type"] == "genomic_tracks"
    assert dc["optional"] is True
    return substitute_template_variables(dc["config"]["dc_specific_properties"], variables)


def test_the_template_tracks_collection_validates() -> None:
    config = DCGenomicTracksConfig(**_tracks_properties({"GENOME": "hg19"}))
    assert config.assembly == "hg19"
    assert config.order_column == "order"
    assert set(config.display_defaults) == {"vcf"}
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
    names = {v["name"]: v for v in template["template"]["variables"]}
    assert {"GENOME", "TRACKS_URI"} <= set(names)
    assert names["GENOME"]["default"] == "hg38"
