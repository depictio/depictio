"""Labels bioimage DCs: segmentation-mask TIFFs converted to OME-Zarr at ingest.

Masks are tiny integer TIFFs written with tifffile in tmp_path; the converted
store is read back as plain JSON + zlib chunks, and S3 is the dict-backed
FakeS3 of the ingest tests.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np
import pytest
import tifffile

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.deltatables import (
    process_bioimage_data_collection,
    upload_labels_tiff,
    validate_ome_zarr_store,
)
from depictio.cli.cli.utils.labels_tiff import (
    convert_labels_tiff,
    inspect_labels_tiff,
    labels_pyramid,
    read_labels_tiff,
)
from depictio.cli.cli.utils.scan import iter_bioimage_stores
from depictio.tests.cli.utils import test_bioimage_ingest as ingest
from depictio.tests.cli.utils.test_bioimage_ingest import (
    BUCKET,
    DC_ID,
    FakeS3,
    _dc,
    _ingest_dc,
    _registered,
)

MASK_PATTERN = r"^(.+?)_mask\.tif$"


@pytest.fixture(autouse=True)
def cli_context(monkeypatch):
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")


@pytest.fixture
def fake_s3(monkeypatch) -> FakeS3:
    s3 = FakeS3()
    monkeypatch.setattr(deltatables, "_s3_client", lambda CLI_config, **kw: s3)
    return s3


@pytest.fixture
def cli_config():
    from unittest.mock import MagicMock

    config = MagicMock()
    config.s3_storage.bucket = BUCKET
    return config


def mask(height: int = 300, width: int = 600, dtype=np.uint16) -> np.ndarray:
    """Blocky cells: ids 1..n in 50 px squares, background in every other column of blocks."""
    ys, xs = np.mgrid[0:height, 0:width]
    ids = (ys // 50) * (width // 50 + 1) + (xs // 50) + 1
    ids[(xs // 50) % 2 == 1] = 0
    return ids.astype(dtype)


def write_mask(path: Path, data: np.ndarray, **kw) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, data, **kw)
    return path


def read_chunk(store: Path, level: int, iy: int, ix: int) -> np.ndarray:
    meta = json.loads((store / str(level) / ".zarray").read_text())
    raw = zlib.decompress((store / str(level) / str(iy) / str(ix)).read_bytes())
    return np.frombuffer(raw, dtype=np.dtype(meta["dtype"])).reshape(meta["chunks"])


class TestConversion:
    @pytest.mark.parametrize("dtype", [np.uint16, np.int32])
    def test_multiscale_ngff_labels_store(self, tmp_path, dtype):
        data = mask(dtype=dtype)
        tiff = write_mask(tmp_path / "s1_mask.tif", data)
        store = Path(convert_labels_tiff(str(tiff), str(tmp_path / "out" / "s1_mask.tif"), "s1"))

        assert validate_ome_zarr_store(str(store), "0.4") == "0.4"
        attrs = json.loads((store / ".zattrs").read_text())
        (ms,) = attrs["multiscales"]
        assert attrs["image-label"]["version"] == "0.4"
        assert ms["name"] == "s1"
        assert [a["name"] for a in ms["axes"]] == ["y", "x"]
        # 600 px wide: one extra level brings the largest side to 300.
        assert [d["path"] for d in ms["datasets"]] == ["0", "1"]
        assert ms["datasets"][1]["coordinateTransformations"][0]["scale"] == [2.0, 2.0]

        level0 = json.loads((store / "0" / ".zarray").read_text())
        assert level0["shape"] == [300, 600]
        assert level0["chunks"] == [256, 256]
        assert level0["dimension_separator"] == "/"
        assert np.dtype(level0["dtype"]) == np.dtype(dtype)
        assert json.loads((store / "1" / ".zarray").read_text())["shape"] == [150, 300]

        # Chunk (0, 0) is the mask's top-left corner; an edge chunk is padded with 0.
        assert np.array_equal(read_chunk(store, 0, 0, 0), data[:256, :256])
        edge = read_chunk(store, 0, 1, 2)
        assert np.array_equal(edge[: 300 - 256, : 600 - 512], data[256:, 512:])
        assert not edge[300 - 256 :, :].any()
        # Nearest neighbour: level 1 holds only ids of level 0, never averages.
        assert np.array_equal(read_chunk(store, 1, 0, 0)[:150, :256], data[::2, ::2][:, :256])

    def test_background_chunks_are_not_written(self, tmp_path):
        data = np.zeros((512, 512), dtype=np.uint8)
        data[300:310, 300:310] = 7
        store = Path(
            convert_labels_tiff(
                str(write_mask(tmp_path / "m.tif", data)), str(tmp_path / "m.tif.out"), "m"
            )
        )
        chunks = sorted(p.relative_to(store / "0").as_posix() for p in (store / "0").rglob("*"))
        assert chunks == [".zarray", "1", "1/1"]

    def test_pyramid_stops_at_512(self):
        levels = labels_pyramid(np.zeros((2100, 900), dtype=np.uint32))
        assert [lvl.shape for lvl in levels] == [(2100, 900), (1050, 450), (525, 225), (263, 113)]
        assert len(labels_pyramid(np.zeros((512, 512), dtype=np.uint8))) == 1

    def test_singleton_axes_are_dropped(self, tmp_path):
        data = mask(64, 64)[None, None]
        tiff = write_mask(tmp_path / "m.tif", data, imagej=True)
        assert read_labels_tiff(str(tiff)).shape == (64, 64)

    def test_small_int64_ids_become_uint32(self, tmp_path):
        tiff = write_mask(tmp_path / "m.tif", mask(64, 64, np.int64))
        assert read_labels_tiff(str(tiff)).dtype == np.uint32

    @pytest.mark.parametrize(
        ("data", "kw", "message"),
        [
            (np.random.default_rng(0).random((32, 32), dtype=np.float32), {}, "not an integer"),
            (np.zeros((32, 32, 3), dtype=np.uint8), {"photometric": "rgb"}, "RGB"),
            (np.zeros((3, 32, 32), dtype=np.uint16), {"photometric": "minisblack"}, "2D plane"),
        ],
    )
    def test_rejected_masks(self, tmp_path, data, kw, message):
        tiff = write_mask(tmp_path / "m.tif", data, **kw)
        with pytest.raises(ValueError, match=message):
            inspect_labels_tiff(str(tiff))

    def test_negative_ids_are_rejected(self, tmp_path):
        tiff = write_mask(tmp_path / "m.tif", np.full((8, 8), -1, dtype=np.int16))
        with pytest.raises(ValueError, match="negative"):
            read_labels_tiff(str(tiff))

    def test_not_a_tiff(self, tmp_path):
        path = tmp_path / "m.tif"
        path.write_bytes(b"not a tiff")
        with pytest.raises(ValueError, match="not a readable TIFF"):
            inspect_labels_tiff(str(path))


class TestScan:
    def test_folder_registers_each_mask(self, tmp_path):
        folder = tmp_path / "masks"
        write_mask(folder / "s1_mask.tif", mask(8, 8))
        write_mask(folder / "nested" / "s2_mask.tiff", mask(8, 8))
        (folder / "notes.txt").write_text("x")
        assert [Path(p).name for p in iter_bioimage_stores(str(folder), "tiff")] == [
            "s2_mask.tiff",
            "s1_mask.tif",
        ]

    def test_single_scan(self, tmp_path):
        tiff = write_mask(tmp_path / "s1_mask.tif", mask(8, 8))
        (result,) = ingest.TestFormatScan()._single(tiff, _dc(format="tiff", kind="labels"))
        assert result.file.filename == "s1_mask.tif"

    def test_recursive_scan_matches_mask_files(self, tmp_path):
        run_dir = tmp_path / "run_1"
        tiff = write_mask(run_dir / "seg" / "s1_mask.tif", mask(8, 8))
        write_mask(run_dir / "seg" / "s1_probabilities.tif", mask(8, 8))
        dc = _dc(
            mode="recursive",
            pattern=r".+_mask\.tif",
            format="tiff",
            kind="labels",
            sample_pattern=MASK_PATTERN,
        )
        files = ingest.TestRecursiveScan()._scan(run_dir, dc)
        assert [f.file_location for f in files] == [str(tiff.resolve())]


class TestIngest:
    def test_converted_store_is_uploaded_under_the_mask_name(
        self, tmp_path, monkeypatch, cli_config, fake_s3
    ):
        tiff = write_mask(tmp_path / "s1_mask.tif", mask())
        _registered(monkeypatch, tiff)
        dc = _ingest_dc(format="tiff", kind="labels", sample_pattern=MASK_PATTERN)

        result = process_bioimage_data_collection(dc, cli_config)  # type: ignore[arg-type]

        assert result["result"] == "success", result
        assert "1 labels TIFF store(s)" in result["message"]
        prefix = f"bioimage/{DC_ID}/s1_mask.tif/"
        assert {
            prefix + ".zattrs",
            prefix + ".zgroup",
            prefix + "0/.zarray",
            prefix + "0/0/0",
        } <= set(fake_s3.uploaded)
        attrs = json.loads(fake_s3.objects[prefix + ".zattrs"])
        assert attrs["multiscales"][0]["name"] == "s1"
        marker = json.loads(fake_s3.objects[f"bioimage/{DC_ID}/.uploads/s1_mask.tif.json"])
        assert marker["hash"].startswith("labels-v1:")

    def test_unchanged_mask_is_not_converted_again(self, tmp_path, monkeypatch):
        tiff = write_mask(tmp_path / "s1_mask.tif", mask(64, 64))
        s3 = FakeS3()
        assert upload_labels_tiff(s3, BUCKET, DC_ID, str(tiff)) > 0
        calls = []
        monkeypatch.setattr(
            "depictio.cli.cli.utils.labels_tiff.convert_labels_tiff",
            lambda *a: calls.append(a),
        )
        assert upload_labels_tiff(s3, BUCKET, DC_ID, str(tiff)) == 0
        assert calls == []

    def test_changed_mask_reuploads(self, tmp_path):
        tiff = write_mask(tmp_path / "s1_mask.tif", mask(64, 64))
        s3 = FakeS3()
        upload_labels_tiff(s3, BUCKET, DC_ID, str(tiff))
        write_mask(tiff, mask(64, 128))
        assert upload_labels_tiff(s3, BUCKET, DC_ID, str(tiff)) > 0
        shape = json.loads(s3.objects[f"bioimage/{DC_ID}/s1_mask.tif/0/.zarray"])["shape"]
        assert shape == [64, 128]

    def test_float_mask_fails_before_upload(self, tmp_path, monkeypatch, cli_config, fake_s3):
        tiff = write_mask(tmp_path / "s1_mask.tif", np.zeros((8, 8), dtype=np.float32))
        _registered(monkeypatch, tiff)
        result = process_bioimage_data_collection(
            _ingest_dc(format="tiff", kind="labels"),
            cli_config,  # type: ignore[arg-type]
        )
        assert result["result"] == "error"
        assert "not an integer" in result["message"]
        assert fake_s3.uploaded == []

    def test_two_masks_of_one_sample_are_an_error(self, tmp_path, monkeypatch, cli_config, fake_s3):
        a = write_mask(tmp_path / "a" / "s1_mask.tif", mask(8, 8))
        b = write_mask(tmp_path / "b" / "s1_mask.tiff", mask(8, 8))
        _registered(monkeypatch, a, b)
        result = process_bioimage_data_collection(
            _ingest_dc(format="tiff", kind="labels", sample_pattern=r"^(.+?)_mask"),
            cli_config,  # type: ignore[arg-type]
        )
        assert result["result"] == "error"
        assert "distinct samples" in result["message"] and "s1" in result["message"]
        assert fake_s3.uploaded == []
