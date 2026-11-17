"""The nf-core/mcmicro hubs: the samplesheet (``samples``) and the marker sheet (``markers``).

mcmicro publishes neither sheet, so both hubs read a vendored or user-given
file. These tests pin the per-sample grouping of a cycle sheet (and of a
sample sheet), the derived ``cycles`` group, that design columns a user adds
are kept, and the marker panel's role, status and counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe

CYCLE_SHEET = (
    "sample,cycle_number,image_tiles,tissue\n"
    "T1,1,https://example.org/t1_c1.ome.tif,tonsil\n"
    "T1,2,https://example.org/t1_c2.ome.tif,tonsil\n"
    "T1,3,https://example.org/t1_c3.ome.tif,tonsil\n"
    "T2,1,/data/t2_c1.ome.tif,lung\n"
)

MARKER_SHEET = (
    "channel_number,cycle_number,marker_name,background,remove,exposure\n"
    "1,1,DNA_1,,,80\n"
    "2,1,CD3,,,\n"
    "3,1,AF488,,TRUE,\n"
    "4,2,DAPI_2,,,100\n"
    "5,2,CD20,AF488,,\n"
)


def _run(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / name).write_text(text)
    return tmp_path


def test_samples_group_the_cycles(tmp_path: Path) -> None:
    out = execute_recipe(
        "nf-core/mcmicro/samples.py", _run(tmp_path, "samplesheet.csv", CYCLE_SHEET)
    )
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}
    assert out.columns[:4] == ["sample", "cycle_count", "cycles", "image_files"]
    assert rows["T1"]["cycle_count"] == 3
    assert rows["T1"]["cycles"] == "3 cycles"
    assert rows["T1"]["image_files"] == 3
    assert rows["T2"]["cycles"] == "1 cycle"
    # A design column a user adds is kept; the paths are not.
    assert rows["T1"]["tissue"] == "tonsil"
    assert "image_tiles" not in out.columns


def test_samples_read_a_sample_sheet_tab_separated(tmp_path: Path) -> None:
    sheet = "sample\timage_directory\nT1\t/data/t1\nT2\t/data/t2\n"
    out = execute_recipe("nf-core/mcmicro/samples.py", _run(tmp_path, "samplesheet.csv", sheet))
    assert out["sample"].to_list() == ["T1", "T2"]
    assert out["cycle_count"].to_list() == [1, 1]


def test_samples_require_the_id_column(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="no 'sample' column"):
        execute_recipe(
            "nf-core/mcmicro/samples.py",
            _run(tmp_path, "samplesheet.csv", "id,cycle_number\nA,1\n"),
        )


def test_markers_role_status_and_background(tmp_path: Path) -> None:
    out = execute_recipe("nf-core/mcmicro/markers.py", _run(tmp_path, "markers.csv", MARKER_SHEET))
    rows = {r["marker_name"]: r for r in out.iter_rows(named=True)}
    assert out["channel_number"].to_list() == [1, 2, 3, 4, 5]
    assert rows["DNA_1"]["marker_role"] == "Nuclear stain"
    assert rows["DAPI_2"]["marker_role"] == "Nuclear stain"
    assert rows["CD3"]["marker_role"] == "Marker"
    assert rows["AF488"]["status"] == "Removed" and rows["AF488"]["quantified"] == 0
    assert rows["CD20"]["status"] == "Quantified" and rows["CD20"]["quantified"] == 1
    assert rows["CD20"]["background"] == "AF488"
    assert rows["CD20"]["background_subtracted"] == 1
    assert rows["DNA_1"]["exposure"] == 80.0
    assert rows["CD3"]["exposure"] is None
    assert int(out["quantified"].sum()) == 4


def test_markers_need_only_the_required_columns(tmp_path: Path) -> None:
    sheet = "channel_number,cycle_number,marker_name\n1,1,DNA\n2,1,CD45\n"
    out = execute_recipe("nf-core/mcmicro/markers.py", _run(tmp_path, "markers.csv", sheet))
    assert out["status"].to_list() == ["Quantified", "Quantified"]
    assert out["background"].null_count() == 2
