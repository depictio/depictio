"""A preview of a recursive scan picks exactly the files the scan itself picks.

The Project Builder and the from_run dry run both show "these files will be
ingested" from :meth:`DataRoot.match` / :func:`scan_dc_hits`; ingestion picks
them with :func:`iter_run_files` + :func:`select_run_files`. Any rule one side
applies and the other does not (bounds, symlinked folders, the basename-then-path
regex rule) makes the preview promise files ingestion never reads, or hide files
it does. Every case below asks both sides the same question.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from depictio.cli.cli.utils.data_root import DirEntry, LocalDataRoot, data_root_for
from depictio.cli.cli.utils.scan_utils import select_run_files
from depictio.cli.cli.utils.scan_walk import ScanBounds, iter_run_files
from depictio.cli.cli.utils.template_preview import scan_dc_hits

from ..s3_stubs import install_s3_listing, s3_cli_config

TREE = [
    "samplesheet.csv",
    "star/S1/quant.tsv",
    "star/S2/quant.tsv",
    "star/S2/deep/nested/quant.tsv",
    "work/ab/cd/quant.tsv",
    "salmon/S1/quant.sf",
    "salmon/S1/quant.tsv.tmp",
    "multiqc/multiqc_data/multiqc.parquet",
    "run_1/star/S1/quant.tsv",
    "run_2/star/S9/quant.tsv",
    "logs/quant.tsv",
]


def _write(base: Path, rels: list[str]) -> Path:
    for rel in rels:
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"gene\tcount\n{rel}\t1\n")
    return base


def _scan(base: Path, regex: str, max_depth: int | None, ignore: list[str]) -> list[str]:
    """What the scan registers for one run folder, root-relative."""
    bounds = ScanBounds(max_depth=max_depth, ignore=tuple(ignore))
    walked = iter_run_files(str(base), max_depth=max_depth, ignore=ignore)
    return sorted(
        os.path.relpath(entry.walk_path, base)
        for entry in select_run_files(walked, str(base), regex, bounds)
    )


CASES = [
    # basename regex reaches every level
    (r"^quant\.tsv$", None, []),
    # path regex falls back to the run-relative path
    (r"^star/[^/]+/quant\.tsv$", None, []),
    # bounds: depth counted from the run folder
    (r"^quant\.tsv$", 2, []),
    (r"^quant\.tsv$", 0, []),
    # fnmatch ignore, by basename and by run-relative path
    (r"^quant\.tsv$", None, ["work"]),
    (r"^quant\.tsv.*$", None, ["*.tmp"]),
    (r"^quant\.tsv$", None, ["star/S2/**"]),
    (r"^multiqc\.parquet$", None, []),
]


@pytest.mark.parametrize(("regex", "max_depth", "ignore"), CASES)
def test_local_match_is_the_scan(tmp_path, regex, max_depth, ignore):
    base = _write(tmp_path / "results", TREE)
    root = LocalDataRoot(str(base))
    assert root.match(regex, max_depth=max_depth, ignore=ignore) == _scan(
        base, regex, max_depth, ignore
    )


@pytest.mark.parametrize(("regex", "max_depth", "ignore"), CASES)
def test_scan_dc_hits_is_the_scan(tmp_path, regex, max_depth, ignore):
    base = _write(tmp_path / "results", TREE)
    dc_config = {
        "scan": {
            "mode": "recursive",
            "scan_parameters": {
                "regex_config": {"pattern": regex},
                "max_depth": max_depth,
                "ignore": ignore,
            },
        }
    }
    hits = scan_dc_hits(dc_config, LocalDataRoot(str(base)), runs=[])
    assert sorted(hits or []) == _scan(base, regex, max_depth, ignore)


def test_sequencing_runs_scan_each_run_folder(tmp_path):
    base = _write(tmp_path / "results", TREE)
    dc_config = {
        "scan": {
            "mode": "recursive",
            "scan_parameters": {"regex_config": {"pattern": r"^quant\.tsv$"}, "max_depth": 2},
        }
    }
    hits = scan_dc_hits(dc_config, LocalDataRoot(str(base)), runs=["run_1", "run_2"])
    expected = sorted(
        f"{run}/{rel}"
        for run in ("run_1", "run_2")
        for rel in _scan(base / run, r"^quant\.tsv$", 2, [])
    )
    assert sorted(hits or []) == expected


def test_symlinked_folders_are_not_descended_like_the_scan(tmp_path):
    base = _write(tmp_path / "results", ["star/S1/quant.tsv"])
    outside = _write(tmp_path / "elsewhere", ["S7/quant.tsv"])
    (base / "linked").symlink_to(outside, target_is_directory=True)
    root = LocalDataRoot(str(base))
    assert root.match(r"^quant\.tsv$") == _scan(base, r"^quant\.tsv$", None, [])
    assert root.match(r"^quant\.tsv$") == ["star/S1/quant.tsv"]


def test_s3_match_ignores_bounds_like_an_s3_prefix_scan(monkeypatch):
    """Under an s3:// root a recursive scan becomes s3_prefix, which never
    applies max_depth/ignore: the preview must not either."""
    prefix = "projects/results/"
    install_s3_listing(monkeypatch, {f"{prefix}{rel}": b"x" for rel in TREE})
    root = data_root_for("s3://depictio-test/projects/results", s3_cli_config())
    unbounded = root.match(r"^quant\.tsv$")
    assert root.match(r"^quant\.tsv$", max_depth=0, ignore=["work"]) == unbounded
    assert "work/ab/cd/quant.tsv" in unbounded


@pytest.fixture
def s3_root(monkeypatch):
    prefix = "projects/results/"
    install_s3_listing(monkeypatch, {f"{prefix}{rel}": b"xy" for rel in TREE})
    return data_root_for("s3://depictio-test/projects/results", s3_cli_config())


def test_children_local_and_s3_agree(tmp_path, s3_root):
    local = LocalDataRoot(str(_write(tmp_path / "results", TREE)))
    for rel in ("", "star", "star/S2", "multiqc/multiqc_data"):
        local_view = [(e.name, e.is_dir) for e in local.children(rel)]
        s3_view = [(e.name, e.is_dir) for e in s3_root.children(rel)]
        assert local_view == s3_view, rel
    assert local.children("")[0].is_dir, "folders first"
    sheet = next(e for e in local.children("") if e.name == "samplesheet.csv")
    assert isinstance(sheet, DirEntry) and sheet.size and sheet.size > 0
    assert next(e for e in s3_root.children("") if e.name == "samplesheet.csv").size == 2


def test_children_of_a_missing_folder_is_empty(tmp_path, s3_root):
    assert LocalDataRoot(str(tmp_path)).children("nope") == []
    assert s3_root.children("nope") == []
