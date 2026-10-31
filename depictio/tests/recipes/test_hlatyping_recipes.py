"""OptiType catalog recipes (nf-core/hlatyping) on small synthetic result tables.

OptiType writes ``optitype/<sample>/<sample>_result.tsv``: an unnamed solution
index, ``A1`` ... ``C2``, ``Reads`` and ``Objective``. These tests pin the long
melt the ``allele_grid`` kind reads (two rows per locus, homozygous loci
repeated), the allele spelling shared with nf-core/epitopeprediction, the
optimum kept when ``--enumerations`` writes several solutions, an untyped locus
dropped rather than invented, and the per-sample summary (zygosity counts, the
epitopeprediction-ready allele list, the objective per read).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe
from depictio.recipes.lib.epitope_predictions import hla_locus, mhc_class, normalize_allele
from depictio.recipes.lib.optitype import allele_group, sample_of

HEADER = "\tA1\tA2\tB1\tB2\tC1\tC2\tReads\tObjective\n"


def _write(root: Path, sample: str, rows: list[str]) -> None:
    folder = root / "optitype" / sample
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sample}_result.tsv").write_text(HEADER + "".join(rows))


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    # Heterozygous everywhere: objective = reads x (1 - 3 x 0.009).
    _write(
        tmp_path, "S1", ["0\tA*02:01\tA*11:01\tB*44:02\tB*07:02\tC*05:01\tC*07:02\t1000.0\t973.0\n"]
    )
    # Homozygous at HLA-A.
    _write(
        tmp_path, "S2", ["0\tA*02:01\tA*02:01\tB*08:01\tB*35:01\tC*04:01\tC*07:01\t500.0\t491.0\n"]
    )
    # Two solutions (--enumerations 2), and the second differs at HLA-C.
    _write(
        tmp_path,
        "S3_RUN",
        [
            "0\tA*03:01\tA*24:02\tB*15:01\tB*18:01\tC*03:03\tC*12:03\t200.0\t194.6\n",
            "1\tA*03:01\tA*24:02\tB*15:01\tB*18:01\tC*03:04\tC*12:03\t200.0\t192.0\n",
        ],
    )
    # HLA-C left empty on one haplotype.
    _write(tmp_path, "S4", ["0\tA*01:01\tA*26:01\tB*07:02\tB*57:01\tC*06:02\t\t80.0\t78.56\n"])
    return tmp_path


def test_genotypes_melt_two_rows_per_locus(run_dir: Path) -> None:
    out = execute_recipe("optitype/genotypes.py", run_dir)
    assert out.columns[:10] == [
        "call_id", "sample_id", "locus", "haplotype", "allele", "allele_group", "hla_class",
        "zygosity", "reads", "objective",
    ]  # fmt: skip
    s1 = out.filter(pl.col("sample_id") == "S1")
    assert s1.height == 6
    assert s1["locus"].to_list() == ["HLA-A", "HLA-A", "HLA-B", "HLA-B", "HLA-C", "HLA-C"]
    assert s1["haplotype"].to_list() == [1, 2, 1, 2, 1, 2]
    assert s1["allele"].to_list()[:2] == ["HLA-A*02:01", "HLA-A*11:01"]
    assert set(s1["hla_class"]) == {"Class I"}
    assert set(s1["zygosity"]) == {"Heterozygous"}
    assert s1["call_id"].to_list()[0] == "S1|HLA-A|1"
    assert s1["reads"].to_list()[0] == 1000


def test_homozygous_locus_keeps_both_haplotypes(run_dir: Path) -> None:
    out = execute_recipe("optitype/genotypes.py", run_dir)
    a = out.filter((pl.col("sample_id") == "S2") & (pl.col("locus") == "HLA-A"))
    assert a["allele"].to_list() == ["HLA-A*02:01", "HLA-A*02:01"]
    assert set(a["zygosity"]) == {"Homozygous"}
    b = out.filter((pl.col("sample_id") == "S2") & (pl.col("locus") == "HLA-B"))
    assert set(b["zygosity"]) == {"Heterozygous"}


def test_only_the_optimal_solution_is_kept(run_dir: Path) -> None:
    out = execute_recipe("optitype/genotypes.py", run_dir)
    c = out.filter((pl.col("sample_id") == "S3_RUN") & (pl.col("locus") == "HLA-C"))
    assert c["allele"].to_list() == ["HLA-C*03:03", "HLA-C*12:03"]
    assert out.filter(pl.col("sample_id") == "S3_RUN")["objective"].unique().to_list() == [194.6]


def test_an_untyped_haplotype_is_dropped_not_invented(run_dir: Path) -> None:
    out = execute_recipe("optitype/genotypes.py", run_dir)
    c = out.filter((pl.col("sample_id") == "S4") & (pl.col("locus") == "HLA-C"))
    assert c.height == 1
    assert c["zygosity"].to_list() == ["One allele typed"]


def test_alleles_are_spelled_as_epitopeprediction_spells_them(run_dir: Path) -> None:
    """The cross-link: a typed allele is the string the prediction tables carry."""
    out = execute_recipe("optitype/genotypes.py", run_dir)
    for row in out.iter_rows(named=True):
        assert normalize_allele(row["allele"]) == row["allele"]
        assert hla_locus(row["allele"]) == row["locus"]
        assert mhc_class(row["allele"], None) == row["hla_class"]
    # OptiType's raw spelling and the predictors' spellings meet on one string.
    assert normalize_allele("A*02:01") == normalize_allele("HLA-A02:01") == "HLA-A*02:01"


def test_summary_counts_zygosity_and_solutions(run_dir: Path) -> None:
    out = execute_recipe("optitype/summary.py", run_dir)
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert set(rows) == {"S1", "S2", "S3_RUN", "S4"}
    s1, s2, s3, s4 = rows["S1"], rows["S2"], rows["S3_RUN"], rows["S4"]
    assert (s1["distinct_alleles"], s1["homozygous_loci"], s1["heterozygous_loci"]) == (6, 0, 3)
    assert (s2["distinct_alleles"], s2["homozygous_loci"], s2["heterozygous_loci"]) == (5, 1, 2)
    assert s2["hla_a"] == "HLA-A*02:01 / HLA-A*02:01"
    assert (s1["homozygous_class"], s2["homozygous_class"]) == (
        "No homozygous locus",
        "1 homozygous locus",
    )
    assert s1["objective_per_read"] == pytest.approx(0.973)
    assert (s3["solutions"], s3["runner_up_gap"]) == (2, pytest.approx(2.6))
    assert s1["solutions"] == 1 and s1["runner_up_gap"] is None
    assert (s4["typed_loci"], s4["homozygous_loci"], s4["heterozygous_loci"]) == (3, 0, 2)
    assert s4["hla_c"] == "HLA-C*06:02"


def test_summary_alleles_read_back_as_an_epitopeprediction_sheet(run_dir: Path) -> None:
    """The `alleles` column is a valid epitopeprediction samplesheet cell, unchanged."""
    out = execute_recipe("optitype/summary.py", run_dir)
    hub = load_recipe("nf-core/epitopeprediction/samples.py")
    for cell in out["alleles"].to_list():
        source, alleles = hub.alleles_of(cell)
        assert source == "Listed"
        assert alleles == cell


def test_helpers() -> None:
    assert sample_of("optitype/S1/S1_result.tsv") == "S1"
    assert sample_of("results/optitype/S1/S1_result.tsv") == "S1"
    assert sample_of("S9_result.tsv") == "S9"
    assert allele_group("HLA-B*57:01") == "HLA-B*57"
    assert allele_group(None) is None


def test_a_run_with_no_typed_locus_fails_with_a_reason(tmp_path: Path) -> None:
    _write(tmp_path, "EMPTY", ["0\t\t\t\t\t\t\t0.0\t0.0\n"])
    with pytest.raises(Exception, match="no sample has a typed locus"):
        execute_recipe("optitype/genotypes.py", tmp_path)
