"""Tests for hash-based change detection and per-data-collection scan bounds.

The metadata hash was computed on every scan and then only written to a debug
log, so a file rewritten in place looked identical to one that had never
changed. These lock in the decision table that replaced it, and the bounds
filtering that lets one shared walk serve data collections with different
``max_depth``/``ignore`` settings.
"""

import os

import pytest

from depictio.cli.cli.utils.scan import (
    _dc_scan_bounds,
    _ScanBounds,
    _walk_bounds,
    scan_single_file,
)
from depictio.cli.cli.utils.scan_utils import generate_file_hash
from depictio.cli.cli.utils.scan_walk import ScannedPath, iter_run_files
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import (
    DataCollection,
    DataCollectionConfig,
    Regex,
    Scan,
    ScanRecursive,
)
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import WorkflowRun


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    monkeypatch.setattr("depictio.models.config.DEPICTIO_CONTEXT", "CLI")
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "CLI")


def make_dc(tag="dc", pattern=".*", max_depth=None, ignore=None) -> DataCollection:
    return DataCollection(
        id=PyObjectId(),
        data_collection_tag=tag,
        config=DataCollectionConfig(
            type="table",
            metatype="aggregate",
            scan=Scan(
                mode="recursive",
                scan_parameters=ScanRecursive(
                    regex_config=Regex(pattern=pattern),
                    max_depth=max_depth,
                    ignore=ignore,
                ),
            ),
            dc_specific_properties={"format": "csv", "polars_kwargs": {"separator": ","}},
        ),
    )


@pytest.fixture
def permissions() -> Permission:
    return Permission(owners=[UserBase(id=PyObjectId(), email="scan@example.com")])


@pytest.fixture
def run(tmp_path, permissions) -> WorkflowRun:
    return WorkflowRun(
        id=PyObjectId(),
        workflow_id=PyObjectId(),
        run_tag="run-1",
        files_id=[],
        workflow_config_id=PyObjectId(),
        run_location=str(tmp_path),
        creation_time="2026-01-01 00:00:00",
        last_modification_time="2026-01-01 00:00:00",
        run_hash="",
        permissions=permissions,
    )


@pytest.fixture
def sample_file(tmp_path):
    target = tmp_path / "sample.csv"
    target.write_text("a,b\n1,2\n")
    (scanned,) = list(iter_run_files(str(tmp_path)))
    return scanned


def registry_entry(scanned: ScannedPath, *, file_hash: str | None = None) -> dict:
    """A registered-file record as /files/list returns it."""
    from depictio.cli.cli.utils.common import format_timestamp

    if file_hash is None:
        file_hash = generate_file_hash(
            scanned.name,
            scanned.size,
            format_timestamp(scanned.ctime),
            format_timestamp(scanned.mtime),
        )
    return {"_id": PyObjectId(), "file_location": scanned.path, "file_hash": file_hash}


def scan(scanned, run, dc, permissions, existing, **kwargs):
    return scan_single_file(
        file_location=scanned.path,
        run=run,
        data_collection=dc,
        permissions=permissions,
        existing_files=existing,
        update_files=kwargs.pop("update_files", False),
        skip_regex=True,
        scanned=scanned,
        **kwargs,
    )


class TestDetectionDecisionTable:
    def test_unregistered_file_is_added(self, sample_file, run, permissions):
        result = scan(sample_file, run, make_dc(), permissions, {})
        assert result is not None
        assert result.scan_result == {"result": "success", "reason": "added"}

    def test_registered_and_identical_is_unchanged(self, sample_file, run, permissions):
        existing = {sample_file.path: registry_entry(sample_file)}
        result = scan(sample_file, run, make_dc(), permissions, existing)
        assert result is not None
        # Not a success: an unchanged file must not be re-uploaded.
        assert result.scan_result == {"result": "failure", "reason": "unchanged"}

    def test_registered_with_different_hash_is_changed_but_not_pushed(
        self, sample_file, run, permissions
    ):
        existing = {sample_file.path: registry_entry(sample_file, file_hash="0" * 64)}
        result = scan(sample_file, run, make_dc(), permissions, existing)
        assert result is not None
        # Detected and reported, but acting on it stays opt-in.
        assert result.scan_result == {"result": "failure", "reason": "changed"}

    def test_sync_changed_pushes_a_changed_file(self, sample_file, run, permissions):
        existing = {sample_file.path: registry_entry(sample_file, file_hash="0" * 64)}
        result = scan(sample_file, run, make_dc(), permissions, existing, sync_changed=True)
        assert result is not None
        assert result.scan_result == {"result": "success", "reason": "changed"}

    def test_sync_changed_leaves_an_unchanged_file_alone(self, sample_file, run, permissions):
        existing = {sample_file.path: registry_entry(sample_file)}
        result = scan(sample_file, run, make_dc(), permissions, existing, sync_changed=True)
        assert result is not None
        assert result.scan_result == {"result": "failure", "reason": "unchanged"}

    @pytest.mark.parametrize("stored_hash", [None, "0" * 64])
    def test_sync_files_updates_regardless_of_hash(
        self, sample_file, run, permissions, stored_hash
    ):
        existing = {sample_file.path: registry_entry(sample_file, file_hash=stored_hash)}
        result = scan(sample_file, run, make_dc(), permissions, existing, update_files=True)
        assert result is not None
        assert result.scan_result == {"result": "success", "reason": "updated"}

    def test_existing_file_id_is_reused(self, sample_file, run, permissions):
        entry = registry_entry(sample_file, file_hash="0" * 64)
        existing = {sample_file.path: entry}
        result = scan(sample_file, run, make_dc(), permissions, existing, sync_changed=True)
        assert result is not None
        # Re-uploading must target the same document, not insert a duplicate.
        assert str(result.file.id) == str(entry["_id"])

    def test_size_change_alone_flips_to_changed(self, tmp_path, run, permissions):
        target = tmp_path / "grow.csv"
        target.write_text("a,b\n")
        (before,) = list(iter_run_files(str(tmp_path)))
        existing = {before.path: registry_entry(before)}

        target.write_text("a,b\n1,2\n3,4\n")
        (after,) = list(iter_run_files(str(tmp_path)))

        result = scan(after, run, make_dc(), permissions, existing)
        assert result is not None
        assert result.scan_result["reason"] == "changed"

    def test_mtime_change_at_equal_size_flips_to_changed(self, tmp_path, run, permissions):
        # The in-place rewrite case that path-only detection could never see.
        target = tmp_path / "same-size.csv"
        target.write_text("a,b\n1,2\n")
        (before,) = list(iter_run_files(str(tmp_path)))
        existing = {before.path: registry_entry(before)}

        stat_result = target.stat()
        os.utime(target, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 5_000_000_000))
        (after,) = list(iter_run_files(str(tmp_path)))
        assert after.size == before.size

        result = scan(after, run, make_dc(), permissions, existing)
        assert result is not None
        assert result.scan_result["reason"] == "changed"


class TestScanBounds:
    def test_absent_config_is_unbounded(self):
        assert _dc_scan_bounds(make_dc()).is_unbounded

    def test_bounds_are_read_from_config(self):
        bounds = _dc_scan_bounds(make_dc(max_depth=2, ignore=["work"]))
        assert bounds.max_depth == 2
        assert bounds.ignore == ("work",)
        assert not bounds.is_unbounded

    @pytest.mark.parametrize(
        "rel_path,max_depth,expected",
        [
            ("top.csv", 0, True),
            ("a/mid.csv", 0, False),
            ("a/mid.csv", 1, True),
            ("a/b/deep.csv", 1, False),
            ("a/b/deep.csv", None, True),
        ],
    )
    def test_depth_filter(self, rel_path, max_depth, expected):
        scanned = ScannedPath(
            path=f"/root/{rel_path}",
            walk_path=f"/root/{rel_path}",
            rel_path=rel_path,
            name=os.path.basename(rel_path),
            match_name=os.path.basename(rel_path),
            size=1,
            ctime=0.0,
            mtime=0.0,
            mtime_ns=0,
        )
        assert _ScanBounds(max_depth=max_depth, ignore=()).allows(scanned) is expected


class TestWalkBounds:
    def test_no_data_collections_is_unbounded(self):
        assert _walk_bounds([]).is_unbounded

    def test_agreeing_collections_keep_their_bounds(self):
        dcs = [
            make_dc("a", max_depth=1, ignore=["work"]),
            make_dc("b", max_depth=1, ignore=["work"]),
        ]
        bounds = _walk_bounds(dcs)
        # Identical settings can still be pruned during the walk itself.
        assert bounds.max_depth == 1
        assert bounds.ignore == ("work",)

    def test_walk_takes_the_deepest_requested_depth(self):
        bounds = _walk_bounds([make_dc("a", max_depth=1), make_dc("b", max_depth=3)])
        assert bounds.max_depth == 3

    def test_one_unbounded_collection_makes_the_walk_unbounded(self):
        # Pruning is shared, so it may only drop what every collection excludes.
        bounds = _walk_bounds([make_dc("a", max_depth=1), make_dc("b")])
        assert bounds.max_depth is None

    def test_ignore_is_intersected_not_unioned(self):
        bounds = _walk_bounds(
            [make_dc("a", ignore=["work", "tmp"]), make_dc("b", ignore=["work", "logs"])]
        )
        # Only "work" is excluded by both; dropping "tmp" during the walk would
        # hide files that collection b legitimately wants.
        assert bounds.ignore == ("work",)

    def test_disjoint_ignores_leave_the_walk_unpruned(self):
        bounds = _walk_bounds([make_dc("a", ignore=["tmp"]), make_dc("b", ignore=["logs"])])
        assert bounds.ignore == ()
