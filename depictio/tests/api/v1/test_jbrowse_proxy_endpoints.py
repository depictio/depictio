"""HTTP behaviour of the genome browser's track proxy.

The router is mounted on a bare FastAPI app; the DC lookup, the manifest, the
access check and the storage reads are faked, so this pins what the browser
sees: signed-URL checks, HEAD sizes, 206/416 Range answers and the caps.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.jbrowse_endpoints import routes
from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse import signing
from depictio.api.v1.services.jbrowse.tracks import TrackRow, TracksDC, track_key
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
UID = "646b0f3c1e4a2d7f8e5b8c10"
CONTENT = b"0123456789"

BW = TrackRow(
    key=track_key("c1.bw"), track_id="c1", name="c1", uri="c1.bw", index_uri=None, fmt="bigwig"
)
BAM = TrackRow(
    key=track_key("r.bam"),
    track_id="r",
    name="r",
    uri="r.bam",
    index_uri="r.bam.bai",
    fmt="bam",
)
FOREIGN = TrackRow(
    key=track_key("s3://not-allowed/x.bw"),
    track_id="f",
    name="f",
    uri="s3://not-allowed/x.bw",
    index_uri=None,
    fmt="bigwig",
)


class FakeStore:
    """Byte store keyed by S3 key; records the sources that were read."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.reads: list[tuple[str | None, remote_read.ByteRange]] = []

    def size(self, src: remote_read.ByteSource) -> int:
        if src.key not in self.files:
            raise remote_read.RemoteReadError(404, "Track file not found")
        return len(self.files[src.key])

    def open(self, src: remote_read.ByteSource, rng: remote_read.ByteRange):
        self.reads.append((src.key, rng))
        return iter([self.files[src.key or ""][rng.start : rng.end + 1]])


@pytest.fixture
def state(monkeypatch):
    props = {"format": "tsv"}
    access = {"allowed": True}
    store = FakeStore()
    prefix = f"genomic_tracks/{DC_ID}/"
    store.files[prefix + "c1.bw"] = CONTENT
    store.files[prefix + "r.bam"] = CONTENT * 3
    store.files[prefix + "r.bam.bai"] = b"idx"
    store.files[prefix + "ref.fa"] = b">chr1\nACGT\n"
    store.files[prefix + "ref.fa.fai"] = b"chr1\t4\t6\t4\t5\n"

    def find(dc_id: str):
        if dc_id != DC_ID:
            return None
        return TracksDC(
            dc_id=DC_ID,
            wf_id="646b0f3c1e4a2d7f8e5b8c00",
            project_id="646b0f3c1e4a2d7f8e5b8c01",
            props=DCGenomicTracksConfig.model_validate(props),
            delta_location=None,
        )

    monkeypatch.setattr(routes, "find_tracks_dc", find)
    monkeypatch.setattr(routes, "tracks_by_key", lambda tdc: {t.key: t for t in (BW, BAM, FOREIGN)})
    monkeypatch.setattr(routes, "user_can_read_project", lambda pid, uid: access["allowed"])
    monkeypatch.setattr(remote_read, "source_size", store.size)
    monkeypatch.setattr(remote_read, "open_range", store.open)
    return {"props": props, "access": access, "store": store}


@pytest.fixture
def user():
    """Bearer-token identity the proxy sees (None: anonymous)."""
    return {"value": None}


@pytest.fixture
def client(state, user):
    app = FastAPI()
    app.include_router(routes.jbrowse_endpoints_router, prefix="/jbrowse")
    app.dependency_overrides[routes._optional_user] = lambda: user["value"]
    with TestClient(app) as c:
        yield c


def _signed(scope: str, item: str, role: str, uid: str = UID) -> dict[str, str]:
    exp = int(time.time()) + 600
    return {"uid": uid, "exp": str(exp), "sig": signing.sign(scope, DC_ID, item, role, uid, exp)}


def _track_url(track: TrackRow, role: str = "data") -> str:
    return f"/jbrowse/tracks/{DC_ID}/{track.key}/{role}"


class TestTrackProxy:
    def test_head_reports_size_and_ranges(self, client):
        resp = client.head(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 200
        assert resp.headers["content-length"] == str(len(CONTENT))
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.headers["content-type"] == "application/octet-stream"

    def test_range_is_206(self, client, state):
        resp = client.get(
            _track_url(BW),
            params=_signed("track", BW.key, "data"),
            headers={"Range": "bytes=2-5"},
        )
        assert resp.status_code == 206
        assert resp.content == b"2345"
        assert resp.headers["content-range"] == f"bytes 2-5/{len(CONTENT)}"
        assert resp.headers["content-length"] == "4"
        assert state["store"].reads == [
            (f"genomic_tracks/{DC_ID}/c1.bw", remote_read.ByteRange(2, 5))
        ]

    def test_clamped_range(self, client):
        resp = client.get(
            _track_url(BW),
            params=_signed("track", BW.key, "data"),
            headers={"Range": "bytes=8-100"},
        )
        assert resp.status_code == 206
        assert resp.content == b"89"
        assert resp.headers["content-range"] == f"bytes 8-9/{len(CONTENT)}"

    def test_whole_file_without_range(self, client):
        resp = client.get(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 200
        assert resp.content == CONTENT
        assert "content-range" not in resp.headers

    def test_unsatisfiable_range_is_416(self, client):
        resp = client.get(
            _track_url(BW),
            params=_signed("track", BW.key, "data"),
            headers={"Range": "bytes=50-60"},
        )
        assert resp.status_code == 416
        assert resp.headers["content-range"] == f"bytes */{len(CONTENT)}"

    def test_index_role(self, client):
        resp = client.get(_track_url(BAM, "index"), params=_signed("track", BAM.key, "index"))
        assert resp.status_code == 200
        assert resp.content == b"idx"

    def test_track_without_index_is_404(self, client):
        resp = client.get(_track_url(BW, "index"), params=_signed("track", BW.key, "index"))
        assert resp.status_code == 404

    def test_unsigned_without_token_is_401(self, client):
        assert client.get(_track_url(BW)).status_code == 401

    def test_expired_signature_is_401(self, client):
        exp = int(time.time()) - 5
        params = {
            "uid": UID,
            "exp": str(exp),
            "sig": signing.sign("track", DC_ID, BW.key, "data", UID, exp),
        }
        assert client.get(_track_url(BW), params=params).status_code == 401

    def test_signature_for_another_role_is_401(self, client):
        resp = client.get(_track_url(BAM, "data"), params=_signed("track", BAM.key, "index"))
        assert resp.status_code == 401

    def test_signature_for_another_track_is_401(self, client):
        resp = client.get(_track_url(BAM), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 401

    def test_signed_but_access_revoked_is_404(self, client, state):
        state["access"]["allowed"] = False
        resp = client.get(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 404

    def test_bearer_user_with_access(self, client, user):
        user["value"] = type("U", (), {"id": UID})()
        assert client.get(_track_url(BW)).status_code == 200

    def test_bearer_user_without_access_is_401(self, client, user, state):
        user["value"] = type("U", (), {"id": UID})()
        state["access"]["allowed"] = False
        assert client.get(_track_url(BW)).status_code == 401

    def test_bad_role_is_404(self, client):
        resp = client.get(_track_url(BW, "bogus"), params=_signed("track", BW.key, "bogus"))
        assert resp.status_code == 404

    def test_unknown_dc_is_404(self, client):
        resp = client.get(f"/jbrowse/tracks/646b0f3c1e4a2d7f8e5b8fff/{BW.key}/data")
        assert resp.status_code == 404

    def test_unknown_track_is_404(self, client):
        resp = client.get(
            f"/jbrowse/tracks/{DC_ID}/deadbeef/data", params=_signed("track", "deadbeef", "data")
        )
        assert resp.status_code == 404

    def test_location_outside_the_allow_list_is_403(self, client):
        resp = client.get(_track_url(FOREIGN), params=_signed("track", FOREIGN.key, "data"))
        assert resp.status_code == 403

    def test_missing_file_is_404(self, client, state):
        state["store"].files.pop(f"genomic_tracks/{DC_ID}/c1.bw")
        resp = client.get(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 404

    def test_open_range_is_capped(self, client, state, monkeypatch):
        monkeypatch.setattr(settings.jbrowse, "max_range_mb", 1)
        big = b"x" * (3 * 1024 * 1024)
        state["store"].files[f"genomic_tracks/{DC_ID}/c1.bw"] = big
        resp = client.get(
            _track_url(BW),
            params=_signed("track", BW.key, "data"),
            headers={"Range": "bytes=0-"},
        )
        assert resp.status_code == 206
        assert resp.headers["content-range"] == f"bytes 0-{1024 * 1024 - 1}/{len(big)}"
        assert len(resp.content) == 1024 * 1024

    def test_whole_read_of_a_large_file_is_413(self, client, state, monkeypatch):
        monkeypatch.setattr(settings.jbrowse, "max_full_read_mb", 1)
        state["store"].files[f"genomic_tracks/{DC_ID}/c1.bw"] = b"x" * (2 * 1024 * 1024)
        resp = client.get(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 413

    def test_custom_base_folder_outside_the_dc_is_403(self, client, state):
        state["props"]["s3_base_folder"] = f"s3://{settings.s3.bucket}/"
        resp = client.get(_track_url(BW), params=_signed("track", BW.key, "data"))
        assert resp.status_code == 403


class TestAssemblyProxy:
    def _url(self, role: str) -> str:
        return f"/jbrowse/assembly/{DC_ID}/{role}"

    def test_preset_assembly_is_404(self, client):
        resp = client.get(self._url("fasta"), params=_signed("assembly", "assembly", "fasta"))
        assert resp.status_code == 404

    def test_custom_assembly_files(self, client, state):
        state["props"]["assembly"] = {"name": "v", "fasta_uri": "ref.fa"}
        resp = client.get(self._url("fasta"), params=_signed("assembly", "assembly", "fasta"))
        assert resp.status_code == 200
        assert resp.content.startswith(b">chr1")
        # the .fai defaults to <fasta>.fai
        resp = client.head(self._url("fai"), params=_signed("assembly", "assembly", "fai"))
        assert resp.status_code == 200
        assert resp.headers["content-length"] == str(len(b"chr1\t4\t6\t4\t5\n"))

    def test_unconfigured_role_is_404(self, client, state):
        state["props"]["assembly"] = {"name": "v", "fasta_uri": "ref.fa"}
        resp = client.get(self._url("twobit"), params=_signed("assembly", "assembly", "twobit"))
        assert resp.status_code == 404

    def test_unknown_role_is_404(self, client):
        assert client.get(self._url("bogus")).status_code == 404

    def test_track_signature_does_not_open_assembly(self, client, state):
        state["props"]["assembly"] = {"name": "v", "fasta_uri": "ref.fa"}
        resp = client.get(self._url("fasta"), params=_signed("track", "assembly", "fasta"))
        assert resp.status_code == 401


class TestCatalogues:
    def test_assemblies_and_presets(self, client):
        names = {a["name"] for a in client.get("/jbrowse/assemblies").json()}
        assert {"hg38", "hg19", "mm10", "wuhCor1"} <= names
        presets = {p["name"] for p in client.get("/jbrowse/presets").json()}
        assert {"signal", "sv-calls", "compact", "peaks"} <= presets
