"""Unit tests for YAML serialization GeoJSON enrichment utilities."""

from depictio.models.yaml_serialization.utils import enrich_component_geojson_dc_tag


class MockProjectsCollection:
    """Simple mock for MongoDB projects collection with nested workflows/DCs."""

    def __init__(self, projects: list[dict]):
        self._projects = projects

    def find(self):
        return iter(self._projects)


def _make_projects(dc_id: str, dc_tag: str) -> list[dict]:
    """Helper: create a minimal projects list containing one DC."""
    return [
        {
            "workflows": [
                {
                    "data_collections": [
                        {
                            "_id": dc_id,
                            "data_collection_tag": dc_tag,
                            "type": "geojson",
                        }
                    ]
                }
            ]
        }
    ]


class TestEnrichComponentGeoJsonDcTag:
    """Tests for enrich_component_geojson_dc_tag utility."""

    def test_enriches_tag_from_dc_id(self):
        """Component with geojson_dc_id gets geojson_dc_tag set."""
        dc_id = "507f1f77bcf86cd799439011"
        projects = _make_projects(dc_id, "europe_regions")
        collection = MockProjectsCollection(projects)
        cache: dict[str, dict | None] = {}

        comp: dict = {"geojson_dc_id": dc_id}
        enrich_component_geojson_dc_tag(comp, cache, collection)

        assert comp["geojson_dc_tag"] == "europe_regions"

    def test_skips_when_no_geojson_dc_id(self):
        """Component without geojson_dc_id is unchanged."""
        collection = MockProjectsCollection([])
        cache: dict[str, dict | None] = {}

        comp: dict = {"map_type": "scatter_map"}
        enrich_component_geojson_dc_tag(comp, cache, collection)

        assert "geojson_dc_tag" not in comp

    def test_caches_dc_lookup(self):
        """Second call with same ID doesn't re-query."""
        dc_id = "507f1f77bcf86cd799439011"
        projects = _make_projects(dc_id, "europe_regions")
        collection = MockProjectsCollection(projects)
        cache: dict[str, dict | None] = {}

        comp1: dict = {"geojson_dc_id": dc_id}
        enrich_component_geojson_dc_tag(comp1, cache, collection)
        assert dc_id in cache

        # Replace collection with empty one; cache should still resolve
        empty_collection = MockProjectsCollection([])
        comp2: dict = {"geojson_dc_id": dc_id}
        enrich_component_geojson_dc_tag(comp2, cache, empty_collection)
        assert comp2["geojson_dc_tag"] == "europe_regions"

    def test_handles_missing_dc(self):
        """Non-existent DC ID results in cache entry of None, no crash."""
        collection = MockProjectsCollection([{"workflows": [{"data_collections": []}]}])
        cache: dict[str, dict | None] = {}

        comp: dict = {"geojson_dc_id": "nonexistent_id"}
        enrich_component_geojson_dc_tag(comp, cache, collection)

        assert cache["nonexistent_id"] is None
        assert "geojson_dc_tag" not in comp

    def test_handles_exception(self):
        """If projects collection raises, cache gets None and no crash."""

        class FailingCollection:
            def find(self):
                raise RuntimeError("DB connection lost")

        cache: dict[str, dict | None] = {}
        comp: dict = {"geojson_dc_id": "some_id"}
        enrich_component_geojson_dc_tag(comp, cache, FailingCollection())

        assert cache["some_id"] is None
        assert "geojson_dc_tag" not in comp
