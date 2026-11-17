"""quantms 1.2.0 renamed its spectrum tables and their peak column.

``mzmlstatistics/<run>_mzml_info.tsv`` (``MS2_peaks``, MS2 rows only) became
``<run>_ms_info.tsv`` (``MS_peaks``, every MS level, plus summed intensities),
so a .d run is covered too. The three acquisition recipes read both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe

_OLD = (
    "SpectrumID\tMSLevel\tCharge\tMS2_peaks\tBase_Peak_Intensity\tRetention_Time\tExp_Mass_To_Charge\n"
    "s1\t1\t\t\t1000\t60.0\t\n"
    "s2\t2\t2\t120\t500\t61.0\t500.1\n"
    "s3\t2\t3\t80\t400\t62.0\t600.2\n"
)
_NEW = (
    "SpectrumID\tMSLevel\tCharge\tMS_peaks\tBase_Peak_Intensity\tSummed_Peak_Intensities\t"
    "Retention_Time\tExp_Mass_To_Charge\tAcquisitionDateTime\n"
    "s1\t1\t\t226\t1000\t5000\t60.0\t\t0000-00-00 00:00:00\n"
    "s2\t2\t2\t120\t500\t900\t61.0\t500.1\t0000-00-00 00:00:00\n"
    "s3\t2\t3\t80\t400\t800\t62.0\t600.2\t0000-00-00 00:00:00\n"
)


def _write(root: Path, name: str, text: str) -> None:
    path = root / "mzmlstatistics" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    (root / "mzmlstatistics" / "mzml_statistics.log").write_text("log\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "text"), [("RUN1_mzml_info.tsv", _OLD), ("RUN1_ms_info.tsv", _NEW)]
)
@pytest.mark.parametrize(
    "recipe",
    [
        "nf-core/quantms/acquisition.py",
        "nf-core/quantms/acquisition_profile.py",
        "nf-core/quantms/ms2_peak_bins.py",
    ],
)
def test_spectrum_tables_of_both_releases(tmp_path: Path, name, text, recipe) -> None:
    _write(tmp_path, name, text)

    df = execute_recipe(recipe, tmp_path)

    assert df["run_id"].unique().to_list() == ["RUN1"]


@pytest.mark.parametrize(
    ("name", "text"), [("RUN1_mzml_info.tsv", _OLD), ("RUN1_ms_info.tsv", _NEW)]
)
def test_ms2_peaks_count_only_ms2_spectra(tmp_path: Path, name, text) -> None:
    _write(tmp_path, name, text)

    df = execute_recipe("nf-core/quantms/acquisition.py", tmp_path)

    assert df["median_ms2_peaks"].to_list() == [100.0]
