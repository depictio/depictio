"""nf-core/rnavar genome-browser manifest and the design-group recipes behind the redone Overview.

The manifest lists the HaplotypeCaller VCF and the BAM of every sample of the hub,
with the design group as a column the tile colours by, and opens on the calls of one sample
per group followed by the reads of the strongest call's sample. The group recipes (window
lanes, replicate agreement, genotype concordance) read the calls and the hub. Nothing
here reads a real track file: the reference run is tables only.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/rnavar/1.3.0/template.yaml"

HUB = pl.DataFrame(
    {"sample": ["A_1", "A_2", "B_1", "B_2"], "cell_line": ["A", "A", "B", "B"]},
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _tracks(root: Path, hub: pl.DataFrame = HUB, extra: dict | None = None, **kwargs):
    return execute_recipe(
        "nf-core/rnavar/tracks.py",
        root,
        extra_sources={"hub": hub, **(extra or {})},
        params={"group_col": "cell_line"},
        **kwargs,
    )


def test_present_files_are_listed_vcfs_first_and_bams_need_their_index(tmp_path: Path) -> None:
    for s in ("A_1", "B_1"):
        _touch(
            tmp_path,
            f"variant_calling/{s}/{s}.haplotypecaller.filtered.vcf.gz",
            f"variant_calling/{s}/{s}.haplotypecaller.filtered.vcf.gz.tbi",
        )
    _touch(tmp_path, "preprocessing/A_1/A_1.md.bam", "preprocessing/A_1/A_1.md.bam.bai")
    _touch(tmp_path, "preprocessing/B_1/B_1.md.bam")  # no index: left out
    df = _tracks(tmp_path)
    assert df["track_id"].to_list() == [
        "A_1.haplotypecaller",
        "B_1.haplotypecaller",
        "A_1.alignments",
    ]
    assert df["format"].to_list() == ["vcf", "vcf", "bam"]
    assert df["order"].to_list() == [1, 2, 3]
    assert df["cell_line"].to_list() == ["A", "B", "A"]
    assert df["uri"].to_list()[-1] == "preprocessing/A_1/A_1.md.bam"


def test_annotated_vcf_comes_first_when_the_run_annotated(tmp_path: Path) -> None:
    ann = "annotation/A_1/A_1.haplotypecaller.filtered_snpEff.ann.vcf.gz"
    _touch(tmp_path, ann, ann + ".tbi")
    _touch(
        tmp_path,
        "variant_calling/A_1/A_1.haplotypecaller.filtered.vcf.gz",
        "variant_calling/A_1/A_1.haplotypecaller.filtered.vcf.gz.tbi",
    )
    assert _tracks(tmp_path)["uri"].to_list() == [ann]


def test_tables_only_run_keeps_every_row(tmp_path: Path) -> None:
    df = _tracks(tmp_path)
    assert df.height == 8
    # One call set per group, the reads of the first one, the other calls, the other reads.
    assert df["format"].to_list() == ["vcf", "vcf", "bam", "vcf", "vcf", "bam", "bam", "bam"]
    assert df["track_id"].is_unique().all()


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "variant_calling/A_1/A_1.haplotypecaller.filtered.vcf.gz",
        "variant_calling/A_1/A_1.haplotypecaller.filtered.vcf.gz.tbi",
    )
    df = _tracks(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 8
    assert df["uri"].to_list()[0] == "variant_calling/A_1/A_1.haplotypecaller.filtered.vcf.gz"


def _strongest(sample: str) -> pl.DataFrame:
    """Two calls per sample; `sample` holds the strongest of the run."""
    rows = [(s, 50.0 + (1000.0 if s == sample else 0.0)) for s in HUB["sample"]]
    return pl.DataFrame(rows, schema={"sample": pl.Utf8, "qual": pl.Float64}, orient="row")


def test_the_reads_of_the_strongest_call_open_beside_the_calls(tmp_path: Path) -> None:
    df = _tracks(tmp_path, extra={"variants": _strongest("B_2")})
    # B_2 stands for group B: its calls open, and its alignment follows them at once.
    assert df["track_id"].to_list()[:4] == [
        "A_1.haplotypecaller",
        "B_2.haplotypecaller",
        "B_2.alignments",
        "A_2.haplotypecaller",
    ]
    assert df.filter(pl.col("format") == "bam")["track_id"].to_list()[0] == "B_2.alignments"
    assert df["order"].to_list() == list(range(1, df.height + 1))


def test_a_bam_without_its_index_is_not_the_opening_reads(tmp_path: Path) -> None:
    for s in ("A_1", "B_2"):
        _touch(
            tmp_path,
            f"variant_calling/{s}/{s}.haplotypecaller.filtered.vcf.gz",
            f"variant_calling/{s}/{s}.haplotypecaller.filtered.vcf.gz.tbi",
        )
    _touch(tmp_path, "preprocessing/A_1/A_1.md.bam", "preprocessing/A_1/A_1.md.bam.bai")
    _touch(tmp_path, "preprocessing/B_2/B_2.md.bam")  # no index: left out
    df = _tracks(tmp_path, extra={"variants": _strongest("B_2")})
    assert df["track_id"].to_list() == [
        "A_1.haplotypecaller",
        "B_2.haplotypecaller",
        "A_1.alignments",
    ]


def test_without_a_design_the_group_is_one_constant_column(tmp_path: Path) -> None:
    df = execute_recipe(
        "nf-core/rnavar/tracks.py",
        tmp_path,
        extra_sources={"hub": HUB.select("sample")},
    )
    assert df["__no_group__"].unique().to_list() == ["All samples"]


def _calls() -> pl.DataFrame:
    def row(sample: str, key: str, gt: str = "0/1", pass_: bool = True, chrom: str = "chr1"):
        return {
            "sample": sample,
            "chrom": chrom,
            "pos": int(key.split(":")[1]),
            "variant_key": key,
            "variant_type": "SNP",
            "gt": gt,
            "is_pass": pass_,
        }

    return pl.DataFrame(
        [
            # A: both replicates call chr1:100, only A_1 calls chr1:200.
            row("A_1", "chr1:100"),
            row("A_2", "chr1:100", "1|0"),
            row("A_1", "chr1:200"),
            # B: one site called by both, one failed filter in B_2.
            row("B_1", "chr1:300", "1/1"),
            row("B_2", "chr1:300", "0/1"),
            row("B_2", "chr1:400", pass_=False),
        ],
        schema_overrides={"pos": pl.Int64},
    )


def test_replicate_sharing_counts_sites_every_sample_of_a_group_calls(tmp_path: Path) -> None:
    df = execute_recipe(
        "nf-core/rnavar/replicate_sharing.py",
        tmp_path,
        extra_sources={"variants": _calls(), "hub": HUB},
        params={"group_col": "cell_line"},
    )
    rows = {r["cell_line"]: r for r in df.iter_rows(named=True)}
    assert rows["A"]["samples"] == 2 and rows["A"]["sites"] == 2 and rows["A"]["shared_sites"] == 1
    assert rows["A"]["shared_pct"] == pytest.approx(50.0)
    # The genotype differs but the site is shared; the filtered call does not count.
    assert rows["B"]["sites"] == 1 and rows["B"]["shared_pct"] == pytest.approx(100.0)


def test_a_group_of_one_sample_has_no_share(tmp_path: Path) -> None:
    hub = pl.DataFrame({"sample": ["A_1"], "cell_line": ["A"]})
    df = execute_recipe(
        "nf-core/rnavar/replicate_sharing.py",
        tmp_path,
        extra_sources={"variants": _calls().filter(pl.col("sample") == "A_1"), "hub": hub},
        params={"group_col": "cell_line"},
    )
    assert df["shared_pct"].to_list() == [None]


def test_concordance_is_a_symmetric_matrix_of_shared_genotypes(tmp_path: Path) -> None:
    df = execute_recipe(
        "nf-core/rnavar/sample_concordance.py", tmp_path, extra_sources={"variants": _calls()}
    )
    assert df.columns == ["sample", "A_1", "A_2", "B_1", "B_2"]
    assert df["sample"].to_list() == ["A_1", "A_2", "B_1", "B_2"]
    m = {r["sample"]: r for r in df.iter_rows(named=True)}
    assert all(m[s][s] == 100.0 for s in m)
    # A_1 {100, 200} against A_2 {100}: one shared of two; "1|0" equals "0/1".
    assert m["A_1"]["A_2"] == m["A_2"]["A_1"] == pytest.approx(50.0)
    # Same site, different genotype: not a match.
    assert m["B_1"]["B_2"] == 0.0
    assert m["A_1"]["B_1"] == 0.0


def test_windows_split_by_group(tmp_path: Path) -> None:
    win = execute_recipe(
        "nf-core/rnavar/variant_windows.py",
        tmp_path,
        extra_sources={"variants": _calls(), "hub": HUB},
        params={"group_col": "cell_line"},
    )
    assert win.columns[3] == "cell_line"
    rows = {(r["cell_line"], r["pos"]): r for r in win.iter_rows(named=True)}
    assert set(rows) == {("A", 0), ("B", 0)}
    assert rows[("A", 0)]["variants"] == 2 and rows[("A", 0)]["samples"] == 2


def _template(variables: dict[str, str]) -> dict:
    return substitute_template_variables(yaml.safe_load(TEMPLATE.read_text()), variables)


def test_template_tracks_dc_validates_with_the_model() -> None:
    resolved = _template({"DATA_ROOT": "/data", "GENOME": "hg38", "GROUP_COL": "cell_line"})
    dcs = [dc for wf in resolved["workflows"] for dc in wf["data_collections"]]
    tracks = next(dc for dc in dcs if dc["data_collection_tag"] == "tracks")
    props = tracks["config"]["dc_specific_properties"]
    config = DCGenomicTracksConfig(**props)
    assert config.assembly == "hg38"
    assert set(config.display_defaults) == {"vcf"}
    assert tracks["config"]["transform"]["params"] == {"group_col": "cell_line"}
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
    for pair in (
        ("samples", "tracks"),
        ("tracks", "samples"),
        ("samples", "replicate_sharing"),
        ("samples", "variant_windows"),
        ("samples", "sample_concordance"),
    ):
        assert pair in links


def test_rows_open_on_one_sample_per_group_in_the_design_order(tmp_path: Path) -> None:
    hub = pl.DataFrame(
        {
            "sample": ["B_1", "B_2", "A_1", "A_2", "C_1"],
            "cell_line": ["B", "B", "A", "A", "C"],
        }
    )
    df = _tracks(tmp_path, hub=hub)
    vcfs = df.filter(pl.col("format") == "vcf")["sample"].to_list()
    # The hub lists B, A, C: one sample of each group first, then the replicates.
    assert vcfs == ["B_1", "A_1", "C_1", "A_2", "B_2"]
    assert df["order"].to_list() == list(range(1, df.height + 1))


def _vaf_calls() -> pl.DataFrame:
    rows = [
        # A_1: a het peak at 0.5 and a hom-alt one at 1.0, one shallow call and one filtered call.
        ("A_1", "SNP", 0.50, 12, True),
        ("A_1", "SNP", 0.52, 30, True),
        ("A_1", "INDEL", 1.00, 120, True),
        ("A_1", "SNP", 0.50, 9, True),  # under 10 reads: left out
        ("A_1", "SNP", 0.50, 40, False),  # failed a filter: left out
        # B_1: low fractions.
        ("B_1", "SNP", 0.12, 25, True),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "sample": pl.Utf8,
            "variant_type": pl.Utf8,
            "vaf": pl.Float64,
            "dp": pl.Int64,
            "is_pass": pl.Boolean,
        },
        orient="row",
    )


def test_allele_fractions_bin_the_deep_pass_calls_per_type_and_depth_class(tmp_path: Path) -> None:
    hub = pl.DataFrame({"sample": ["A_1", "B_1"], "cell_line": ["A", "B"]})
    df = execute_recipe(
        "nf-core/rnavar/allele_fractions.py",
        tmp_path,
        extra_sources={"variants": _vaf_calls(), "hub": hub},
        params={"group_col": "cell_line"},
    )
    assert df.columns == [
        "sample",
        "cell_line",
        "variant_type",
        "depth_class",
        "vaf_bin",
        "vaf",
        "calls",
    ]
    assert df["calls"].sum() == 4  # the shallow and the filtered call are not counted
    a_het = df.filter((pl.col("sample") == "A_1") & (pl.col("vaf_bin") == 0.5))
    assert sorted(a_het["depth_class"].to_list()) == ["10-19", "20-49"]
    assert a_het["vaf"].unique().to_list() == [0.525]
    # A fraction of exactly 1 falls in the last bin, not past it.
    hom = df.filter(pl.col("vaf_bin") == 0.95)
    assert hom["depth_class"].to_list() == ["100+"] and hom["variant_type"].to_list() == ["INDEL"]
    assert set(df.filter(pl.col("sample") == "B_1")["cell_line"]) == {"B"}


def test_allele_fractions_without_a_design_use_the_constant_group(tmp_path: Path) -> None:
    df = execute_recipe(
        "nf-core/rnavar/allele_fractions.py",
        tmp_path,
        extra_sources={"variants": _vaf_calls(), "hub": HUB.select("sample")},
    )
    assert df["__no_group__"].unique().to_list() == ["All samples"]


def test_template_routes_swap_the_replicate_agreement_for_the_tstv_card() -> None:
    rules = yaml.safe_load(TEMPLATE.read_text())["template"]["conditional"]

    absent = {
        tag
        for r in rules
        if r.get("if_var_absent") == "METADATA_FILE"
        for tag in r.get("remove_dc_tags", [])
    }
    present = {
        tag
        for r in rules
        if r.get("if_var_present") == "METADATA_FILE"
        for tag in r.get("remove_dc_tags", [])
    }
    # No design: no groups to compare replicates in, the Ts/Tv alternate takes the slot.
    assert "replicate_sharing" in absent and "vcf_callset_nodesign" not in absent
    assert present == {"vcf_callset_nodesign"}
