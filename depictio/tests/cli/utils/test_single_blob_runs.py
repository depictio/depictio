"""A one-object collection (phylogeny, GeoJSON) keeps the first run's file (epic #1399)."""

from __future__ import annotations

from types import SimpleNamespace

from depictio.cli.cli.utils.deltatables import _project_level_file


def _dc(filename: str | None):
    params = SimpleNamespace(filename=filename) if filename else None
    scan = SimpleNamespace(scan_parameters=params) if params else None
    return SimpleNamespace(data_collection_tag="tree", config=SimpleNamespace(scan=scan))


def _files(*locations: str):
    return [SimpleNamespace(file_location=loc) for loc in locations]


def test_first_run_file_is_kept_whatever_the_listing_order():
    files = _files("/runs/b/tree.nwk", "/runs/a/tree.nwk")
    assert _project_level_file(files, _dc("/runs/a/tree.nwk")).file_location == "/runs/a/tree.nwk"


def test_unknown_filename_falls_back_to_the_first_file():
    files = _files("/runs/b/tree.nwk")
    assert _project_level_file(files, _dc("/runs/a/tree.nwk")).file_location == "/runs/b/tree.nwk"


def test_collection_without_scan_takes_the_first_file():
    files = _files("/x/tree.nwk", "/y/tree.nwk")
    assert _project_level_file(files, _dc(None)).file_location == "/x/tree.nwk"
