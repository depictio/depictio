"""Tests for the provenance a browser-triggered ingestion writes, and for the
aggregation hash and the column types carried across re-ingests.

Both are about the same thing: what the Delta commit history can be joined
against afterwards. A commit with no ingestion_run_id cannot be traced back to
the run ledger entry the task itself opened — for the one trigger that always
has one.
"""

from __future__ import annotations

import polars as pl

from depictio.api.v1.endpoints.deltatables_endpoints.utils import (
    delta_identity_hash,
    new_aggregation_hash,
    previous_column_types,
)
from depictio.api.v1.ingestion_tasks import _merge_scan_signals


class TestAggregationHash:
    def test_two_hashes_of_the_same_table_differ(self):
        # Documents what this value is: a per-aggregation identifier salted with
        # the write time, not a content digest. Consumers only test it for
        # inequality, and a redundant recompute is the safe failure.
        first = new_aggregation_hash("s3://bucket/dc1", "identity")
        second = new_aggregation_hash("s3://bucket/dc1", "identity")

        assert first != second

    def test_different_tables_hash_differently(self):
        assert new_aggregation_hash("s3://bucket/dc1") != new_aggregation_hash("s3://bucket/dc2")

    def test_the_hash_is_a_hex_digest(self):
        digest = new_aggregation_hash("s3://bucket/dc1")

        assert len(digest) == 64
        assert all(char in "0123456789abcdef" for char in digest)


class TestDeltaIdentityHash:
    def test_stable_while_the_table_is_unchanged(self, tmp_path):
        location = str(tmp_path / "dc")
        pl.DataFrame({"a": [1, 2, 3]}).write_delta(location)

        assert delta_identity_hash(location, {}) == delta_identity_hash(location, {})

    def test_changes_with_every_commit(self, tmp_path):
        # Read from the Delta log alone: a new commit is a new identity even
        # when the rows it adds are identical to ones already there.
        location = str(tmp_path / "dc")
        pl.DataFrame({"a": [1, 2, 3]}).write_delta(location)
        before = delta_identity_hash(location, {})

        pl.DataFrame({"a": [1, 2, 3]}).write_delta(location, mode="append")

        assert delta_identity_hash(location, {}) != before


def _aggregation(version: int, specs: list[dict]) -> dict:
    return {"aggregation_version": version, "aggregation_columns_specs": specs}


class TestPreviousColumnTypes:
    def test_no_document_means_no_recorded_types(self):
        assert previous_column_types(None) == {}

    def test_reads_the_latest_aggregation(self):
        doc = {
            "aggregation": [
                _aggregation(1, [{"name": "x", "type": "int64"}]),
                _aggregation(2, [{"name": "x", "type": "float64"}]),
            ]
        }

        assert previous_column_types(doc) == {"x": "float64"}

    def test_before_version_skips_the_entry_being_finalized(self):
        # The offloaded path runs after its own pending entry was appended; the
        # types it must honour are the ones recorded before that entry.
        doc = {
            "aggregation": [
                _aggregation(1, [{"name": "x", "type": "float64"}]),
                _aggregation(2, [{"name": "x", "type": "int64"}]),
                _aggregation(3, []),
            ]
        }

        assert previous_column_types(doc, before_version=3) == {"x": "int64"}
        assert previous_column_types(doc, before_version=2) == {"x": "float64"}

    def test_a_specless_entry_does_not_erase_the_recorded_types(self):
        # A row edit from the table-management endpoints, or an offload that
        # never finished, records no specs. Reading those as "no types known"
        # would let the next re-ingest silently retype every column.
        doc = {
            "aggregation": [
                _aggregation(1, [{"name": "x", "type": "float64"}]),
                _aggregation(2, []),
            ]
        }

        assert previous_column_types(doc) == {"x": "float64"}


class TestMergeScanSignals:
    def test_an_empty_start_takes_the_first_result(self):
        merged = _merge_scan_signals(
            {},
            {
                "changed_dcs": {"a": ["run_1"]},
                "covered_dcs": ["a", "b"],
                "removed_runs": [],
                "complete": True,
            },
        )

        assert merged["changed_dcs"] == {"a": ["run_1"]}
        assert merged["covered_dcs"] == ["a", "b"]
        assert merged["complete"] is True

    def test_runs_accumulate_per_collection_across_workflows(self):
        first = _merge_scan_signals(
            {}, {"changed_dcs": {"a": ["run_1"]}, "covered_dcs": ["a"], "complete": True}
        )
        merged = _merge_scan_signals(
            first,
            {
                "changed_dcs": {"a": ["run_2"], "b": ["run_3"]},
                "covered_dcs": ["b"],
                "complete": True,
            },
        )

        assert merged["changed_dcs"] == {"a": ["run_1", "run_2"], "b": ["run_3"]}
        assert merged["covered_dcs"] == ["a", "b"]

    def test_one_incomplete_workflow_makes_the_whole_signal_incomplete(self):
        # A signal that cannot speak for one workflow must not authorise
        # skipping anything anywhere in the project.
        first = _merge_scan_signals({}, {"covered_dcs": ["a"], "complete": True})
        merged = _merge_scan_signals(first, {"covered_dcs": ["b"], "complete": False})

        assert merged["complete"] is False

    def test_a_non_dict_result_makes_the_signal_incomplete(self):
        # An older scan path returning None must not read as "nothing changed".
        assert _merge_scan_signals({"complete": True}, None)["complete"] is False

    def test_removed_runs_accumulate(self):
        first = _merge_scan_signals({}, {"removed_runs": ["run_x"], "complete": True})
        merged = _merge_scan_signals(first, {"removed_runs": ["run_y"], "complete": True})

        assert merged["removed_runs"] == ["run_x", "run_y"]
