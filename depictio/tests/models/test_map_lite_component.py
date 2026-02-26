"""Unit tests for MapLiteComponent model validation."""

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import MapLiteComponent

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_scatter_map() -> MapLiteComponent:
    """Minimal valid scatter_map component."""
    return MapLiteComponent(
        tag="scatter-locations",
        lat_column="latitude",
        lon_column="longitude",
    )


@pytest.fixture
def sample_choropleth_map() -> MapLiteComponent:
    """Minimal valid choropleth_map component."""
    return MapLiteComponent(
        tag="choropleth-europe",
        map_type="choropleth_map",
        locations_column="country_code",
        geojson_url="https://example.com/europe.geojson",
        color_column="population",
    )


# ============================================================================
# Scatter map tests
# ============================================================================


class TestMapLiteComponentScatter:
    """Tests for scatter_map type."""

    def test_valid_scatter_map(self, sample_scatter_map: MapLiteComponent):
        """Valid scatter_map with required lat/lon columns."""
        assert sample_scatter_map.map_type == "scatter_map"
        assert sample_scatter_map.lat_column == "latitude"
        assert sample_scatter_map.lon_column == "longitude"

    def test_scatter_requires_lat_column(self):
        """scatter_map without lat_column should fail."""
        with pytest.raises(ValidationError, match="lat_column is required"):
            MapLiteComponent(
                tag="missing-lat",
                map_type="scatter_map",
                lon_column="longitude",
            )

    def test_scatter_requires_lon_column(self):
        """scatter_map without lon_column should fail."""
        with pytest.raises(ValidationError, match="lon_column is required"):
            MapLiteComponent(
                tag="missing-lon",
                map_type="scatter_map",
                lat_column="latitude",
            )

    def test_scatter_with_selection(self):
        """scatter_map with selection enabled."""
        comp = MapLiteComponent(
            tag="selectable",
            lat_column="lat",
            lon_column="lon",
            selection_enabled=True,
            selection_column="sample_id",
        )
        assert comp.selection_enabled is True
        assert comp.selection_column == "sample_id"

    def test_scatter_selection_requires_column(self):
        """selection_enabled=True without selection_column should fail."""
        with pytest.raises(ValidationError, match="selection_column is required"):
            MapLiteComponent(
                tag="bad-selection",
                lat_column="lat",
                lon_column="lon",
                selection_enabled=True,
            )


# ============================================================================
# Density map tests
# ============================================================================


class TestMapLiteComponentDensity:
    """Tests for density_map type."""

    def test_valid_density_map(self):
        """Valid density_map with required z_column."""
        comp = MapLiteComponent(
            tag="density",
            map_type="density_map",
            lat_column="lat",
            lon_column="lon",
            z_column="weight",
        )
        assert comp.map_type == "density_map"
        assert comp.z_column == "weight"

    def test_density_requires_z_column(self):
        """density_map without z_column should fail."""
        with pytest.raises(ValidationError, match="z_column is required"):
            MapLiteComponent(
                tag="no-z",
                map_type="density_map",
                lat_column="lat",
                lon_column="lon",
            )


# ============================================================================
# Choropleth map tests
# ============================================================================


class TestMapLiteComponentChoropleth:
    """Tests for choropleth_map type."""

    def test_valid_choropleth_with_url(self, sample_choropleth_map: MapLiteComponent):
        """Valid choropleth_map with geojson_url."""
        assert sample_choropleth_map.map_type == "choropleth_map"
        assert sample_choropleth_map.locations_column == "country_code"
        assert sample_choropleth_map.geojson_url == "https://example.com/europe.geojson"
        assert sample_choropleth_map.color_column == "population"

    def test_valid_choropleth_with_geojson_dc_id(self):
        """Valid choropleth_map with geojson_dc_id reference."""
        comp = MapLiteComponent(
            tag="choropleth-dc",
            map_type="choropleth_map",
            locations_column="region",
            geojson_dc_id="507f1f77bcf86cd799439011",
            color_column="value",
        )
        assert comp.geojson_dc_id == "507f1f77bcf86cd799439011"

    def test_valid_choropleth_with_inline_data(self):
        """Valid choropleth_map with inline geojson_data."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Test"},
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ],
        }
        comp = MapLiteComponent(
            tag="choropleth-inline",
            map_type="choropleth_map",
            locations_column="name",
            geojson_data=geojson,
            color_column="value",
        )
        assert comp.geojson_data is not None

    def test_choropleth_requires_locations_column(self):
        """choropleth_map without locations_column should fail."""
        with pytest.raises(ValidationError, match="locations_column is required"):
            MapLiteComponent(
                tag="no-locations",
                map_type="choropleth_map",
                geojson_url="https://example.com/geo.geojson",
                color_column="value",
            )

    def test_choropleth_requires_geojson_source(self):
        """choropleth_map without any geojson source should fail."""
        with pytest.raises(ValidationError, match="geojson_data, geojson_url, or geojson_dc_id"):
            MapLiteComponent(
                tag="no-geojson",
                map_type="choropleth_map",
                locations_column="country",
                color_column="value",
            )

    def test_choropleth_requires_color_column(self):
        """choropleth_map without color_column should fail."""
        with pytest.raises(ValidationError, match="color_column is required"):
            MapLiteComponent(
                tag="no-color",
                map_type="choropleth_map",
                locations_column="country",
                geojson_url="https://example.com/geo.geojson",
            )

    def test_choropleth_selection_not_supported(self):
        """choropleth_map does not support selection_enabled."""
        with pytest.raises(ValidationError, match="selection_enabled is not supported"):
            MapLiteComponent(
                tag="choropleth-select",
                map_type="choropleth_map",
                locations_column="country",
                geojson_url="https://example.com/geo.geojson",
                color_column="value",
                selection_enabled=True,
                selection_column="country",
            )


# ============================================================================
# General validation tests
# ============================================================================


class TestMapLiteComponentValidation:
    """Tests for general MapLiteComponent validation rules."""

    def test_invalid_map_type(self):
        """Unknown map_type should fail."""
        with pytest.raises(ValidationError, match="Invalid map_type"):
            MapLiteComponent(
                tag="bad-type",
                map_type="heatmap_3d",
                lat_column="lat",
                lon_column="lon",
            )

    def test_invalid_map_style(self):
        """Unknown map_style should fail."""
        with pytest.raises(ValidationError, match="Invalid map_style"):
            MapLiteComponent(
                tag="bad-style",
                lat_column="lat",
                lon_column="lon",
                map_style="google-satellite",
            )

    def test_invalid_choropleth_aggregation(self):
        """Invalid choropleth_aggregation value should fail."""
        with pytest.raises(ValidationError, match="Invalid choropleth_aggregation"):
            MapLiteComponent(
                tag="bad-agg",
                lat_column="lat",
                lon_column="lon",
                choropleth_aggregation="percentile",
            )

    def test_range_color_must_have_two_elements(self):
        """range_color with wrong number of elements should fail."""
        with pytest.raises(ValidationError, match="range_color must have exactly 2 elements"):
            MapLiteComponent(
                tag="bad-range",
                lat_column="lat",
                lon_column="lon",
                range_color=[0.0, 50.0, 100.0],
            )

    def test_default_center_requires_lat_lon(self):
        """default_center missing lat or lon keys should fail."""
        with pytest.raises(ValidationError, match="default_center must have 'lat' and 'lon'"):
            MapLiteComponent(
                tag="bad-center",
                lat_column="lat",
                lon_column="lon",
                default_center={"latitude": 45.0, "longitude": 5.0},
            )

    def test_valid_default_center(self):
        """default_center with proper lat/lon keys should pass."""
        comp = MapLiteComponent(
            tag="centered",
            lat_column="lat",
            lon_column="lon",
            default_center={"lat": 45.0, "lon": 5.0},
        )
        assert comp.default_center == {"lat": 45.0, "lon": 5.0}

    def test_valid_choropleth_aggregation(self):
        """Valid choropleth_aggregation values should pass."""
        for agg in ("count", "sum", "mean", "min", "max"):
            comp = MapLiteComponent(
                tag=f"agg-{agg}",
                lat_column="lat",
                lon_column="lon",
                choropleth_aggregation=agg,
            )
            assert comp.choropleth_aggregation == agg
