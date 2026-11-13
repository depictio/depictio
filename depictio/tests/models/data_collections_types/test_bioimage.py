"""Unit tests for the bioimage data collection model and its S3 layout."""

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import DataCollectionConfig
from depictio.models.models.data_collections_types.bioimage import (
    DCBioimageConfig,
    bioimage_s3_object_key,
    bioimage_s3_prefix,
    bioimage_sample_name,
    is_bioimage_store_name,
    is_single_file_format,
    remote_store_name,
)
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


class TestDCBioimageConfig:
    def test_defaults(self):
        config = DCBioimageConfig()
        assert config.format == "ome-zarr"
        assert config.ngff_version is None
        assert config.upload is True

    def test_explicit_format(self):
        assert DCBioimageConfig(format="ome-zarr").format == "ome-zarr"

    def test_unsupported_format_rejected(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(format="czi")  # type: ignore[arg-type]

    def test_reference_only(self):
        assert DCBioimageConfig(upload=False).upload is False

    def test_unsupported_ngff_version_rejected(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(ngff_version="0.6")  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(separator=",")  # type: ignore[call-arg]

    def test_spatialdata_needs_image_path(self):
        with pytest.raises(ValidationError, match="needs image_path"):
            DCBioimageConfig(format="spatialdata")
        config = DCBioimageConfig(format="spatialdata", image_path="images/he/")
        assert config.image_path == "images/he"

    @pytest.mark.parametrize("path", ["/images/he", "../he", "images/../../he", ""])
    def test_image_path_must_stay_inside_the_store(self, path):
        with pytest.raises(ValidationError):
            DCBioimageConfig(format="spatialdata", image_path=path)

    def test_image_path_is_spatialdata_only(self):
        with pytest.raises(ValidationError, match="only applies"):
            DCBioimageConfig(image_path="images/he")

    def test_remote_stores(self):
        config = DCBioimageConfig(
            format="ome-tiff",
            remote_stores=["https://example.org/data/a.ome.tif", "s3://bucket/b.ome.tiff"],
        )
        assert [remote_store_name(u) for u in config.remote_stores] == ["a.ome.tif", "b.ome.tiff"]

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.org/a.zarr",
            "file:///data/a.zarr",
            "https://user:pw@example.org/a.zarr",
            "https://example.org/a.zarr?sig=1",
            "https://example.org/x/../a.zarr",
            "https://example.org/a.ome.tif",
        ],
    )
    def test_bad_remote_store_rejected(self, url):
        with pytest.raises(ValidationError):
            DCBioimageConfig(remote_stores=[url])

    def test_remote_store_names_are_unique(self):
        with pytest.raises(ValidationError, match="share a name"):
            DCBioimageConfig(remote_stores=["s3://a/x/s.zarr", "https://example.org/s.zarr"])


class TestRemoteOnlyDataCollection:
    def _config(self, **props):
        return DataCollectionConfig(type="bioimage", dc_specific_properties=props)

    def test_remote_only_needs_no_scan(self):
        config = self._config(remote_stores=["https://example.org/a.zarr"])
        assert config.scan is None

    def test_local_bioimage_still_needs_a_scan(self):
        with pytest.raises(ValidationError, match="scan field is required"):
            self._config()


class TestStoreNames:
    @pytest.mark.parametrize(
        ("name", "fmt", "ok"),
        [
            ("a.zarr", "ome-zarr", True),
            ("a.zarr", "spatialdata", True),
            ("a.ome.tif", "ome-tiff", True),
            ("a.ome.tiff", "ome-tiff", True),
            ("a.tif", "ome-tiff", False),
            ("a.zarr", "ome-tiff", False),
            (".zarr", "ome-zarr", False),
            ("x/a.zarr", "ome-zarr", False),
            ("..a.zarr", "ome-zarr", False),
        ],
    )
    def test_is_bioimage_store_name(self, name, fmt, ok):
        assert is_bioimage_store_name(name, fmt) is ok

    def test_single_file_formats(self):
        assert is_single_file_format("ome-tiff")
        assert not is_single_file_format("ome-zarr")
        assert not is_single_file_format("spatialdata")

    def test_tiff_object_key(self):
        assert bioimage_s3_object_key(DC_ID, "a.ome.tif") == f"bioimage/{DC_ID}/a.ome.tif"


class TestS3Layout:
    def test_dc_prefix(self):
        assert bioimage_s3_prefix(DC_ID) == f"bioimage/{DC_ID}/"

    def test_store_prefix(self):
        assert bioimage_s3_prefix(DC_ID, "sample_A.zarr") == f"bioimage/{DC_ID}/sample_A.zarr/"

    def test_prefix_is_not_an_objectid_prefix(self):
        """Orphan cleanup deletes 24-hex top-level prefixes with no deltatable document."""
        assert bioimage_s3_prefix(DC_ID).split("/")[0] == "bioimage"

    @pytest.mark.parametrize(
        ("store", "sample"),
        [
            ("sample_A.zarr", "sample_A"),
            ("sample_A.zarr/", "sample_A"),
            ("sample_A.ome.tif", "sample_A"),
            ("sample_A.ome.tiff", "sample_A"),
            ("plain", "plain"),
        ],
    )
    def test_sample_name(self, store, sample):
        assert bioimage_sample_name(store) == sample


class TestStoreDirectoryAsFile:
    """In CLI context a File must be a readable file, except for a *.zarr store dir."""

    @pytest.fixture
    def cli_context(self, monkeypatch):
        monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")

    def _file(self, location: str) -> File:
        return File(  # type: ignore[missing-argument]
            filename="x",
            file_location=location,
            creation_time="2025-01-01 10:00:00",
            modification_time="2025-01-01 11:00:00",
            data_collection_id=PyObjectId(),
            filesize=10,
            file_hash="a" * 64,
            permissions=Permission(
                owners=[UserBase(id=PyObjectId(), email="t@example.com", is_admin=True)]
            ),
        )

    def test_zarr_store_directory_accepted(self, tmp_path, cli_context):
        store = tmp_path / "sample_A.zarr"
        store.mkdir()
        assert self._file(str(store)).file_location == str(store)

    def test_plain_directory_still_rejected(self, tmp_path, cli_context):
        folder = tmp_path / "images"
        folder.mkdir()
        with pytest.raises(ValidationError, match="is not a file"):
            self._file(str(folder))
