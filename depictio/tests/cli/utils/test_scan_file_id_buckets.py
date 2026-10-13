"""The run ledger must record file *identities* for departures, not just counts.

``WorkflowRunScan`` persists two parallel structures per scan: ``stats``
(counts) and ``files_id`` (ObjectId lists). Departures used to appear only in
the counts — the ids were computed to drive the delete call and then discarded,
so the ledger could say "3 files left this data collection" but not which
three. Under ``--sync-files`` the file documents are hard-deleted, so that
count was the only surviving trace and "which files backed this data collection
at time T" was unanswerable across a removal.

``unchanged_files`` is deliberately *not* an id bucket: it is the bulk of a
steady-state scan and would bloat the run document for no benefit. These tests
pin both the addition and that deliberate omission.
"""

from __future__ import annotations

from depictio.cli.cli.utils.scan import SCAN_FILE_ID_BUCKETS


def test_departure_buckets_are_recorded() -> None:
    """Both departure fates must carry identities, not just a count."""
    assert "deleted_files" in SCAN_FILE_ID_BUCKETS, (
        "files removed under --sync-files are hard-deleted; without their ids the "
        "run ledger is the only record that they ever existed"
    )
    assert "missing_files" in SCAN_FILE_ID_BUCKETS, (
        "files absent from a scan but left registered must be identifiable too"
    )


def test_the_original_buckets_are_still_there() -> None:
    """Adding buckets must not quietly drop the ones the report already reads."""
    for bucket in ("updated_files", "new_files", "skipped_files", "other_failure_files"):
        assert bucket in SCAN_FILE_ID_BUCKETS


def test_unchanged_files_stays_count_only() -> None:
    """The deliberate omission — reversing it would bloat every run document."""
    assert "unchanged_files" not in SCAN_FILE_ID_BUCKETS, (
        "unchanged files are the bulk of a steady-state scan; persisting their ids "
        "would grow the run document without making anything reconstructible"
    )


def test_buckets_are_unique() -> None:
    """Duplicate keys would silently double-count on the combine step."""
    assert len(SCAN_FILE_ID_BUCKETS) == len(set(SCAN_FILE_ID_BUCKETS))
