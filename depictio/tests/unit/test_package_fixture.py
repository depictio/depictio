"""scripts/package_fixture.py packs fixtures the way fetch_fixtures.py unpacks them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pf = _load("package_fixture")
ff = _load("fetch_fixtures")


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    (source / "sub").mkdir(parents=True)
    (source / "b.tsv").write_text("b\n")
    (source / "a.tsv").write_text("a\n")
    (source / "sub" / "c.png").write_bytes(b"png")
    return source


def test_packing_twice_gives_the_same_bytes(tmp_path):
    source = _source(tmp_path)
    first = pf.pack(source, tmp_path / "one" / "x.tar.gz")
    (source / "a.tsv").touch()  # a new mtime must not change the archive
    second = pf.pack(source, tmp_path / "two" / "x.tar.gz")
    assert first == second


def test_packed_archive_round_trips_through_fetch_fixtures(tmp_path):
    source = _source(tmp_path)
    archive = tmp_path / "out" / "pack.tar.gz"
    sha256, size, count = pf.pack(source, archive)
    assert count == 3
    item = pf.entry("pack", archive.as_uri(), sha256, size, "dest/dir", merge=True)
    assert item["merge"] is True

    root = tmp_path / "root"
    (root / "dest" / "dir").mkdir(parents=True)
    (root / "dest" / "dir" / "kept.yaml").write_text("x\n")
    fixture = ff.Fixture(
        name="pack", url=archive.as_uri(), sha256=sha256, size=size, to="dest/dir",
        extract=True, merge=True,
    )  # fmt: skip
    ff.fetch(fixture, root, backoff=0)

    assert (root / "dest/dir/kept.yaml").read_text() == "x\n"
    assert (root / "dest/dir/a.tsv").read_text() == "a\n"
    assert (root / "dest/dir/sub/c.png").read_bytes() == b"png"


def test_glob_narrows_what_is_packed(tmp_path):
    source = _source(tmp_path)
    _, _, count = pf.pack(source, tmp_path / "o.tar.gz", ["*.tsv"])
    assert count == 2


def test_an_empty_selection_is_refused(tmp_path):
    with pytest.raises(ValueError):
        pf.pack(_source(tmp_path), tmp_path / "o.tar.gz", ["*.nope"])
