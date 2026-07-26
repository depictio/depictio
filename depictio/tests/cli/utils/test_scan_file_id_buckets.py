"""The run ledger must record file *identities* for departures, not just counts.

``WorkflowRunScan`` persists two parallel structures per scan: ``stats``
(counts, keyed by ``SCAN_STAT_KEYS``) and ``files_id`` (ObjectId lists, keyed by
``SCAN_FILE_ID_BUCKETS``). Departures used to appear only in the counts — the
ids were computed to drive the delete call and then discarded — so the ledger
could say "3 files left this data collection" but not which three. Under
``--sync-files`` the file documents are hard-deleted, so that count was the only
surviving trace and "which files backed this data collection at time T" was
unanswerable across a removal.

``unchanged_files`` is deliberately *not* an id bucket: it is the bulk of a
steady-state scan and would bloat the run document for no benefit. These tests
pin both the addition and that deliberate omission, so neither is reversed by
accident.
"""

from __future__ import annotations

from depictio.cli.cli.utils.scan import SCAN_FILE_ID_BUCKETS, SCAN_STAT_KEYS


def test_departure_buckets_are_recorded() -> None:
    """Both departure fates must carry identities, not just a count."""
    assert "deleted_files" in SCAN_FILE_ID_BUCKETS, (
        "files removed under --sync-files are hard-deleted; without their ids the "
        "run ledger is the only record that they ever existed"
    )
    assert "missing_files" in SCAN_FILE_ID_BUCKETS, (
        "files absent from a scan but left registered must be identifiable too"
    )


def test_every_id_bucket_is_a_known_stat() -> None:
    """A bucket with no matching counter would be unreadable by the report UI."""
    unknown = set(SCAN_FILE_ID_BUCKETS) - set(SCAN_STAT_KEYS)
    assert not unknown, f"id buckets with no corresponding stat key: {unknown}"


def test_unchanged_files_stays_count_only() -> None:
    """The deliberate omission — reversing it would bloat every run document."""
    assert "unchanged_files" not in SCAN_FILE_ID_BUCKETS, (
        "unchanged files are the bulk of a steady-state scan; persisting their ids "
        "would grow the run document without making anything reconstructible"
    )


def test_omissions_are_exactly_the_documented_ones() -> None:
    """Guards against a new counter silently gaining or losing an id bucket."""
    omitted = set(SCAN_STAT_KEYS) - set(SCAN_FILE_ID_BUCKETS)
    assert omitted == {"total_files", "unchanged_files"}, (
        f"unexpected count-only stats {omitted}: either add an id bucket or "
        "document why the identities are not worth persisting"
    )


def test_buckets_are_unique() -> None:
    """Duplicate keys would silently double-count on the combine step."""
    assert len(SCAN_FILE_ID_BUCKETS) == len(set(SCAN_FILE_ID_BUCKETS))
