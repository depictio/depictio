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
import yaml

from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.cli.cli.utils.templates import substitute_template_variables
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig
from depictio.recipes import execute_recipe, load_recipe

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


def test_colours_follow_the_assay_and_the_reverse_strand_is_lighter(tmp_path: Path) -> None:
    df = _run(tmp_path)
    colour = dict(zip(df["track_id"].to_list(), df["color"].to_list(), strict=True))
    assert colour["F1.coverage.forward"] == colour["F2.coverage.forward"]
    assert colour["F1.coverage.forward"] != colour["R1.coverage"]
    assert colour["F1.coverage.forward"] != colour["F1.coverage.reverse"]
    assert all(c.startswith("rgb(") for c in colour.values())
    assert set(df["assay"].to_list()) == {"RNA-seq", "Ribo-seq"}


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
