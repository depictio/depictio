"""Tests for the provenance a browser-triggered ingestion writes, and for the
aggregation hash.

Both are about the same thing: what the Delta commit history can be joined
against afterwards. A commit with no ingestion_run_id cannot be traced back to
the run ledger entry the task itself opened — for the one trigger that always
has one.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.deltatables_endpoints.utils import build_aggregation_hash
from depictio.api.v1.ingestion_tasks import _merge_scan_signals


class TestAggregationHash:
    def test_two_hashes_of_the_same_table_differ(self):
        # Documents what this value is: a per-aggregation identifier, not a
        # content digest. It never was one — the previous implementation hashed
        # every row and then mixed datetime.now() into the digest anyway, so the
        # O(rows) pass could not have been buying content identity.
        first = build_aggregation_hash("s3://bucket/dc1")
        second = build_aggregation_hash("s3://bucket/dc1")

        assert first != second

    def test_different_tables_hash_differently(self):
        assert build_aggregation_hash("s3://bucket/dc1") != build_aggregation_hash(
            "s3://bucket/dc2"
        )

    def test_the_hash_is_a_hex_digest(self):
        digest = build_aggregation_hash("s3://bucket/dc1")

        assert len(digest) == 64
        assert all(char in "0123456789abcdef" for char in digest)


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
