"""Unit tests for GeoJSON Data Collection model."""

import pytest
from pydantic import ValidationError

from depictio.models.models.data_collections_types.geojson import DCGeoJSONConfig


class TestDCGeoJSONConfig:
    """Test suite for DCGeoJSONConfig model validation and behavior."""

    def test_valid_config_defaults(self):
        """Test creating config with default values."""
        config = DCGeoJSONConfig()
        assert config.feature_id_key == "id"
        assert config.s3_location is None
        assert config.file_size_bytes is None

    def test_valid_config_all_fields(self):
        """Test creating config with all fields populated."""
        config = DCGeoJSONConfig(
            feature_id_key="properties.ISO_A3",
            s3_location="s3://bucket/geojson/europe.geojson",
            file_size_bytes=1024000,
        )
        assert config.feature_id_key == "properties.ISO_A3"
        assert config.s3_location == "s3://bucket/geojson/europe.geojson"
        assert config.file_size_bytes == 1024000

    def test_custom_feature_id_key(self):
        """Test custom feature_id_key with nested property path."""
        config = DCGeoJSONConfig(feature_id_key="properties.NAME")
        assert config.feature_id_key == "properties.NAME"

    def test_extra_fields_forbidden(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError) as exc_info:
            DCGeoJSONConfig(
                feature_id_key="id",
                unknown_field="should_fail",  # type: ignore[call-arg]
            )
        assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()
