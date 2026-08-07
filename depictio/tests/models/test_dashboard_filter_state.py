"""Validation rules of the per-user filter-state payload."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboard_filter_state import (
    MAX_FILTER_ENTRIES,
    DashboardFilterStatePayload,
)


class TestDashboardFilterStatePayload:
    def test_accepts_normal_filters(self):
        payload = DashboardFilterStatePayload(
            filters=[
                {"index": "abc", "value": ["a", "b"], "column_name": "col"},
                {"index": "def", "value": [0, 10], "source": "scatter_selection"},
            ]
        )
        assert len(payload.filters) == 2
        assert payload.enabled is True

    def test_defaults_to_empty_enabled(self):
        payload = DashboardFilterStatePayload()
        assert payload.filters == []
        assert payload.enabled is True

    def test_enabled_false_roundtrips(self):
        assert DashboardFilterStatePayload(enabled=False).enabled is False

    def test_rejects_too_many_entries(self):
        entries = [{"index": str(i), "value": [i]} for i in range(MAX_FILTER_ENTRIES + 1)]
        with pytest.raises(ValidationError, match="too many filter entries"):
            DashboardFilterStatePayload(filters=entries)

    def test_rejects_entry_without_index(self):
        with pytest.raises(ValidationError, match="string 'index'"):
            DashboardFilterStatePayload(filters=[{"value": ["a"]}])

    def test_rejects_non_string_index(self):
        with pytest.raises(ValidationError, match="string 'index'"):
            DashboardFilterStatePayload(filters=[{"index": 3, "value": ["a"]}])

    def test_rejects_oversized_payload(self):
        # A single huge selection blowing past the byte cap.
        huge = [{"index": "img", "value": ["x" * 1000] * 300}]
        with pytest.raises(ValidationError, match="too large"):
            DashboardFilterStatePayload(filters=huge)
