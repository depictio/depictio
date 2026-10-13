"""`nf-core/atacseq/peak_summary.py` (2.1.2): the FRiP score joins its sample.

atacseq 2.x names the peak QC summary rows after the merged library
(`<sample>.mLb.clN`) and writes the FRiP score under the bare sample. The catalog
recipe joins the two on the raw name and leaves every FRiP score null; the
version recipe keys both on the bare sample. Only merged-library files are read.
"""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe

RECIPE = "nf-core/atacseq/peak_summary.py"
VERSION = "2.1.2"

_SUMMARY = (
    "Min.\t1st Qu.\tMedian\tMean\t3rd Qu.\tMax.\tnum_peaks\tmeasure\tsample\n"
    "3\t4\t4.5\t4.6\t5\t7\t120\tfold\tWT_REP1.mLb.clN\n"
    "1\t1.2\t1.5\t1.6\t1.7\t12\t120\t-log10(qvalue)\tWT_REP1.mLb.clN\n"
    "2\t2.2\t2.5\t2.6\t2.7\t15\t120\t-log10(pvalue)\tWT_REP1.mLb.clN\n"
    "200\t250\t300\t350\t400\t2000\t120\tlength\tWT_REP1.mLb.clN\n"
    "3\t4\t5\t5\t6\t8\t80\tfold\tKO_REP1.mLb.clN\n"
    "150\t200\t260\t280\t300\t1500\t80\tlength\tKO_REP1.mLb.clN\n"
)

_FRIP_HEADER = "#id: 'mlib_frip_score'\n#plot_type: 'bargraph'\n"


def _write_run(root: Path) -> None:
    qc = root / "bwa" / "merged_library" / "macs2" / "broad_peak" / "qc"
    qc.mkdir(parents=True)
    (qc / "macs2_peak.mLb.clN.summary.txt").write_text(_SUMMARY)
    (qc / "WT_REP1.mLb.clN_peaks.FRiP_mqc.tsv").write_text(_FRIP_HEADER + "WT_REP1\t0.31\n")
    (qc / "KO_REP1.mLb.clN_peaks.FRiP_mqc.tsv").write_text(_FRIP_HEADER + "KO_REP1\t0.12\n")
    # The merged-replicate level writes the same pair under .mRp.clN: never read.
    rep = root / "bwa" / "merged_replicate" / "macs2" / "broad_peak" / "qc"
    rep.mkdir(parents=True)
    (rep / "macs2_peak.mRp.clN.summary.txt").write_text(
        _SUMMARY.replace("_REP1.mLb.clN", ".mRp.clN")
    )
    (rep / "WT.mRp.clN_peaks.FRiP_mqc.tsv").write_text(_FRIP_HEADER + "WT\t0.5\n")


def test_frip_score_joins_the_bare_sample(tmp_path: Path) -> None:
    _write_run(tmp_path)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}

    assert sorted(rows) == ["KO_REP1", "WT_REP1"]
    assert rows["WT_REP1"]["frip_score"] == 0.31
    assert rows["KO_REP1"]["frip_score"] == 0.12
    assert rows["WT_REP1"]["num_peaks"] == 120
    assert rows["WT_REP1"]["width_median"] == 300.0
    assert rows["WT_REP1"]["fold_enrichment_mean"] == 4.6
    assert rows["WT_REP1"]["neg_log10_qvalue_median"] == 1.5
    # A measure the summary does not carry for a sample stays null, not 0.
    assert rows["KO_REP1"]["neg_log10_pvalue_median"] is None


def test_output_keeps_the_catalog_schema(tmp_path: Path) -> None:
    _write_run(tmp_path)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    assert out.columns == [
        "sample",
        "num_peaks",
        "frip_score",
        "width_median",
        "width_mean",
        "width_max",
        "fold_enrichment_median",
        "fold_enrichment_mean",
        "neg_log10_qvalue_median",
        "neg_log10_pvalue_median",
    ]
