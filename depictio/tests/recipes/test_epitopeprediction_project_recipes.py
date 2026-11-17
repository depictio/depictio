"""The nf-core/epitopeprediction sample hub (``nf-core/epitopeprediction/samples.py``).

The pipeline does not publish its samplesheet, so the hub reads the vendored or
user-given sheet. These tests pin the derived columns the dashboard groups and
filters by (input type, allele source, normalised alleles, MHC class labels) and
that a tab-separated sheet reads like a comma-separated one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe

SHEET = (
    "sample,alleles,mhc_class,filename,tumor_sample,germline_vcf\n"
    "T1,A*01:01;B*07:02,I,https://example.org/data/tumour.vcf.gz,TUMOR,/data/normal.vcf\n"
    "T2,DRB1*01:01,II,/data/tumour.vcf,TUMOR,\n"
    "P1,https://example.org/alleles/alleles.txt,I,/data/proteins.fasta,,\n"
    "Q1,HLA-all,I,/data/peptides.tsv,,\n"
)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(SHEET)
    return tmp_path


def test_samples_derive_input_type_and_alleles(run_dir: Path) -> None:
    out = execute_recipe("nf-core/epitopeprediction/samples.py", run_dir)
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}
    assert out.columns[:8] == [
        "sample", "input_type", "mhc_class", "allele_source", "alleles", "input_file",
        "tumor_sample", "germline_vcf",
    ]  # fmt: skip
    assert rows["T1"]["input_type"] == "Variants"
    assert rows["T1"]["alleles"] == "HLA-A*01:01;HLA-B*07:02"
    assert rows["T1"]["allele_source"] == "Listed"
    assert rows["T1"]["input_file"] == "tumour.vcf.gz"
    assert rows["T1"]["germline_vcf"] == "normal.vcf"
    assert rows["T2"]["mhc_class"] == "Class II"
    assert rows["T2"]["alleles"] == "HLA-DRB1*01:01"
    assert rows["T2"]["germline_vcf"] is None
    assert rows["P1"]["input_type"] == "Proteins"
    assert rows["P1"]["allele_source"] == "Allele file"
    assert rows["P1"]["alleles"] == "alleles.txt"
    assert rows["P1"]["tumor_sample"] is None
    assert rows["Q1"]["input_type"] == "Peptides"
    assert rows["Q1"]["allele_source"] == "All supported"
    assert rows["Q1"]["mhc_class"] == "Class I"


def test_samples_read_a_tab_separated_sheet(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(SHEET.replace(",", "\t"))
    out = execute_recipe("nf-core/epitopeprediction/samples.py", tmp_path)
    assert out.height == 4
    assert set(out["input_type"]) == {"Variants", "Proteins", "Peptides"}


def test_samples_require_the_schema_columns(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text("sample,alleles\nT1,A*01:01\n")
    with pytest.raises(Exception, match="missing required column"):
        execute_recipe("nf-core/epitopeprediction/samples.py", tmp_path)
