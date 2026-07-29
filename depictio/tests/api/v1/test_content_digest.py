"""Content addressing, and the three things that make it an integrity claim.

A content-addressed key asserts what its bytes are. That is only useful if the
digest is the real one, if something checks it, and if a partial write can never
land under it — hence the three groups here.

The tree previously had three different functions that all read as "the file's
hash" and none of which were interchangeable:

- ``backup_endpoints._compute_file_sha256`` — full streamed sha256. Correct.
- ``cli.utils.file_utils.compute_file_hash`` — sha256 truncated to 12 hex chars.
  Fine as a cache-busting path segment, not an integrity claim.
- ``File.file_hash`` via ``generate_file_hash`` — a hash of *metadata*
  (``filename + filesize + ctime + mtime``), so a ``touch`` reads as a change
  and a rewrite with matching metadata is invisible.

Only the first is usable as an address, and a test says so rather than a comment.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from depictio.models.content_digest import (
    ContentDigestMismatch,
    atomic_write,
    compute_bytes_sha256,
    compute_file_sha256,
    content_key,
    read_sidecar,
    sidecar_path,
    verify_against_sidecar,
    write_sidecar,
)


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "tree.nwk"
    path.write_bytes(b"((A:0.1,B:0.2):0.3,C:0.4);\n")
    return str(path)


class TestTheDigest:
    def test_it_is_the_real_sha256_of_the_bytes(self, sample):
        expected = hashlib.sha256(open(sample, "rb").read()).hexdigest()

        assert compute_file_sha256(sample) == expected

    def test_it_is_not_truncated(self, sample):
        """The CLI's `compute_file_hash` truncates to 12; an address cannot."""
        assert len(compute_file_sha256(sample)) == 64

    def test_it_survives_a_file_larger_than_one_chunk(self, tmp_path):
        """Streamed in 1 MiB reads — a bug in the loop would only show above it."""
        path = tmp_path / "big.bin"
        payload = os.urandom(1024 * 1024 * 2 + 17)
        path.write_bytes(payload)

        assert compute_file_sha256(str(path)) == compute_bytes_sha256(payload)

    def test_identical_bytes_give_identical_digests(self, tmp_path):
        """Which is what makes a PUT to a content key idempotent."""
        (tmp_path / "a").write_bytes(b"same")
        (tmp_path / "b").write_bytes(b"same")

        assert compute_file_sha256(str(tmp_path / "a")) == compute_file_sha256(str(tmp_path / "b"))

    def test_it_does_not_depend_on_the_file_s_metadata(self, tmp_path):
        """The distinction from `File.file_hash`, which digests exactly that —
        so a touch reads as a change and a silent rewrite does not."""
        path = tmp_path / "x"
        path.write_bytes(b"content")
        before = compute_file_sha256(str(path))
        os.utime(path, (0, 0))

        assert compute_file_sha256(str(path)) == before


class TestTheKey:
    def test_it_puts_the_object_under_the_collection_s_prefix(self):
        """What keeps the migrate sweep and the project-delete cleanup working
        unchanged — both treat a returned path as a prefix, and the orphan GC
        is DC-granular."""
        key = content_key("dc123", "a" * 64, "map.geojson")

        assert key.startswith("dc123/")
        assert key == f"dc123/versions/{'a' * 64}/map.geojson"

    def test_a_path_in_the_filename_cannot_escape_the_prefix(self):
        key = content_key("dc123", "b" * 64, "../../etc/passwd")

        assert key == f"dc123/versions/{'b' * 64}/passwd"

    def test_an_empty_filename_still_produces_a_usable_key(self):
        assert content_key("dc", "c" * 64, "").endswith("/asset")


class TestTheSidecar:
    def test_a_written_sidecar_reads_back(self, sample):
        digest = compute_file_sha256(sample)
        write_sidecar(sample, digest)

        assert read_sidecar(sidecar_path(sample)) == digest

    def test_it_uses_the_sha256sum_convention(self, sample):
        """Two spaces, so `sha256sum -c` can check it too — an integrity claim
        nothing but us can verify is worth less."""
        digest = compute_file_sha256(sample)
        write_sidecar(sample, digest)

        line = open(sidecar_path(sample)).readline()
        assert line == f"{digest}  {os.path.basename(sample)}\n"

    def test_a_missing_sidecar_is_not_an_error(self, sample):
        assert read_sidecar(sidecar_path(sample)) is None

    def test_a_malformed_sidecar_is_treated_as_missing(self, sample):
        open(sidecar_path(sample), "w").write("not-a-digest  tree.nwk\n")

        assert read_sidecar(sidecar_path(sample)) is None

    def test_a_truncated_digest_is_rejected(self, sample):
        """A 12-char CLI-style hash must not be mistaken for a sha256."""
        open(sidecar_path(sample), "w").write("abc123def456  tree.nwk\n")

        assert read_sidecar(sidecar_path(sample)) is None


class TestVerification:
    def test_matching_bytes_verify(self, sample):
        digest = compute_file_sha256(sample)
        write_sidecar(sample, digest)

        assert verify_against_sidecar(sample) == digest

    def test_a_mismatch_always_raises(self, sample):
        """Never suppressible. A missing digest means "unknown"; a wrong one
        means the object was replaced, and serving it would make every pin that
        references it a lie."""
        write_sidecar(sample, "0" * 64)

        with pytest.raises(ContentDigestMismatch):
            verify_against_sidecar(sample)

    def test_a_mismatch_raises_even_when_unverified_is_allowed(self, sample):
        write_sidecar(sample, "0" * 64)

        with pytest.raises(ContentDigestMismatch):
            verify_against_sidecar(sample, allow_unverified=True)

    def test_a_missing_sidecar_is_tolerated_by_default(self, sample):
        assert verify_against_sidecar(sample) is None

    def test_but_can_be_made_fatal(self, sample):
        with pytest.raises(ContentDigestMismatch):
            verify_against_sidecar(sample, allow_unverified=False)


class TestAtomicWrite:
    def test_it_writes_the_payload(self, tmp_path):
        target = str(tmp_path / "out" / "file.bin")
        atomic_write(target, b"hello")

        assert open(target, "rb").read() == b"hello"

    def test_it_leaves_no_temp_file_behind(self, tmp_path):
        target = str(tmp_path / "file.bin")
        atomic_write(target, b"hello")

        assert [p.name for p in tmp_path.iterdir()] == ["file.bin"]

    def test_a_failed_write_cleans_up_and_leaves_the_original(self, tmp_path, monkeypatch):
        """A half-written object under a content key is worse than none, because
        the key asserts what the bytes are."""
        target = tmp_path / "file.bin"
        target.write_bytes(b"original")

        real_replace = os.replace

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            atomic_write(str(target), b"new")

        monkeypatch.setattr(os, "replace", real_replace)
        assert target.read_bytes() == b"original"
        assert [p.name for p in tmp_path.iterdir()] == ["file.bin"]

    def test_it_overwrites_in_one_step(self, tmp_path):
        target = str(tmp_path / "file.bin")
        atomic_write(target, b"first")
        atomic_write(target, b"second")

        assert open(target, "rb").read() == b"second"
