"""`nf-core/chipseq/peaks.py` at 2.1.0: MACS3 calls of either peak type in one table.

The recipe reads `*_peaks.*Peak` headerless, tells narrowPeak, broadPeak and
gappedPeak rows apart by their width, and hands them to the catalog reader of their
type. Its output is the catalog `macs2/peaks.py` schema plus `peak_type`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe, load_recipe

RECIPE = "nf-core/chipseq/peaks.py"
VERSION = "2.1.0"

_NARROW = (
    "chr1\t100\t400\tABX_WT_REP1_peak_1\t55\t.\t4.2\t8.1\t5.5\t150\n"
    "chr2\t1000\t1200\tABX_WT_REP1_peak_2\t30\t.\t2.5\t5.0\t3.1\t80\n"
)
_BROAD = (
    "chr1\t100\t900\tABX_WT_REP1_peak_1\t55\t.\t4.2\t8.1\t5.5\n"
    "chr2\t1000\t1400\tABX_WT_REP1_peak_2\t30\t.\t2.5\t5.0\t3.1\n"
)
_GAPPED = "chr1\t100\t900\tABX_WT_REP1_peak_1\t55\t.\t100\t900\t0\t1\t800,\t0,\t4.2\t8.1\t5.5\n"


def _write(tmp_path: Path, peak_dir: str, name: str, body: str) -> None:
    folder = tmp_path / "bwa/merged_library/macs3" / peak_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body)


def test_output_is_the_catalog_schema_plus_peak_type() -> None:
    catalog = load_recipe("macs2/peaks.py")
    local = load_recipe(RECIPE, VERSION)
    assert list(local.OUTPUT_SCHEMA) == [*catalog.OUTPUT_SCHEMA, "peak_type"]


def test_narrow_peaks_keep_their_summit(tmp_path: Path) -> None:
    _write(tmp_path, "narrow_peak", "ABX_WT_REP1_peaks.narrowPeak", _NARROW)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    assert out.height == 2
    assert out["peak_type"].unique().to_list() == ["narrowPeak"]
    assert out["sample"].unique().to_list() == ["ABX_WT_REP1"]
    # The 1-based summit: the 0-based start plus the tenth column's offset, plus one.
    assert out["summit"].to_list() == [251, 1081]


def test_broad_peaks_take_the_midpoint_and_drop_gapped_rows(tmp_path: Path) -> None:
    _write(tmp_path, "broad_peak", "ABX_WT_REP1_peaks.broadPeak", _BROAD)
    _write(tmp_path, "broad_peak", "ABX_WT_REP1_peaks.gappedPeak", _GAPPED)
    out = execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
    assert out.height == 2
    assert out["peak_type"].unique().to_list() == ["broadPeak"]
    assert out.filter(out["summit"].is_null()).height == 0
    assert ((out["summit"] >= out["start"]) & (out["summit"] <= out["end"])).all()


def test_a_tree_with_both_peak_types_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, "narrow_peak", "ABX_WT_REP1_peaks.narrowPeak", _NARROW)
    _write(tmp_path, "broad_peak", "ABX_WT_REP1_peaks.broadPeak", _BROAD)
    with pytest.raises(ValueError, match="both narrowPeak and broadPeak"):
        execute_recipe(RECIPE, tmp_path, pipeline_version=VERSION)
