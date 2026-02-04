"""
Unit tests for shared selection utilities.

Tests cover:
- Store initialization
- Metadata lookup building
- Reset button handling
- Value filtering
- Update prevention logic
- Selection entry creation
- Value merging
"""


from depictio.dash.modules.shared.selection_utils import (
    build_metadata_lookup,
    create_selection_entry,
    filter_existing_values,
    handle_reset_button,
    initialize_store,
    merge_selection_values,
    should_prevent_update,
)


class TestInitializeStore:
    """Tests for initialize_store function."""

    def test_returns_default_when_none(self):
        """Should return default store structure when input is None."""
        result = initialize_store(None)

        assert result == {"interactive_components_values": [], "first_load": False}

    def test_returns_existing_store_unchanged(self):
        """Should return existing store when not None."""
        existing = {
            "interactive_components_values": [{"index": "abc", "value": [1, 2]}],
            "first_load": True,
        }

        result = initialize_store(existing)

        assert result is existing
        assert result["interactive_components_values"] == [{"index": "abc", "value": [1, 2]}]

    def test_returns_empty_store_structure(self):
        """Should return proper structure for empty store."""
        empty_store = {"interactive_components_values": [], "first_load": False}

        result = initialize_store(empty_store)

        assert result is empty_store


class TestBuildMetadataLookup:
    """Tests for build_metadata_lookup function."""

    def test_builds_lookup_from_lists(self):
        """Should build correct lookup from metadata lists."""
        metadata_list = [
            {"component_type": "figure", "dc_id": "dc1"},
            {"component_type": "table", "dc_id": "dc2"},
        ]
        metadata_ids = [{"index": "fig-123"}, {"index": "tbl-456"}]

        result = build_metadata_lookup(metadata_list, metadata_ids)

        assert "fig-123" in result
        assert "tbl-456" in result
        assert result["fig-123"]["dc_id"] == "dc1"
        assert result["tbl-456"]["dc_id"] == "dc2"

    def test_filters_by_component_type(self):
        """Should filter by component type when specified."""
        metadata_list = [
            {"component_type": "figure", "dc_id": "dc1"},
            {"component_type": "table", "dc_id": "dc2"},
            {"component_type": "figure", "dc_id": "dc3"},
        ]
        metadata_ids = [{"index": "fig-1"}, {"index": "tbl-1"}, {"index": "fig-2"}]

        result = build_metadata_lookup(metadata_list, metadata_ids, component_type_filter="table")

        assert "tbl-1" in result
        assert "fig-1" not in result
        assert "fig-2" not in result

    def test_handles_empty_lists(self):
        """Should return empty dict for empty inputs."""
        result = build_metadata_lookup([], [])

        assert result == {}

    def test_handles_mismatched_lengths(self):
        """Should handle when metadata_list is shorter than metadata_ids."""
        metadata_list = [{"component_type": "figure", "dc_id": "dc1"}]
        metadata_ids = [{"index": "fig-1"}, {"index": "fig-2"}]

        result = build_metadata_lookup(metadata_list, metadata_ids)

        assert "fig-1" in result
        assert "fig-2" not in result

    def test_handles_none_metadata(self):
        """Should skip None entries in metadata list."""
        metadata_list = [{"component_type": "figure"}, None, {"component_type": "table"}]
        metadata_ids = [{"index": "fig-1"}, {"index": "none-1"}, {"index": "tbl-1"}]

        result = build_metadata_lookup(metadata_list, metadata_ids)

        assert "fig-1" in result
        assert "none-1" not in result
        assert "tbl-1" in result

    def test_handles_string_ids(self):
        """Should handle string IDs (fallback to str())."""
        metadata_list = [{"component_type": "figure"}]
        metadata_ids = ["string-id"]

        result = build_metadata_lookup(metadata_list, metadata_ids)

        assert "string-id" in result


class TestHandleResetButton:
    """Tests for handle_reset_button function."""

    def test_returns_none_for_non_dict_trigger(self):
        """Should return None when triggered_id is not a dict."""
        result = handle_reset_button("string-trigger", "reset-btn", "scatter_selection", {})

        assert result is None

    def test_returns_none_for_wrong_button_type(self):
        """Should return None when button type doesn't match."""
        triggered_id = {"type": "other-button", "index": "abc"}

        result = handle_reset_button(triggered_id, "reset-btn", "scatter_selection", {})

        assert result is None

    def test_clears_matching_selection(self):
        """Should clear selection entries for matching component."""
        triggered_id = {"type": "reset-btn", "index": "comp-123"}
        current_store = {
            "interactive_components_values": [
                {"index": "comp-123", "source": "scatter_selection", "value": [1]},
                {"index": "comp-456", "source": "scatter_selection", "value": [2]},
                {"index": "comp-123", "source": "dropdown", "value": [3]},
            ]
        }

        result = handle_reset_button(triggered_id, "reset-btn", "scatter_selection", current_store)

        assert result is not None
        values = result["interactive_components_values"]
        assert len(values) == 2
        # comp-123 scatter_selection should be removed
        assert not any(
            v["index"] == "comp-123" and v["source"] == "scatter_selection" for v in values
        )
        # comp-456 scatter_selection should remain
        assert any(v["index"] == "comp-456" and v["source"] == "scatter_selection" for v in values)
        # comp-123 dropdown should remain
        assert any(v["index"] == "comp-123" and v["source"] == "dropdown" for v in values)

    def test_returns_empty_values_when_all_cleared(self):
        """Should return empty values list when all matching entries cleared."""
        triggered_id = {"type": "reset-btn", "index": "comp-123"}
        current_store = {
            "interactive_components_values": [
                {"index": "comp-123", "source": "scatter_selection", "value": [1]},
            ]
        }

        result = handle_reset_button(triggered_id, "reset-btn", "scatter_selection", current_store)

        assert result["interactive_components_values"] == []
        assert result["first_load"] is False


class TestFilterExistingValues:
    """Tests for filter_existing_values function."""

    def test_filters_out_source_type(self):
        """Should remove entries with matching source type."""
        current_store = {
            "interactive_components_values": [
                {"source": "scatter_selection", "value": [1]},
                {"source": "dropdown", "value": [2]},
                {"source": "scatter_selection", "value": [3]},
            ]
        }

        result = filter_existing_values(current_store, "scatter_selection")

        assert len(result) == 1
        assert result[0]["source"] == "dropdown"

    def test_returns_all_when_no_match(self):
        """Should return all values when no source matches."""
        current_store = {
            "interactive_components_values": [
                {"source": "dropdown", "value": [1]},
                {"source": "slider", "value": [2]},
            ]
        }

        result = filter_existing_values(current_store, "scatter_selection")

        assert len(result) == 2

    def test_returns_empty_for_empty_store(self):
        """Should return empty list for empty store."""
        current_store = {"interactive_components_values": []}

        result = filter_existing_values(current_store, "scatter_selection")

        assert result == []


class TestShouldPreventUpdate:
    """Tests for should_prevent_update function."""

    def test_returns_false_when_has_selection(self):
        """Should not prevent update when there are new selections."""
        result = should_prevent_update(
            has_any_selection=True,
            current_store={"interactive_components_values": []},
            source_type="scatter_selection",
        )

        assert result is False

    def test_returns_false_when_clearing_previous(self):
        """Should not prevent update when clearing previous selections."""
        current_store = {
            "interactive_components_values": [
                {"source": "scatter_selection", "value": [1]},
            ]
        }

        result = should_prevent_update(
            has_any_selection=False,
            current_store=current_store,
            source_type="scatter_selection",
        )

        assert result is False

    def test_returns_true_when_no_change(self):
        """Should prevent update when no selection and no previous to clear."""
        current_store = {
            "interactive_components_values": [
                {"source": "dropdown", "value": [1]},
            ]
        }

        result = should_prevent_update(
            has_any_selection=False,
            current_store=current_store,
            source_type="scatter_selection",
        )

        assert result is True

    def test_returns_true_for_empty_store(self):
        """Should prevent update for empty store with no selection."""
        result = should_prevent_update(
            has_any_selection=False,
            current_store={"interactive_components_values": []},
            source_type="scatter_selection",
        )

        assert result is True


class TestCreateSelectionEntry:
    """Tests for create_selection_entry function."""

    def test_creates_correct_structure(self):
        """Should create entry with all required fields."""
        result = create_selection_entry(
            component_index="comp-123",
            values=["a", "b", "c"],
            source_type="scatter_selection",
            column_name="sample_id",
            dc_id="dc-456",
        )

        assert result == {
            "index": "comp-123",
            "value": ["a", "b", "c"],
            "source": "scatter_selection",
            "column_name": "sample_id",
            "dc_id": "dc-456",
        }

    def test_handles_none_dc_id(self):
        """Should handle None dc_id."""
        result = create_selection_entry(
            component_index="comp-123",
            values=[1],
            source_type="table_selection",
            column_name="id",
            dc_id=None,
        )

        assert result["dc_id"] is None


class TestMergeSelectionValues:
    """Tests for merge_selection_values function."""

    def test_merges_lists(self):
        """Should merge existing and new selection values."""
        existing = [{"source": "dropdown", "value": [1]}]
        new = [{"source": "scatter_selection", "value": [2]}]

        result = merge_selection_values(existing, new)

        assert len(result["interactive_components_values"]) == 2
        assert result["first_load"] is False

    def test_handles_empty_existing(self):
        """Should handle empty existing values."""
        result = merge_selection_values([], [{"source": "scatter_selection", "value": [1]}])

        assert len(result["interactive_components_values"]) == 1

    def test_handles_empty_new(self):
        """Should handle empty new values."""
        existing = [{"source": "dropdown", "value": [1]}]

        result = merge_selection_values(existing, [])

        assert len(result["interactive_components_values"]) == 1
        assert result["interactive_components_values"][0]["source"] == "dropdown"
