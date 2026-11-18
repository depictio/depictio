#!/usr/bin/env python3
"""Pack files into a reproducible .tar.gz and print the ``fixtures.lock`` entry for it.

The counterpart of ``scripts/fetch_fixtures.py``: to publish a new version of a fixture,
pack it here, upload the archive as a release asset, then paste the entry into
``fixtures.lock``. Packing the same files twice gives the same bytes (sorted members, no
timestamps or owners), so the sha256 only moves when the content does.

Usage::

    python scripts/package_fixture.py --name ampliseq-3.1.0-data \\
        --source /path/to/full/files --to depictio/projects/nf-core/ampliseq/3.1.0 \\
        --url-base https://github.com/depictio/depictio/releases/download/fixtures-v1 \\
        --out /tmp/fixtures --merge

``--source`` is a folder: its files are stored with paths relative to it. ``--glob``
(repeatable) narrows what is packed, e.g. ``--glob '*.tsv'``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tarfile
from pathlib import Path


def pack(source: Path, out_file: Path, globs: list[str] | None = None) -> tuple[str, int, int]:
    """Write ``source``'s files to ``out_file``; return ``(sha256, size, file_count)``."""
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f"--source is not a folder: {source}")
    patterns = globs or ["*"]
    files = sorted(
        {p for pattern in patterns for p in source.rglob(pattern) if p.is_file()},
        key=lambda p: p.relative_to(source).as_posix(),
    )
    if not files:
        raise ValueError(f"nothing to pack under {source} for {patterns}")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in files:
                    info = tarfile.TarInfo(path.relative_to(source).as_posix())
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with open(path, "rb") as fh:
                        tar.addfile(info, fh)
    digest = hashlib.sha256(out_file.read_bytes()).hexdigest()
    return digest, out_file.stat().st_size, len(files)


def entry(
    name: str, url: str, sha256: str, size: int, to: str, *, merge: bool = False
) -> dict[str, object]:
    """The ``fixtures.lock`` object for a packed archive."""
    result: dict[str, object] = {
        "name": name,
        "url": url,
        "sha256": sha256,
        "size": size,
        "to": to,
        "extract": True,
    }
    if merge:
        result["merge"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--name", required=True, help="fixture name (also the archive name)")
    parser.add_argument("--source", required=True, type=Path, help="folder to pack")
    parser.add_argument("--to", required=True, help="destination relative to the repo root")
    parser.add_argument("--url-base", required=True, help="where the archive will be published")
    parser.add_argument("--out", required=True, type=Path, help="folder for the archive")
    parser.add_argument("--glob", action="append", help="only pack files matching this pattern")
    parser.add_argument("--merge", action="store_true", help="unpack over the existing folder")
    args = parser.parse_args(argv)

    archive = args.out / f"{args.name}.tar.gz"
    try:
        sha256, size, count = pack(args.source, archive, args.glob)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    url = f"{args.url_base.rstrip('/')}/{archive.name}"
    print(f"packed {count} files into {archive} ({size} bytes)", file=sys.stderr)
    print(json.dumps(entry(args.name, url, sha256, size, args.to, merge=args.merge), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
