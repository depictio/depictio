"""riboseq's genome-track manifest: P-sites, coverage and a BAM per library.

The manifest is spelled out from the samplesheet and trimmed to the files the
run holds; read in place (``remote_base_uri``) every expected row is kept.
Nothing here reads a real track file: the megatest subset is tables only, so the
wiring is covered by these recipe and template tests alone. The ORF coordinates
the genome browser frames come from the pooled ORF table (``orf_overlap``).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe, validate_schema

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/riboseq/2.0.0/template.yaml"

_SHEET = (
    "sample,fastq_1,fastq_2,strandedness,type\n"
    "R1,r1_1.fq.gz,r1_2.fq.gz,auto,rnaseq\n"
    "R2,r2_1.fq.gz,r2_2.fq.gz,auto,rnaseq\n"
    "F1,f1_1.fq.gz,f1_2.fq.gz,auto,riboseq\n"
    "F2,f2_1.fq.gz,f2_2.fq.gz,auto,riboseq\n"
)


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _run(root: Path, sheet: str = _SHEET, **kwargs):
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / "samplesheet.csv").write_text(sheet, encoding="utf-8")
    return execute_recipe("nf-core/riboseq/tracks.py", root, **kwargs)


def test_missing_files_are_dropped(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "psites/plastid/tracks/F1_fw.bedgraph",
        "coverage/R1.unstranded.bigWig",
        "coverage/F1.forward.bigWig",
        "alignment/star/sorted/F1.genome.sorted.bam",
    )
    df = _run(tmp_path)
    assert df["track_id"].to_list() == [
        "R1.coverage",
        "F1.coverage.forward",
        "F1.psites.forward",
        "F1.alignments",
    ]
    assert df["format"].to_list() == ["bigwig", "bigwig", "bedgraph", "bam"]
    assert df["order"].to_list() == [1, 2, 3, 4]
    assert df["sample"].to_list() == ["R1", "F1", "F1", "F1"]


def test_a_run_holding_none_lists_every_file_light_tracks_first(tmp_path: Path) -> None:
    df = _run(tmp_path)
    kinds = df["kind"].to_list()
    # Coverage (range-read bigWig), then the P-sites (footprint libraries only,
    # plain-text bedGraph), then the BAMs.
    assert kinds == ["coverage"] * 6 + ["psites"] * 4 + ["alignments"] * 4
    assert df["format"].to_list()[-4:] == ["bam"] * 4
    assert df["order"].to_list() == list(range(1, df.height + 1))
    assert "R1.psites.forward" not in df["track_id"].to_list()
    # Total mRNA reads unstranded by default, footprints stranded.
    assert "R1.coverage" in df["track_id"].to_list()
    assert "F1.coverage.reverse" in df["track_id"].to_list()
    assert df.filter(pl.col("track_id") == "R1.coverage")["uri"].item() == (
        "coverage/R1.unstranded.bigWig"
    )


def test_first_library_of_every_assay_comes_before_the_second(tmp_path: Path) -> None:
    df = _run(tmp_path)
    coverage = df.filter(pl.col("kind") == "coverage")["sample"].unique(maintain_order=True)
    assert coverage.to_list() == ["R1", "F1", "R2", "F2"]
    bams = df.filter(pl.col("kind") == "alignments")["sample"].to_list()
    assert bams == ["R1", "F1", "R2", "F2"]


def test_declared_strandedness_wins_over_the_assay_default(tmp_path: Path) -> None:
    sheet = (
        "sample,fastq_1,strandedness,type\n"
        "R1,r1.fq.gz,reverse,rnaseq\n"
        "F1,f1.fq.gz,unstranded,riboseq\n"
    )
    df = _run(tmp_path, sheet=sheet)
    ids = df["track_id"].to_list()
    assert "R1.coverage.forward" in ids and "R1.coverage.reverse" in ids
    assert "F1.coverage" in ids and "F1.coverage.forward" not in ids


def test_the_layout_the_run_holds_wins_over_the_guess(tmp_path: Path) -> None:
    # R1 was inferred stranded although it is total mRNA: the files say so.
    _touch(tmp_path, "coverage/R1.forward.bigWig", "coverage/R1.reverse.bigWig")
    df = _run(tmp_path)
    assert df["uri"].to_list() == ["coverage/R1.forward.bigWig", "coverage/R1.reverse.bigWig"]


def test_read_in_place_keeps_every_row(tmp_path: Path) -> None:
    _touch(tmp_path, "alignment/star/sorted/R1.genome.sorted.bam")
    df = _run(tmp_path, properties={"remote_base_uri": "s3://bucket/results"})
    assert df.height == 14
    assert df["track_id"].to_list()[-1] == "F2.alignments"


def test_the_manifest_carries_no_colour_and_names_the_assay(tmp_path: Path) -> None:
    # A colour column would win over the dashboard's colours; the tile colours by
    # the design group instead.
    df = _run(tmp_path)
    assert "color" not in df.columns
    assert set(df["assay"].to_list()) == {"RNA-seq", "Ribo-seq"}


_DESIGN_SHEET = (
    "sample,fastq_1,fastq_2,strandedness,type,sample_description,treatment\n"
    "R1,r1_1.fq.gz,r1_2.fq.gz,auto,rnaseq,rna_c1,control\n"
    "R2,r2_1.fq.gz,r2_2.fq.gz,auto,rnaseq,rna_c2,control\n"
    "R3,r3_1.fq.gz,r3_2.fq.gz,auto,rnaseq,rna_t1,treated\n"
    "F1,f1_1.fq.gz,,auto,riboseq,ribo_c1,control\n"
    "F2,f2_1.fq.gz,,auto,riboseq,ribo_c2,control\n"
    "F3,f3_1.fq.gz,,auto,riboseq,ribo_t1,treated\n"
)


def test_the_group_column_is_named_by_group_col_and_opening_tracks_cover_the_design(
    tmp_path: Path,
) -> None:
    df = _run(tmp_path, sheet=_DESIGN_SHEET, params={"group_col": "treatment"})
    assert "treatment" in df.columns
    by_sample = dict(zip(df["sample"].to_list(), df["treatment"].to_list(), strict=True))
    assert by_sample == {
        "R1": "control",
        "R2": "control",
        "R3": "treated",
        "F1": "control",
        "F2": "control",
        "F3": "treated",
    }
    # One control and one treated library of each assay open first (coverage: one
    # track for total mRNA, a forward / reverse pair for the footprints).
    opening = df.head(6)
    assert opening["sample"].to_list() == ["R1", "R3", "F1", "F1", "F3", "F3"]
    assert set(opening["kind"].to_list()) == {"coverage"}
    # The second control library comes after the representatives.
    assert df["sample"].to_list().index("R2") > 5


def test_the_group_comes_from_the_design_table_when_it_has_the_column(tmp_path: Path) -> None:
    design = pl.DataFrame(
        {
            "sample": ["R1", "R2", "F1", "F2"],
            "condition": ["a", "b", "a", "b"],
            "sample_description": ["lib_r1", "lib_r2", "lib_f1", "lib_f2"],
        }
    )
    df = _run(tmp_path, params={"group_col": "condition"}, extra_sources={"metadata": design})
    assert dict(zip(df["sample"].to_list(), df["condition"].to_list(), strict=True)) == {
        "R1": "a",
        "R2": "b",
        "F1": "a",
        "F2": "b",
    }
    # The library's description names its tracks.
    assert df.filter(pl.col("track_id") == "R1.coverage")["name"].item() == "lib_r1 coverage"


def test_without_a_design_group_the_column_is_constant(tmp_path: Path) -> None:
    df = _run(tmp_path, params={"group_col": "__no_group__"})
    assert df["__no_group__"].unique().to_list() == ["All libraries"]
    # A group column the run does not hold still gets its column, so color_by matches.
    other = _run(tmp_path, params={"group_col": "missing"})
    assert other["missing"].unique().to_list() == ["All libraries"]


def test_track_names_use_the_description_of_the_sheet(tmp_path: Path) -> None:
    df = _run(tmp_path, sheet=_DESIGN_SHEET, params={"group_col": "treatment"})
    row = df.filter(pl.col("track_id") == "F1.psites.forward").row(0, named=True)
    assert row["name"] == "ribo_c1 P-sites forward"
    assert row["sample"] == "F1"


def test_orf_overlap_carries_the_contig_and_a_span_to_frame() -> None:
    def orfs(ids: list[str], klass: str, aa: int) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "sample": ["l1"] * len(ids),
                "orf_id": ids,
                "gene_id": ["G"] * len(ids),
                "gene_name": ["S"] * len(ids),
                "gene_type": ["protein_coding"] * len(ids),
                "orf_class": [klass] * len(ids),
                "aa_length": [aa] * len(ids),
            }
        )

    module = load_recipe("nf-core/riboseq/orf_overlap.py")
    out = module.transform(
        {
            "ribotish": orfs(["1:+:1000", "7:-:500", "HLA-A*01:01:+:30"], "Annotated CDS", 100),
            "ribocode": orfs(["1:+:10"], "Upstream ORF", 20),
        }
    )
    rows = {r["orf_id"]: r for r in out.to_dicts()}
    # Forward strand: the ORF reaches back from the stop codon.
    assert (rows["1:+:1000"]["chrom"], rows["1:+:1000"]["orf_start"]) == ("1", 700)
    assert rows["1:+:1000"]["orf_end"] == 1000
    # Reverse strand: it reaches forward in genome coordinates.
    assert (rows["7:-:500"]["orf_start"], rows["7:-:500"]["orf_end"]) == (500, 800)
    # A contig name with a colon stays whole; a short reach is clamped at 1.
    assert rows["HLA-A*01:01:+:30"]["chrom"] == "HLA-A*01:01"
    assert rows["1:+:10"]["orf_start"] == 1


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
    assert set(config.display_defaults) == {"bedgraph", "bigwig", "bam"}
    # The manifest colour would win over the dashboard's: the tile colours by the group.
    assert config.color_column is None
    assert tracks["config"]["transform"]["params"]["group_col"]
    assert (
        DCGenomicTracksConfig(
            **{**props, "remote_base_uri": "https://host/results"}
        ).remote_base_uri
        == "https://host/results/"
    )

    # The ORF table the browser frames from carries the coordinate columns.
    orf = next(dc for dc in dcs if dc["data_collection_tag"] == "orf_overlap")
    described = orf["config"]["dc_specific_properties"]["columns_description"]
    assert {"chrom", "orf_start", "orf_end"} <= set(described)


def test_template_wires_the_genome_variable_the_override_and_the_links() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    variables = {v["name"]: v for v in raw["template"]["variables"]}
    assert variables["GENOME"]["default"] == "hg38"
    assert "TRACKS_URI" in variables
    rules = [r for r in raw["template"]["conditional"] if r.get("if_var_present") == "TRACKS_URI"]
    assert len(rules) == 1
    override = rules[0]["override_dcs"][0]
    assert override["data_collection_tag"] == "tracks"
    assert override["dc_properties"] == {"remote_base_uri": "{TRACKS_URI}"}

    links = {(link["source_dc_tag"], link["target_dc_tag"]) for link in raw["links"]}
    assert ("samples", "tracks") in links
    assert ("tracks", "samples") in links

    tags = [dc["data_collection_tag"] for wf in raw["workflows"] for dc in wf["data_collections"]]
    assert "tracks" in tags


def test_orf_overlap_ranks_new_orfs_both_callers_report_first() -> None:
    def orfs(rows: list[tuple[str, str, int, str]]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "sample": [r[3] for r in rows],
                "orf_id": [r[0] for r in rows],
                "gene_id": ["G"] * len(rows),
                "gene_name": ["S"] * len(rows),
                "gene_type": ["protein_coding"] * len(rows),
                "orf_class": [r[1] for r in rows],
                "aa_length": [r[2] for r in rows],
            }
        )

    # annotated: both callers, longest protein; new_both: both callers; new_one: one caller
    # in two libraries; new_short: both callers, shorter than new_both.
    tish = orfs(
        [
            ("1:+:900", "Annotated CDS", 900, "l1"),
            ("1:+:500", "Novel ORF", 100, "l1"),
            ("1:+:600", "Novel ORF", 300, "l1"),
            ("1:+:600", "Novel ORF", 300, "l2"),
            ("1:+:700", "Novel ORF", 50, "l1"),
        ]
    )
    code = orfs(
        [
            ("1:+:900", "Annotated CDS", 900, "l1"),
            ("1:+:500", "Novel ORF", 100, "l1"),
            ("1:+:700", "Novel ORF", 50, "l1"),
        ]
    )
    module = load_recipe("nf-core/riboseq/orf_overlap.py")
    out = module.transform({"ribotish": tish, "ribocode": code})
    validate_schema(out, module.OUTPUT_SCHEMA, "orf_overlap", None)
    ranked = out.sort("support_score", descending=True)["orf_id"].to_list()
    assert ranked == ["1:+:500", "1:+:700", "1:+:600", "1:+:900"]
    assert out["support_score"].dtype == pl.Int64
    # A skipped caller leaves every ORF a one-caller ORF, still ranked.
    only = module.transform({"ribotish": tish})
    assert only.sort("support_score", descending=True)["orf_id"].to_list()[0] == "1:+:600"


def test_library_summary_adds_the_group_and_the_description() -> None:
    module = load_recipe("nf-core/riboseq/library_summary.py")
    frames = pl.DataFrame(
        {
            "sample": ["F1.ribowaltz", "F1.ribowaltz", "F2.ribowaltz", "F2.ribowaltz"],
            "region": ["CDS", "CDS", "CDS", "CDS"],
            "frame": [0, 1, 0, 1],
            "count": [70, 30, 40, 60],
        }
    )
    regions = pl.DataFrame(
        {
            "sample": ["F1.ribowaltz", "F1.ribowaltz", "RNAs", "F2.ribowaltz", "F2.ribowaltz"],
            "region": ["CDS", "3' UTR", "CDS", "CDS", "3' UTR"],
            "count": [80.0, 20.0, 50.0, 60.0, 40.0],
            "source_path": ["a", "a", "a", "b", "b"],
        }
    )
    lengths = pl.DataFrame(
        {
            "sample": ["F1.ribowaltz", "F1.ribowaltz", "F2.ribowaltz", "F2.ribowaltz"],
            "length": [27, 28, 27, 28],
            "count": [10, 90, 50, 50],
        }
    )
    sheet = pl.DataFrame(
        {
            "sample": ["F1", "F2"],
            "treatment": ["control", "treated"],
            "sample_description": ["ribo_c1", "ribo_t1"],
        }
    )
    sources = {"frames": frames, "regions": regions, "lengths": lengths, "samplesheet": sheet}
    out = module.transform({**sources, "metadata": None}, params={"group_col": "treatment"})
    validate_schema(out, module.OUTPUT_SCHEMA, "library_summary", module.OPTIONAL_OUTPUT_SCHEMA)
    rows = {r["sample"]: r for r in out.to_dicts()}
    assert rows["F1"]["treatment"] == "control"
    assert rows["F2"]["sample_description"] == "ribo_t1"
    # The catalog's own columns are untouched.
    assert rows["F1"]["frame0_cds_pct"] == pytest.approx(70.0)

    plain = module.transform({**sources, "metadata": None}, params={"group_col": "__no_group__"})
    assert "treatment" not in plain.columns and "__no_group__" not in plain.columns
