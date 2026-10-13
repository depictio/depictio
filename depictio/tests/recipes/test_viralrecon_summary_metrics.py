"""viralrecon's summary metrics read the nanopore (ARTIC) CSV as well as the illumina one.

The ARTIC route writes the same summary_variants_metrics_mqc.csv without the
"% Mapped reads" column, and "NA" where a sample has no INDEL count or lineage.
The output schema required the missing column, so the recipe failed and the
template dropped the table on nanopore runs, and the Overview its Key figures.
"""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe

_ILLUMINA = (
    "Sample,# Mapped reads,% Mapped reads,Coverage median,% Coverage > 1x,"
    "% Coverage > 10x,# SNPs,# INDELs,Pangolin lineage\n"
    "S1,1000,98.5,120,100.0,99.0,20,2,B.1\n"
)
_NANOPORE = (
    "Sample,# Mapped reads,% Non-host reads (Kraken 2),Coverage median,% Coverage > 1x,"
    "% Coverage > 10x,# SNPs,# INDELs,# Missense variants,Pangolin lineage,Nextclade clade\n"
    "S1,2871,100.0,30,100.0,95.0,12,NA,7,NA,20B\n"
    "S2,10,100.0,0,1.0,0.0,NA,NA,NA,NA,NA\n"
)


def _run(tmp_path: Path, csv: str):
    (tmp_path / "multiqc").mkdir()
    (tmp_path / "multiqc" / "summary_variants_metrics_mqc.csv").write_text(csv)
    return execute_recipe("multiqc/summary_metrics.py", tmp_path).sort("sample")


def test_illumina_keeps_every_column(tmp_path: Path) -> None:
    row = _run(tmp_path, _ILLUMINA).row(0, named=True)
    assert row["pct_reads_mapped"] == 98.5
    assert row["num_variants_total"] == 22.0
    assert row["lineage"] == "B.1"


def test_nanopore_leaves_the_missing_column_empty(tmp_path: Path) -> None:
    rows = {r["sample"]: r for r in _run(tmp_path, _NANOPORE).iter_rows(named=True)}
    assert rows["S1"]["pct_reads_mapped"] is None
    assert rows["S1"]["num_reads_mapped"] == 2871.0
    assert rows["S1"]["pct_genome_covered_10x"] == 95.0
    # An NA count is a missing count; NA for both means the sample was not called.
    assert rows["S1"]["num_variants_total"] == 12.0
    assert rows["S2"]["num_variants_total"] is None
    assert rows["S1"]["lineage"] == "Unassigned"
