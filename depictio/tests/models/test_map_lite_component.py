"""Unit tests for MapLiteComponent model validation."""

import pytest
import yaml
from pydantic import ValidationError

from depictio.models.components.lite import MapLiteComponent
from depictio.models.models.dashboards import DashboardDataLite

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


# ============================================================================
# Placement: grid tile vs floating panel
# ============================================================================


class TestMapLiteComponentPlacement:
    """A map may be lifted out of the grid into the dashboard-wide floating panel."""

    def test_defaults_to_grid(self, sample_scatter_map: MapLiteComponent):
        """Floating is opt-in: an unannotated map stays a normal grid tile."""
        assert sample_scatter_map.placement == "grid"
        assert sample_scatter_map.floating_initial_state == "compact"

    @pytest.mark.parametrize("placement", ["grid", "floating"])
    def test_valid_placements(self, placement: str):
        comp = MapLiteComponent(
            tag=f"map-{placement}",
            lat_column="lat",
            lon_column="lon",
            placement=placement,
        )
        assert comp.placement == placement

    def test_rejects_unknown_placement(self):
        """'top' is the *interactive* placement — it must not leak onto maps."""
        with pytest.raises(ValidationError, match="Invalid placement 'top'"):
            MapLiteComponent(
                tag="bad-placement",
                lat_column="lat",
                lon_column="lon",
                placement="top",
            )

    @pytest.mark.parametrize("state", ["compact", "expanded", "docked", "hidden"])
    def test_valid_floating_initial_states(self, state: str):
        comp = MapLiteComponent(
            tag=f"map-{state}",
            lat_column="lat",
            lon_column="lon",
            placement="floating",
            floating_initial_state=state,
        )
        assert comp.floating_initial_state == state

    def test_rejects_unknown_floating_initial_state(self):
        with pytest.raises(ValidationError, match="Invalid floating_initial_state 'huge'"):
            MapLiteComponent(
                tag="bad-state",
                lat_column="lat",
                lon_column="lon",
                placement="floating",
                floating_initial_state="huge",
            )

    def test_floating_composes_with_selection(self):
        """The point of a floating map is cross-filtering, so the two must coexist."""
        comp = MapLiteComponent(
            tag="floating-filter",
            lat_column="lat",
            lon_column="lon",
            placement="floating",
            selection_enabled=True,
            selection_column="sample_id",
        )
        assert comp.placement == "floating"
        assert comp.selection_enabled is True


# ============================================================================
# Placement round-trips through the dashboard layout and YAML export
# ============================================================================


def _dashboard_with(map_component: dict) -> DashboardDataLite:
    """A dashboard holding one map plus one card, so layout emptiness is meaningful."""
    return DashboardDataLite(
        version="1.0.0",
        title="Placement test",
        project_tag="proj",
        components=[
            map_component,
            {
                "tag": "a-card",
                "component_type": "card",
                "workflow_tag": "wf/x",
                "data_collection_tag": "dc",
                "column_name": "latitude",
                "aggregation": "mean",
            },
        ],
    )


_MAP_BASE = {
    "tag": "sites",
    "component_type": "map",
    "workflow_tag": "wf/x",
    "data_collection_tag": "dc",
    "lat_column": "latitude",
    "lon_column": "longitude",
}


class TestMapPlacementLayout:
    """A floating map is rendered by the React shell, so it must claim no grid slot."""

    def test_grid_map_gets_a_layout_item(self):
        full = _dashboard_with(dict(_MAP_BASE)).to_full()
        assert len(full["right_panel_layout_data"]) == 2

    def test_floating_map_gets_no_layout_item(self):
        full = _dashboard_with({**_MAP_BASE, "placement": "floating"}).to_full()
        layout = full["right_panel_layout_data"]
        assert len(layout) == 1, "only the card should occupy the grid"

        map_index = next(
            c["index"] for c in full["stored_metadata"] if c["component_type"] == "map"
        )
        assert all(item["i"] != f"box-{map_index}" for item in layout)

    def test_floating_map_still_reaches_stored_metadata(self):
        """It leaves the grid, not the dashboard — the panel reads it from here."""
        full = _dashboard_with({**_MAP_BASE, "placement": "floating"}).to_full()
        stored = next(c for c in full["stored_metadata"] if c["component_type"] == "map")
        assert stored["placement"] == "floating"
        assert stored["floating_initial_state"] == "compact"

    def test_floating_map_does_not_leave_a_gap(self):
        """Skipping it must not consume an auto-layout row the card then skips over."""
        full = _dashboard_with({**_MAP_BASE, "placement": "floating"}).to_full()
        assert full["right_panel_layout_data"][0]["y"] == 0


class TestMapPlacementExport:
    """Export keeps YAML terse: only non-default placement is written out."""

    def _exported_map(self, **overrides) -> dict:
        full_map = {
            "index": "map-1",
            "component_type": "map",
            "wf_id": "wf",
            "dc_id": "dc",
            "map_type": "scatter_map",
            "lat_column": "latitude",
            "lon_column": "longitude",
            "map_style": "open-street-map",
            "opacity": 1.0,
            "size_max": 15,
            "featureidkey": "id",
            "selection_enabled": False,
            "placement": "grid",
            "floating_initial_state": "compact",
        }
        full_map.update(overrides)
        lite = DashboardDataLite.from_full(
            {
                "dashboard_id": "d1",
                "title": "T",
                "project_id": "p1",
                "version": "1.0.0",
                "stored_metadata": [full_map],
            }
        )
        comp = lite.components[0]
        return comp if isinstance(comp, dict) else comp.model_dump(exclude_unset=True)

    def test_grid_default_is_omitted(self):
        comp = self._exported_map()
        assert "placement" not in comp
        assert "floating_initial_state" not in comp

    def test_floating_is_exported(self):
        comp = self._exported_map(placement="floating", floating_initial_state="expanded")
        assert comp["placement"] == "floating"
        assert comp["floating_initial_state"] == "expanded"

    def test_floating_with_default_state_omits_the_state(self):
        comp = self._exported_map(placement="floating")
        assert comp["placement"] == "floating"
        assert "floating_initial_state" not in comp

    def test_survives_a_full_yaml_round_trip(self):
        lite = _dashboard_with(
            {**_MAP_BASE, "placement": "floating", "floating_initial_state": "hidden"}
        )
        reimported = DashboardDataLite(**yaml.safe_load(lite.to_yaml()))
        comp = reimported.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp["placement"] == "floating"
        assert comp["floating_initial_state"] == "hidden"
