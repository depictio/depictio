"""Content digests, and the sidecar discipline that makes them worth having.

A content-addressed object is one whose key *is* a digest of its bytes, so a PUT
to that key is idempotent and a read from it either returns the bytes the key
describes or fails loudly. That is what lets a dashboard version pin an asset by
digest and still resolve it months later, without bucket versioning and without
copying anything.

Three things had to be true for this to be reusable, and only one of them was:

**The digest must be the full one.** ``backup_endpoints`` has streamed a full
sha256 since backups gained integrity checks; the CLI's ``compute_file_hash``
truncates to 12 hex characters, which is fine as a cache-busting path segment
and not fine as an integrity claim. ``File.file_hash`` is a third thing again —
a hash of *metadata* (``filename + filesize + ctime + mtime``), so a ``touch``
reads as a change and a rewrite with matching metadata is invisible. None of the
three were interchangeable and all three looked like "the file's hash".

**A digest is only an integrity claim if something checks it.** Hence the
sidecar, and ``verify_against_sidecar``: a missing sidecar is tolerable behind an
explicit flag, a *mismatch* never is.

**Writes must be atomic.** A half-written object under a content key is worse
than no object, because the key asserts what the bytes are. ``atomic_write``
does ``mkstemp`` in the target's own directory then ``os.replace``, the same
pattern ``multiqc_prerender_store`` uses — same directory so the rename is
same-filesystem and therefore atomic.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from typing import BinaryIO, Iterator

#: Read size for streamed digests. Large enough that the syscall overhead
#: disappears, small enough that a big asset never has to be resident.
_CHUNK_BYTES = 1024 * 1024

#: A full lowercase sha256, and nothing else. Used to reject a malformed sidecar
#: rather than comparing against garbage.
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def compute_file_sha256(file_path: str) -> str:
    """Full sha256 of a file's contents, streamed.

    Not truncated, and not ``File.file_hash`` — see the module docstring for why
    those are different things that all read as "the hash".
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_stream_sha256(stream: BinaryIO) -> str:
    """Full sha256 of an already-open stream, from its current position."""
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
        sha256.update(chunk)
    return sha256.hexdigest()


def compute_bytes_sha256(payload: bytes) -> str:
    """Full sha256 of an in-memory payload."""
    return hashlib.sha256(payload).hexdigest()


def content_key(dc_id: str, digest: str, filename: str) -> str:
    """The S3 key an asset version lives at.

    ``{dc_id}/versions/{sha256}/{filename}`` — deliberately under the data
    collection's own prefix, which is what keeps the existing sweeps working
    unchanged: ``_collect_s3_locations_for_project`` and the project-delete
    cleanup both treat a returned path as a prefix, and
    ``cleanup_orphaned_s3_files`` is DC-granular. An asset version is therefore
    collected and deleted with its collection and needs no separate handling.

    The ``versions/`` segment separates these from the flat, unversioned keys
    written before this existed, so the two can coexist during rollout.
    """
    safe_name = os.path.basename(filename) or "asset"
    return f"{dc_id}/versions/{digest}/{safe_name}"


def sidecar_path(path: str) -> str:
    """``<path>.sha256``."""
    return f"{path}.sha256"


def write_sidecar(path: str, digest: str, filename: str | None = None) -> str:
    """Write a ``sha256sum``-format sidecar next to ``path``. Returns its path.

    Two spaces between digest and name, matching ``sha256sum`` output, so the
    file is checkable with the standard tool and not just by this module.
    """
    target = sidecar_path(path)
    name = filename or os.path.basename(path)
    atomic_write(target, f"{digest}  {name}\n".encode())
    return target


def read_sidecar(checksum_path: str) -> str | None:
    """The digest a sidecar claims, or ``None`` if it is missing or malformed.

    ``None`` rather than an exception because "no sidecar" is a legitimate
    state — every object written before sidecars existed — and the caller
    decides whether that is acceptable.
    """
    if not os.path.exists(checksum_path):
        return None
    try:
        with open(checksum_path, "r") as handle:
            first_line = handle.readline().strip()
    except OSError:
        return None
    if not first_line:
        return None
    digest = first_line.split()[0].strip().lower()
    return digest if _SHA256_RE.fullmatch(digest) else None


class ContentDigestMismatch(Exception):
    """The bytes are not what the digest said they would be.

    Never suppressible. A missing digest means "unknown"; a wrong one means the
    object has been replaced or corrupted, and serving it anyway would make
    every pin that references it a lie.
    """

    def __init__(self, path: str, expected: str, actual: str) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Content digest mismatch for {os.path.basename(path)}: "
            f"expected {expected[:12]}…, got {actual[:12]}…"
        )


def verify_against_sidecar(path: str, *, allow_unverified: bool = True) -> str | None:
    """Check a file against its sidecar. Returns the verified digest, or ``None``.

    ``allow_unverified`` governs only the *missing* case. A present-but-wrong
    digest always raises, because that is the one outcome that means something
    went wrong rather than something was never recorded.
    """
    expected = read_sidecar(sidecar_path(path))
    if expected is None:
        if allow_unverified:
            return None
        raise ContentDigestMismatch(path, "<missing>", "<unknown>")

    actual = compute_file_sha256(path)
    if actual != expected:
        raise ContentDigestMismatch(path, expected, actual)
    return actual


def atomic_write(path: str, payload: bytes) -> None:
    """Write ``payload`` to ``path`` so a reader never sees a partial file.

    ``mkstemp`` in the target's *own* directory, so ``os.replace`` is a
    same-filesystem rename and therefore atomic. A temp file elsewhere would
    make it a copy, which is exactly the non-atomic case this avoids.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp.", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def iter_file_chunks(file_path: str) -> Iterator[bytes]:
    """Stream a file in digest-sized chunks."""
    with open(file_path, "rb") as handle:
        yield from iter(lambda: handle.read(_CHUNK_BYTES), b"")
