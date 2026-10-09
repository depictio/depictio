"""Tests that the preview endpoint's task actually time-travels.

Runs against a real Delta table on a local path — the whole point is to verify
that a historical read returns the *old* rows, which a mock cannot tell you.

The safety property being pinned down here is that the row total is read at the
same version as the rows. Reading it from the current table would produce a
preview claiming "showing 2 of 5 rows" while displaying data from a version
that only ever had 2.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.celery_tasks import preview_deltatable


@pytest.fixture
def versioned_table(tmp_path, monkeypatch) -> str:
    """A table with two commits: v0 has 2 rows, v1 has 4."""
    # The task pulls credentials from the module-level config; local file://
    # paths need none, and an empty mapping keeps object_store out of the way.
    monkeypatch.setattr("depictio.api.v1.s3.polars_s3_config", {})

    destination = str(tmp_path / "table")
    pl.DataFrame({"sample": ["a", "b"], "value": [1, 2]}).write_delta(destination)
    pl.DataFrame({"sample": ["a", "b", "c", "d"], "value": [1, 2, 3, 4]}).write_delta(
        destination, mode="overwrite"
    )
    return destination


class TestPreviewTimeTravel:
    def test_current_read_returns_the_latest_commit(self, versioned_table):
        result = preview_deltatable({"delta_table_location": versioned_table, "limit": 100})

        assert result["total_rows"] == 4
        assert result["version"] is None

    def test_a_version_returns_that_commit(self, versioned_table):
        result = preview_deltatable(
            {"delta_table_location": versioned_table, "limit": 100, "version": 0}
        )

        assert result["total_rows"] == 2
        assert [row["sample"] for row in result["rows"]] == ["a", "b"]
        assert result["version"] == 0

    def test_the_row_total_matches_the_version_being_shown(self, versioned_table):
        """The bug this pins: counting the current table while showing an old one."""
        result = preview_deltatable(
            {"delta_table_location": versioned_table, "limit": 100, "version": 0}
        )

        assert result["total_rows"] == len(result["rows"])

    def test_limit_still_applies_to_a_historical_read(self, versioned_table):
        result = preview_deltatable(
            {"delta_table_location": versioned_table, "limit": 1, "version": 1}
        )

        assert len(result["rows"]) == 1
        # The total describes the version, not the page.
        assert result["total_rows"] == 4
