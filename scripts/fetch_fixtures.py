#!/usr/bin/env python3
"""Download the pinned files listed in ``fixtures.lock`` and verify them.

Large example data (the full ampliseq dataset, test projects, ...) is not committed:
the repo holds only this manifest. Each entry pins one file by sha256, so a moved or
tampered asset fails loudly instead of shipping silently wrong data.

``fixtures.lock`` is a JSON array of objects::

    {"name": "ampliseq-3.1.0",          # used by --only
     "url": "https://.../asset.tar.gz",  # https:// or file:// (tests)
     "sha256": "<64 hex chars>",         # of the downloaded file
     "size": 12345,                      # bytes, of the downloaded file
     "to": "depictio/projects/nf-core/ampliseq/3.1.0",  # relative to --root
     "extract": true}                    # optional: unpack a .tar.gz into ``to``

Usage::

    python scripts/fetch_fixtures.py                    # fetch everything missing
    python scripts/fetch_fixtures.py --only ampliseq-3.1.0
    python scripts/fetch_fixtures.py --check            # verify only, no network

Stdlib only, so it runs in the Docker fetch stage, in CI and on a bare machine.
Exit codes: 0 ok, 1 a fixture is missing or does not match, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures.lock"
STAMP_PREFIX = ".fixture-"  # written next to an extracted folder to remember its archive hash
CHUNK = 1 << 20


class ChecksumError(RuntimeError):
    """A downloaded file does not match its pinned sha256 or size, or is unsafe to unpack."""


@dataclass(frozen=True)
class Fixture:
    name: str
    url: str
    sha256: str
    size: int
    to: str
    extract: bool = False


def load_manifest(path: Path) -> list[Fixture]:
    entries = json.loads(Path(path).read_text())
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a JSON array")
    fixtures = []
    for i, raw in enumerate(entries):
        for key in ("name", "url", "sha256", "size", "to"):
            if key not in raw:
                raise ValueError(f"{path}: entry {i} has no {key!r}")
        if len(raw["sha256"]) != 64:
            raise ValueError(f"{path}: entry {raw['name']!r} sha256 must be 64 hex characters")
        fixtures.append(
            Fixture(
                name=raw["name"],
                url=raw["url"],
                sha256=raw["sha256"].lower(),
                size=int(raw["size"]),
                to=raw["to"],
                extract=bool(raw.get("extract", False)),
            )
        )
    return fixtures


def _destination(fixture: Fixture, root: Path) -> Path:
    to = Path(fixture.to)
    if to.is_absolute() or ".." in to.parts:
        raise ValueError(f"{fixture.name}: 'to' must stay inside the root, got {fixture.to!r}")
    return Path(root) / to


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp(dest: Path) -> Path:
    return dest.parent / f"{STAMP_PREFIX}{dest.name}.sha256"


def is_present(fixture: Fixture, root: Path) -> bool:
    """True when the destination exists and matches the pinned hash (no network)."""
    dest = _destination(fixture, root)
    if fixture.extract:
        stamp = _stamp(dest)
        return dest.is_dir() and stamp.is_file() and stamp.read_text().strip() == fixture.sha256
    return (
        dest.is_file() and dest.stat().st_size == fixture.size and _sha256(dest) == fixture.sha256
    )


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(target, "wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out, CHUNK)


def _safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if base != target and base not in target.parents:
                raise ChecksumError(f"archive member {member.name!r} escapes the destination")
            if member.issym() or member.islnk() or member.isdev():
                raise ChecksumError(f"archive member {member.name!r} is a link or device")
        tar.extractall(dest, filter="data")


def fetch(fixture: Fixture, root: Path, *, retries: int = 5, backoff: float = 2.0) -> Path:
    """Make ``fixture`` present under ``root`` and return its path.

    No-op when it is already there and matches. A download that fails the sha256 or size
    check raises ``ChecksumError`` and leaves nothing behind. Network errors and HTTP 5xx
    are retried with exponential backoff, anything else (404, bad hash) is not.
    """
    dest = _destination(fixture, root)
    if is_present(fixture, root):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".fetch-")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            _download(fixture.url, tmp)
            if tmp.stat().st_size != fixture.size or _sha256(tmp) != fixture.sha256:
                raise ChecksumError(
                    f"{fixture.name}: downloaded file does not match the pinned sha256/size"
                )
            if fixture.extract:
                staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".extract-"))
                try:
                    _safe_extract(tmp, staging)
                    if dest.exists():
                        shutil.rmtree(dest)
                    os.replace(staging, dest)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
                _stamp(dest).write_text(fixture.sha256 + "\n")
            else:
                os.replace(tmp, dest)
            return dest
        except ChecksumError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        finally:
            tmp.unlink(missing_ok=True)
        if attempt < retries:
            time.sleep(backoff * 2 ** (attempt - 1))
    raise RuntimeError(f"{fixture.name}: download failed after {retries} attempts: {last}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="folder 'to' is relative to")
    parser.add_argument("--only", action="append", default=[], metavar="NAME")
    parser.add_argument("--check", action="store_true", help="verify present files, no download")
    args = parser.parse_args(argv)

    fixtures = load_manifest(args.manifest)
    if args.only:
        known = {f.name for f in fixtures}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            print(f"unknown fixture(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        fixtures = [f for f in fixtures if f.name in args.only]

    status = 0
    for fixture in fixtures:
        if args.check:
            ok = is_present(fixture, args.root)
            print(f"{'ok     ' if ok else 'MISSING'} {fixture.name} -> {fixture.to}")
            status |= 0 if ok else 1
            continue
        try:
            path = fetch(fixture, args.root)
            print(f"ok      {fixture.name} -> {path}")
        except (ChecksumError, RuntimeError, ValueError) as exc:
            print(f"FAILED  {fixture.name}: {exc}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
