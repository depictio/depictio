"""The protein structure resolver behind molecule_3d's ``structure_source: resolve``.

What is pinned here is the contract the viewer codes against and the limits an
operator relies on when they turn the feature on: off means 403, so does an
anonymous visitor outside single-user mode, each identifier takes its
documented path (cache, AlphaFold DB, UniProt then AlphaFold DB, ESMFold), the
bucket cache short-circuits the upstreams, and a failing, oversized, slow or
off-allowlist upstream turns into a clear 502 rather than a hang or a 500.

No network and no bucket: upstreams answer through ``httpx.MockTransport`` and
the bucket is a dict.
"""

from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

os.environ.setdefault("DEPICTIO_MINIO_ROOT_PASSWORD", "test-secret-for-unit-tests")

from depictio.api.v1.configs.config import settings  # noqa: E402
from depictio.api.v1.configs.settings_models import StructureResolverSettings  # noqa: E402
from depictio.api.v1.endpoints.advanced_viz_endpoints import (  # noqa: E402
    structure_resolver as sr,
)
from depictio.api.v1.endpoints.advanced_viz_endpoints.structure_resolver import (  # noqa: E402
    StructureResolveRequest,
)

AFDB = "https://alphafold.ebi.ac.uk"
ACC = "P12345"
PDB_URL = f"{AFDB}/files/AF-{ACC}-F1-model_v4.pdb"

AFDB_PDB = (
    "HEADER    PREDICTED MODEL\n"
    "SEQRES   1 A    3  MET LYS TRP\n"
    "ATOM      1  N   MET A   1      11.104   6.134  -6.504  1.00 91.20           N\n"
    "ATOM      2  CA  MET A   1      11.639   6.071  -5.147  1.00 91.20           C\n"
    "ATOM      3  CA  LYS A   2      12.000   7.000  -4.000  1.00 88.10           C\n"
    "ATOM      4  CA  TRP A   3      13.000   8.000  -3.000  1.00 75.30           C\n"
    "END\n"
)
# ESMFold output carries no SEQRES: the sequence comes from the CA atoms.
ESM_PDB = (
    "ATOM      1  N   GLY A   1       1.000   1.000   1.000  1.00 50.00           N\n"
    "ATOM      2  CA  GLY A   1       1.500   1.000   1.000  1.00 50.00           C\n"
    "ATOM      3  CA  SER A   2       2.000   1.000   1.000  1.00 60.00           C\n"
    "ATOM      4  CA  CYS A   3       3.000   1.000   1.000  1.00 70.00           C\n"
    "END\n"
)


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}


class Upstreams:
    """Routes requests to per-test handlers and records what was asked."""

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, url: str, responder):
        self.routes[(method, url)] = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, str(request.url.copy_with(query=None)))
        responder = self.routes.get(key)
        if responder is None:
            return httpx.Response(404, json={"detail": "unrouted"})
        return responder(request) if callable(responder) else responder


@pytest.fixture
def cfg(monkeypatch):
    conf = StructureResolverSettings(enabled=True)
    monkeypatch.setattr(settings, "structure_resolver", conf)
    return conf


@pytest.fixture
def bucket(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(sr, "_s3_client", lambda: fake)
    monkeypatch.setattr(sr, "_presign", lambda key: f"https://s3.test/{key}?X-Amz-Signature=x")
    return fake


@pytest.fixture
def upstreams(monkeypatch):
    routes = Upstreams()
    monkeypatch.setattr(
        sr,
        "_http_client",
        lambda conf: httpx.Client(transport=httpx.MockTransport(routes), follow_redirects=False),
    )
    return routes


def _afdb_hit(routes: Upstreams, accession: str = ACC, pdb: str = AFDB_PDB):
    url = f"{AFDB}/files/AF-{accession}-F1-model_v4.pdb"
    routes.on(
        "GET",
        f"{AFDB}/api/prediction/{accession}",
        httpx.Response(200, json=[{"uniprotAccession": accession, "pdbUrl": url}]),
    )
    routes.on("GET", url, httpx.Response(200, text=pdb))


SIGNED_IN = SimpleNamespace(is_anonymous=False)
ANONYMOUS = SimpleNamespace(is_anonymous=True)


def _resolve(user=SIGNED_IN, **body):
    return sr.resolve_structure(StructureResolveRequest(**body), current_user=user)


def _status(user=SIGNED_IN, **body) -> HTTPException:
    with pytest.raises(HTTPException) as info:
        _resolve(user, **body)
    return info.value


class FakeClock:
    """``sr._clock`` stand-in: time moves only when a test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(sr, "_clock", fake)
    monkeypatch.setattr(sr, "_RETRY_DELAY_S", 0)
    return fake


class TestGate:
    def test_disabled_by_default(self):
        assert StructureResolverSettings().enabled is False

    def test_disabled_is_403(self, monkeypatch, bucket, upstreams):
        monkeypatch.setattr(settings, "structure_resolver", StructureResolverSettings())
        err = _status(uniprot=ACC)
        assert err.status_code == 403
        assert "DEPICTIO_STRUCTURE_RESOLVER_ENABLED" in err.detail
        assert upstreams.calls == []

    def test_anonymous_visitor_is_403(self, monkeypatch, cfg, bucket, upstreams):
        monkeypatch.setattr(settings.auth, "single_user_mode", False)
        err = _status(ANONYMOUS, uniprot=ACC)
        assert err.status_code == 403
        assert err.detail == sr.ANONYMOUS_REFUSAL
        assert upstreams.calls == [] and bucket.objects == {}

    def test_single_user_mode_anonymous_user_resolves(self, monkeypatch, cfg, bucket, upstreams):
        monkeypatch.setattr(settings.auth, "single_user_mode", True)
        _afdb_hit(upstreams)
        assert _resolve(ANONYMOUS, uniprot=ACC)["source"] == "afdb"

    def test_allowed_hosts_follow_the_urls(self):
        conf = StructureResolverSettings(esmfold_url="https://fold.example.org/pdb/")
        assert conf.allowed_hosts == {
            "alphafold.ebi.ac.uk",
            "rest.uniprot.org",
            "fold.example.org",
        }

    def test_route_is_on_the_advanced_viz_router(self):
        from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
            advanced_viz_endpoint_router,
        )

        assert any(
            getattr(r, "path", None) == "/structure/resolve" and "POST" in r.methods
            for r in advanced_viz_endpoint_router.routes
        )


class TestResolution:
    def test_uniprot_goes_to_alphafold(self, cfg, bucket, upstreams):
        _afdb_hit(upstreams)
        out = _resolve(uniprot=f" {ACC.lower()} ")
        assert out["source"] == "afdb"
        assert out["origin"] == "afdb"
        assert out["accession"] == ACC
        assert out["sequence"] == "MKW"
        assert out["format"] == "pdb"
        assert out["url"].startswith(f"https://s3.test/{cfg.cache_prefix}/")
        pdb_keys = [k for k in bucket.objects if k.endswith(".pdb")]
        assert len(pdb_keys) == 1 and bucket.objects[pdb_keys[0]] == AFDB_PDB.encode()
        sidecar = json.loads(bucket.objects[pdb_keys[0][: -len(".pdb")] + ".json"])
        assert sidecar["source"] == "afdb" and sidecar["accession"] == ACC

    def test_gene_searches_uniprot_then_alphafold(self, cfg, bucket, upstreams):
        upstreams.on(
            "GET",
            "https://rest.uniprot.org/uniprotkb/search",
            httpx.Response(200, json={"results": [{"primaryAccession": ACC}]}),
        )
        _afdb_hit(upstreams)
        out = _resolve(gene="abc1", taxon=10090)
        assert (out["source"], out["accession"]) == ("afdb", ACC)
        query = upstreams.calls[0].url.params["query"]
        assert query == "gene_exact:ABC1 AND organism_id:10090 AND reviewed:true"
        assert upstreams.calls[0].url.params["fields"] == "accession"

    def test_sequence_falls_back_to_esmfold(self, cfg, bucket, upstreams):
        upstreams.on("GET", f"{AFDB}/api/prediction/{ACC}", httpx.Response(404))
        upstreams.on("POST", cfg.esmfold_url, httpx.Response(200, text=ESM_PDB))
        out = _resolve(uniprot=ACC, sequence="gsc\n")
        assert out["source"] == "esmfold"
        assert out["accession"] is None
        assert out["sequence"] == "GSC"
        esm_call = upstreams.calls[-1]
        assert esm_call.content == b"GSC"
        assert esm_call.headers["content-type"] == "text/plain"

    def test_second_call_is_served_from_the_cache(self, cfg, bucket, upstreams):
        _afdb_hit(upstreams)
        first = _resolve(uniprot=ACC)
        calls = len(upstreams.calls)
        again = _resolve(uniprot=ACC.lower())
        assert len(upstreams.calls) == calls
        assert again["source"] == "cache"
        assert again["origin"] == "afdb"
        assert (again["url"], again["accession"], again["sequence"]) == (
            first["url"],
            first["accession"],
            first["sequence"],
        )

    def test_nothing_found_is_404(self, cfg, bucket, upstreams):
        upstreams.on(
            "GET",
            "https://rest.uniprot.org/uniprotkb/search",
            httpx.Response(200, json={"results": []}),
        )
        err = _status(uniprot=ACC, gene="ABC1")
        assert err.status_code == 404
        assert "AlphaFold DB has no model" in err.detail and "UniProt has no" in err.detail
        assert bucket.objects == {}


class TestUpstreamFailures:
    def test_alphafold_error_is_502_naming_it(self, monkeypatch, cfg, bucket, upstreams):
        monkeypatch.setattr(sr, "_RETRY_DELAY_S", 0)
        upstreams.on("GET", f"{AFDB}/api/prediction/{ACC}", httpx.Response(503))
        err = _status(uniprot=ACC)
        assert err.status_code == 502
        assert "AlphaFold DB" in err.detail and "503" in err.detail

    def test_gateway_error_is_retried_once(self, monkeypatch, cfg, bucket, upstreams):
        monkeypatch.setattr(sr, "_RETRY_DELAY_S", 0)
        answers = iter([httpx.Response(504), httpx.Response(200, text=ESM_PDB)])
        upstreams.on("POST", cfg.esmfold_url, lambda request: next(answers))
        out = _resolve(sequence="MKW")
        assert out["source"] == "esmfold"
        assert len(upstreams.calls) == 2

    def test_esmfold_timeout_is_502(self, cfg, bucket, upstreams):
        def timeout(request):
            raise httpx.ReadTimeout("slow", request=request)

        upstreams.on("POST", cfg.esmfold_url, timeout)
        err = _status(sequence="MKW")
        assert err.status_code == 502 and "ESMFold" in err.detail and "timed out" in err.detail

    def test_oversized_download_is_refused(self, monkeypatch, bucket, upstreams):
        monkeypatch.setattr(
            settings, "structure_resolver", StructureResolverSettings(enabled=True, max_bytes=100)
        )
        _afdb_hit(upstreams)
        err = _status(uniprot=ACC)
        assert err.status_code == 502 and "larger than 100 bytes" in err.detail
        assert bucket.objects == {}

    def test_redirect_off_the_allowlist_is_refused(self, cfg, bucket, upstreams):
        upstreams.on(
            "GET",
            f"{AFDB}/api/prediction/{ACC}",
            httpx.Response(302, headers={"location": "https://evil.example/x.pdb"}),
        )
        err = _status(uniprot=ACC)
        assert err.status_code == 502 and "evil.example" in err.detail
        assert all(c.url.host != "evil.example" for c in upstreams.calls)

    def test_redirect_inside_the_allowlist_is_followed(self, cfg, bucket, upstreams):
        _afdb_hit(upstreams)
        upstreams.on(
            "GET",
            f"{AFDB}/api/prediction/{ACC}",
            httpx.Response(301, headers={"location": f"/api/prediction/{ACC}/v2"}),
        )
        upstreams.on(
            "GET",
            f"{AFDB}/api/prediction/{ACC}/v2",
            httpx.Response(200, json=[{"uniprotAccession": ACC, "pdbUrl": PDB_URL}]),
        )
        assert _resolve(uniprot=ACC)["source"] == "afdb"

    def test_deadline_skips_the_retry(self, cfg, bucket, upstreams, clock):
        def slow_gateway_error(request):
            clock.now += cfg.total_timeout_s + 1
            return httpx.Response(504)

        upstreams.on("POST", cfg.esmfold_url, slow_gateway_error)
        err = _status(sequence="MKW")
        assert err.status_code == 502 and "504" in err.detail
        assert len(upstreams.calls) == 1

    def test_deadline_is_shared_by_every_strategy(self, cfg, bucket, upstreams, clock):
        def slow_miss(request):
            clock.now += cfg.total_timeout_s + 1
            return httpx.Response(404)

        upstreams.on("GET", f"{AFDB}/api/prediction/{ACC}", slow_miss)
        err = _status(uniprot=ACC, gene="ABC1", sequence="MKW")
        assert err.status_code == 502
        assert f"{cfg.total_timeout_s:g}s budget" in err.detail
        # AlphaFold DB used the whole budget: UniProt and ESMFold are never asked.
        assert [c.url.host for c in upstreams.calls] == ["alphafold.ebi.ac.uk"]

    def test_deadline_caps_each_request_timeout(self, monkeypatch, bucket, clock):
        timeouts: list[object] = []

        class RecordingClient(httpx.Client):
            def stream(self, *args, **kwargs):
                timeouts.append(kwargs.get("timeout"))
                return super().stream(*args, **kwargs)

        conf = StructureResolverSettings(enabled=True, timeout_s=60, total_timeout_s=5)
        monkeypatch.setattr(settings, "structure_resolver", conf)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=ESM_PDB))
        monkeypatch.setattr(sr, "_http_client", lambda c: RecordingClient(transport=transport))
        assert _resolve(sequence="MKW")["source"] == "esmfold"
        assert timeouts == [5]

    def test_body_without_atoms_is_502(self, cfg, bucket, upstreams):
        upstreams.on("POST", cfg.esmfold_url, httpx.Response(200, text="<html>busy</html>"))
        err = _status(sequence="MKW")
        assert err.status_code == 502 and "no ATOM records" in err.detail


class TestBadRequests:
    def test_non_standard_letters(self, cfg, bucket, upstreams):
        err = _status(sequence="MKWBZ1")
        assert err.status_code == 400 and "1BZ" in err.detail
        assert upstreams.calls == []

    def test_sequence_too_long_for_esmfold(self, cfg, bucket, upstreams):
        err = _status(sequence="A" * (cfg.esmfold_max_length + 1))
        assert err.status_code == 400 and str(cfg.esmfold_max_length) in err.detail

    def test_long_sequence_with_an_accession_is_a_fallback_note(self, cfg, bucket, upstreams):
        err = _status(uniprot=ACC, sequence="A" * (cfg.esmfold_max_length + 1))
        assert err.status_code == 404 and "ESMFold limit" in err.detail

    def test_malformed_accession_and_gene(self, cfg, bucket, upstreams):
        assert _status(uniprot="../../etc").status_code == 400
        assert _status(gene="TP53 OR reviewed:false").status_code == 400

    def test_empty_request(self, cfg, bucket, upstreams):
        assert _status(uniprot=" ", sequence="").status_code == 400


def test_sequence_prefers_seqres_of_the_first_chain():
    two_chains = "SEQRES   1 B    2  GLY ALA\nSEQRES   1 C    1  TRP\n" + AFDB_PDB
    assert sr._sequence_from_pdb(two_chains) == "GA"
    assert sr._sequence_from_pdb(ESM_PDB) == "GSC"
    assert sr._sequence_from_pdb("REMARK nothing\n") == ""
