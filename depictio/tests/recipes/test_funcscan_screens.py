"""The nf-core/funcscan recipes added for the four-screen dashboard.

Each test builds the recipe's real input shape in a temp dir (or injects the
``dc_ref`` frames), runs it through ``execute_recipe`` so the engine enforces
``EXPECTED_SCHEMA``, and checks the binding the dashboard relies on with
``validate_binding``.

The interesting cases are the ones the megatest run exposed and a fixture
cannot: a contig name that does not carry ``length-``/``cov-``, the three ARG
drug-class vocabularies that have to fold onto one row, and a comBGC region
that has no strand at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from depictio.models.components.advanced_viz.configs import (
    ComplexHeatmapConfig,
    CoverageTrackConfig,
    GeneArrowTrackConfig,
    ScatterXyConfig,
)
from depictio.models.components.advanced_viz.schemas import validate_binding
from depictio.recipes import execute_recipe


def _schema_names(df: pl.DataFrame) -> dict[str, str]:
    return {name: str(dtype) for name, dtype in df.schema.items()}


def _contig(sample: str, node: int, length: int, cov: float) -> str:
    """A contig name in the shape the MGnify assemblies use."""
    return f"{sample}.{node}-NODE-{node}-length-{length}-cov-{cov}"


# ---------------------------------------------------------------------------
# funcscan/contig_annotation: the locus layer rebuilt from the four screens
# ---------------------------------------------------------------------------


def test_contig_annotation_counts_every_screen(tmp_path: Path) -> None:
    long_contig = _contig("S1", 16, 49668, 9.81)
    short_contig = _contig("S1", 1029, 1602, 1.46)

    arg = pl.DataFrame({"sample": ["S1", "S1"], "contig": [long_contig, short_contig]})
    amp = pl.DataFrame({"sample": ["S1"], "contig": [long_contig]})
    bgc = pl.DataFrame({"sample": ["S1"], "contig": [long_contig]})
    cazyme = pl.DataFrame({"sample": ["S1"] * 3, "contig": [long_contig] * 3})

    result = execute_recipe(
        "funcscan/contig_annotation.py",
        tmp_path,
        extra_sources={
            "arg": arg,
            "amp": amp,
            "bgc": bgc,
            "cazyme": cazyme,
        },
    )

    rows = {r["contig"]: r for r in result.to_dicts()}
    assert set(rows) == {long_contig, short_contig}

    long_row = rows[long_contig]
    assert long_row["arg_hits"] == 1
    assert long_row["amp_candidates"] == 1
    assert long_row["bgc_regions"] == 1
    assert long_row["cazyme_genes"] == 3
    assert long_row["features"] == 6
    assert long_row["screens_on_contig"] == 4
    # CAZyme contributes 3 of the 6, so it leads.
    assert long_row["top_screen"] == "CAZyme"
    # Length and coverage come out of the contig name, not out of a screen.
    assert long_row["contig_length"] == 49668
    assert long_row["contig_coverage"] == 9.81

    short_row = rows[short_contig]
    assert short_row["screens_on_contig"] == 1
    assert short_row["top_screen"] == "ARG"

    cfg = ScatterXyConfig(
        x_col="contig_length",
        y_col="features",
        label_col="contig",
        color_col="top_screen",
        size_col="features_per_kb",
    )
    assert validate_binding(cfg, _schema_names(result)) == []


def test_contig_annotation_keeps_a_contig_with_no_length_in_its_name(tmp_path: Path) -> None:
    """A different assembler names contigs differently; the row must survive."""
    arg = pl.DataFrame({"sample": ["S1"], "contig": ["scaffold_00017"]})

    result = execute_recipe(
        "funcscan/contig_annotation.py",
        tmp_path,
        extra_sources={"arg": arg},
    )

    row = result.to_dicts()[0]
    assert row["contig"] == "scaffold_00017"
    assert row["features"] == 1
    # No length in the name: the row stays, the density axis just has no value.
    assert row["contig_length"] is None
    assert row["features_per_kb"] is None


def test_contig_annotation_zero_fills_a_screen_that_did_not_run(tmp_path: Path) -> None:
    contig = _contig("S1", 5, 2000, 3.5)
    result = execute_recipe(
        "funcscan/contig_annotation.py",
        tmp_path,
        extra_sources={"bgc": pl.DataFrame({"sample": ["S1"], "contig": [contig]})},
    )
    row = result.to_dicts()[0]
    assert row["bgc_regions"] == 1
    assert row["arg_hits"] == 0
    assert row["amp_candidates"] == 0
    assert row["cazyme_genes"] == 0
    assert row["screens_on_contig"] == 1


# ---------------------------------------------------------------------------
# funcscan/software_versions: the only payload funcscan's MultiQC report holds
# ---------------------------------------------------------------------------


def test_software_versions_labels_the_screen_each_process_belongs_to(tmp_path: Path) -> None:
    payload = {
        "ABRICATE_RUN": {"abricate": ["1.0.1"]},
        "AMP_HMMER_HMMSEARCH": {"hmmer": ["3.4"]},
        "ANTISMASH_ANTISMASH": {"antismash": ["8.0.1"]},
        "CAZYME_DBCAN": {"dbcan": ["5.1.2"]},
        "PYRODIGAL": {"pyrodigal": ["3.6.3"]},
        "UNTAR": {"untar": ["1.34"]},
    }
    report = tmp_path / "multiqc" / "multiqc_data"
    report.mkdir(parents=True)
    pl.DataFrame(
        {"anchor": ["run_metadata"], "software_versions": [json.dumps(payload)]}
    ).write_parquet(report / "multiqc.parquet")

    result = execute_recipe("funcscan/software_versions.py", tmp_path)

    by_process = {r["process"]: r for r in result.to_dicts()}
    assert by_process["ABRICATE_RUN"]["screen"] == "ARG"
    assert by_process["AMP_HMMER_HMMSEARCH"]["screen"] == "AMP"
    assert by_process["ANTISMASH_ANTISMASH"]["screen"] == "BGC"
    assert by_process["CAZYME_DBCAN"]["screen"] == "CAZyme"
    assert by_process["PYRODIGAL"]["screen"] == "Annotation"
    # Plumbing is labelled, not dropped, so the table accounts for the run.
    assert by_process["UNTAR"]["screen"] == "Workflow"
    assert by_process["ABRICATE_RUN"]["version"] == "1.0.1"
    assert result["tools"].sum() == len(payload)


# ---------------------------------------------------------------------------
# combgc/region_track: the coordinate view the three track tiles read
# ---------------------------------------------------------------------------


_COMBGC_HEADER = (
    "sample_id\tcontig_id\tPrediction_tool\tProduct_class\tBGC_probability\tBGC_complete\t"
    "BGC_start\tBGC_end\tBGC_length\tBGC_region_contig_ids\tCDS_count\tPFAM_domains\t"
    "MIBiG_ID\tInterPro_ID\n"
)


def test_region_track_mints_coordinates_and_a_blank_strand(tmp_path: Path) -> None:
    contig = _contig("S1", 16, 49668, 9.81)
    out = tmp_path / "reports" / "combgc"
    out.mkdir(parents=True)
    (out / "combgc_complete_summary.tsv").write_text(
        _COMBGC_HEADER
        + f"S1\t{contig}\tantiSMASH\tArylpolyene\tNA\tNo\t18134\t49668\t31535\tNA\t31\tPF1;PF2\tNA\tNA\n"
        + f"S1\t{contig}\tGECCO\tTerpene\t0.82\tNA\t100\t1200\t1101\tNA\t2\tPF3\tNA\tNA\n"
    )

    result = execute_recipe("combgc/region_track.py", tmp_path)

    assert result.height == 2
    rows = sorted(result.to_dicts(), key=lambda r: r["start"])
    # Tool, class, contig and interval: the only combination unique per row.
    assert rows[0]["region_id"] == f"GECCO Terpene {contig}:100-1200"
    assert rows[0]["length_kb"] == 1.101
    assert rows[1]["region_id"] == f"antiSMASH Arylpolyene {contig}:18134-49668"
    assert rows[1]["length_kb"] == 31.535
    # comBGC reports no orientation, so every region carries GFF's "no strand".
    assert set(result["strand"].to_list()) == {"."}

    arrows = GeneArrowTrackConfig(
        contig_col="contig",
        feature_id_col="region_id",
        start_col="start",
        end_col="end",
        strand_col="strand",
        class_col="product_class",
    )
    assert validate_binding(arrows, _schema_names(result)) == []

    coverage = CoverageTrackConfig(
        chromosome_col="contig",
        position_col="start",
        value_col="length_kb",
        end_col="end",
        sample_col="sample",
        category_col="product_class",
    )
    assert validate_binding(coverage, _schema_names(result)) == []


# ---------------------------------------------------------------------------
# hamronization/class_matrix: one aggregation level above the gene matrix
# ---------------------------------------------------------------------------


def test_class_matrix_folds_the_three_drug_class_vocabularies(tmp_path: Path) -> None:
    """CARD prose, AMRFinderPlus slashes and a bare label are one class."""
    report = pl.DataFrame(
        {
            "sample": ["S1", "S2", "S1", "S2"],
            "tool": ["rgi", "amrfinderplus", "abricate", "rgi"],
            "gene_symbol": ["ermB", "ermB", "tetQ", "tetQ"],
            "drug_class": [
                "macrolide antibiotic; lincosamide antibiotic",
                "MACROLIDE/LINCOSAMIDE/STREPTOGRAMIN",
                "TETRACYCLINE",
                "tetracycline antibiotic",
            ],
        }
    )

    result = execute_recipe(
        "hamronization/class_matrix.py",
        tmp_path,
        extra_sources={"report": report},
    )

    assert result["drug_class"].to_list() == ["MACROLIDE", "TETRACYCLINE"]
    # Sample ids become columns, one hit each.
    assert result.columns[:3] == ["drug_class", "top_tool", "n_genes_band"]
    assert {"S1", "S2"}.issubset(result.columns)
    assert result["S1"].to_list() == [1.0, 1.0]
    assert set(result["n_genes_band"].to_list()) == {"1 gene"}

    # `complex_heatmap` names its row-label field `index_column`, not
    # `index_col`, so `validate_binding` (which reads the `<role>_col`
    # convention) cannot see it. Check what the renderer actually needs: the
    # index column is a string column and every other column is numeric, which
    # is what makes the rest of the frame the matrix.
    cfg = ComplexHeatmapConfig(index_column="drug_class")
    schema = _schema_names(result)
    assert schema[cfg.index_column] == "String"
    matrix_cols = [c for c in result.columns if c not in ("drug_class", "top_tool", "n_genes_band")]
    assert matrix_cols and all(schema[c] == "Float64" for c in matrix_cols)


# ---------------------------------------------------------------------------
# funcscan/screening_summary: the hub, now a catalog recipe
# ---------------------------------------------------------------------------


def test_screening_summary_resolves_from_the_catalog_module(tmp_path: Path) -> None:
    """The recipe moved out of the pipeline folder; the handle has to follow."""
    arg = pl.DataFrame(
        {"sample": ["S1", "S1"], "gene_symbol": ["ermB", "tetQ"], "tool": ["rgi", "abricate"]}
    )
    amp = pl.DataFrame({"sample": ["S1", "S1"], "prob_max": [0.9, 0.4]})

    result = execute_recipe(
        "funcscan/screening_summary.py",
        tmp_path,
        extra_sources={"arg": arg, "amp": amp},
    )

    row = result.to_dicts()[0]
    assert row["arg_hits"] == 2
    assert row["arg_genes"] == 2
    assert row["arg_tools"] == 2
    assert row["amp_candidates"] == 2
    assert row["amp_high_confidence"] == 1
    # The two screens that did not run contribute zeros, not nulls.
    assert row["bgc_regions"] == 0
    assert row["cazymes"] == 0
    assert row["screens"] == 2
