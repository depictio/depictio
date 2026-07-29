"""Tests for the scan's change signal, and for what counts as a missing run.

Two things are locked in here.

The first is the signal itself: which data collections changed, which runs
changed in them, and whether the scan is in a position to answer at all. The
process step uses it to leave untouched Delta tables alone, so a wrong "nothing
changed" is a table that silently never catches up.

The second is the missing-run rule. The state cache deliberately does not
rescan a run whose tree is byte-for-byte what it was, which means "was not
scanned this cycle" and "is no longer on disk" are different questions. Treating
them as the same one deleted every unchanged run — and every one of its files —
on the second cycle of a watch, which is exactly when the cache first has an
answer to give.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli.utils.scan import (
    _change_signal,
    _resolve_pending_runs,
    _ScanBounds,
)
from depictio.cli.cli.utils.scan_walk import iter_run_files, run_signature
from depictio.cli.cli.utils.state import ProjectScanState, RunState


def make_run(tag: str, dc_stats: dict) -> SimpleNamespace:
    """A stand-in for the WorkflowRun the scan hands back."""
    return SimpleNamespace(run_tag=tag, _dc_stats_for_display=dc_stats)


def make_dc(tag: str, dc_id: str) -> SimpleNamespace:
    return SimpleNamespace(data_collection_tag=tag, id=dc_id)


NOTHING = {
    "total_files": 3,
    "new_files": 0,
    "changed_files": 0,
    "updated_files": 0,
    "deleted_files": 0,
    "unchanged_files": 3,
}


class TestChangeSignal:
    def test_a_run_with_no_movement_reports_nothing(self):
        signal = _change_signal(
            [make_run("run_A", {"dc": NOTHING})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {}
        assert signal["covered_dcs"] == ["id1"]
        assert signal["complete"] is True

    @pytest.mark.parametrize(
        "key", ["new_files", "changed_files", "updated_files", "vanished_files"]
    )
    def test_every_movement_counter_marks_the_collection(self, key):
        signal = _change_signal(
            [make_run("run_A", {"dc": {**NOTHING, key: 1}})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {"id1": ["run_A"]}

    @pytest.mark.parametrize("key", ["missing_files", "deleted_files"])
    def test_the_collection_wide_counters_are_ignored(self, key):
        # Both derive from a count that compares the whole collection's registry
        # against a single run's matches, so on a multi-run collection they are
        # large and meaningless. Acting on them would mark everything changed
        # every cycle and quietly undo the skip.
        signal = _change_signal(
            [make_run("run_A", {"dc": {**NOTHING, key: 40}})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {}

    def test_unchanged_files_alone_is_not_a_change(self):
        # The counter that dominates a steady-state scan must never trigger work.
        signal = _change_signal(
            [make_run("run_A", {"dc": {**NOTHING, "unchanged_files": 900}})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {}

    def test_runs_are_reported_per_collection(self):
        signal = _change_signal(
            [
                make_run("run_A", {"dc1": {**NOTHING, "new_files": 1}, "dc2": NOTHING}),
                make_run("run_B", {"dc1": NOTHING, "dc2": {**NOTHING, "changed_files": 2}}),
                make_run("run_C", {"dc1": {**NOTHING, "new_files": 5}, "dc2": NOTHING}),
            ],
            [make_dc("dc1", "id1"), make_dc("dc2", "id2")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {"id1": ["run_A", "run_C"], "id2": ["run_B"]}

    def test_collections_are_keyed_by_id_not_tag(self):
        # Tags are only unique within a workflow; the process step matches on id.
        signal = _change_signal(
            [make_run("run_A", {"dc": {**NOTHING, "new_files": 1}})],
            [make_dc("dc", "507f1f77bcf86cd799439011")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert "507f1f77bcf86cd799439011" in signal["changed_dcs"]

    def test_a_scan_without_rescan_cannot_vouch_for_anything(self):
        # Already-registered runs are skipped with no check at all, so "nothing
        # changed" would be a guess.
        signal = _change_signal(
            [make_run("run_A", {"dc": NOTHING})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=False,
            dry_run=False,
        )
        assert signal["complete"] is False

    def test_a_dry_run_cannot_vouch_for_anything(self):
        signal = _change_signal(
            [make_run("run_A", {"dc": NOTHING})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=True,
        )
        assert signal["complete"] is False

    def test_removed_runs_are_carried_through(self):
        signal = _change_signal(
            [make_run("run_A", {"dc": NOTHING})],
            [make_dc("dc", "id1")],
            {"run_gone", "run_also_gone"},
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["removed_runs"] == ["run_also_gone", "run_gone"]

    def test_an_unknown_tag_is_dropped_rather_than_guessed(self):
        signal = _change_signal(
            [make_run("run_A", {"mystery_dc": {**NOTHING, "new_files": 1}})],
            [make_dc("dc", "id1")],
            set(),
            rescan_folders=True,
            dry_run=False,
        )
        assert signal["changed_dcs"] == {}


def build_runs(root, tags=("run_A", "run_B")):
    for tag in tags:
        (root / tag).mkdir()
        (root / tag / "data.tsv").write_text("a\tb\n1\t2\n")
    return root


def sequencing_workflow():
    workflow = MagicMock()
    workflow.id = "wf1"
    workflow.data_location.structure = "sequencing-runs"
    workflow.data_location.runs_regex = r"run_.*"
    return workflow


def warm_state(root, tags) -> ProjectScanState:
    """State as a previous successful scan would have left it."""
    state = ProjectScanState(api_base_url="http://api", project_id="p1")
    for tag in tags:
        location = str(root / tag)
        state.record_run(
            "wf1",
            RunState(
                run_tag=tag,
                run_location=location,
                signature=run_signature(list(iter_run_files(location))),
                file_count=1,
            ),
        )
    return state


class TestPresentRuns:
    """``present_tags`` is what the missing-run cleanup must compare against."""

    def test_a_cached_run_is_skipped_but_still_present(self, tmp_path):
        root = build_runs(tmp_path)
        tags = ("run_A", "run_B")

        pending = _resolve_pending_runs(
            workflow=sequencing_workflow(),
            locations=[str(root)],
            existing_runs={tag: MagicMock() for tag in tags},
            rescan_folders=True,
            state=warm_state(root, tags),
            walk_bounds=_ScanBounds(None, ()),
        )

        scanned = {run.tag for location in pending for run in location.runs}
        present = {tag for location in pending for tag in location.present_tags}

        assert scanned == set(), "an unchanged run should not be rescanned"
        assert present == set(tags), (
            "an unchanged run is still on disk; comparing the registry against "
            "the scanned runs instead would delete it and all of its files"
        )

    def test_a_run_removed_from_disk_is_absent(self, tmp_path):
        root = build_runs(tmp_path)
        state = warm_state(root, ("run_A", "run_B"))
        (root / "run_B" / "data.tsv").unlink()
        (root / "run_B").rmdir()

        pending = _resolve_pending_runs(
            workflow=sequencing_workflow(),
            locations=[str(root)],
            existing_runs={"run_A": MagicMock(), "run_B": MagicMock()},
            rescan_folders=True,
            state=state,
            walk_bounds=_ScanBounds(None, ()),
        )

        present = {tag for location in pending for tag in location.present_tags}
        assert present == {"run_A"}
        assert {"run_A", "run_B"} - present == {"run_B"}

    def test_a_changed_run_is_both_pending_and_present(self, tmp_path):
        root = build_runs(tmp_path)
        state = warm_state(root, ("run_A", "run_B"))
        (root / "run_B" / "data.tsv").write_text("a\tb\n1\t2\n3\t4\n")

        pending = _resolve_pending_runs(
            workflow=sequencing_workflow(),
            locations=[str(root)],
            existing_runs={"run_A": MagicMock(), "run_B": MagicMock()},
            rescan_folders=True,
            state=state,
            walk_bounds=_ScanBounds(None, ()),
        )

        scanned = {run.tag for location in pending for run in location.runs}
        present = {tag for location in pending for tag in location.present_tags}
        assert scanned == {"run_B"}
        assert present == {"run_A", "run_B"}
