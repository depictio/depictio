"""nf-core/rnaseq pipeline-local recipes behind the QC profile and the gene record."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema


@pytest.mark.no_db
def test_general_stats_folds_read_rows_onto_their_library():
    module = load_recipe("nf-core/rnaseq/general_stats.py")
    raw = pl.DataFrame(
        {
            "Sample": [
                "ctrl_REP1",
                "ctrl_REP1 Read 1",
                "ctrl_REP1 Read 2",
                "ko_1",
                "ko_1_1",
                "ko_1_2",
            ],
            "star-uniquely_mapped_percent": ["90.1", "", "", "85.0", "", ""],
            # MultiQC 1.33 copies the per-read mean onto the sample row; older
            # reports leave it empty there, which the second library mimics.
            "fastqc_trimmed-percent_gc": ["50.0", "49.0", "51.0", "", "44.0", "46.0"],
            "qualimap_rnaseq-reads_aligned_exonic": ["80", "", "", "60", "", ""],
            "qualimap_rnaseq-reads_aligned_intronic": ["15", "", "", "30", "", ""],
            "qualimap_rnaseq-reads_aligned_intergenic": ["5", "", "", "10", "", ""],
        }
    ).with_columns(pl.all().replace("", None))
    out = module.transform({"stats": raw})
    validate_schema(out, module.OUTPUT_SCHEMA, "general_stats", None)

    assert out["sample"].to_list() == ["ctrl_REP1", "ko_1"]
    assert out["condition"].to_list() == ["ctrl", "ko"]
    rows = {r["sample"]: r for r in out.to_dicts()}
    assert rows["ctrl_REP1"]["pct_gc"] == 50.0  # the sample row wins
    assert rows["ko_1"]["pct_gc"] == 45.0  # the per-read mean fills the gap
    assert rows["ctrl_REP1"]["pct_exonic"] == pytest.approx(80.0)
    assert rows["ko_1"]["pct_uniquely_mapped"] == 85.0
    assert rows["ko_1"]["insert_size"] is None  # a module that did not run stays null


@pytest.mark.no_db
def test_gene_summary_ranks_genes_on_the_mean_variance_plane():
    module = load_recipe("nf-core/rnaseq/gene_summary.py")
    matrix = pl.DataFrame(
        {
            "gene_id": ["ENSG1", "ENSG2", "ENSG3"],
            "gene_name": ["FLAT", "PEAK", "OFF"],
            "A_REP1": [10.0, 1000.0, 0.1],
            "A_REP2": [10.0, 900.0, 0.2],
            "B_REP1": [10.0, 1.0, 0.0],
            "B_REP2": [10.0, 2.0, 0.3],
        }
    )
    out = module.transform({"matrix": matrix})
    validate_schema(out, module.OUTPUT_SCHEMA, "gene_summary", None)

    assert out["gene_name"].to_list() == ["PEAK", "FLAT"]  # OFF never reaches 1 TPM
    peak = out.row(0, named=True)
    assert peak["top_condition"] == "A"
    assert peak["top_sample"] == "A_REP1"
    assert peak["log2fc_top_vs_rest"] > 8
    assert out.filter(pl.col("gene_name") == "FLAT")["sd_log2_tpm"].item() == 0.0


def _matrix() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "gene_id": ["ENSG1", "ENSG2", "ENSG3"],
            "gene_name": ["FLAT", "PEAK", "PAR"],
            "A_REP1": [10.0, 1000.0, 5.0],
            "A_REP2": [10.0, 900.0, 5.0],
            "B_REP1": [10.0, 1.0, 5.0],
            "B_REP2": [10.0, 2.0, 5.0],
        }
    )


@pytest.mark.no_db
def test_gene_summary_carries_the_stringtie_coordinates():
    module = load_recipe("nf-core/rnaseq/gene_summary.py")
    stringtie = pl.DataFrame(
        {
            "Gene ID": ["ENSG1", "ENSG2", "ENSG2", "ENSG3", "ENSG3", "ENSG3"],
            "Gene Name": ["FLAT", "PEAK", "PEAK", "PAR", "PAR", "PAR"],
            "Reference": ["1", "11", "11", "X", "X", "Y"],
            "Strand": ["+", "-", "-", "+", "+", "+"],
            "Start": ["100", "5000", "4900", "10", "12", "10"],
            "End": ["900", "6000", "6100", "20", "25", "20"],
        }
    )
    out = module.transform({"matrix": _matrix(), "stringtie": stringtie})
    validate_schema(out, module.OUTPUT_SCHEMA, "gene_summary", None)

    rows = {r["gene_name"]: r for r in out.to_dicts()}
    assert (rows["FLAT"]["chrom"], rows["FLAT"]["start"], rows["FLAT"]["end"]) == ("1", 100, 900)
    # The widest span over the libraries.
    assert (rows["PEAK"]["start"], rows["PEAK"]["end"]) == (4900, 6100)
    # A gene id on two contigs keeps the contig most libraries report it on.
    assert (rows["PAR"]["chrom"], rows["PAR"]["start"], rows["PAR"]["end"]) == ("X", 10, 25)


@pytest.mark.no_db
def test_gene_summary_without_stringtie_has_null_coordinates():
    module = load_recipe("nf-core/rnaseq/gene_summary.py")
    for stringtie in (None, pl.DataFrame({"unrelated": ["x"]})):
        out = module.transform({"matrix": _matrix(), "stringtie": stringtie})
        validate_schema(out, module.OUTPUT_SCHEMA, "gene_summary", None)
        assert out["chrom"].null_count() == out.height
        assert out["start"].null_count() == out.height


@pytest.mark.no_db
def test_gene_explorer_browser_frames_genes_on_columns_the_recipe_writes():
    from pathlib import Path

    import yaml

    base = Path(__file__).parents[2] / "projects/nf-core/rnaseq/3.26.0/dashboards/base.yaml"
    doc = yaml.safe_load(base.read_text())
    assert "Genome tracks" not in [t["title"] for t in doc["tabs"]]
    explorer = next(t for t in doc["tabs"] if t["title"] == "Gene Explorer")
    browsers = [c for c in explorer["components"] if c["component_type"] == "jbrowse"]
    assert len(browsers) == 1
    locus = browsers[0]["locus_from"]
    schema = load_recipe("nf-core/rnaseq/gene_summary.py").OUTPUT_SCHEMA
    assert locus["data_collection_tag"] == "gene_summary"
    for key in ("chrom_column", "start_column", "end_column", "sort_by", "label_column"):
        assert locus[key] in schema, key
