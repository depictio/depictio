"""UCSC Genome Browser tracks as default genome-browser tracks.

A component names UCSC tracks (``ucsc_tracks: [clinvarMain, encodeCcreCombined]``)
and they open next to the collection's own tracks. The names are resolved
through the UCSC REST API (``/list/tracks``), which gives each track's type and
``bigDataUrl``; only tracks backed by a file JBrowse can read by range are
offered: bigWig, the bigBed family and tabix-indexed VCF.

The catalogue of an assembly is one large JSON document (hg38: ~24k tracks,
~18 MB). It is read as a tree, so each track keeps the UCSC group and the
top-level collection (composite or super track) it sits under, which is what
the builder browses by. One worker fetches it, the cache (Redis when it is up)
shares it, and it is refetched after ``ucsc_catalog_ttl_s``: tracks UCSC adds
show up then without a release, and the last catalogue keeps being served
while UCSC is unreachable.

Files are read from UCSC's download server (relative ``/gbdb/...`` paths), or
from an absolute URL whose host is UCSC's or already allow-listed for remote
tracks; the browser reaches them through ``/jbrowse/ucsc/...`` (the same
public, fixed-source proxy as the preset assembly files) unless
``preset_access`` is ``direct`` and the host is UCSC's.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.jbrowse.assemblies import AssemblyPreset, get_assembly_preset
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

UCSC_DOWNLOAD_HOST = "hgdownload.soe.ucsc.edu"
UCSC_ROLES = ("data", "index")

# UCSC track type (first word of `type`) -> (JBrowse track type, adapter type)
_BIGBED_TYPES = (
    "bigBed",
    "bigGenePred",
    "bigNarrowPeak",
    "bigDbSnp",
    "bigLolly",
    "bigBarChart",
    "bigPsl",
)
_TRACK_TYPES: dict[str, tuple[str, str]] = {
    "bigWig": ("QuantitativeTrack", "BigWigAdapter"),
    "vcfTabix": ("VariantTrack", "VcfTabixAdapter"),
    **{t: ("FeatureTrack", "BigBedAdapter") for t in _BIGBED_TYPES},
}


@dataclass(frozen=True)
class UcscTrack:
    name: str
    label: str
    long_label: str
    kind: str  # UCSC type, first word
    url: str  # absolute file URL
    group: str | None
    # shortLabel of the top-level composite / super track; None at the top.
    collection: str | None = None

    @property
    def index_url(self) -> str | None:
        return f"{self.url}.tbi" if self.kind == "vcfTabix" else None

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.kind,
            "group": self.group,
            "collection": self.collection,
        }


# Labels of UCSC's track groups (``group`` holds the id).
GROUP_LABELS: dict[str, str] = {
    "map": "Mapping and Sequencing",
    "genes": "Genes and Gene Predictions",
    "phenDis": "Phenotype and Literature",
    "varRep": "Variation",
    "rep": "Repeats",
    "compGeno": "Comparative Genomics",
    "regulation": "Regulation",
    "expression": "Expression",
    "rna": "mRNA and EST",
    "singleCell": "Single Cell",
    "hprc": "Human Pangenome",
    "x": "Experimental",
}


def ucsc_genome(assembly: str | CustomAssembly | None) -> str | None:
    """The UCSC genome (database or GenArk accession) behind an assembly.

    A preset maps to its UCSC database, or to its GenArk accession for a hub
    assembly (TAIR10). A custom assembly maps through its name or aliases when
    one of them is a preset or a GenArk accession (e.g. MN908947.3 -> wuhCor1).
    """
    if assembly is None:
        return None
    names = [assembly] if isinstance(assembly, str) else [assembly.name, *(assembly.aliases or [])]
    for name in names:
        preset = get_assembly_preset(name)
        if preset is not None:
            return _preset_genome(preset)
        if name.upper().startswith(("GCF_", "GCA_")):
            return name
    return None


def _preset_genome(preset: AssemblyPreset) -> str:
    if "/goldenPath/" in preset.twobit_uri:
        return preset.name
    for alias in preset.aliases:
        if alias.upper().startswith(("GCF_", "GCA_")):
            return alias
    return preset.name


def _file_url(big_data_url: str) -> str | None:
    """Absolute URL of a track file, or None when its host is not readable."""
    if big_data_url.startswith("/"):
        return f"https://{UCSC_DOWNLOAD_HOST}{big_data_url}"
    parsed = urlparse(big_data_url)
    if parsed.scheme != "https":
        return None
    host = (parsed.hostname or "").lower()
    if host == UCSC_DOWNLOAD_HOST or host in settings.jbrowse.https_hosts:
        return big_data_url
    return None


def parse_catalog(genome: str, payload: dict[str, Any]) -> dict[str, UcscTrack]:
    """The readable tracks of a ``/list/tracks`` response, by track name.

    The response is a tree (super track > composite > view > subtrack, each a
    dict nested in its parent); a flat ``trackLeavesOnly`` one parses too. A
    track inherits the nearest ``group`` above it, which UCSC only sets on the
    container, and the label of its top-level container.
    """
    raw = payload.get(genome)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, UcscTrack] = {}

    def walk(name: str, info: dict[str, Any], group: str | None, collection: str | None):
        own = info.get("group")
        group = own if isinstance(own, str) and own else group
        kind = str(info.get("type") or "").split(" ")[0]
        big = info.get("bigDataUrl")
        url = _file_url(big) if kind in _TRACK_TYPES and isinstance(big, str) and big else None
        if url is not None and name not in out:
            out[name] = UcscTrack(
                name=name,
                label=str(info.get("shortLabel") or name),
                long_label=str(info.get("longLabel") or ""),
                kind=kind,
                url=url,
                group=group,
                collection=collection,
            )
        children = {k: v for k, v in info.items() if isinstance(v, dict)}
        if children:
            top = collection or str(info.get("shortLabel") or name)
            for child, sub in children.items():
                walk(child, sub, group, top)

    for name, info in raw.items():
        if isinstance(info, dict):
            walk(name, info, None, None)
    return out


@dataclass
class _Catalog:
    tracks: dict[str, UcscTrack]
    fetched_at: float  # epoch seconds, when UCSC answered
    checked_at: float = 0.0  # monotonic, when this process last read the shared copy


# This process's copy of the shared catalogues, re-read from the cache at most
# every _RECHECK_S so a refresh by another worker reaches it.
_cache: dict[str, _Catalog] = {}
_failed_at: dict[str, float] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_RECHECK_S = 60.0
# After a failed fetch, wait this long before asking UCSC again.
_RETRY_S = 60.0
# The shared copy outlives its TTL so it can still be served stale.
_KEEP_STALE_FACTOR = 7
_REFRESH_LOCK_S = 120


def _shared_key(genome: str) -> str:
    return f"jbrowse:ucsc:catalog:{genome}"


def _shared_get(genome: str) -> _Catalog | None:
    try:
        from depictio.api.cache import get_cache

        hit = get_cache().get(_shared_key(genome))
    except Exception as exc:  # cache unavailable: this process fetches its own
        logger.debug(f"jbrowse: UCSC catalogue cache read failed: {exc}")
        return None
    if isinstance(hit, tuple) and len(hit) == 2 and isinstance(hit[1], dict):
        return _Catalog(tracks=hit[1], fetched_at=float(hit[0]))
    return None


def _shared_set(genome: str, entry: _Catalog) -> None:
    try:
        from depictio.api.cache import get_cache

        ttl = settings.jbrowse.ucsc_catalog_ttl_s * _KEEP_STALE_FACTOR
        get_cache().set(_shared_key(genome), (entry.fetched_at, entry.tracks), ttl=ttl)
    except Exception as exc:
        logger.debug(f"jbrowse: UCSC catalogue cache write failed: {exc}")


def _claim_refresh(genome: str) -> bool:
    """One worker refreshes a catalogue at a time; True when it is this one."""
    try:
        from depictio.api.cache import get_cache

        return get_cache().set_nx(f"jbrowse:ucsc:refresh:{genome}", 1, ttl=_REFRESH_LOCK_S)
    except Exception:
        return True


def _release_refresh(genome: str) -> None:
    try:
        from depictio.api.cache import get_cache

        get_cache().delete(f"jbrowse:ucsc:refresh:{genome}")
    except Exception:
        pass


def _genome_lock(genome: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(genome, threading.Lock())


def _fetch_catalog(genome: str) -> dict[str, UcscTrack]:
    url = f"{settings.jbrowse.ucsc_api_url.rstrip('/')}/list/tracks"
    resp = httpx.get(
        url,
        params={"genome": genome},
        timeout=settings.jbrowse.remote_timeout_s * 4,
        follow_redirects=False,
    )
    resp.raise_for_status()
    return parse_catalog(genome, resp.json())


def _current(genome: str) -> _Catalog | None:
    """This process's copy, refreshed from the shared one when it is due."""
    now = time.monotonic()
    entry = _cache.get(genome)
    if entry is None or now - entry.checked_at > _RECHECK_S:
        shared = _shared_get(genome)
        if shared is not None and (entry is None or shared.fetched_at >= entry.fetched_at):
            entry = shared
        if entry is not None:
            entry.checked_at = now
            _cache[genome] = entry
    return entry


def _fresh(entry: _Catalog | None) -> bool:
    return (
        entry is not None and time.time() - entry.fetched_at < settings.jbrowse.ucsc_catalog_ttl_s
    )


def catalog_entry(genome: str) -> _Catalog | None:
    """The catalogue of a UCSC genome, refetched when stale; None when UCSC has
    never answered.

    A stale catalogue is served as is while another thread or worker refreshes
    it, and after a failed fetch for ``_RETRY_S``: a UCSC outage costs one slow
    request per minute, not one per render.
    """
    entry = _current(genome)
    if _fresh(entry):
        return entry
    if time.monotonic() - _failed_at.get(genome, float("-inf")) < _RETRY_S:
        return entry
    lock = _genome_lock(genome)
    # With something to serve, never queue behind a refresh already running.
    if not lock.acquire(blocking=entry is None):
        return entry
    try:
        entry = _current(genome)
        if _fresh(entry):
            return entry
        if entry is not None and not _claim_refresh(genome):
            return entry
        try:
            tracks = _fetch_catalog(genome)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"jbrowse: UCSC track list for {genome} unavailable: {exc}")
            _failed_at[genome] = time.monotonic()
            return entry
        finally:
            _release_refresh(genome)
        _failed_at.pop(genome, None)
        entry = _Catalog(tracks=tracks, fetched_at=time.time(), checked_at=time.monotonic())
        _cache[genome] = entry
        _shared_set(genome, entry)
        return entry
    finally:
        lock.release()


def catalog(genome: str) -> dict[str, UcscTrack]:
    """Readable tracks of a UCSC genome; empty when UCSC has never answered."""
    entry = catalog_entry(genome)
    return entry.tracks if entry is not None else {}


def _matches(track: UcscTrack, q: str) -> bool:
    return (
        q in track.name.lower()
        or q in track.label.lower()
        or q in track.long_label.lower()
        or q in (track.collection or "").lower()
    )


def search(
    genome: str,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    group: str | None = None,
) -> dict[str, Any]:
    """One page of the catalogue entries matching ``query`` and ``group``.

    ``total`` counts every match, so the builder can say how much is left, and
    ``groups`` counts the query's matches per UCSC group (before the group
    filter), so picking a group never hides the others' counts. Without a
    query, entries come grouped (group, then collection); with one, the best
    matches come first.
    """
    q = query.strip().lower()
    entry = catalog_entry(genome)
    entries = list(entry.tracks.values()) if entry is not None else []
    if q:
        entries = [t for t in entries if _matches(t, q)]
    counts: dict[str | None, int] = {}
    for t in entries:
        counts[t.group] = counts.get(t.group, 0) + 1
    if group is not None:
        wanted = group or None  # "" selects the tracks without a group
        entries = [t for t in entries if t.group == wanted]
    if q:
        entries.sort(
            key=lambda t: (not t.name.lower().startswith(q), q not in t.label.lower(), t.name)
        )
    else:
        entries.sort(
            key=lambda t: (t.group is None, t.group or "", t.collection or "", t.label.lower())
        )
    start = max(0, offset)
    page = entries[start : start + max(1, min(limit, 500))]
    fetched = (
        dt.datetime.fromtimestamp(entry.fetched_at, dt.UTC).replace(tzinfo=None).isoformat()
        if entry is not None
        else None
    )
    return {
        "tracks": [t.summary() for t in page],
        "total": len(entries),
        "groups": [
            {"id": g or "", "label": GROUP_LABELS.get(g, g) if g else "Other", "count": n}
            for g, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] or ""))
        ],
        "fetched_at": fetched,
    }


UcscUrlFor = Callable[[str, UcscTrack, str], str]


def proxy_url(api_prefix: str) -> UcscUrlFor:
    """URLs through the API's fixed-source UCSC proxy (or direct, per settings)."""

    def url_for(genome: str, track: UcscTrack, role: str) -> str:
        direct = track.url if role == "data" else track.index_url
        host = (urlparse(direct or "").hostname or "").lower()
        if settings.jbrowse.preset_access == "direct" and host == UCSC_DOWNLOAD_HOST and direct:
            return direct
        return f"{api_prefix}/jbrowse/ucsc/{quote(genome)}/{quote(track.name)}/{role}"

    return url_for


def track_config(
    genome: str, track: UcscTrack, assembly_name: str, url_for: UcscUrlFor
) -> dict[str, Any]:
    """JBrowse track config for one UCSC track."""
    track_type, adapter_type = _TRACK_TYPES[track.kind]
    loc = {"uri": url_for(genome, track, "data"), "locationType": "UriLocation"}
    if adapter_type == "BigWigAdapter":
        adapter: dict[str, Any] = {"type": adapter_type, "bigWigLocation": loc}
    elif adapter_type == "BigBedAdapter":
        adapter = {"type": adapter_type, "bigBedLocation": loc}
    else:
        adapter = {
            "type": adapter_type,
            "vcfGzLocation": loc,
            "index": {
                "location": {
                    "uri": url_for(genome, track, "index"),
                    "locationType": "UriLocation",
                },
                "indexType": "TBI",
            },
        }
    return {
        "type": track_type,
        "trackId": f"ucsc-{genome}-{track.name}",
        "name": track.label,
        "description": track.long_label,
        "category": ["UCSC", *([track.group] if track.group else [])],
        "assemblyNames": [assembly_name],
        "adapter": adapter,
    }


def track_configs(
    genome: str | None,
    names: list[str],
    assembly_name: str,
    url_for: UcscUrlFor,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Configs of the named UCSC tracks, and the names that could not be resolved."""
    if not names:
        return [], []
    if genome is None or not settings.jbrowse.ucsc_tracks_enabled:
        return [], list(names)
    known = catalog(genome)
    confs: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in names:
        track = known.get(name)
        if track is None:
            missing.append(name)
            continue
        confs.append(track_config(genome, track, assembly_name, url_for))
    return confs, missing
