"""Resolve a protein to a 3D structure file for the molecule_3d viz kind.

``POST /advanced_viz/structure/resolve`` takes a UniProt accession, a gene name
plus taxon, or an amino-acid sequence, and returns a presigned URL of a PDB
file in the deployment's bucket. Tried in this order, first hit wins:

1. the bucket cache, keyed by the SHA-256 of the normalised request;
2. ``uniprot``: AlphaFold DB ``/api/prediction/{acc}``, then its ``pdbUrl``;
3. ``gene`` + ``taxon``: UniProt search (reviewed entries only) for the
   accession, then AlphaFold DB as above;
4. ``sequence``: ESMFold, when the sequence is short enough.

The data that leaves the server is exactly the accession, the gene name and
taxon, or the sequence. That is why ``settings.structure_resolver.enabled``
defaults to False and the route answers 403 until an operator turns it on.
Signed-in users only: the anonymous visitor of a public instance gets a 403
(single-user mode, whose one user is the anonymous account, keeps working),
so an open dashboard cannot be used to fill the bucket.

Only the upstream hosts named in the settings are ever contacted, redirects
included, and every response is capped at ``max_bytes``. One request spends at
most ``total_timeout_s`` across all its upstream calls and retries, so it
cannot hold a worker thread for minutes. Failures map to 400 (the request
cannot be served as written), 404 (every upstream answered, none had a
structure) and 502 (an upstream failed or the time ran out; the detail names
which).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import StructureResolverSettings
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

logger = logging.getLogger(__name__)

#: Redirect hops followed by hand, each one re-checked against the allowlist.
_MAX_REDIRECTS = 3
#: Gateway errors an upstream recovers from on its own (ESM Atlas answers 504
#: while a fold is still warming up): retried once after a short pause.
_RETRY_STATUSES = frozenset({502, 503, 504})
_RETRY_DELAY_S = 2.0
#: Monotonic clock of the per-request deadline (patched by the tests).
_clock = time.monotonic

# UniProtKB accession format (uniprot.org/help/accession_numbers).
_UNIPROT_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)
# Gene symbols: letters, digits and the few separators real symbols use. Keeps
# the value from reaching into the UniProt query syntax.
_GENE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
_STANDARD_AA = frozenset("ACDEFGHIKLMNPQRSTVWY")

_THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "MSE": "M",
    "SEC": "U",
    "PYL": "O",
}


#: Detail of the 403 an anonymous visitor gets; the viewer matches on it.
ANONYMOUS_REFUSAL = "Sign in to look up protein structures on this server."


class StructureResolveRequest(BaseModel):
    """Body of ``POST /advanced_viz/structure/resolve`` (at least one identifier)."""

    uniprot: str | None = None
    gene: str | None = None
    taxon: int = 9606
    sequence: str | None = None


@dataclass(frozen=True)
class _Query:
    uniprot: str | None
    gene: str | None
    taxon: int
    sequence: str | None

    def cache_key(self) -> str:
        """SHA-256 of the fields that change the answer (taxon only matters for gene)."""
        canonical = {
            "uniprot": self.uniprot,
            "gene": self.gene,
            "taxon": self.taxon if self.gene else None,
            "sequence": self.sequence,
        }
        return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class _Resolved:
    pdb: bytes
    source: str  # "afdb" | "esmfold"
    accession: str | None
    sequence: str


class _UpstreamError(Exception):
    """An upstream failed (network, status, size, shape): the route answers 502."""

    def __init__(self, upstream: str, reason: str):
        super().__init__(f"{upstream}: {reason}")


class _NotFound(Exception):
    """An upstream answered, and it has nothing for this query."""


# ---------------------------------------------------------------------------
# Request normalisation
# ---------------------------------------------------------------------------


def _normalise(payload: StructureResolveRequest, cfg: StructureResolverSettings) -> _Query:
    uniprot = (payload.uniprot or "").strip().upper() or None
    gene = (payload.gene or "").strip().upper() or None
    sequence = re.sub(r"\s+", "", payload.sequence or "").upper().rstrip("*") or None

    if not (uniprot or gene or sequence):
        raise HTTPException(
            status_code=400, detail="Give at least one of uniprot, gene or sequence."
        )
    if uniprot and not _UNIPROT_RE.match(uniprot):
        raise HTTPException(status_code=400, detail=f"'{uniprot}' is not a UniProtKB accession.")
    if gene and not _GENE_RE.match(gene):
        raise HTTPException(status_code=400, detail=f"'{payload.gene}' is not a gene symbol.")
    if payload.taxon <= 0:
        raise HTTPException(status_code=400, detail="taxon must be a positive NCBI taxon id.")
    if sequence:
        bad = sorted(set(sequence) - _STANDARD_AA)
        if bad:
            raise HTTPException(
                status_code=400,
                detail=(
                    "sequence may only hold the 20 standard amino-acid letters; "
                    f"found {''.join(bad)}."
                ),
            )
        if len(sequence) > cfg.esmfold_max_length and not (uniprot or gene):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"sequence has {len(sequence)} residues; ESMFold is limited to "
                    f"{cfg.esmfold_max_length} on this server. Give a uniprot accession or gene."
                ),
            )
    return _Query(uniprot=uniprot, gene=gene, taxon=payload.taxon, sequence=sequence)


# ---------------------------------------------------------------------------
# Upstream HTTP
# ---------------------------------------------------------------------------


def _http_client(cfg: StructureResolverSettings) -> httpx.Client:
    """Client for the upstreams. Redirects are followed by hand, see ``_fetch``."""
    return httpx.Client(
        timeout=cfg.timeout_s,
        follow_redirects=False,
        headers={"User-Agent": "depictio-structure-resolver"},
    )


def _check_host(url: str, upstream: str, cfg: StructureResolverSettings) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname not in cfg.allowed_hosts:
        raise _UpstreamError(upstream, f"refused to contact {parts.hostname or url!r}")


def _remaining(deadline: float, upstream: str, cfg: StructureResolverSettings) -> float:
    """Seconds left before ``deadline``; past it, the request gives up with a 502."""
    left = deadline - _clock()
    if left <= 0:
        raise _UpstreamError(
            upstream, f"gave up: the lookup exceeded its {cfg.total_timeout_s:g}s budget"
        )
    return left


def _fetch(
    client: httpx.Client, method: str, url: str, *, deadline: float, **request: Any
) -> tuple[int, bytes]:
    """``_fetch_once``, retried once when the upstream answers a gateway error
    and the deadline leaves room for the pause and another try."""
    status, body = _fetch_once(client, method, url, deadline=deadline, **request)
    if status in _RETRY_STATUSES and deadline - _clock() > _RETRY_DELAY_S:
        time.sleep(_RETRY_DELAY_S)
        status, body = _fetch_once(client, method, url, deadline=deadline, **request)
    return status, body


def _fetch_once(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    upstream: str,
    cfg: StructureResolverSettings,
    deadline: float,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    """One request with allowlisted redirects, a streamed size cap and the
    request's deadline (httpx times each operation, not the whole exchange,
    so the deadline is also checked between chunks)."""
    for _ in range(_MAX_REDIRECTS + 1):
        _check_host(url, upstream, cfg)
        timeout = min(cfg.timeout_s, _remaining(deadline, upstream, cfg))
        try:
            with client.stream(
                method, url, params=params, content=content, headers=headers, timeout=timeout
            ) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise _UpstreamError(upstream, "redirect without a Location header")
                    url = urljoin(str(resp.url), location)
                    params = None  # carried by the Location URL
                    if resp.status_code in (301, 302, 303):
                        method, content = "GET", None
                    continue
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > cfg.max_bytes:
                    raise _UpstreamError(upstream, f"response larger than {cfg.max_bytes} bytes")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > cfg.max_bytes:
                        raise _UpstreamError(
                            upstream, f"response larger than {cfg.max_bytes} bytes"
                        )
                    _remaining(deadline, upstream, cfg)
                return resp.status_code, bytes(body)
        except httpx.TimeoutException as exc:
            raise _UpstreamError(upstream, f"timed out after {timeout:g}s") from exc
        except httpx.HTTPError as exc:
            raise _UpstreamError(upstream, f"request failed ({type(exc).__name__})") from exc
    raise _UpstreamError(upstream, f"more than {_MAX_REDIRECTS} redirects")


def _json(body: bytes, upstream: str):
    try:
        return json.loads(body)
    except ValueError as exc:
        raise _UpstreamError(upstream, "returned a body that is not JSON") from exc


def _pdb_text(body: bytes, upstream: str) -> str:
    """``body`` decoded, once it is known to be a PDB file with ATOM records."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _UpstreamError(upstream, "returned a body that is not text") from exc
    if not any(line.startswith("ATOM") for line in text.splitlines()):
        raise _UpstreamError(upstream, "returned no ATOM records")
    return text


def _from_afdb(
    client: httpx.Client, cfg: StructureResolverSettings, accession: str, deadline: float
) -> _Resolved:
    base = cfg.afdb_base_url.rstrip("/")
    status, body = _fetch(
        client,
        "GET",
        f"{base}/api/prediction/{quote(accession)}",
        upstream="AlphaFold DB",
        cfg=cfg,
        deadline=deadline,
    )
    if status in (400, 404, 422):
        raise _NotFound(f"AlphaFold DB has no model for {accession}")
    if status != 200:
        raise _UpstreamError("AlphaFold DB", f"prediction API answered HTTP {status}")
    entries = _json(body, "AlphaFold DB")
    if not isinstance(entries, list) or not entries:
        raise _NotFound(f"AlphaFold DB has no model for {accession}")
    entry = next(
        (e for e in entries if isinstance(e, dict) and e.get("uniprotAccession") == accession),
        entries[0],
    )
    pdb_url = entry.get("pdbUrl") if isinstance(entry, dict) else None
    if not isinstance(pdb_url, str) or not pdb_url:
        raise _UpstreamError("AlphaFold DB", f"entry for {accession} has no pdbUrl")
    status, pdb = _fetch(
        client, "GET", pdb_url, upstream="AlphaFold DB", cfg=cfg, deadline=deadline
    )
    if status != 200:
        raise _UpstreamError("AlphaFold DB", f"PDB download answered HTTP {status}")
    text = _pdb_text(pdb, "AlphaFold DB")
    return _Resolved(pdb, "afdb", accession, _sequence_from_pdb(text))


def _uniprot_accession(
    client: httpx.Client, cfg: StructureResolverSettings, gene: str, taxon: int, deadline: float
) -> str:
    status, body = _fetch(
        client,
        "GET",
        f"{cfg.uniprot_base_url.rstrip('/')}/uniprotkb/search",
        upstream="UniProt",
        cfg=cfg,
        deadline=deadline,
        params={
            "query": f"gene_exact:{gene} AND organism_id:{taxon} AND reviewed:true",
            "fields": "accession",
            "format": "json",
            "size": "1",
        },
    )
    if status != 200:
        raise _UpstreamError("UniProt", f"search answered HTTP {status}")
    data = _json(body, "UniProt")
    results = (data.get("results") if isinstance(data, dict) else None) or []
    first = results[0] if results and isinstance(results[0], dict) else {}
    accession = first.get("primaryAccession")
    if not accession:
        raise _NotFound(f"UniProt has no reviewed entry for gene {gene} in taxon {taxon}")
    return str(accession)


def _from_esmfold(
    client: httpx.Client, cfg: StructureResolverSettings, sequence: str, deadline: float
) -> _Resolved:
    status, body = _fetch(
        client,
        "POST",
        cfg.esmfold_url,
        upstream="ESMFold",
        cfg=cfg,
        deadline=deadline,
        content=sequence.encode(),
        headers={"Content-Type": "text/plain"},
    )
    if status != 200:
        raise _UpstreamError("ESMFold", f"answered HTTP {status}")
    text = _pdb_text(body, "ESMFold")
    return _Resolved(body, "esmfold", None, _sequence_from_pdb(text) or sequence)


def _resolve(query: _Query, cfg: StructureResolverSettings) -> _Resolved:
    """Try each strategy the query allows; 404 when all miss, 502 when one failed.

    The strategies share one deadline: once it has passed, the ones left fail
    fast (``_remaining``) instead of each spending their own timeout.
    """
    misses: list[str] = []
    failures: list[str] = []
    deadline = _clock() + cfg.total_timeout_s
    with _http_client(cfg) as client:
        if query.uniprot:
            try:
                return _from_afdb(client, cfg, query.uniprot, deadline)
            except _NotFound as exc:
                misses.append(str(exc))
            except _UpstreamError as exc:
                failures.append(str(exc))
        if query.gene:
            try:
                accession = _uniprot_accession(client, cfg, query.gene, query.taxon, deadline)
                return _from_afdb(client, cfg, accession, deadline)
            except _NotFound as exc:
                misses.append(str(exc))
            except _UpstreamError as exc:
                failures.append(str(exc))
        if query.sequence:
            if len(query.sequence) > cfg.esmfold_max_length:
                misses.append(
                    f"sequence has {len(query.sequence)} residues, above the ESMFold limit "
                    f"of {cfg.esmfold_max_length}"
                )
            else:
                try:
                    return _from_esmfold(client, cfg, query.sequence, deadline)
                except _UpstreamError as exc:
                    failures.append(str(exc))
    if failures:
        raise HTTPException(
            status_code=502, detail="Structure upstream failed: " + "; ".join(failures)
        )
    raise HTTPException(status_code=404, detail="No structure found: " + "; ".join(misses))


# ---------------------------------------------------------------------------
# PDB sequence
# ---------------------------------------------------------------------------


def _sequence_from_pdb(text: str) -> str:
    """One-letter sequence of the first chain: SEQRES when present, else CA atoms."""
    seqres: dict[str, list[str]] = {}
    ca: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        record = line[:6].strip()
        if record == "SEQRES" and len(line) > 19:
            seqres.setdefault(line[11], []).extend(line[19:].split())
        elif record == "ATOM" and line[12:16].strip() == "CA" and len(line) >= 27:
            chain, residue_id = line[21], line[22:27]
            if (chain, residue_id) not in seen:
                seen.add((chain, residue_id))
                ca.setdefault(chain, []).append(line[17:20].strip())
        elif record == "ENDMDL":
            break
    chains = seqres or ca
    if not chains:
        return ""
    first = next(iter(chains.values()))
    return "".join(_THREE_TO_ONE.get(name.upper(), "X") for name in first)


# ---------------------------------------------------------------------------
# Bucket cache
# ---------------------------------------------------------------------------


@cache
def _s3_client():
    """boto3 client on the backend's own endpoint (reads and writes)."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.aws_access_key_id,
        aws_secret_access_key=settings.s3.aws_secret_access_key,
        verify=settings.s3.verify_tls,
        config=Config(connect_timeout=3, retries={"total_max_attempts": 2}),
    )


def _presign(key: str) -> str:
    """Browser-reachable presigned GET, shared with the indexed_file routes."""
    from depictio.api.v1.endpoints.files_endpoints.routes import presign_indexed_file

    return presign_indexed_file(key)


def _keys(cfg: StructureResolverSettings, digest: str) -> tuple[str, str]:
    prefix = cfg.cache_prefix.strip("/")
    return f"{prefix}/{digest}.pdb", f"{prefix}/{digest}.json"


def _cache_lookup(cfg: StructureResolverSettings, digest: str) -> dict | None:
    """Sidecar of a cached structure, or None on any miss (the sidecar is written last)."""
    _, sidecar_key = _keys(cfg, digest)
    try:
        obj = _s3_client().get_object(Bucket=settings.s3.bucket, Key=sidecar_key)
        sidecar = json.loads(obj["Body"].read())
    except Exception as exc:
        response = getattr(exc, "response", None)
        code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        if code not in ("NoSuchKey", "404"):
            logger.warning("structure cache lookup failed for %s: %s", sidecar_key, exc)
        return None
    return sidecar if isinstance(sidecar, dict) else None


def _cache_store(
    cfg: StructureResolverSettings, digest: str, query: _Query, resolved: _Resolved
) -> dict:
    pdb_key, sidecar_key = _keys(cfg, digest)
    sidecar = {
        "source": resolved.source,
        "accession": resolved.accession,
        "sequence": resolved.sequence,
        "request": {
            "uniprot": query.uniprot,
            "gene": query.gene,
            "taxon": query.taxon,
            "sequence": query.sequence,
        },
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        s3 = _s3_client()
        s3.put_object(
            Bucket=settings.s3.bucket,
            Key=pdb_key,
            Body=resolved.pdb,
            ContentType="text/plain; charset=utf-8",
        )
        s3.put_object(
            Bucket=settings.s3.bucket,
            Key=sidecar_key,
            Body=json.dumps(sidecar).encode(),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.error("structure cache write failed for %s: %s", pdb_key, exc)
        raise HTTPException(
            status_code=500, detail="The resolved structure could not be stored in the bucket."
        ) from exc
    return sidecar


# ---------------------------------------------------------------------------
# In-flight dedupe: identical concurrent requests wait for the first one and
# then read its cache entry, instead of each calling the upstream.
# ---------------------------------------------------------------------------

_inflight: dict[str, list] = {}
_inflight_guard = threading.Lock()


@contextmanager
def _single_flight(digest: str) -> Iterator[None]:
    with _inflight_guard:
        entry = _inflight.setdefault(digest, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _inflight_guard:
            entry[1] -= 1
            if entry[1] == 0:
                _inflight.pop(digest, None)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _response(cfg: StructureResolverSettings, digest: str, sidecar: dict, source: str) -> dict:
    pdb_key, _ = _keys(cfg, digest)
    return {
        "url": _presign(pdb_key),
        "source": source,
        # Where the model came from, also on a cache hit (AlphaFold DB models
        # are CC-BY 4.0: the viewer credits them).
        "origin": sidecar.get("source"),
        "accession": sidecar.get("accession"),
        "sequence": sidecar.get("sequence") or "",
        "format": "pdb",
    }


def resolve_structure(
    payload: StructureResolveRequest,
    current_user=Depends(get_user_or_anonymous),
) -> dict:
    """Presigned URL of a PDB model for a UniProt accession, a gene, or a sequence.

    Mounted as ``POST /advanced_viz/structure/resolve`` by ``routes.py``.
    """
    cfg = settings.structure_resolver
    if not cfg.enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "The structure resolver is disabled on this server "
                "(set DEPICTIO_STRUCTURE_RESOLVER_ENABLED=true to allow it)."
            ),
        )
    # 403, not 401: the browser client treats a 401 as an expired session and
    # sends the visitor to the login page.
    if getattr(current_user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(status_code=403, detail=ANONYMOUS_REFUSAL)
    query = _normalise(payload, cfg)
    digest = query.cache_key()
    with _single_flight(digest):
        sidecar = _cache_lookup(cfg, digest)
        if sidecar is not None:
            return _response(cfg, digest, sidecar, "cache")
        resolved = _resolve(query, cfg)
        sidecar = _cache_store(cfg, digest, query, resolved)
    return _response(cfg, digest, sidecar, resolved.source)
