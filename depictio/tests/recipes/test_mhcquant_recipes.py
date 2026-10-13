"""nf-core/mhcquant recipes on small synthetic outputs.

The template reads the samplesheet it ships, the per-sample peptide tables at
the output root and the Comet pin files. These tests pin the joins the
dashboard depends on: the sample and replicate keys, per-precursor rows summed
per replicate, the class I/II length windows, condition sharing and the
target-decoy q-values.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

SHEET = (
    "ID\tCondition\tSample\tReplicateFileName\tFasta\n"
    "3\tA\tS1\t/data/run_c.raw\t/db/proteome.fasta\n"
    "1\tA\tS1\t/data/run_a.raw\t/db/proteome.fasta\n"
    "2\tA\tS1\t/data/run_b.mzML\t/db/proteome.fasta\n"
    "4\tB\tS2\t/data/run_d.raw\t/db/proteome.fasta\n"
    "5\tB\tS2\t/data/run_e.raw\t/db/proteome.fasta\n"
)

PEP_COLS = [
    "sequence", "peptidoform", "score", "score_type", "psm", "rt", "mz", "charge",
    "accessions", "aa_before", "aa_after", "start", "predicted_retention_time_best",
    "spec_pearson", "intensity_cf",
]  # fmt: skip


def _peptide_table(rows: list[dict], n_rep: int) -> str:
    cols = PEP_COLS + [f"intensity_{k}" for k in range(n_rep)]
    lines = ["\t".join(cols)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "nan")) for c in cols))
    return "\n".join(lines) + "\n"


def _row(seq: str, charge: int, reps: list[object], **kw: object) -> dict:
    row = {
        "sequence": seq,
        "peptidoform": kw.get("peptidoform", seq),
        "score": kw.get("score", 1.5),
        "score_type": "xcorr",
        "psm": 2,
        "rt": 1200.0,
        "mz": 500.0,
        "charge": charge,
        "accessions": "sp|P01234|PROT_HUMAN;sp|P05678|OTHER_HUMAN",
        "aa_before": "K",
        "aa_after": "L",
        "start": "10;20",
        "predicted_retention_time_best": 1140.0,
        "spec_pearson": 0.9,
        "intensity_cf": 1000.0,
    }
    row.update({f"intensity_{k}": v for k, v in enumerate(reps)})
    return row


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.tsv").write_text(SHEET)
    s1 = [
        # One peptidoform at two charge states: two rows, one per precursor.
        _row("SIINFEKLV", 2, [100.0, "nan", 300.0]),
        _row("SIINFEKLV", 3, [100.0, "nan", "nan"]),
        _row("AAAAAAAAAAAAAAA", 2, [50.0, 50.0, 50.0]),
    ]
    s2 = [_row("SIINFEKLV", 2, [10.0, 20.0]), _row("KLLLLLLLY", 2, ["nan", 5.0])]
    (tmp_path / "S1_A.tsv").write_text(_peptide_table(s1, 3))
    (tmp_path / "S2_B.tsv").write_text(_peptide_table(s2, 2))
    return tmp_path


def test_samples_keys_and_replicate_rank(run_dir: Path) -> None:
    out = execute_recipe("nf-core/mhcquant/samples.py", run_dir)
    s1 = out.filter(pl.col("sample_id") == "S1_A")
    # Replicate follows the numeric ID, not the sheet order.
    assert s1["run_id"].to_list() == ["run_a", "run_b", "run_c"]
    assert s1["replicate"].to_list() == [1, 2, 3]
    assert out["Fasta"].unique().to_list() == ["proteome.fasta"]
    assert set(out["Condition"]) == {"A", "B"}


def test_peptides_windows_and_replicate_counts(run_dir: Path) -> None:
    out = execute_recipe("mhcquant/peptides.py", run_dir)
    assert out.height == 5
    windows = dict(zip(out["sequence"], out["length_window"], strict=False))
    assert windows["SIINFEKLV"] == "Class I range"
    assert windows["AAAAAAAAAAAAAAA"] == "Class II range"
    row = out.filter((pl.col("sample") == "S1_A") & (pl.col("charge") == 2)).filter(
        pl.col("sequence") == "SIINFEKLV"
    )
    assert row["replicates_quantified"].item() == 2
    assert row["replicates_total"].item() == 3
    assert row["protein"].item() == "P01234"
    assert row["n_proteins"].item() == 2
    assert row["rt_error_min"].item() == pytest.approx(1.0)
    # The S2 sample wrote two replicate columns, not three.
    assert out.filter(pl.col("sample") == "S2_B")["replicates_total"].unique().item() == 2


def test_replicate_intensity_sums_charge_states(run_dir: Path) -> None:
    out = execute_recipe("mhcquant/replicate_intensity.py", run_dir)
    s1 = out.filter((pl.col("sample") == "S1_A") & (pl.col("peptide") == "SIINFEKLV"))
    assert s1["replicate"].to_list() == [1, 2, 3]
    assert s1["detected"].to_list() == [1, 0, 1]
    assert s1["log10_intensity"][0] == pytest.approx(pl.Series([200.0]).log10()[0])
    # No phantom third replicate for the two-replicate sample.
    assert out.filter(pl.col("sample") == "S2_B")["replicate"].max() == 2


def test_downstream_tables_chain(run_dir: Path) -> None:
    peptides = execute_recipe("mhcquant/peptides.py", run_dir)
    reps = execute_recipe("mhcquant/replicate_intensity.py", run_dir)
    samples = execute_recipe("nf-core/mhcquant/samples.py", run_dir)

    summary = execute_recipe(
        "mhcquant/sample_summary.py",
        run_dir,
        extra_sources={"peptides": peptides, "replicates": reps},
    )
    assert set(summary["sample"]) == {"S1_A", "S2_B"}
    s1 = summary.filter(pl.col("sample") == "S1_A")
    assert s1["peptides"].item() == 2
    assert s1["class_ii_fraction"].item() == pytest.approx(0.5)

    lengths = execute_recipe(
        "mhcquant/length_distribution.py", run_dir, extra_sources={"peptides": peptides}
    )
    assert lengths.group_by("sample").agg(pl.col("fraction").sum())["fraction"].to_list() == [
        pytest.approx(1.0),
        pytest.approx(1.0),
    ]

    sharing = execute_recipe(
        "nf-core/mhcquant/condition_sharing.py",
        run_dir,
        extra_sources={"peptides": peptides, "samples": samples},
    )
    labels = dict(zip(sharing["sequence"], sharing["sharing"], strict=False))
    assert labels["SIINFEKLV"] == "All conditions"
    assert labels["KLLLLLLLY"] == "One condition"
    assert {"A", "B"} <= set(sharing.columns)


def test_comet_target_decoy_q_values(tmp_path: Path) -> None:
    comet = tmp_path / "intermediate_results" / "comet"
    comet.mkdir(parents=True)
    header = "SpecId\tLabel\tScanNr\tExpMass\tCalcMass\tXcorr\tPepLen\tPeptide\tProteins"
    lines = [header]
    # 20 targets above every decoy, then a decoy: the top 20 pass 1% FDR.
    for i in range(20):
        lines.append(f"t{i}\t1\t{i}\t1000.0\t1000.0\t{5 - i * 0.1:.2f}\t9\tK.SIINFEKLV.L\tP1")
    lines.append("d0\t-1\t99\t1000.0\t1000.0\t2.50\t9\tK.VLKEFNIIS.L\tDECOY_P1")
    lines.append("t20\t1\t100\t1000.0\t1000.0\t2.40\t9\tK.SIINFEKLA.L\tP1")
    (comet / "run_a_pin.tsv").write_text("\n".join(lines) + "\n")

    out = execute_recipe("openms/comet_psms.py", tmp_path)
    row = out.row(0, named=True)
    assert row["run_id"] == "run_a"
    assert row["target_psms"] == 21
    assert row["decoy_psms"] == 1
    assert row["psms_1pct_fdr"] == 20
