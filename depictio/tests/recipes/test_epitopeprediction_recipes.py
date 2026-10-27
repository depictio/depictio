"""nf-core/epitopeprediction catalog recipes on small synthetic outputs.

The merged ``predictions/<sample>.tsv`` comes in two shapes: wide
(``--wide_format_output``, three columns per tool and allele) and long (the
default, one row per peptide, allele and tool). These tests pin that both give
the same long rows, that alleles are normalised for a later cross-link, that
IC50 is derived from the 0-1 affinity score the pipeline writes, that the
pipeline's own binder call is kept, that a peptide no tool scored is reported
as unsupported, and that mutants meet their wild type.
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe
from depictio.recipes.lib.epitope_predictions import hla_locus, mhc_class, normalize_allele

VARIANT_COLS = [
    "sequence", "gene", "transcript", "consequence", "HGVSp", "genomic_anchor", "uniprot",
    "protein_ids", "counts", "peptide_origin", "wildtype",
]  # fmt: skip


def _ba(ic50: float) -> float:
    """The pipeline's affinity score for an IC50 in nM."""
    return 1 - math.log10(ic50) / math.log10(50000)


def _wide_table() -> str:
    """Two tools x two alleles, a mutant with its wild type and an unscored peptide."""
    alleles = ["HLA-A*01:01", "HLA-A*02:01"]
    tools = ["mhcflurry", "mhcnuggets"]
    value_cols = [f"{t}_{a}_{f}" for f in ("BA", "binder", "rank") for t in tools for a in alleles]
    cols = VARIANT_COLS + value_cols + [
        "best_value_mhcflurry", "best_allele_mhcflurry", "best_value_mhcnuggets",
        "best_allele_mhcnuggets", "best_allele", "binder",
    ]  # fmt: skip

    def row(seq: str, origin: str, wildtype: str, ic50: dict, binder: dict) -> str:
        cells = {
            "sequence": seq, "gene": "GENE1", "transcript": "ENST1", "consequence": "missense",
            "HGVSp": "p.Ser1Cys", "genomic_anchor": "1:100:C:G", "uniprot": "P00001",
            "protein_ids": f"{origin}.1.GENE1", "counts": "1", "peptide_origin": origin,
            "wildtype": wildtype, "best_value_mhcflurry": "1", "best_allele_mhcflurry": "x",
            "best_value_mhcnuggets": "1", "best_allele_mhcnuggets": "x", "best_allele": "x",
            "binder": "True",
        }  # fmt: skip
        for t in tools:
            for a in alleles:
                key = (t, a)
                if key in ic50:
                    cells[f"{t}_{a}_BA"] = str(_ba(ic50[key]))
                    cells[f"{t}_{a}_rank"] = "1.5" if binder.get(key) else "40.0"
                    cells[f"{t}_{a}_binder"] = str(bool(binder.get(key)))
        return "\t".join(cells.get(c, "") for c in cols)

    full = {(t, a): 5000.0 for t in tools for a in alleles}
    mutant_ic50 = {**full, ("mhcflurry", "HLA-A*02:01"): 40.0, ("mhcnuggets", "HLA-A*02:01"): 300.0}
    mutant_bind = {("mhcflurry", "HLA-A*02:01"): True, ("mhcnuggets", "HLA-A*02:01"): True}
    wt_bind = {}
    lines = [
        "\t".join(cols),
        row("SIINFEKLC", "MT", "SIINFEKLS", mutant_ic50, mutant_bind),
        row("SIINFEKLS", "WT", "NA", full, wt_bind),
        # Scored by one tool only, for one allele.
        row("KLLLLLLLY", "MT", "NA", {("mhcflurry", "HLA-A*01:01"): 20000.0}, {}),
        # No tool could score it.
        row("AAAAAAAAAAAAAAAAAAAA", "MT", "NA", {}, {}),
    ]
    return "\n".join(lines) + "\n"


LONG_TABLE = (
    "id\tsequence\tallele\tBA\trank\tbinder\tpredictor\n"
    f"p1\tGILGFVFTL\tHLA-A*02:01\t{_ba(20.0)}\t0.1\tTrue\tmhcflurry\n"
    f"p1\tGILGFVFTL\tHLA-A*02:01\t{_ba(800.0)}\t0.2\tFalse\tmhcnuggets\n"
    f"p2\tNLVPMVATV\tHLA-A*02:01\t{_ba(30000.0)}\t60.0\tFalse\tmhcflurry\n"
    "p3\tRLDSHLHTHVY\t\t\t\t\t\n"
)

VARIANT_PEPTIDES = (
    "\t".join(VARIANT_COLS) + "\n"
    "SIINFEKLC\tGENE1\tENST1\tmissense\tp.Ser1Cys\t1:100:C:G\tP00001\tMT.1.GENE1\t1\tMT\tSIINFEKLS\n"
    "SIINFEKLS\tGENE1\tENST1\tmissense\tp.Ser1Cys\t1:100:C:G\tP00001\tWT.1.GENE1\t1\tWT\tNA\n"
    "KLLLLLLLY\tGENE2\tENST2\tFS;inframe_del\tp.Ala2fs\t2:200:GA:G\tP00002\tMT.2.GENE2\t2\tMT\tNA\n"
)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "predictions").mkdir()
    (tmp_path / "predictions" / "TUMOR1.tsv").write_text(_wide_table())
    (tmp_path / "predictions" / "PEPTIDES1.tsv").write_text(LONG_TABLE)
    (tmp_path / "variant_peptides").mkdir()
    (tmp_path / "variant_peptides" / "TUMOR1_length_9.tsv").write_text(VARIANT_PEPTIDES)
    return tmp_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A*02:01", "HLA-A*02:01"),
        ("HLA-A*02:01", "HLA-A*02:01"),
        ("HLA-A*02:01:01:02L", "HLA-A*02:01"),
        ("A0201", "HLA-A*02:01"),
        ("hla-b*07:02", "HLA-B*07:02"),
        ("DRB1*01:01", "HLA-DRB1*01:01"),
        ("HLA-DPA1*01:03/DPB1*02:01", "HLA-DPA1*01:03/DPB1*02:01"),
        ("A*01:100", "HLA-A*01:100"),
        ("H-2-Kb", "H-2-Kb"),
        ("", None),
        (None, None),
    ],
)
def test_alleles_are_normalised_for_cross_linking(raw: str | None, expected: str | None) -> None:
    assert normalize_allele(raw) == expected


def test_allele_locus_and_class() -> None:
    assert hla_locus("HLA-A*02:01") == "HLA-A"
    assert hla_locus("HLA-DRB1*01:01") == "HLA-DR"
    assert hla_locus("HLA-DPA1*01:03/DPB1*02:01") == "HLA-DP"
    assert hla_locus("H-2-Kb") == "Other"
    assert mhc_class("HLA-C*07:01", "mhcflurry") == "Class I"
    assert mhc_class("HLA-DQA1*05:01/DQB1*02:01", "mhcnuggetsii") == "Class II"
    assert mhc_class("H-2-IAb", "netmhciipan") == "Class II"


def test_predictions_read_both_shapes(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/predictions.py", run_dir)
    wide = out.filter(pl.col("sample") == "TUMOR1")
    long = out.filter(pl.col("sample") == "PEPTIDES1")
    # 2 tools x 2 alleles for the mutant and its wild type, one for KLL..., none
    # for the unscored peptide.
    assert wide.height == 9
    assert long.height == 3
    assert out["row_id"].n_unique() == out.height
    assert set(out["allele"]) == {"HLA-A*01:01", "HLA-A*02:01"}
    gil = long.filter((pl.col("sequence") == "GILGFVFTL") & (pl.col("predictor") == "mhcflurry"))
    assert gil["ic50_nm"][0] == pytest.approx(20.0, rel=1e-3)
    assert gil["binder"][0] == 1
    assert gil["call"][0] == "Binder"
    assert gil["affinity_class"][0] == "Strong (50 nM or less)"
    assert gil["peptide_id"][0] == "p1"
    assert gil["origin"][0] == "Input sequence"
    assert gil["length_class"][0] == "9-mer"


def test_predictions_join_the_wild_type(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/predictions.py", run_dir)
    mt = out.filter(
        (pl.col("sequence") == "SIINFEKLC")
        & (pl.col("allele") == "HLA-A*02:01")
        & (pl.col("predictor") == "mhcflurry")
    )
    assert mt["origin"][0] == "Mutant"
    assert mt["wt_ic50_nm"][0] == pytest.approx(5000.0, rel=1e-3)
    assert mt["agretopicity"][0] == pytest.approx(40.0 / 5000.0, rel=1e-2)
    assert mt["consequence"][0] == "Missense"


def test_peptides_report_best_prediction_and_unsupported(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/peptides.py", run_dir)
    by_seq = {r["sequence"]: r for r in out.iter_rows(named=True)}
    assert by_seq["AAAAAAAAAAAAAAAAAAAA"]["call"] == "Unsupported"
    assert by_seq["AAAAAAAAAAAAAAAAAAAA"]["alleles_scored"] == 0
    mutant = by_seq["SIINFEKLC"]
    assert mutant["call"] == "Binder"
    assert mutant["binder"] == 1
    assert mutant["best_allele"] == "HLA-A*02:01"
    assert mutant["best_predictor"] == "mhcflurry"
    assert mutant["binding_alleles"] == 1
    assert mutant["binder_calls"] == 2
    assert mutant["alleles_scored"] == 2
    assert mutant["gene"] == "GENE1"
    assert by_seq["SIINFEKLS"]["call"] == "Non-binder"
    assert by_seq["RLDSHLHTHVY"]["call"] == "Unsupported"
    assert by_seq["NLVPMVATV"]["call"] == "Non-binder"


def test_allele_summary_counts_peptides_once_over_tools(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/allele_summary.py", run_dir)
    row = out.filter((pl.col("sample") == "TUMOR1") & (pl.col("allele") == "HLA-A*02:01")).row(
        0, named=True
    )
    assert row["peptides"] == 2  # the mutant and its wild type
    assert row["binders"] == 1
    assert row["binder_rate"] == pytest.approx(0.5)
    assert row["predictors"] == "mhcflurry, mhcnuggets"
    assert row["hla_locus"] == "HLA-A"


def test_predictor_summary_leaves_out_wild_types(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/predictor_summary.py", run_dir)
    flurry = out.filter((pl.col("sample") == "TUMOR1") & (pl.col("predictor") == "mhcflurry"))
    row = flurry.row(0, named=True)
    # Three non-wild-type peptides, one of them unscored by any tool.
    assert row["peptides"] == 3
    assert row["scored"] == 2
    assert row["unsupported"] == 1
    assert row["binders"] == 1
    nuggets = out.filter((pl.col("sample") == "TUMOR1") & (pl.col("predictor") == "mhcnuggets"))
    assert nuggets["scored"][0] == 1


def test_predictor_agreement_pairs_tools(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/predictor_agreement.py", run_dir)
    assert set(out["predictor_pair"]) == {"mhcflurry vs mhcnuggets"}
    gil = out.filter(pl.col("sequence") == "GILGFVFTL").row(0, named=True)
    assert gil["agreement"] == "mhcflurry only"
    assert gil["concordant"] == 0
    assert gil["log10_ratio"] == pytest.approx(math.log10(800 / 20), abs=1e-2)
    mutant = out.filter(
        (pl.col("sequence") == "SIINFEKLC") & (pl.col("allele") == "HLA-A*02:01")
    ).row(0, named=True)
    assert mutant["agreement"] == "Both binder"
    # KLL... was scored by one tool only: no pair.
    assert out.filter(pl.col("sequence") == "KLLLLLLLY").is_empty()


def test_predictor_agreement_needs_two_tools(tmp_path: Path) -> None:
    (tmp_path / "predictions").mkdir()
    (tmp_path / "predictions" / "S1.tsv").write_text(
        "sequence\tallele\tBA\trank\tbinder\tpredictor\n"
        f"GILGFVFTL\tHLA-A*02:01\t{_ba(20.0)}\t0.1\tTrue\tmhcflurry\n"
    )
    with pytest.raises(Exception, match="two tools"):
        execute_recipe("epitopeprediction/predictor_agreement.py", tmp_path)


def test_wildtype_pairs(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/wildtype_pairs.py", run_dir)
    assert set(out["sequence"]) == {"SIINFEKLC"}
    assert out.height == 4  # two tools x two alleles
    hit = out.filter(
        (pl.col("allele") == "HLA-A*02:01") & (pl.col("predictor") == "mhcflurry")
    ).row(0, named=True)
    assert hit["pair_call"] == "Mutant binds, wild type does not"
    assert hit["log10_agretopicity"] < 0
    assert hit["wildtype"] == "SIINFEKLS"


def test_wildtype_pairs_need_a_wild_type(tmp_path: Path) -> None:
    (tmp_path / "predictions").mkdir()
    (tmp_path / "predictions" / "P1.tsv").write_text(LONG_TABLE)
    with pytest.raises(Exception, match="wild type"):
        execute_recipe("epitopeprediction/wildtype_pairs.py", tmp_path)


def test_variant_peptides_read_sample_and_length_from_the_file(run_dir: Path) -> None:
    out = execute_recipe("epitopeprediction/variant_peptides.py", run_dir)
    assert out.height == 3
    assert set(out["sample"]) == {"TUMOR1"}
    origins = dict(zip(out["sequence"], out["origin"], strict=True))
    assert origins == {"SIINFEKLC": "Mutant", "SIINFEKLS": "Wild type", "KLLLLLLLY": "Mutant"}
    fs = out.filter(pl.col("sequence") == "KLLLLLLLY").row(0, named=True)
    assert fs["consequence"] == "Frameshift, In-frame deletion"
    assert fs["source_records"] == 2
    assert out.filter(pl.col("origin") == "Wild type")["wildtype"][0] is None
