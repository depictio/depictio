"""Benchmark recipes leave a ratio with nothing to divide empty, not 0.0.

som.py prints 0.0 for the precision of a callset that made no calls and for the
recall and F1 of an allele-fraction bin that holds no truth variant (it bins a true
positive or a miss by the truth set's allele fraction, which a truth set may lack).
Truvari's table does the same for a callset without calls. A 0.0 reads as a measured
failure and drags every median to the floor, so the recipes null those values: precision
when tp + fp == 0, recall when tp + fn == 0, and F1 when either is undefined. hap.py's
pooled summary recomputes the ratios, and must not turn 0/0 into NaN either.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

_SOMPY_HEADER = (
    "Tool,File,Caller,F1,Type,TP_base,TP_comp,FN,TP_Total,FP,UNK,Recall,Precision,"
    "recall_lower,recall_upper,recall2,precision_lower,precision_upper,na,ambiguous,"
    "fp.region.size,fp.rate\n"
)

# A normal callset, a callset that made no calls, and one whose calls all miss.
_SOMPY_SUMMARY = _SOMPY_HEADER + (
    "cs1,cs1.TRUTH.mutect2.stats.csv,mutect2,0.0561,indels,1577,46,1531,64,18,0,"
    "0.0292,0.71875,0.0217,0.0384,0.0292,0.6007,0.8175,0.0,0.0,2875001522.0,0.0063\n"
    "cs2,cs2.TRUTH.strelka.stats.csv,strelka,0.0,indels,1577,0,1577,0,0,0,"
    "0.0,0.0,0.0,0.0009,0.0,0.0,1.0,0.0,0.0,2875001522.0,0.0\n"
    "cs3,cs3.TRUTH.freebayes.stats.csv,freebayes,0.0,indels,1577,0,1577,50,50,0,"
    "0.0,0.0,0.0,0.0009,0.0,0.0,0.07,0.0,0.0,2875001522.0,0.017\n"
)

# A bin without calls or truth, a bin with false positives only (the truth set has no
# allele fractions, so no true positive or miss is binned), and a normal bin.
_SOMPY_REGIONS = _SOMPY_HEADER + (
    "cs2,cs2.TRUTH.strelka.stats.csv,strelka,0.0,indels.0.400000-0.600000,0,0,0,0,0,0,"
    "0.0,0.0,0.0,1.0,0.0,0.0,1.0,0.0,0.0,2875001522.0,0.0\n"
    "cs2,cs2.TRUTH.strelka.stats.csv,strelka,0.0,indels.0.000000-0.200000,0,0,0,105,105,0,"
    "0.0,0.0,0.0,1.0,0.0,0.0,0.0345,0.0,0.0,2875001522.0,0.0365\n"
    "cs2,cs2.TRUTH.strelka.stats.csv,strelka,0.7407,indels.0.200000-0.400000,15,10,5,12,2,0,"
    "0.6667,0.8333,0.4,0.9,0.6667,0.55,0.97,0.0,0.0,2875001522.0,0.0007\n"
)

_TRUVARI = (
    "Tool,File,Caller,TP_base,TP_comp,FP,FN,Precision,Recall,F1\n"
    "cs1,cs1.TRUTH.manta.summary.json,manta,0,0,0,1464,0.0,0.0,0.0\n"
    "cs2,cs2.TRUTH.lumpy.summary.json,lumpy,45,45,12,1419,0.7895,0.0307,0.0592\n"
)


def _stage(tmp_path: Path, rel: str, text: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _by(df: pl.DataFrame, key: str) -> dict[str, dict]:
    return {r[key]: r for r in df.iter_rows(named=True)}


def test_sompy_summary_nulls_the_precision_of_a_callset_without_calls(tmp_path: Path) -> None:
    _stage(tmp_path, "indel/summary/tables/sompy/sompy.summary.csv", _SOMPY_SUMMARY)
    df = execute_recipe("sompy/summary.py", tmp_path)
    assert df.schema["precision"] == pl.Float64
    rows = _by(df, "label")

    # No calls: precision and F1 are undefined, recall is a measured 0 of the truth set.
    assert rows["cs2"]["precision"] is None
    assert rows["cs2"]["f1"] is None
    assert rows["cs2"]["recall"] == 0.0
    # Calls that all miss: every ratio is defined and is 0.
    assert rows["cs3"]["precision"] == 0.0
    assert rows["cs3"]["recall"] == 0.0
    assert rows["cs3"]["f1"] == 0.0
    # A normal callset keeps som.py's values.
    assert rows["cs1"]["precision"] == pytest.approx(0.71875)
    assert rows["cs1"]["recall"] == pytest.approx(0.0292)
    assert rows["cs1"]["f1"] == pytest.approx(0.0561)
    # The truth-set size the Overview quotes stays on every row.
    assert {r["tp_base"] for r in rows.values()} == {1577}


def test_sompy_regions_nulls_recall_and_f1_of_a_bin_without_truth(tmp_path: Path) -> None:
    _stage(tmp_path, "indel/summary/tables/sompy/sompy.regions.csv", _SOMPY_REGIONS)
    df = execute_recipe("sompy/regions.py", tmp_path)
    assert df.schema["recall"] == pl.Float64
    rows = _by(df, "af_bin")

    empty = rows["0.400000-0.600000"]
    assert (empty["precision"], empty["recall"], empty["f1"]) == (None, None, None)

    fp_only = rows["0.000000-0.200000"]
    assert fp_only["fp"] == 105
    assert fp_only["precision"] == 0.0
    assert fp_only["recall"] is None
    assert fp_only["f1"] is None

    normal = rows["0.200000-0.400000"]
    assert normal["precision"] == pytest.approx(0.8333)
    assert normal["recall"] == pytest.approx(0.6667)
    assert normal["f1"] == pytest.approx(0.7407)


def test_truvari_nulls_the_precision_of_a_callset_without_calls(tmp_path: Path) -> None:
    _stage(tmp_path, "structural/summary/tables/truvari/truvari.summary.csv", _TRUVARI)
    rows = _by(execute_recipe("truvari/summary.py", tmp_path), "label")

    assert rows["cs1"]["precision"] is None
    assert rows["cs1"]["f1"] is None
    assert rows["cs1"]["recall"] == 0.0
    assert rows["cs2"]["precision"] == pytest.approx(0.7895)
    assert rows["cs2"]["f1"] == pytest.approx(0.0592)


def test_happy_pooled_summary_has_no_nan(tmp_path: Path) -> None:
    header = "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.FP\n"
    _stage(
        tmp_path,
        "small/cs1/benchmarks/happy/cs1.TRUTH.summary.csv",
        header
        # INDEL: no truth variant and no call. SNP: calls that all miss.
        + "INDEL,ALL,0,0,0,0,0\nSNP,ALL,100,0,100,20,20\nSNP,PASS,100,90,10,95,5\n",
    )
    df = execute_recipe("happy/summary.py", tmp_path)
    assert not any(df[c].is_nan().any() for c in ("recall", "precision", "f1"))
    rows = {(r["variant_type"], r["filter"]): r for r in df.iter_rows(named=True)}

    indel = rows[("INDEL", "ALL")]
    assert (indel["recall"], indel["precision"], indel["f1"]) == (None, None, None)
    miss = rows[("SNP", "ALL")]
    assert (miss["recall"], miss["precision"], miss["f1"]) == (0.0, 0.0, 0.0)
    snp = rows[("SNP", "PASS")]
    assert snp["recall"] == pytest.approx(0.9)
    assert snp["precision"] == pytest.approx(90 / 95)
    assert snp["f1"] == pytest.approx(2 * 0.9 * (90 / 95) / (0.9 + 90 / 95))
