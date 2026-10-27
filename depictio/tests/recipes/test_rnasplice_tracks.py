"""rnasplice's genome-track manifest: stranded bigWigs and a BAM per sample.

The manifest is spelled out from the validated samplesheet (runs of one sample
merged) and trimmed to the files the run holds; read in place
(``remote_base_uri``) every expected row is kept. Nothing here reads a real
track file: the reference run is tables only, so the wiring is covered by these
recipe and template tests alone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/rnasplice/1.0.4/template.yaml"

_SHEET = (
    "sample,fastq_1,fastq_2,strandedness,condition,single_end\n"
    "S1_T1,a.fq.gz,a2.fq.gz,auto,ctrl,false\n"
    "S1_T2,b.fq.gz,b2.fq.gz,auto,ctrl,false\n"
    "S2,c.fq.gz,c2.fq.gz,auto,ctrl,false\n"
    "S3,d.fq.gz,d2.fq.gz,auto,treated,false\n"
    "S4,e.fq.gz,e2.fq.gz,auto,treated,false\n"
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "pipeline_info").mkdir(exist_ok=True)
    (root / "pipeline_info" / "samplesheet.valid.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/rnasplice/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "star_salmon/bigwig/S1.forward.bigWig",
        "star_salmon/bigwig/S1.reverse.bigWig",
        "star_salmon/bigwig/S3.forward.bigWig",
        "star_salmon/S1_sorted.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "S1.coverage_forward",
        "S1.coverage_reverse",
        "S3.coverage_forward",
        "S1.alignments",
    ]
    assert df["format"].to_list() == ["bigwig", "bigwig", "bigwig", "bam"]
    assert df["order"].to_list() == [1, 2, 3, 4]
    assert df["uri"].to_list()[-1] == "star_salmon/S1_sorted.bam"


def test_runs_of_a_sample_collapse_and_every_file_is_listed_light_tracks_first(
    tmp_path: Path,
) -> None:
    df = _run(tmp_path)
    # 4 samples (S1_T1 and S1_T2 are one), 2 strands each, then the BAMs.
    assert df.height == 12
    assert df["sample"].unique(maintain_order=True).to_list() == ["S1", "S3", "S2", "S4"]
    assert df["format"].to_list() == ["bigwig"] * 8 + ["bam"] * 4
    assert df["order"].to_list() == list(range(1, 13))
    # The first sample of every condition comes before the second of any.
    assert df["track_id"].to_list()[:4] == [
        "S1.coverage_forward",
        "S1.coverage_reverse",
        "S3.coverage_forward",
        "S3.coverage_reverse",
    ]
    assert df["track_id"].is_unique().all()


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "star_salmon/S1_sorted.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 12
    assert df["track_id"].to_list()[-1] == "S4.alignments"


def test_colours_follow_the_condition_and_the_reverse_strand_is_lighter(tmp_path: Path) -> None:
    df = _run(tmp_path)
    colour = dict(zip(df["track_id"].to_list(), df["color"].to_list(), strict=True))
    assert colour["S1.coverage_forward"] == colour["S2.coverage_forward"] == colour["S1.alignments"]
    assert colour["S1.coverage_forward"] != colour["S3.coverage_forward"]
    assert colour["S1.coverage_forward"] != colour["S1.coverage_reverse"]
    assert all(c.startswith("rgb(") for c in colour.values())
    assert set(df["condition"].to_list()) == {"ctrl", "treated"}


def _template(variables: dict[str, str]) -> dict:
    return substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)


def test_template_tracks_dc_validates_with_the_model() -> None:
    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg19"})
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    props = tracks["config"]["dc_specific_properties"]
    config = DCGenomicTracksConfig(**props)
    assert config.assembly == "hg19"
    assert get_assembly_preset("hg19") is not None
    assert set(config.display_defaults) == {"bigwig", "bam"}
    assert (
        DCGenomicTracksConfig(**{**props, "remote_base_uri": "s3://bucket/results"}).remote_base_uri
        == "s3://bucket/results/"
    )


def test_template_wires_the_override_and_the_links() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    variables = {v["name"]: v for v in raw["template"]["variables"]}
    assert get_assembly_preset(variables["GENOME"]["default"]) is not None
    assert "TRACKS_URI" in variables
    rules = [r for r in raw["template"]["conditional"] if r.get("if_var_present") == "TRACKS_URI"]
    assert len(rules) == 1
    override = rules[0]["override_dcs"][0]
    assert override["data_collection_tag"] == "tracks"
    assert override["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}

    links = {(link["source_dc_tag"], link["target_dc_tag"]) for link in raw["links"]}
    assert ("samples", "tracks") in links
    assert ("tracks", "samples") in links
