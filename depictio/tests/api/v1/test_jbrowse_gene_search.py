"""``GET /jbrowse/preset/{name}/search``: gene search through the UCSC search API.

UCSC is never called: ``httpx.get`` is replaced by a canned response shaped like
the real one (a trimmed answer for ``BCR`` on hg38).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.jbrowse_endpoints import routes
from depictio.api.v1.services.jbrowse import assemblies

BCR: dict[str, Any] = {
    "genome": "hg38",
    "positionMatches": [
        {
            "name": "knownGene",
            "trackName": "knownGene",
            "matches": [
                {
                    "position": "chr22:23180509-23318037",
                    "posName": "BCR (ENST00000305877.13)",
                },
                {"position": "chr17:41848518-41865423", "posName": "KLHL11 (ENST00000319121.4)"},
            ],
        },
        {
            "name": "hgnc",
            "trackName": "hgnc",
            "matches": [
                {"position": "chr22:23179704-23318037", "posName": "BCR"},
                {"position": "chr22:24259929-24263764", "posName": "BCRP1"},
            ],
        },
        {
            "name": "mane",
            "trackName": "mane",
            "matches": [
                {
                    "position": "chr22:23180509-23318037",
                    "posName": "BCR (NM_004327.4 &#x2F; ENST00000305877.13)",
                }
            ],
        },
        {
            "name": "all_mrna",
            "trackName": "mrna",
            "matches": [{"position": "AB069693", "posName": "AB069693"}],
        },
    ],
}


@pytest.fixture
def upstream(monkeypatch):
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"payload": BCR, "error": None}

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def get(url, params=None, timeout=None, follow_redirects=None, **kw):
        calls.append({"url": url, "params": params, "timeout": timeout, "follow": follow_redirects})
        if state["error"]:
            raise state["error"]
        return Response(state["payload"])

    monkeypatch.setattr(assemblies.httpx, "get", get)
    assemblies.clear_search_cache()
    state["calls"] = calls
    yield state
    assemblies.clear_search_cache()


@pytest.fixture
def client(upstream) -> TestClient:
    app = FastAPI()
    app.include_router(routes.jbrowse_endpoints_router, prefix="/jbrowse")
    return TestClient(app)


def _search(client: TestClient, name: str = "hg38", q: str = "BCR", **params: Any):
    return client.get(f"/jbrowse/preset/{name}/search", params={"q": q, **params})


def test_the_mane_locus_comes_first_then_hgnc_deduplicated(client):
    resp = _search(client)
    assert resp.status_code == 200
    assert resp.json() == [
        {"label": "BCR", "locus": "chr22:23180509-23318037"},
        {"label": "BCRP1", "locus": "chr22:24259929-24263764"},
        {"label": "KLHL11", "locus": "chr17:41848518-41865423"},
    ]


def test_accessions_are_dropped_and_the_limit_applies(client):
    assert [r["label"] for r in _search(client, limit=2).json()] == ["BCR", "BCRP1"]


def test_the_query_goes_to_ucsc_for_the_assemblys_genome(client, upstream):
    _search(client, name="GRCh38")  # an alias of hg38
    (call,) = upstream["calls"]
    assert call["url"] == "https://api.genome.ucsc.edu/search"
    assert call["params"] == {"search": "BCR", "genome": "hg38"}
    assert call["timeout"] == 5.0
    assert call["follow"] is False


def test_a_repeated_search_is_served_from_the_cache(client, upstream):
    first = _search(client).json()
    assert _search(client, q="bcr").json() == first  # case-insensitive key
    assert len(upstream["calls"]) == 1
    _search(client, limit=3)  # another page size is its own entry
    assert len(upstream["calls"]) == 2


def test_the_cache_expires(client, upstream, monkeypatch):
    _search(client)
    monkeypatch.setattr(assemblies, "_SEARCH_TTL_S", 0.0)
    _search(client)
    assert len(upstream["calls"]) == 2


def test_the_cache_is_bounded(client, upstream, monkeypatch):
    monkeypatch.setattr(assemblies, "_SEARCH_CACHE_MAX", 2)
    for q in ("AA", "BB", "CC"):
        _search(client, q=q)
    assert len(assemblies._search_cache) == 2


@pytest.mark.parametrize("q", ["", "x" * 65, "BCR ABL", "BCR;rm", "a/b", "BCR%20", "é"])
def test_an_invalid_query_is_refused_before_reaching_ucsc(client, upstream, q):
    assert _search(client, q=q).status_code == 422
    assert upstream["calls"] == []


def test_a_query_with_the_allowed_punctuation_passes(client):
    assert _search(client, q="HLA-A.1_x").status_code == 200


def test_an_unknown_assembly_is_404(client, upstream):
    assert _search(client, name="notAnAssembly").status_code == 404
    assert upstream["calls"] == []


def test_an_unreachable_ucsc_is_a_502_and_is_not_cached(client, upstream):
    upstream["error"] = httpx.ConnectError("offline")
    assert _search(client).status_code == 502
    upstream["error"] = None
    assert _search(client).status_code == 200


def test_a_body_that_is_not_json_is_a_502(client, upstream, monkeypatch):
    class Bad:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(assemblies.httpx, "get", lambda *a, **k: Bad())
    assert _search(client).status_code == 502


def test_disabled_ucsc_access_finds_nothing(client, upstream, monkeypatch):
    monkeypatch.setattr(settings.jbrowse, "ucsc_tracks_enabled", False)
    assert _search(client).json() == []
    assert upstream["calls"] == []


def test_search_is_not_taken_for_a_preset_file_role(client, upstream):
    # ``/preset/{name}/{role}`` serves files; "search" must not reach it.
    assert _search(client).headers["content-type"].startswith("application/json")
