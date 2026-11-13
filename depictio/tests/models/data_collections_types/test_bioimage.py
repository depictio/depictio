"""Unit tests for the bioimage data collection model and its S3 layout."""

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections_types.bioimage import (
    DCBioimageConfig,
    bioimage_s3_prefix,
    bioimage_sample_name,
)
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


class TestDCBioimageConfig:
    def test_defaults(self):
        config = DCBioimageConfig()
        assert config.format == "ome-zarr"
        assert config.ngff_version == "0.4"
        assert config.upload is True

    def test_explicit_format(self):
        assert DCBioimageConfig(format="ome-zarr").format == "ome-zarr"

    def test_unsupported_format_rejected(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(format="ome-tiff")  # type: ignore[arg-type]

    def test_reference_only(self):
        assert DCBioimageConfig(upload=False).upload is False

    def test_unsupported_ngff_version_rejected(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(ngff_version="0.5")  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DCBioimageConfig(separator=",")  # type: ignore[call-arg]


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
        [("sample_A.zarr", "sample_A"), ("sample_A.zarr/", "sample_A"), ("plain", "plain")],
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
