"""NGFF metadata validation of bioimage stores (reported, never blocking)."""

from __future__ import annotations

from pathlib import Path

import pytest

zarr = pytest.importorskip("zarr")
from depictio.cli.cli.utils import ngff_validation  # noqa: E402
from depictio.cli.cli.utils.ngff_validation import validate_ngff_store  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ngff_validation.validator_available(), reason="ome-zarr-models cannot validate here"
)

CYX_AXES = [
    {"name": "c", "type": "channel"},
    {"name": "y", "type": "space", "unit": "micrometer"},
    {"name": "x", "type": "space", "unit": "micrometer"},
]


def _multiscales(axes: list[dict], version: str = "0.4") -> list[dict]:
    ndim = len(axes)
    return [
        {
            "version": version,
            "axes": axes,
            "datasets": [
                {
                    "path": "0",
                    "coordinateTransformations": [{"type": "scale", "scale": [1.0] * ndim}],
                }
            ],
        }
    ]


def _image(path: Path, axes: list[dict] = CYX_AXES, version: str = "0.4", **attrs) -> Path:
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    group.create_array(
        "0", shape=(2, 8, 8)[-len(axes) :], chunks=(1, 8, 8)[-len(axes) :], dtype="uint16"
    )
    group.attrs.update({"multiscales": _multiscales(axes, version), **attrs})
    return path


def test_a_valid_image_passes(tmp_path):
    report = validate_ngff_store(str(_image(tmp_path / "ok.zarr")))

    assert report.ok
    assert (report.ngff_version, report.layout, report.issues) == ("0.4", "image", [])
    assert report.validator and report.validator.startswith("ome-zarr-models ")


def test_axes_out_of_spec_order_are_reported_with_their_location(tmp_path):
    axes = [CYX_AXES[1], CYX_AXES[2], CYX_AXES[0]]  # y, x, c: channel after space
    report = validate_ngff_store(str(_image(tmp_path / "yxc.zarr", axes=axes)))

    assert not report.ok
    assert report.layout == "image"
    assert report.issues and all(":" in issue for issue in report.issues)
    # One line per location: a union field does not repeat per branch.
    assert len(report.issues) == len(set(report.issues))


def test_label_images_are_listed_and_validated(tmp_path):
    store = _image(tmp_path / "with_labels.zarr")
    root = zarr.open_group(str(store), mode="a", zarr_format=2)
    labels = root.create_group("labels")
    labels.attrs["labels"] = ["nuclei"]
    nuclei = labels.create_group("nuclei")
    nuclei.create_array("0", shape=(8, 8), chunks=(8, 8), dtype="uint32")
    nuclei.attrs.update(
        {
            "multiscales": _multiscales([CYX_AXES[1], CYX_AXES[2]]),
            "image-label": {
                "version": "0.4",
                "colors": [{"label-value": 1, "rgba": [255, 0, 0, 255]}],
            },
        }
    )

    report = validate_ngff_store(str(store))

    assert report.labels == ["nuclei"]
    assert report.ok, report.issues


def test_a_listed_label_that_is_missing_is_an_issue(tmp_path):
    store = _image(tmp_path / "missing_label.zarr")
    root = zarr.open_group(str(store), mode="a", zarr_format=2)
    root.create_group("labels").attrs["labels"] = ["cells"]

    report = validate_ngff_store(str(store))

    assert not report.ok
    assert "labels/cells: listed in labels/ but missing" in report.issues


def test_a_plate_is_recognised_as_a_plate(tmp_path):
    plate = zarr.open_group(str(tmp_path / "plate.zarr"), mode="w", zarr_format=2)
    plate.attrs["plate"] = {
        "version": "0.4",
        "columns": [{"name": "1"}],
        "rows": [{"name": "A"}],
        "wells": [{"path": "A/1", "rowIndex": 0, "columnIndex": 0}],
        "field_count": 1,
    }
    well = plate.create_group("A/1")
    well.attrs["well"] = {"version": "0.4", "images": [{"path": "0"}]}
    _image(tmp_path / "plate.zarr" / "A" / "1" / "0")

    report = validate_ngff_store(str(tmp_path / "plate.zarr"))

    assert report.layout == "plate"
    assert report.ngff_version == "0.4"


def test_an_unreleased_version_is_named_not_parsed(tmp_path):
    report = validate_ngff_store(str(_image(tmp_path / "dev.zarr", version="0.5-dev-spatialdata")))

    assert not report.ok
    assert report.issues == [
        "NGFF version '0.5-dev-spatialdata' is not a released spec version (0.4, 0.5); "
        "other viewers may refuse it"
    ]


def test_a_spatialdata_store_is_validated_on_its_image_element(tmp_path):
    store = tmp_path / "sample.zarr"
    zarr.open_group(str(store), mode="w", zarr_format=2).create_group("images")
    _image(store / "images" / "he")

    report = validate_ngff_store(str(store), "images/he")

    assert report.ok and report.layout == "image"


@pytest.mark.parametrize("make", ["missing", "empty_group"])
def test_a_store_without_ngff_metadata_never_raises(tmp_path, make):
    path = tmp_path / "plain.zarr"
    if make == "empty_group":
        zarr.open_group(str(path), mode="w", zarr_format=2)

    report = validate_ngff_store(str(path))

    assert not report.ok
    assert len(report.issues) == 1


def test_an_install_that_cannot_validate_reports_nothing(tmp_path, monkeypatch):
    """No report rather than every store marked invalid (Python 3.11 installs)."""
    monkeypatch.setattr(ngff_validation, "validator_available", lambda: False)
    assert validate_ngff_store(str(_image(tmp_path / "a.zarr"))) is None


def _plate(path: Path, n_wells: int, broken: set[int] = frozenset()) -> Path:
    """A one-row plate of ``n_wells`` wells, one field each; a ``broken``
    well's field has a scale shorter than its axes."""
    plate = zarr.open_group(str(path), mode="w", zarr_format=2)
    plate.attrs["plate"] = {
        "version": "0.4",
        "columns": [{"name": str(i + 1)} for i in range(n_wells)],
        "rows": [{"name": "A"}],
        "wells": [{"path": f"A/{i + 1}", "rowIndex": 0, "columnIndex": i} for i in range(n_wells)],
        "field_count": 1,
    }
    for i in range(n_wells):
        well = plate.create_group(f"A/{i + 1}")
        well.attrs["well"] = {"version": "0.4", "images": [{"path": "0"}]}
        field = _image(path / "A" / str(i + 1) / "0")
        if i in broken:
            bad = _multiscales(CYX_AXES)
            bad[0]["datasets"][0]["coordinateTransformations"][0]["scale"] = [1.0, 1.0]
            zarr.open_group(str(field), mode="a").attrs["multiscales"] = bad
    return path


def test_a_large_plate_is_checked_on_a_few_wells(tmp_path, monkeypatch):
    """A plate is not walked well by well: on a remote 384-well plate that is
    thousands of reads. The plate metadata and the first, middle and last
    wells are checked, and the report says so."""
    from ome_zarr_models import v04

    opened: list[str] = []
    real = v04.Image.from_zarr.__func__

    def spy(cls, group):
        opened.append(group.path)
        return real(cls, group)

    monkeypatch.setattr(v04.Image, "from_zarr", classmethod(spy))
    store = _plate(tmp_path / "plate.zarr", n_wells=9, broken={8})

    report = validate_ngff_store(str(store))

    assert sorted(opened) == ["A/1/0", "A/5/0", "A/9/0"]
    assert report.layout == "plate"
    assert report.checked == "plate metadata and 3 of 9 wells"
    assert not report.ok
    assert all(issue.startswith("A/9/") for issue in report.issues)


def test_a_small_plate_is_checked_whole(tmp_path):
    report = validate_ngff_store(str(_plate(tmp_path / "plate.zarr", n_wells=2)))

    assert report.ok
    assert report.checked == "plate metadata and 2 of 2 wells"


def test_a_well_the_plate_lists_but_lacks_is_reported(tmp_path):
    store = _plate(tmp_path / "plate.zarr", n_wells=3)
    import shutil

    shutil.rmtree(store / "A" / "3")

    report = validate_ngff_store(str(store))

    assert "A/3: listed in the plate but missing" in report.issues


def test_bioformats2raw_is_checked_on_its_first_series(tmp_path):
    root = zarr.open_group(str(tmp_path / "b2r.zarr"), mode="w", zarr_format=2)
    root.attrs["bioformats2raw.layout"] = 3
    for i in range(5):
        _image(tmp_path / "b2r.zarr" / str(i))

    report = validate_ngff_store(str(tmp_path / "b2r.zarr"))

    assert report.layout == "bioformats2raw"
    assert report.ok, report.issues
    assert report.checked == "bioformats2raw metadata and the first 3 series"


def test_an_array_zarr_python_cannot_read_is_not_an_ngff_error(tmp_path):
    """``>u1`` is a valid Zarr v2 dtype (IDR writes it) that zarr-python 3
    refuses. The metadata is checked alone, and the report says the arrays
    were not read, rather than calling a valid store invalid."""
    import json

    store = _image(tmp_path / "be.zarr")
    zarray = store / "0" / ".zarray"
    meta = json.loads(zarray.read_text())
    meta["dtype"] = ">u1"
    zarray.write_text(json.dumps(meta))

    report = validate_ngff_store(str(store))

    assert report.ok, report.issues
    assert report.checked.startswith("metadata only: zarr-python could not read the arrays")


def test_a_well_with_many_fields_is_checked_on_a_few(tmp_path, monkeypatch):
    from ome_zarr_models import v04

    opened: list[str] = []
    real = v04.Image.from_zarr.__func__

    def spy(cls, group):
        opened.append(group.path)
        return real(cls, group)

    monkeypatch.setattr(v04.Image, "from_zarr", classmethod(spy))
    plate = zarr.open_group(str(tmp_path / "p.zarr"), mode="w", zarr_format=2)
    plate.attrs["plate"] = {
        "version": "0.4",
        "columns": [{"name": "1"}],
        "rows": [{"name": "A"}],
        "wells": [{"path": "A/1", "rowIndex": 0, "columnIndex": 0}],
        "field_count": 9,
    }
    well = plate.create_group("A/1")
    well.attrs["well"] = {"version": "0.4", "images": [{"path": str(i)} for i in range(9)]}
    for i in range(9):
        _image(tmp_path / "p.zarr" / "A" / "1" / str(i))

    report = validate_ngff_store(str(tmp_path / "p.zarr"))

    assert report.ok, report.issues
    assert sorted(opened) == ["A/1/0", "A/1/4", "A/1/8"]
    assert report.checked == "plate metadata and 1 of 1 wells, 3 of up to 9 fields each"
