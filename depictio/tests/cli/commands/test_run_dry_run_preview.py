"""Tests for the `--dry-run` scan preview helpers in the run command.

The preview exists to answer "is --data-root pointing at the right level?"
before anything is written, which the dry run could not do while every step was
wrapped in `if not dry_run:`.
"""

import pytest

from depictio.cli.cli.commands.run import (
    _ingestion_data_collections,
    _shorten_scan_pattern,
)
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.projects import Project
from depictio.models.models.workflows import Workflow


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "server")
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "server")


class TestShortenScanPattern:
    """A single-file pattern is an absolute path and truncates to the shared
    data root in a terminal-width table, hiding the part that identifies it."""

    def test_renders_a_path_relative_to_its_location(self):
        assert _shorten_scan_pattern("/data/run_1/input/samplesheet.csv", ["/data/run_1"]) == (
            "input/samplesheet.csv"
        )

    def test_tries_every_configured_location(self):
        assert _shorten_scan_pattern("/data/b/x.csv", ["/data/a", "/data/b"]) == "x.csv"

    def test_a_path_outside_every_location_is_left_alone(self):
        assert _shorten_scan_pattern("/elsewhere/x.csv", ["/data/a"]) == "/elsewhere/x.csv"

    def test_no_pattern_renders_as_a_dash(self):
        assert _shorten_scan_pattern(None, ["/data/a"]) == "-"


def _project_with_run(tmp_path) -> Project:
    run = tmp_path / "run_1"
    (run / "tables").mkdir(parents=True)
    (run / "tables" / "counts.csv").write_text("a\n")
    (run / "tables" / "notes.txt").write_text("a\n")
    metadata = tmp_path / "run_1" / "metadata.csv"
    metadata.write_text("a\n")

    workflow = Workflow(
        name="wf",
        engine={"name": "python"},
        data_location={"structure": "flat", "locations": [str(run)]},
        data_collections=[
            DataCollection(
                data_collection_tag="counts",
                config={
                    "type": "table",
                    "scan": {
                        "mode": "recursive",
                        "scan_parameters": {"regex_config": {"pattern": r".*\.csv"}},
                    },
                    "dc_specific_properties": {"format": "csv"},
                },
            ),
            DataCollection(
                data_collection_tag="metadata",
                config={
                    "type": "table",
                    "scan": {"mode": "single", "scan_parameters": {"filename": str(metadata)}},
                    "dc_specific_properties": {"format": "csv"},
                },
            ),
        ],
    )
    return Project(
        name="preview_project",
        workflows=[workflow],
        data_collections=[],
        permissions={"owners": [], "editors": [], "viewers": []},
    )


class TestIngestionDataCollections:
    def test_counting_is_off_by_default(self, tmp_path):
        """The monitoring ledger is written after the scan, which already knows
        the real counts, so pre-walking for it would be slower and less accurate."""
        records = _ingestion_data_collections(_project_with_run(tmp_path))

        assert [record["file_count"] for record in records] == [None, None]

    def test_count_files_fills_real_counts(self, tmp_path):
        records = _ingestion_data_collections(_project_with_run(tmp_path), count_files=True)

        assert [(record["tag"], record["file_count"]) for record in records] == [
            ("counts", 2),
            ("metadata", 1),
        ]

    def test_records_carry_the_locations_the_preview_shortens_against(self, tmp_path):
        records = _ingestion_data_collections(_project_with_run(tmp_path), count_files=True)

        assert records[1]["locations"] == [str(tmp_path / "run_1")]
        assert _shorten_scan_pattern(records[1]["scan_pattern"], records[1]["locations"]) == (
            "metadata.csv"
        )
