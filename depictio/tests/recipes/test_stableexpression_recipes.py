"""nf-core/stableexpression catalog recipes on a small synthetic run.

The run below has two sections of three genes (two candidates each), two
datasets that reach the merged matrix (one microarray, one RNA-seq), one whose
ids map to nothing and one whose samples all fail the zero filter. These tests
pin that the gene tables keep the pipeline's sections and ranks and split the
score into parts that add up to it (weights recovered from the scores), that
box statistics are drawn from measured values only, and that every dataset's
funnel and ID mapping add up.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from depictio.recipes import execute_recipe
from depictio.recipes.lib.stable_expression import (
    accession_of,
    array_design_of,
    box_stats,
    section_label,
)

SUMMARY_COLS = [
    "gene_id", "mean", "standard_deviation", "median", "median_absolute_deviation",
    "coefficient_of_variation", "robust_coefficient_of_variation_median",
    "ratio_nulls_in_all_samples", "ratio_nulls_in_valid_samples", "ratio_zeros",
    "expression_level_quantile_interval", "section", "normfinder_stability_value",
    "genorm_m_measure", "is_candidate", "normfinder_stability_value_normalised",
    "genorm_m_measure_normalised", "coefficient_of_variation_normalised",
    "robust_coefficient_of_variation_median_normalised", "stability_score", "rank", "name",
    "description", "original_gene_ids", "rnaseq_mean", "rnaseq_coefficient_of_variation",
    "microarray_mean", "microarray_coefficient_of_variation", "expression_level_status",
]  # fmt: skip

# Weights the synthetic scores are built with: not the default 0.25 each, so a
# recipe that assumed the default would get the parts wrong.
WEIGHTS = (0.4, 0.2, 0.3, 0.1)


def _gene(gid, section, candidate, norms=None, missing=0.0, name="", rank=1, mean=0.5):
    """One all_genes_summary.csv row; a candidate's score is built from ``norms``."""
    row = dict.fromkeys(SUMMARY_COLS, "")
    row.update(
        gene_id=gid, mean=str(mean), standard_deviation="0.1", median=str(mean),
        median_absolute_deviation="0.05", coefficient_of_variation="0.2",
        robust_coefficient_of_variation_median="0.1", ratio_nulls_in_all_samples="0.25",
        ratio_nulls_in_valid_samples=str(missing), ratio_zeros="0.0",
        expression_level_quantile_interval="50.0", section=section,
        is_candidate="1" if candidate else "0", rank=str(rank), name=name,
        description="a gene", original_gene_ids="p1;p2;" + gid, rnaseq_mean=str(mean),
        rnaseq_coefficient_of_variation="0.3", microarray_mean="" if gid.endswith("9") else str(mean),
        microarray_coefficient_of_variation="0.1", expression_level_status="Medium range",
    )  # fmt: skip
    if candidate:
        row["normfinder_stability_value"] = "0.01"
        row["genorm_m_measure"] = "1.5"
        for col, value in zip(
            [
                "normfinder_stability_value_normalised",
                "genorm_m_measure_normalised",
                "coefficient_of_variation_normalised",
                "robust_coefficient_of_variation_median_normalised",
            ],
            norms,
            strict=True,
        ):
            row[col] = str(value)
        row["stability_score"] = str(
            missing + sum(w * n for w, n in zip(WEIGHTS, norms, strict=True))
        )
    return row


# Scores: ENSG01 0.08, ENSG06 0.31, ENSG02 0.56 (section 1); ENSG04 0.63,
# ENSG07 0.82, ENSG05 1.0 (section 2). Six candidates, enough to solve for the
# four weights.
GENES = [
    _gene("ENSG01", "section_1", True, (0.0, 0.1, 0.2, 0.0), 0.0, "AAA1", 1, 0.9),
    _gene("ENSG02", "section_1", True, (0.5, 0.4, 0.3, 0.9), 0.1, "", 3, 0.85),
    _gene("ENSG03", "section_1", False, rank=251, mean=0.8),
    _gene("ENSG04", "section_2", True, (0.2, 0.0, 0.0, 0.5), 0.5, "BBB2", 1, 0.2),
    _gene("ENSG05", "section_2", True, (1.0, 1.0, 1.0, 1.0), 0.0, "CCC3", 3, 0.25),
    _gene("ENSG09", "section_2", False, rank=252, mean=0.1),
    _gene("ENSG06", "section_1", True, (0.3, 0.7, 0.1, 0.2), 0.0, "DDD4", 2, 0.88),
    _gene("ENSG07", "section_2", True, (0.9, 0.2, 0.6, 0.4), 0.2, "EEE5", 2, 0.22),
]

# Four datasets: two merged, one whose ids map to nothing, one filtered out.
DATASETS = {
    ("microarray", "normalised", "E_GEOD_1_A_AFFY_44"): ["s1", "s2", "s3"],
    ("rnaseq", "raw", "E_MTAB_2_rnaseq"): ["r1", "r2", "r3", "r4"],
    ("microarray", "normalised", "E_GEOD_3_A_AFFY_141"): ["x1", "x2"],
    ("rnaseq", "raw", "E_MTAB_4_rnaseq"): ["z1", "z2"],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    lines = [",".join(SUMMARY_COLS)] + [",".join(g[c] for c in SUMMARY_COLS) for g in GENES]
    _write(tmp_path / "reporting" / "all_genes_summary.csv", "\n".join(lines) + "\n")

    design = ["batch,condition,sample"]
    for (platform, norm, ds), samples in DATASETS.items():
        rows = [f"{ds},g{i % 2 + 1},{ds}_{s}" for i, s in enumerate(samples)]
        _write(
            tmp_path / "datasets" / platform / norm / ds / f"{ds}.design.csv",
            "batch,condition,sample\n" + "\n".join(rows) + "\n",
        )
        if ds in ("E_GEOD_1_A_AFFY_44", "E_MTAB_2_rnaseq"):
            design += rows
    _write(tmp_path / "merged_data" / "whole_design.csv", "\n".join(design) + "\n")

    # Seven merged samples; the microarray samples never measured ENSG04.
    samples = [f"E_GEOD_1_A_AFFY_44_{s}" for s in ("s1", "s2", "s3")] + [
        f"E_MTAB_2_rnaseq_{s}" for s in ("r1", "r2", "r3", "r4")
    ]
    rng = np.random.default_rng(0)
    data = {"gene_id": [g["gene_id"] for g in GENES]}
    for s in samples:
        data[s] = [float(v) for v in rng.uniform(0, 1, len(GENES))]
    for s in samples[:3]:
        data[s][3] = None
    pl.DataFrame(
        data, schema={"gene_id": pl.Utf8, **dict.fromkeys(samples, pl.Float32)}
    ).write_parquet(tmp_path / "merged_data" / "all_counts.parquet")

    stats = tmp_path / "statistics"
    _write(
        stats / "id_mapping_stats.csv",
        "dataset,final,merged,not_valid,unmapped\n"
        "E_GEOD_1_A_AFFY_44,900,60,10,40\n"
        "E_MTAB_2_rnaseq,1800,150,150,50\n"
        "E_GEOD_3_A_AFFY_141,0,0,0,700\n"
        "E_MTAB_4_rnaseq,500,20,5,10\n",
    )
    _write(
        stats / "zero_values_filter_stats.csv",
        "dataset,kept,rejected\nE_GEOD_1_A_AFFY_44,3,0\nE_MTAB_2_rnaseq,4,0\nE_MTAB_4_rnaseq,0,2\n",
    )
    _write(
        stats / "missing_values_filter_stats.csv",
        "dataset,kept,rejected\nE_GEOD_1_A_AFFY_44,3,0\nE_MTAB_2_rnaseq,4,0\n",
    )
    _write(
        stats / "ratio_zeros.csv",
        "E_GEOD_1_A_AFFY_44,0.0,0.0,0.0\nE_MTAB_2_rnaseq,0.1,0.2,0.3,0.5\n",
    )
    _write(
        stats / "ratio_nulls.csv",
        "E_GEOD_1_A_AFFY_44,0.6,0.6,0.6\nE_MTAB_2_rnaseq,0.01,0.02,0.03,0.04\n",
    )
    _write(stats / "skewness.csv", "E_GEOD_1_A_AFFY_44,0,0,0.1\nE_MTAB_2_rnaseq,0.1,0.2,0.3,0.4\n")
    _write(
        stats / "ratio_nulls_per_sample.csv",
        "sample,ratio\n" + "\n".join(f"{s},0.1" for s in samples) + "\n",
    )
    _write(
        tmp_path / "errors" / "renaming_failure_reasons.tsv",
        "Dataset\tReason\nE_GEOD_3_A_AFFY_141\tNO GENES WERE MAPPED. EXAMPLE OF GENE IDS: ['1', '2']\n",
    )
    _write(
        tmp_path / "warnings" / "renaming_warning_reasons.tsv",
        "Dataset\tReason\nE_GEOD_1_A_AFFY_44\t96.00% of genes were mapped (960 out of 1000).\n",
    )
    return tmp_path


def test_names_and_sections() -> None:
    assert accession_of("E_GEOD_10070_A_AFFY_44") == "E-GEOD-10070"
    assert array_design_of("E_GEOD_10070_A_AFFY_44") == "A-AFFY-44"
    assert accession_of("E_MTAB_9962_rnaseq") == "E-MTAB-9962"
    assert array_design_of("E_MTAB_9962_rnaseq") is None
    assert accession_of("GSE12345_custom") == "GSE12345_custom"
    assert section_label(3, 10) == "Section 03"
    assert section_label(12, 120) == "Section 012"


def test_box_stats_whiskers_stop_at_the_last_value_inside_the_fences() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 100.0, np.nan])
    stats = box_stats(values)
    assert stats["n"] == 6
    assert stats["median"] == pytest.approx(3.5)
    assert stats["q1"] == pytest.approx(np.quantile([1, 2, 3, 4, 5, 100], 0.25))
    assert stats["upper"] == 5.0  # 100 lies past Q3 + 1.5 IQR
    assert stats["lower"] == 1.0
    assert stats["max"] == 100.0
    assert box_stats(np.array([np.nan]))["n"] == 0


def test_gene_statistics_keep_every_gene(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/gene_statistics.py", run_dir)
    rows = {r["gene_id"]: r for r in out.iter_rows(named=True)}
    assert out.height == 8
    assert rows["ENSG01"]["section"] == "Section 01"
    assert rows["ENSG04"]["section_index"] == 2
    assert rows["ENSG02"]["gene_name"] == "ENSG02"  # no symbol: the id stands in
    assert rows["ENSG02"]["gene_symbol"] is None
    assert rows["ENSG03"]["candidate"] == "Not a candidate"
    assert rows["ENSG01"]["candidate"] == "Candidate"
    assert rows["ENSG01"]["measured_share"] == pytest.approx(0.75)
    assert rows["ENSG01"]["source_ids"] == 3
    assert rows["ENSG01"]["platforms"] == "Both platforms"
    assert rows["ENSG09"]["platforms"] == "RNA-seq only"
    assert "rnaseq_cv" in out.columns


def test_gene_stability_splits_the_score_into_parts(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/gene_stability.py", run_dir)
    assert out.height == 6  # candidates only
    parts = out.select(
        (
            pl.col("normfinder_part") + pl.col("genorm_part") + pl.col("cv_part")
            + pl.col("robust_cv_part") + pl.col("missing_penalty")
        ).alias("total"),
        "stability_score",
    )  # fmt: skip
    assert parts["total"].to_list() == pytest.approx(parts["stability_score"].to_list(), abs=1e-6)
    rows = {r["gene_id"]: r for r in out.iter_rows(named=True)}
    # The weights are recovered from the scores, not assumed.
    assert rows["ENSG05"]["normfinder_part"] == pytest.approx(WEIGHTS[0])
    assert rows["ENSG05"]["robust_cv_part"] == pytest.approx(WEIGHTS[3])
    # Ranks: within the section as written, over every candidate by score.
    assert rows["ENSG01"]["section_rank"] == 1
    assert rows["ENSG01"]["overall_rank"] == 1
    assert rows["ENSG06"]["overall_rank"] == 2
    assert rows["ENSG05"]["overall_rank"] == 6
    assert rows["ENSG01"]["rank_weight"] == pytest.approx(1.0)
    assert rows["ENSG05"]["rank_weight"] == pytest.approx(1 / 6)
    # Each measure is also ranked within its section, 1 the steadiest.
    for _, section in out.group_by("section"):
        for value, rank in (
            ("normfinder_stability", "normfinder_rank"),
            ("genorm_m", "genorm_rank"),
        ):
            ordered = section.sort(rank)
            assert ordered[rank].to_list() == list(range(1, section.height + 1))
            assert ordered[value].is_sorted()


def test_gene_stability_reads_a_run_without_genorm(run_dir: Path) -> None:
    path = run_dir / "reporting" / "all_genes_summary.csv"
    df = pl.read_csv(path, infer_schema_length=0).drop(
        "genorm_m_measure", "genorm_m_measure_normalised"
    )
    df.write_csv(path)
    out = execute_recipe("stableexpression/gene_stability.py", run_dir)
    assert out["genorm_m"].null_count() == out.height
    assert out["genorm_part"].to_list() == [0.0] * out.height
    assert out["genorm_rank"].null_count() == out.height


def test_score_components_add_up(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/score_components.py", run_dir)
    assert out.height == 6 * 5
    assert set(out["component"]) == {
        "Normfinder", "geNorm M", "Coefficient of variation", "Robust CV", "Missing values",
    }  # fmt: skip
    totals = out.group_by("gene_id").agg(
        pl.col("contribution").sum(), pl.col("stability_score").first()
    )
    assert totals["contribution"].to_list() == pytest.approx(
        totals["stability_score"].to_list(), abs=1e-6
    )


def test_stable_gene_distribution_uses_measured_values(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/stable_gene_distribution.py", run_dir)
    assert out.height == 6
    rows = {r["gene_id"]: r for r in out.iter_rows(named=True)}
    assert rows["ENSG04"]["n_measured"] == 4  # the three microarray samples are null
    assert rows["ENSG04"]["n_samples"] == 7
    assert rows["ENSG04"]["measured_share"] == pytest.approx(4 / 7, abs=1e-4)
    counts = pl.read_parquet(run_dir / "merged_data" / "all_counts.parquet")
    values = counts.filter(pl.col("gene_id") == "ENSG01").drop("gene_id").to_numpy().ravel()
    assert rows["ENSG01"]["median"] == pytest.approx(float(np.median(values)), abs=1e-5)
    assert rows["ENSG01"]["q1"] <= rows["ENSG01"]["median"] <= rows["ENSG01"]["q3"]
    top1 = execute_recipe(
        "stableexpression/stable_gene_distribution.py", run_dir, params={"top_per_section": "1"}
    )
    assert sorted(top1["gene_id"]) == ["ENSG01", "ENSG04"]


def test_stable_gene_values_are_long_and_carry_the_dataset(run_dir: Path) -> None:
    out = execute_recipe(
        "stableexpression/stable_gene_values.py", run_dir, params={"top_per_section": "1"}
    )
    assert set(out["gene_id"]) == {"ENSG01", "ENSG04"}
    assert out.filter(pl.col("gene_id") == "ENSG04").height == 4
    assert out.filter(pl.col("gene_id") == "ENSG01").height == 7
    assert set(out["dataset"]) == {"E_GEOD_1_A_AFFY_44", "E_MTAB_2_rnaseq"}
    assert out["value_key"].n_unique() == out.height


def test_dataset_summary_follows_every_dataset(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/dataset_summary.py", run_dir)
    rows = {r["dataset"]: r for r in out.iter_rows(named=True)}
    assert out.height == 4
    merged = rows["E_GEOD_1_A_AFFY_44"]
    assert merged["platform"] == "Microarray"
    assert merged["normalisation"] == "Normalised"
    assert merged["accession"] == "E-GEOD-1"
    assert merged["outcome"] == "Merged"
    assert merged["samples_kept"] == 3
    assert merged["gene_ids_in"] == 1000  # kept + merged + unmapped
    assert merged["ids_collapsed"] == 50  # merged minus rare
    assert merged["mapped_share"] == pytest.approx(0.96)
    assert merged["missing_share"] == pytest.approx(0.6)
    assert merged["mapping_note"].startswith("96.00%")
    assert rows["E_MTAB_2_rnaseq"]["platform"] == "RNA-seq"
    assert rows["E_MTAB_2_rnaseq"]["normalisation"] == "Raw counts"
    assert rows["E_MTAB_2_rnaseq"]["zero_share"] == pytest.approx(0.25)
    failed = rows["E_GEOD_3_A_AFFY_141"]
    assert failed["outcome"] == "No gene mapped"
    assert failed["samples_id_mapped"] == 0
    assert failed["mapped_share"] == 0.0
    assert failed["failure_reason"].startswith("NO GENES")
    filtered = rows["E_MTAB_4_rnaseq"]
    assert filtered["outcome"] == "All samples filtered out"
    assert filtered["samples_rejected_zeros"] == 2
    assert filtered["merged"] == 0


def test_dataset_summary_without_id_mapping(run_dir: Path) -> None:
    (run_dir / "statistics" / "id_mapping_stats.csv").unlink()
    (run_dir / "errors" / "renaming_failure_reasons.tsv").unlink()
    out = execute_recipe("stableexpression/dataset_summary.py", run_dir)
    assert out["id_mapped"].to_list() == [1, 1, 1, 1]
    assert out["gene_ids_in"].null_count() == 4
    with pytest.raises(Exception, match="no ID mapping statistics"):
        execute_recipe("stableexpression/id_mapping.py", run_dir)


def test_dataset_funnel_sums_to_the_run(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/dataset_funnel.py", run_dir)
    steps = (
        out.group_by("step_order", "step")
        .agg(pl.col("samples").sum(), pl.col("samples_lost").sum())
        .sort("step_order")
    )
    assert steps["step"].to_list() == [
        "Downloaded",
        "Gene IDs mapped",
        "Zero filter",
        "Missing-value filter",
    ]
    assert steps["samples"].to_list() == [11, 9, 7, 7]
    assert steps["samples_lost"].to_list() == [0, 2, 2, 0]


def test_id_mapping_fates_add_up(run_dir: Path) -> None:
    out = execute_recipe("stableexpression/id_mapping.py", run_dir)
    per_dataset = out.group_by("dataset").agg(pl.col("gene_ids").sum(), pl.col("share").sum())
    totals = dict(zip(per_dataset["dataset"], per_dataset["gene_ids"], strict=True))
    assert totals["E_GEOD_1_A_AFFY_44"] == 1000
    assert totals["E_GEOD_3_A_AFFY_141"] == 700
    assert per_dataset["share"].to_list() == pytest.approx([1.0] * 4, abs=1e-3)
    unmapped = out.filter(
        (pl.col("dataset") == "E_GEOD_3_A_AFFY_141") & (pl.col("fate") == "Unmapped")
    )
    assert unmapped["share"].to_list() == [1.0]
