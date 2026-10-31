"""MCQUANT catalog recipes (nf-core/mcmicro) on small synthetic outputs.

nf-core/mcmicro publishes one MCQUANT table per image and segmenter under
``quantification/mcquant/<segmenter>/``. These tests pin that the sample is read
back from every file name the pipeline writes (``<sample>.csv`` and the
``<image>_<mask>.csv`` of 2.0.0's Cellpose route), that a cell gets a run-wide
key (``CellID`` restarts per image and mask), that the marker columns pass
through untyped whatever the panel, and that the summaries, the marker
correlation and the segmenter agreement read them right. The PNG preview
helper is checked last, when its maintainer dependencies are installed.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from depictio.recipes import RecipeError, execute_recipe
from depictio.recipes.lib.mcquant import (
    centroid_hits,
    is_nuclear,
    marker_columns,
    sample_from_stem,
    segmenter_label,
)

HEADER = (
    "CellID,DNA_1,CD3,CD20,X_centroid,Y_centroid,Area,MajorAxisLength,MinorAxisLength,"
    "Eccentricity,Solidity,Extent,Orientation"
)


def _row(cell: int, dna: float, cd3: float, cd20: float, x: float, y: float, area: float) -> str:
    major, minor = 2 * math.sqrt(area / math.pi) * 1.2, 2 * math.sqrt(area / math.pi) / 1.2
    return f"{cell},{dna},{cd3},{cd20},{x},{y},{area},{major},{minor},0.5,0.95,0.8,0.1"


def _write(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([HEADER, *rows]) + "\n")


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    q = tmp_path / "quantification" / "mcquant"
    # Image S1, segmented twice: Mesmer nuclei and one large Cellpose cell that
    # holds two of them.
    _write(
        q / "mesmer" / "S1.csv",
        [
            _row(1, 1000, 10, 500, 10.0, 10.0, 20.0),
            _row(2, 1200, 30, 400, 13.0, 10.0, 22.0),
            _row(3, 900, 20, 0, 80.0, 80.0, 18.0),
        ],
    )
    _write(
        q / "cellpose" / "S1_backsub_S1_backsub.csv",
        [_row(1, 1100, 15, 450, 11.0, 10.0, math.pi * 25.0)],
    )
    # Image S2: Mesmer only; CellID restarts at 1.
    _write(q / "mesmer" / "S2.csv", [_row(1, 800, 40, 0, 5.0, 5.0, 30.0)])
    return tmp_path


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "sample"),
    [
        ("TEST1", "TEST1"),
        ("TEST1.csv", "TEST1"),
        ("TEST1_backsub_TEST1_backsub", "TEST1"),
        ("TEST1_backsub_TEST1_mask", "TEST1"),
        ("TEST1_TEST1_mask", "TEST1"),
        ("TEST1_backsub", "TEST1"),
        ("tissue_A", "tissue_A"),
        ("TEST1_backsub.ome_cp_masks", "TEST1"),
    ],
)
def test_sample_from_stem(stem: str, sample: str) -> None:
    assert sample_from_stem(stem) == sample


def test_segmenter_labels_and_nuclear_stains() -> None:
    assert segmenter_label("mesmer") == "Mesmer"
    assert segmenter_label("deepcell_mesmer") == "Mesmer"
    assert segmenter_label("cellpose") == "Cellpose"
    assert segmenter_label("stardist") == "stardist"
    assert is_nuclear("DNA_6") and is_nuclear("DAPI") and is_nuclear("Hoechst33342")
    assert not is_nuclear("CD45") and not is_nuclear("PanCK")


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def test_cells_key_sample_segmenter_and_markers(run_dir: Path) -> None:
    out = execute_recipe("mcquant/cells.py", run_dir)
    assert out.height == 5
    assert out["cell_key"].n_unique() == 5
    assert set(out["sample"]) == {"S1", "S2"}
    assert set(out["segmenter"]) == {"Mesmer", "Cellpose"}
    assert "S1|Cellpose|1" in out["cell_key"].to_list()
    assert "S2|Mesmer|1" in out["cell_key"].to_list()
    # The panel passes through, between CellID and the centroid, in file order.
    assert marker_columns(out) == ["DNA_1", "CD3", "CD20"]
    assert out.columns.index("DNA_1") == out.columns.index("CellID") + 1
    assert out["aspect_ratio"].round(2).unique().to_list() == [1.44]


def test_cell_markers_are_long_with_asinh(run_dir: Path) -> None:
    out = execute_recipe("mcquant/cell_markers.py", run_dir)
    assert out.height == 5 * 3
    row = out.filter((pl.col("cell_key") == "S1|Mesmer|1") & (pl.col("marker") == "CD20")).row(
        0, named=True
    )
    assert row["intensity"] == 500.0
    assert row["asinh_intensity"] == pytest.approx(math.asinh(500 / 150), abs=1e-4)
    assert row["marker_order"] == 3
    roles = dict(out.select("marker", "marker_role").unique().iter_rows())
    assert roles == {"DNA_1": "Nuclear stain", "CD3": "Marker", "CD20": "Marker"}


def test_segmentation_summary_per_image_and_method(run_dir: Path) -> None:
    out = execute_recipe("mcquant/segmentation_summary.py", run_dir)
    rows = {r["summary_key"]: r for r in out.iter_rows(named=True)}
    assert set(rows) == {"S1|Cellpose", "S1|Mesmer", "S2|Mesmer"}
    assert rows["S1|Mesmer"]["n_cells"] == 3
    assert rows["S1|Mesmer"]["median_area"] == 20.0
    assert rows["S1|Cellpose"]["n_cells"] == 1


def test_marker_summary_spread_is_null_without_signal(run_dir: Path) -> None:
    out = execute_recipe("mcquant/marker_summary.py", run_dir)
    s2 = out.filter((pl.col("sample") == "S2") & (pl.col("marker") == "CD20")).row(0, named=True)
    assert s2["mean_intensity"] == 0.0
    assert s2["cv"] is None
    s1 = out.filter(pl.col("summary_key") == "S1|Mesmer|DNA_1").row(0, named=True)
    assert s1["n_cells"] == 3
    assert s1["median_intensity"] == 1000.0
    assert s1["cv"] > 0


def test_marker_correlation_is_square_per_segmenter(run_dir: Path) -> None:
    out = execute_recipe("mcquant/marker_correlation.py", run_dir)
    assert set(out["segmenter"]) == {"Mesmer", "Cellpose"}
    mesmer = out.filter(pl.col("segmenter") == "Mesmer")
    assert mesmer.height == 3
    assert mesmer["marker_row"].to_list() == ["DNA_1 (Mesmer)", "CD3 (Mesmer)", "CD20 (Mesmer)"]
    for marker in ("DNA_1", "CD3", "CD20"):
        assert mesmer.filter(pl.col("marker") == marker)[marker][0] == pytest.approx(1.0)
    # One Cellpose cell: no variance, so no correlation at all.
    cellpose = out.filter(pl.col("segmenter") == "Cellpose")
    assert cellpose.select(["DNA_1", "CD3", "CD20"]).null_count().sum_horizontal()[0] == 9


def test_segmenter_agreement_counts_held_centroids(run_dir: Path) -> None:
    out = execute_recipe("mcquant/segmenter_agreement.py", run_dir)
    rows = {r["pair_key"]: r for r in out.iter_rows(named=True)}
    # S2 has one method only: nothing to compare there.
    assert set(rows) == {"S1|Cellpose|Mesmer", "S1|Mesmer|Cellpose"}
    whole = rows["S1|Cellpose|Mesmer"]
    assert whole["n_cells"] == 1 and whole["other_cells"] == 3
    assert whole["cells_holding_other"] == 1
    assert whole["matched_share"] == 1.0
    assert whole["median_held"] == 2.0  # two nuclei within its radius of 5
    nuclei = rows["S1|Mesmer|Cellpose"]
    # A nucleus of radius ~2.5 holds the whole cell's centroid 1 px away; the
    # second one sits 2 px off with radius ~2.65, the third far away.
    assert nuclei["cells_holding_other"] == 2
    assert nuclei["matched_share"] == pytest.approx(2 / 3, abs=1e-4)


def test_segmenter_agreement_needs_two_methods(tmp_path: Path) -> None:
    _write(
        tmp_path / "quantification" / "mcquant" / "mesmer" / "S1.csv",
        [_row(1, 1, 1, 1, 1.0, 1.0, 10.0)],
    )
    with pytest.raises((RecipeError, ValueError), match="two methods"):
        execute_recipe("mcquant/segmenter_agreement.py", tmp_path)


def test_centroid_hits_matches_brute_force() -> None:
    rng = np.random.default_rng(7)
    cx, cy = rng.uniform(0, 100, 50), rng.uniform(0, 100, 50)
    cr = rng.uniform(1, 8, 50)
    px, py = rng.uniform(0, 100, 400), rng.uniform(0, 100, 400)
    fast = centroid_hits((cx, cy, cr), (px, py))
    slow = [int(((px - x) ** 2 + (py - y) ** 2 <= r * r).sum()) for x, y, r in zip(cx, cy, cr)]
    assert fast.tolist() == slow


def test_missing_mcquant_columns_are_named(tmp_path: Path) -> None:
    path = tmp_path / "quantification" / "mcquant" / "mesmer" / "S1.csv"
    path.parent.mkdir(parents=True)
    path.write_text("CellID,X_centroid,Y_centroid\n1,1.0,1.0\n")
    with pytest.raises((RecipeError, ValueError), match="Area"):
        execute_recipe("mcquant/cells.py", tmp_path)


# ---------------------------------------------------------------------------
# The fetch-time PNG previews (maintainer helper; needs tifffile and Pillow)
# ---------------------------------------------------------------------------

PREVIEWS_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "projects"
    / "nf-core"
    / "mcmicro"
    / "2.0.0"
    / "scripts"
    / "make_previews.py"
)


def _previews_module():
    pytest.importorskip("tifffile")
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("mcmicro_make_previews", PREVIEWS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_make_previews_writes_the_manifest_and_the_underlay(tmp_path: Path) -> None:
    previews = _previews_module()
    import tifffile

    rng = np.random.default_rng(1)
    image = rng.integers(0, 60000, size=(3, 60, 120), dtype=np.uint16)
    (tmp_path / "registration" / "ashlar").mkdir(parents=True)
    tifffile.imwrite(
        tmp_path / "registration" / "ashlar" / "S1.ome.tif", image, metadata={"axes": "CYX"}
    )
    labels = np.zeros((60, 120), dtype=np.int32)
    labels[10:20, 10:20] = 1
    labels[30:40, 50:70] = 2
    (tmp_path / "segmentation" / "deepcell_mesmer").mkdir(parents=True)
    tifffile.imwrite(tmp_path / "segmentation" / "deepcell_mesmer" / "S1_mask.tif", labels)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "markers.csv").write_text(
        "channel_number,cycle_number,marker_name\n1,1,DNA_1\n2,1,CD3\n3,1,CD20\n"
    )

    rows = previews.make_previews(tmp_path, tmp_path / "input" / "markers.csv", max_px=60)
    manifest = pl.read_csv(tmp_path / "previews" / "previews.tsv", separator="\t")
    assert manifest.columns == previews.COLUMNS
    assert manifest.height == len(rows) == 1 + 3 + 1  # composite, 3 channels, outlines
    assert set(manifest["stage"]) == {"Registered", "Segmentation"}
    assert "Mesmer outlines" in manifest["channel"].to_list()
    # Downscaled to 60 px on the long side, the full frame kept beside it.
    assert manifest["width"].unique().to_list() == [60]
    assert manifest["height"].unique().to_list() == [30]
    assert manifest["full_width"].unique().to_list() == [120]
    assert manifest["scale"].unique().to_list() == [0.5]
    # One underlay per image: its nuclear stain.
    underlay = manifest.filter(pl.col("underlay_sample").is_not_null())
    assert underlay.select("sample", "channel").rows() == [("S1", "DNA_1")]
    for name in manifest["image_path"]:
        assert (tmp_path / "previews" / name).is_file()
