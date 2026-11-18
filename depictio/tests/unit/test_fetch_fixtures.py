"""scripts/fetch_fixtures.py: download pinned files and verify them before use.

The manifest (fixtures.lock) pins every external file by sha256. A download that does
not match must fail loudly and leave nothing behind, so a moved or tampered release
asset can never ship as silently empty or wrong data in an image.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fetch_fixtures.py"
_spec = importlib.util.spec_from_file_location("fetch_fixtures", SCRIPT)
ff = importlib.util.module_from_spec(_spec)
sys.modules["fetch_fixtures"] = ff  # dataclasses looks its module up here
_spec.loader.exec_module(ff)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(
    src: Path, data: bytes, to: str, *, extract: bool = False, merge: bool = False, name: str = "f"
):
    return ff.Fixture(
        name=name,
        url=src.as_uri(),
        sha256=_sha(data),
        size=len(data),
        to=to,
        extract=extract or merge,
        merge=merge,
    )


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_fetch_writes_file_and_matches_sha(tmp_path):
    data = b"a,b\n1,2\n"
    src = tmp_path / "src.csv"
    src.write_bytes(data)
    out = ff.fetch(_fixture(src, data, "out/data.csv"), tmp_path / "root", backoff=0)
    assert out == tmp_path / "root" / "out" / "data.csv"
    assert out.read_bytes() == data


def test_fetch_raises_checksum_error_and_leaves_no_file(tmp_path):
    data = b"real content"
    src = tmp_path / "src.bin"
    src.write_bytes(b"tampered content")
    fixture = _fixture(src, data, "out/data.bin")
    with pytest.raises(ff.ChecksumError):
        ff.fetch(fixture, tmp_path / "root", retries=1, backoff=0)
    root = tmp_path / "root"
    assert not (root / "out" / "data.bin").exists()
    assert not [p for p in root.rglob("*") if p.is_file()], "no partial file may stay behind"


def test_fetch_is_noop_when_file_already_matches(tmp_path):
    data = b"stable"
    src = tmp_path / "src.bin"
    src.write_bytes(data)
    fixture = _fixture(src, data, "out/data.bin")
    ff.fetch(fixture, tmp_path / "root", backoff=0)
    src.unlink()  # a second fetch would now fail if it downloaded again
    out = ff.fetch(fixture, tmp_path / "root", retries=1, backoff=0)
    assert out.read_bytes() == data


def test_fetch_redownloads_when_existing_file_is_corrupt(tmp_path):
    data = b"expected"
    src = tmp_path / "src.bin"
    src.write_bytes(data)
    root = tmp_path / "root"
    (root / "out").mkdir(parents=True)
    (root / "out" / "data.bin").write_bytes(b"corrupt")
    out = ff.fetch(_fixture(src, data, "out/data.bin"), root, backoff=0)
    assert out.read_bytes() == data


def test_fetch_extracts_archive_to_destination(tmp_path):
    archive = _tar_bytes({"proj/project.yaml": b"name: x\n", "proj/data/a.csv": b"1,2\n"})
    src = tmp_path / "pack.tar.gz"
    src.write_bytes(archive)
    out = ff.fetch(
        _fixture(src, archive, "projects/test", extract=True), tmp_path / "root", backoff=0
    )
    assert (out / "proj" / "project.yaml").read_text() == "name: x\n"
    assert (out / "proj" / "data" / "a.csv").read_text() == "1,2\n"


def test_fetch_extract_rejects_path_traversal(tmp_path):
    archive = _tar_bytes({"../escape.txt": b"nope"})
    src = tmp_path / "evil.tar.gz"
    src.write_bytes(archive)
    with pytest.raises(ff.ChecksumError):
        ff.fetch(
            _fixture(src, archive, "projects/test", extract=True),
            tmp_path / "root",
            retries=1,
            backoff=0,
        )
    assert not (tmp_path / "escape.txt").exists()


def test_fetch_rejects_destination_outside_root(tmp_path):
    data = b"x"
    src = tmp_path / "src.bin"
    src.write_bytes(data)
    for bad in ("../outside.bin", "/abs/path.bin"):
        with pytest.raises(ValueError):
            ff.fetch(_fixture(src, data, bad), tmp_path / "root", retries=1, backoff=0)


def test_load_manifest_rejects_missing_sha256(tmp_path):
    lock = tmp_path / "fixtures.lock"
    lock.write_text(json.dumps([{"name": "n", "url": "https://x", "size": 1, "to": "a"}]))
    with pytest.raises(ValueError, match="sha256"):
        ff.load_manifest(lock)


def test_load_manifest_reads_entries(tmp_path):
    lock = tmp_path / "fixtures.lock"
    lock.write_text(
        json.dumps(
            [{"name": "n", "url": "https://x/y", "sha256": "ab" * 32, "size": 3, "to": "a/b"}]
        )
    )
    (entry,) = ff.load_manifest(lock)
    assert (entry.name, entry.to, entry.size, entry.extract) == ("n", "a/b", 3, False)


def test_check_flag_exits_1_when_file_missing(tmp_path):
    data = b"x"
    lock = tmp_path / "fixtures.lock"
    lock.write_text(
        json.dumps(
            [{"name": "n", "url": "https://x/y", "sha256": _sha(data), "size": 1, "to": "a.bin"}]
        )
    )
    root = tmp_path / "root"
    root.mkdir()
    assert ff.main(["--manifest", str(lock), "--root", str(root), "--check"]) == 1
    (root / "a.bin").write_bytes(data)
    assert ff.main(["--manifest", str(lock), "--root", str(root), "--check"]) == 0


def test_only_flag_limits_to_named_fixtures(tmp_path):
    a, b = b"aa", b"bb"
    (tmp_path / "a.src").write_bytes(a)
    (tmp_path / "b.src").write_bytes(b)
    lock = tmp_path / "fixtures.lock"
    lock.write_text(
        json.dumps(
            [
                {
                    "name": "a",
                    "url": (tmp_path / "a.src").as_uri(),
                    "sha256": _sha(a),
                    "size": 2,
                    "to": "a.bin",
                },
                {
                    "name": "b",
                    "url": (tmp_path / "b.src").as_uri(),
                    "sha256": _sha(b),
                    "size": 2,
                    "to": "b.bin",
                },
            ]
        )
    )
    root = tmp_path / "root"
    assert ff.main(["--manifest", str(lock), "--root", str(root), "--only", "a"]) == 0
    assert (root / "a.bin").exists() and not (root / "b.bin").exists()
    assert ff.main(["--manifest", str(lock), "--root", str(root), "--only", "nope"]) == 2


def test_merge_unpacks_over_the_existing_folder_and_keeps_its_files(tmp_path):
    archive = _tar_bytes({"big.tsv": b"full\n", "sub/more.tsv": b"x\n"})
    src = tmp_path / "pack.tar.gz"
    src.write_bytes(archive)
    root = tmp_path / "root"
    dest = root / "tpl" / "3.1.0"
    dest.mkdir(parents=True)
    (dest / "template.yaml").write_text("id: tpl\n")  # tracked in git, not in the archive
    (dest / "big.tsv").write_text("subsample\n")  # replaced by the full file

    fixture = _fixture(src, archive, "tpl/3.1.0", merge=True)
    ff.fetch(fixture, root, backoff=0)

    assert (dest / "template.yaml").read_text() == "id: tpl\n"
    assert (dest / "big.tsv").read_text() == "full\n"
    assert (dest / "sub" / "more.tsv").read_text() == "x\n"
    assert ff.is_present(fixture, root)


def test_merge_manifest_key_implies_extract(tmp_path):
    manifest = tmp_path / "fixtures.lock"
    manifest.write_text(
        '[{"name": "a", "url": "file:///x", "sha256": "' + "0" * 64 + '", "size": 1,'
        ' "to": "p", "merge": true}]'
    )
    (fixture,) = ff.load_manifest(manifest)
    assert fixture.extract and fixture.merge
