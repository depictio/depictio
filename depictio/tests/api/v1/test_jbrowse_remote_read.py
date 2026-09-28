"""Track proxy building blocks: Range parsing, location resolution, URL signing.

``resolve_location`` is the security boundary of the genome browser: a track
location comes from a manifest, and it must never let a user read Depictio's
bucket outside the collection's folder, nor make the API fetch an arbitrary
host. These tests pin those rules; no S3 or network is touched.
"""

from __future__ import annotations

import time

import pytest

from depictio.api.v1.configs.config import settings
from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse import signing
from depictio.api.v1.services.remote_read import (
    ByteRange,
    RemoteReadError,
    parse_range,
    resolve_location,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


@pytest.fixture
def own_bucket() -> str:
    return settings.s3.bucket


@pytest.fixture
def base_folder(own_bucket) -> str:
    return f"s3://{own_bucket}/genomic_tracks/{DC_ID}/"


@pytest.fixture
def allow_lists(monkeypatch):
    monkeypatch.setattr(settings.jbrowse, "remote_https_hosts", "tracks.example.org")
    monkeypatch.setattr(settings.jbrowse, "remote_s3_buckets", "public-genomes")


# --------------------------------------------------------------------------
# parse_range
# --------------------------------------------------------------------------


class TestParseRange:
    def test_no_header_is_whole_file(self):
        assert parse_range(None, 100) is None
        assert parse_range("", 100) is None

    def test_closed_range(self):
        assert parse_range("bytes=10-19", 100) == ByteRange(10, 19)
        assert ByteRange(10, 19).length == 10

    def test_open_ended_range(self):
        assert parse_range("bytes=90-", 100) == ByteRange(90, 99)

    def test_suffix_range(self):
        assert parse_range("bytes=-10", 100) == ByteRange(90, 99)

    def test_suffix_longer_than_file(self):
        assert parse_range("bytes=-500", 100) == ByteRange(0, 99)

    def test_end_is_clamped(self):
        """JBrowse over-reads the end of small tabix files; that must not 416."""
        assert parse_range("bytes=50-100000", 100) == ByteRange(50, 99)

    def test_unit_is_case_insensitive(self):
        assert parse_range("Bytes=0-0", 100) == ByteRange(0, 0)

    @pytest.mark.parametrize(
        "header",
        [
            "bytes=100-",  # start past the end
            "bytes=150-160",
            "bytes=0-10,20-30",  # multi-range
            "bytes=abc-def",  # malformed
            "bytes=-0",
            "bytes=10-5",  # end before start
            "items=0-10",  # wrong unit
            "bytes=",
            "bytes=--5",
        ],
    )
    def test_unsatisfiable_or_malformed_is_416(self, header):
        with pytest.raises(RemoteReadError) as exc:
            parse_range(header, 100)
        assert exc.value.status == 416


# --------------------------------------------------------------------------
# resolve_location
# --------------------------------------------------------------------------


class TestResolveLocation:
    def test_relative_path_lives_under_the_collection_folder(self, base_folder, own_bucket):
        src = resolve_location("cells/c1.bw", base_folder)
        assert src.kind == "depictio_s3"
        assert src.bucket == own_bucket
        assert src.key == f"genomic_tracks/{DC_ID}/cells/c1.bw"

    def test_relative_path_is_normalised(self, base_folder):
        src = resolve_location("./cells//c1.bw", base_folder)
        assert src.key == f"genomic_tracks/{DC_ID}/cells/c1.bw"

    def test_leading_slash_stays_inside(self, base_folder):
        src = resolve_location("/etc/passwd", base_folder)
        assert src.key == f"genomic_tracks/{DC_ID}/etc/passwd"

    @pytest.mark.parametrize("uri", ["../other/x.bw", "cells/../../x.bw", "a\\..\\..\\x.bw"])
    def test_traversal_is_refused(self, base_folder, uri):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location(uri, base_folder)
        assert exc.value.status == 400

    def test_empty_relative_path_is_refused(self, base_folder):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("./", base_folder)
        assert exc.value.status == 400

    def test_own_bucket_inside_the_folder_is_ok(self, base_folder, own_bucket):
        uri = f"s3://{own_bucket}/genomic_tracks/{DC_ID}/c1.bw"
        src = resolve_location(uri, base_folder)
        assert src.kind == "depictio_s3"
        assert src.key == f"genomic_tracks/{DC_ID}/c1.bw"

    @pytest.mark.parametrize(
        "key",
        [
            "646b0f3c1e4a2d7f8e5b8caa/part-0.parquet",  # another DC's delta table
            f"genomic_tracks/{DC_ID}x/c1.bw",  # sibling prefix sharing the id
            f"genomic_tracks/{DC_ID}/../other/c1.bw",
        ],
    )
    def test_own_bucket_outside_the_folder_is_403(self, base_folder, own_bucket, key):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location(f"s3://{own_bucket}/{key}", base_folder)
        assert exc.value.status == 403

    def test_remote_bucket_not_allow_listed_is_403(self, base_folder, allow_lists):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("s3://someone-else/x.bw", base_folder)
        assert exc.value.status == 403

    def test_remote_bucket_allow_listed(self, base_folder, allow_lists):
        src = resolve_location("s3://public-genomes/hg38/x.bw", base_folder)
        assert src.kind == "remote_s3"
        assert (src.bucket, src.key) == ("public-genomes", "hg38/x.bw")

    def test_malformed_s3_is_400(self, base_folder, allow_lists):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("s3://public-genomes", base_folder)
        assert exc.value.status == 400

    def test_https_allow_listed_host(self, base_folder, allow_lists):
        src = resolve_location("https://TRACKS.example.org/a.bw?x=1", base_folder)
        assert src.kind == "https"
        assert src.url == "https://TRACKS.example.org/a.bw?x=1"
        assert src.cache_key == src.url

    def test_https_other_host_is_403(self, base_folder, allow_lists):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("https://evil.example.com/a.bw", base_folder)
        assert exc.value.status == 403

    def test_https_lookalike_host_is_403(self, base_folder, allow_lists):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("https://tracks.example.org.evil.com/a.bw", base_folder)
        assert exc.value.status == 403

    def test_plain_http_is_refused_even_when_allow_listed(self, base_folder, allow_lists):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("http://tracks.example.org/a.bw", base_folder)
        assert exc.value.status == 403

    @pytest.mark.parametrize("uri", ["file:///etc/passwd", "ftp://host/a.bw", "gs://b/a.bw"])
    def test_other_schemes_are_400(self, base_folder, uri):
        with pytest.raises(RemoteReadError) as exc:
            resolve_location(uri, base_folder)
        assert exc.value.status == 400

    def test_base_folder_in_another_bucket_needs_the_allow_list(self, allow_lists):
        """Relative paths under a foreign base folder must not be read with
        Depictio's own credentials, nor bypass the remote bucket allow-list."""
        with pytest.raises(RemoteReadError) as exc:
            resolve_location("a.bw", "s3://other-bucket/tracks/")
        assert exc.value.status == 403

        src = resolve_location("a.bw", "s3://public-genomes/tracks/")
        assert src.kind == "remote_s3"
        assert (src.bucket, src.key) == ("public-genomes", "tracks/a.bw")


class TestCollectionBaseFolder:
    """The DC config is owner-controlled: its base folder must not widen access."""

    def _props(self, folder=None):
        from depictio.models.models.data_collections_types.genomic_tracks import (
            DCGenomicTracksConfig,
        )

        return DCGenomicTracksConfig(format="tsv", s3_base_folder=folder)

    def test_default(self, own_bucket):
        from depictio.api.v1.services.jbrowse.tracks import s3_base_folder

        assert s3_base_folder(DC_ID, self._props()) == (
            f"s3://{own_bucket}/genomic_tracks/{DC_ID}/"
        )

    def test_subfolder_of_the_default_is_ok(self, own_bucket):
        from depictio.api.v1.services.jbrowse.tracks import s3_base_folder

        folder = f"s3://{own_bucket}/genomic_tracks/{DC_ID}/run1/"
        assert s3_base_folder(DC_ID, self._props(folder)) == folder

    @pytest.mark.parametrize(
        "prefix", ["", "646b0f3c1e4a2d7f8e5b8caa/", "genomic_tracks/646b0f3c1e4a2d7f8e5b8caa/"]
    )
    def test_other_folders_of_the_own_bucket_are_refused(self, own_bucket, prefix):
        from depictio.api.v1.services.jbrowse.tracks import s3_base_folder

        with pytest.raises(RemoteReadError) as exc:
            s3_base_folder(DC_ID, self._props(f"s3://{own_bucket}/{prefix}"))
        assert exc.value.status == 403

    def test_foreign_bucket_is_passed_through(self):
        from depictio.api.v1.services.jbrowse.tracks import s3_base_folder

        assert s3_base_folder(DC_ID, self._props("s3://lab-data/t/")) == "s3://lab-data/t/"


class TestReadAll:
    def test_too_large_is_413(self, monkeypatch):
        monkeypatch.setattr(remote_read, "source_size", lambda src: 10_000)
        with pytest.raises(RemoteReadError) as exc:
            remote_read.read_all(remote_read.ByteSource("https", url="https://h/a"), 100)
        assert exc.value.status == 413

    def test_empty_file(self, monkeypatch):
        monkeypatch.setattr(remote_read, "source_size", lambda src: 0)
        assert remote_read.read_all(remote_read.ByteSource("https", url="https://h/a"), 100) == b""

    def test_joins_chunks(self, monkeypatch):
        monkeypatch.setattr(remote_read, "source_size", lambda src: 6)
        seen: list[ByteRange] = []

        def _open(src, rng):
            seen.append(rng)
            return iter([b"abc", b"def"])

        monkeypatch.setattr(remote_read, "open_range", _open)
        data = remote_read.read_all(remote_read.ByteSource("https", url="https://h/a"), 100)
        assert data == b"abcdef"
        assert seen == [ByteRange(0, 5)]


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------


class TestSigning:
    ARGS = ("track", DC_ID, "abcd1234", "data", "user-1")

    def _signed(self, exp: int | None = None) -> tuple[str, str]:
        exp = exp if exp is not None else int(time.time()) + 600
        return str(exp), signing.sign(*self.ARGS, exp)

    def test_roundtrip(self):
        exp, sig = self._signed()
        assert signing.verify(*self.ARGS, exp, sig)

    def test_signed_query_roundtrip(self):
        from urllib.parse import parse_qs

        query = parse_qs(signing.signed_query(*self.ARGS))
        assert query["uid"] == ["user-1"]
        assert signing.verify(*self.ARGS, query["exp"][0], query["sig"][0])

    def test_tampered_signature(self):
        exp, sig = self._signed()
        tampered = ("0" if sig[0] != "0" else "1") + sig[1:]
        assert not signing.verify(*self.ARGS, exp, tampered)

    def test_tampered_expiry(self):
        exp, sig = self._signed()
        assert not signing.verify(*self.ARGS, str(int(exp) + 3600), sig)

    def test_expired(self):
        exp, sig = self._signed(int(time.time()) - 1)
        assert not signing.verify(*self.ARGS, exp, sig)

    @pytest.mark.parametrize(
        "args",
        [
            ("track", DC_ID, "abcd1234", "index", "user-1"),  # other role
            ("track", DC_ID, "ffff0000", "data", "user-1"),  # other track
            ("track", "646b0f3c1e4a2d7f8e5b8caa", "abcd1234", "data", "user-1"),  # other DC
            ("track", DC_ID, "abcd1234", "data", "user-2"),  # other user
            ("assembly", DC_ID, "abcd1234", "data", "user-1"),  # other scope
        ],
    )
    def test_signature_does_not_widen(self, args):
        exp, sig = self._signed()
        assert not signing.verify(*args, exp, sig)

    @pytest.mark.parametrize(
        "uid, exp, sig",
        [(None, "1", "x"), ("u", None, "x"), ("u", "1", None), ("u", "soon", "x")],
    )
    def test_missing_or_malformed_parts(self, uid, exp, sig):
        assert not signing.verify("track", DC_ID, "k", "data", uid, exp, sig)
