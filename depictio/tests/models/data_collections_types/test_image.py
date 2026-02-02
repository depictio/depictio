"""Unit tests for Image Data Collection model."""

import pytest
from pydantic import ValidationError

from depictio.models.models.data_collections_types.image import (
    DEFAULT_IMAGE_EXTENSIONS,
    DCImageConfig,
)


class TestDCImageConfig:
    """Test suite for DCImageConfig model validation and behavior."""

    def test_valid_config_minimal(self):
        """Test creating minimal valid config with required fields only."""
        config = DCImageConfig(
            format="csv",
            image_column="image_path",
        )
        assert config.format == "csv"
        assert config.image_column == "image_path"
        assert config.polars_kwargs == {}
        assert config.keep_columns is None
        assert config.s3_base_folder is None
        assert config.thumbnail_size == 150
        assert config.supported_formats == DEFAULT_IMAGE_EXTENSIONS

    def test_valid_config_all_fields(self):
        """Test creating config with all optional fields."""
        config = DCImageConfig(
            format="parquet",
            image_column="images",
            polars_kwargs={"delimiter": ","},
            keep_columns=["id", "name", "images"],
            columns_description={"id": "Unique ID", "name": "Sample name"},
            s3_base_folder="s3://bucket/images/",
            local_images_path="/data/images",
            supported_formats=[".png", ".jpg"],
            thumbnail_size=200,
        )
        assert config.format == "parquet"
        assert config.image_column == "images"
        assert config.s3_base_folder == "s3://bucket/images/"
        assert config.local_images_path == "/data/images"
        assert config.supported_formats == [".png", ".jpg"]
        assert config.thumbnail_size == 200

    def test_format_validation_valid_formats(self):
        """Test format field accepts all valid formats."""
        for fmt in ["csv", "tsv", "parquet", "feather", "xls", "xlsx", "mixed"]:
            config = DCImageConfig(format=fmt, image_column="img")
            assert config.format == fmt

    def test_format_validation_case_insensitive(self):
        """Test format validation normalizes to lowercase."""
        config = DCImageConfig(format="CSV", image_column="img")
        assert config.format == "csv"

    def test_format_validation_invalid(self):
        """Test format field rejects invalid formats."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(format="json", image_column="img")
        assert "format must be one of" in str(exc_info.value)

    def test_image_column_required(self):
        """Test image_column is a required field."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(format="csv")  # type: ignore[call-arg]
        assert "image_column" in str(exc_info.value)

    def test_image_column_empty_rejected(self):
        """Test empty image_column is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(format="csv", image_column="  ")
        assert "image_column is required" in str(exc_info.value)

    def test_image_column_whitespace_stripped(self):
        """Test image_column whitespace is stripped."""
        config = DCImageConfig(format="csv", image_column="  image_path  ")
        assert config.image_column == "image_path"

    def test_s3_base_folder_validation_valid(self):
        """Test s3_base_folder accepts valid S3 paths."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            s3_base_folder="s3://bucket/path/to/images",
        )
        # Should add trailing slash
        assert config.s3_base_folder == "s3://bucket/path/to/images/"

    def test_s3_base_folder_adds_trailing_slash(self):
        """Test s3_base_folder automatically adds trailing slash."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            s3_base_folder="s3://bucket/images",
        )
        assert config.s3_base_folder == "s3://bucket/images/"

    def test_s3_base_folder_invalid_prefix(self):
        """Test s3_base_folder rejects paths without s3:// prefix."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(
                format="csv",
                image_column="img",
                s3_base_folder="bucket/images",
            )
        assert "s3_base_folder must start with 's3://'" in str(exc_info.value)

    def test_s3_base_folder_empty_allowed(self):
        """Test s3_base_folder can be None or empty."""
        config1 = DCImageConfig(format="csv", image_column="img", s3_base_folder=None)
        assert config1.s3_base_folder is None

        config2 = DCImageConfig(format="csv", image_column="img")
        assert config2.s3_base_folder is None

    def test_supported_formats_normalization(self):
        """Test supported_formats normalizes extensions."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            supported_formats=["png", ".jpg", "JPEG", ".GIF"],
        )
        # All should be lowercase with leading dot
        assert config.supported_formats == [".png", ".jpg", ".jpeg", ".gif"]

    def test_thumbnail_size_validation_valid_range(self):
        """Test thumbnail_size accepts valid values."""
        config = DCImageConfig(format="csv", image_column="img", thumbnail_size=100)
        assert config.thumbnail_size == 100

    def test_thumbnail_size_validation_too_small(self):
        """Test thumbnail_size rejects values below minimum."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(format="csv", image_column="img", thumbnail_size=30)
        assert "greater than or equal to 50" in str(exc_info.value)

    def test_thumbnail_size_validation_too_large(self):
        """Test thumbnail_size rejects values above maximum."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(format="csv", image_column="img", thumbnail_size=1500)
        assert "less than or equal to 1000" in str(exc_info.value)

    def test_thumbnail_size_default(self):
        """Test thumbnail_size uses default value."""
        config = DCImageConfig(format="csv", image_column="img")
        assert config.thumbnail_size == 150

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            DCImageConfig(
                format="csv",
                image_column="img",
                unknown_field="should_fail",  # type: ignore[call-arg]
            )
        assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()

    def test_polars_kwargs_inheritance(self):
        """Test polars_kwargs from Table DC is available."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            polars_kwargs={"separator": ";", "has_header": True},
        )
        assert config.polars_kwargs == {"separator": ";", "has_header": True}

    def test_keep_columns_inheritance(self):
        """Test keep_columns from Table DC is available."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            keep_columns=["sample_id", "image_path", "timestamp"],
        )
        assert config.keep_columns == ["sample_id", "image_path", "timestamp"]

    def test_columns_description_inheritance(self):
        """Test columns_description from Table DC is available."""
        config = DCImageConfig(
            format="csv",
            image_column="img",
            columns_description={
                "sample_id": "Unique sample identifier",
                "image_path": "Path to image file",
            },
        )
        assert config.columns_description["sample_id"] == "Unique sample identifier"
        assert config.columns_description["image_path"] == "Path to image file"
