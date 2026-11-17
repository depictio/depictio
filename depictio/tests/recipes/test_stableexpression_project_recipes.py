"""The nf-core/stableexpression sample hub (``nf-core/stableexpression/samples.py``).

stableexpression publishes its samples' design (merged_data/whole_design.csv)
but not their platform, which is only a directory name under datasets/. These
tests pin the derived columns the dashboard groups and filters by (platform,
normalisation, accession, the dataset-qualified condition, the filtered-out
status), that an annotated design keeps its extra columns for GROUP_COL, and
that a dataset without a published directory still gets a platform.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe

DESIGN = (
    "batch,condition,sample\n"
    "E_GEOD_1_A_AFFY_44,g1,E_GEOD_1_A_AFFY_44_s1\n"
    "E_GEOD_1_A_AFFY_44,g2,E_GEOD_1_A_AFFY_44_s2\n"
    "E_MTAB_2_rnaseq,g1,E_MTAB_2_rnaseq_r1\n"
    "E_MTAB_2_rnaseq,g1,E_MTAB_2_rnaseq_r2\n"
    "E_MTAB_5_rnaseq,g1,E_MTAB_5_rnaseq_q1\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    _write(tmp_path / "merged_data" / "whole_design.csv", DESIGN)
    _write(
        tmp_path
        / "datasets/microarray/normalised/E_GEOD_1_A_AFFY_44/E_GEOD_1_A_AFFY_44.design.csv",
        "batch,condition,sample\nE_GEOD_1_A_AFFY_44,g1,E_GEOD_1_A_AFFY_44_s1\n",
    )
    _write(
        tmp_path / "datasets/rnaseq/raw/E_MTAB_2_rnaseq/E_MTAB_2_rnaseq.design.csv",
        "batch,condition,sample\nE_MTAB_2_rnaseq,g1,E_MTAB_2_rnaseq_r1\n",
    )
    # r2 was removed by a filter: the per-sample table of the matrix lacks it.
    _write(
        tmp_path / "statistics" / "ratio_nulls_per_sample.csv",
        "sample,ratio\nE_GEOD_1_A_AFFY_44_s1,0.6\nE_GEOD_1_A_AFFY_44_s2,0.6\n"
        "E_MTAB_2_rnaseq_r1,0.01\nE_MTAB_5_rnaseq_q1,0.02\n",
    )
    return tmp_path


def test_samples_derive_platform_and_status(run_dir: Path) -> None:
    out = execute_recipe("nf-core/stableexpression/samples.py", run_dir)
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}
    assert out.columns[:9] == [
        "sample", "dataset", "accession", "array_design", "platform", "normalisation",
        "condition", "status", "missing_share",
    ]  # fmt: skip
    s1 = rows["E_GEOD_1_A_AFFY_44_s1"]
    assert s1["platform"] == "Microarray"
    assert s1["normalisation"] == "Normalised"
    assert s1["accession"] == "E-GEOD-1"
    assert s1["array_design"] == "A-AFFY-44"
    assert s1["condition"] == "E_GEOD_1_A_AFFY_44 g1"
    assert s1["status"] == "Analysed"
    assert s1["missing_share"] == pytest.approx(0.6)
    assert rows["E_MTAB_2_rnaseq_r1"]["platform"] == "RNA-seq"
    assert rows["E_MTAB_2_rnaseq_r1"]["normalisation"] == "Raw counts"
    assert rows["E_MTAB_2_rnaseq_r2"]["status"] == "Filtered out"
    # No datasets/ directory for this one: the platform comes from its id.
    q1 = rows["E_MTAB_5_rnaseq_q1"]
    assert q1["platform"] == "RNA-seq"
    assert q1["normalisation"] is None


def test_samples_keep_annotation_columns(run_dir: Path) -> None:
    annotated = DESIGN.replace("batch,condition,sample", "batch,condition,sample,Tissue type")
    annotated = "\n".join(
        line if i == 0 else f"{line},liver" for i, line in enumerate(annotated.strip().split("\n"))
    )
    _write(run_dir / "input" / "design.csv", annotated + "\n")
    out = execute_recipe(
        "nf-core/stableexpression/samples.py",
        run_dir,
        overrides={"design": str(run_dir / "input" / "design.csv")},
    )
    assert "Tissue_type" in out.columns
    assert set(out["Tissue_type"]) == {"liver"}


def test_samples_without_the_per_sample_table(run_dir: Path) -> None:
    (run_dir / "statistics" / "ratio_nulls_per_sample.csv").unlink()
    out = execute_recipe("nf-core/stableexpression/samples.py", run_dir)
    assert set(out["status"]) == {"Analysed"}
    assert out["missing_share"].null_count() == out.height
