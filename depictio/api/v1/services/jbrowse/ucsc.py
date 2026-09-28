"""UCSC Genome Browser tracks as default genome-browser tracks.

A component names UCSC tracks (``ucsc_tracks: [clinvarMain, encodeCcreCombined]``)
and they open next to the collection's own tracks. The names are resolved
through the UCSC REST API (``/list/tracks``), which gives each track's type and
``bigDataUrl``; only tracks backed by a file JBrowse can read by range are
offered: bigWig, the bigBed family and tabix-indexed VCF.

The catalogue of an assembly is one large JSON document (hg38: ~24k tracks,
~18 MB), fetched once per process and kept for ``ucsc_catalog_ttl_s``.

Files are read from UCSC's download server (relative ``/gbdb/...`` paths), or
from an absolute URL whose host is UCSC's or already allow-listed for remote
tracks; the browser reaches them through ``/jbrowse/ucsc/...`` (the same
public, fixed-source proxy as the preset assembly files) unless
``preset_access`` is ``direct`` and the host is UCSC's.
"""

from __future__ import annotations

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

    @property
    def index_url(self) -> str | None:
        return f"{self.url}.tbi" if self.kind == "vcfTabix" else None

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "type": self.kind, "group": self.group}


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
    """The readable tracks of a ``/list/tracks`` response, by track name."""
    raw = payload.get(genome)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, UcscTrack] = {}
    for name, info in raw.items():
        if not isinstance(info, dict):
            continue
        kind = str(info.get("type") or "").split(" ")[0]
        big = info.get("bigDataUrl")
        if kind not in _TRACK_TYPES or not isinstance(big, str) or not big:
            continue
        url = _file_url(big)
        if url is None:
            continue
        out[name] = UcscTrack(
            name=name,
            label=str(info.get("shortLabel") or name),
            long_label=str(info.get("longLabel") or ""),
            kind=kind,
            url=url,
            group=info.get("group") if isinstance(info.get("group"), str) else None,
        )
    return out


_cache: dict[str, tuple[float, dict[str, UcscTrack]]] = {}
_lock = threading.Lock()


def _fetch_catalog(genome: str) -> dict[str, UcscTrack]:
    url = f"{settings.jbrowse.ucsc_api_url.rstrip('/')}/list/tracks"
    resp = httpx.get(
        url,
        params={"genome": genome, "trackLeavesOnly": "1"},
        timeout=settings.jbrowse.remote_timeout_s * 4,
        follow_redirects=False,
    )
    resp.raise_for_status()
    return parse_catalog(genome, resp.json())


def catalog(genome: str) -> dict[str, UcscTrack]:
    """Readable tracks of a UCSC genome, cached; empty when UCSC is unreachable."""
    now = time.monotonic()
    hit = _cache.get(genome)
    if hit and now - hit[0] < settings.jbrowse.ucsc_catalog_ttl_s:
        return hit[1]
    with _lock:
        hit = _cache.get(genome)
        if hit and now - hit[0] < settings.jbrowse.ucsc_catalog_ttl_s:
            return hit[1]
        try:
            tracks = _fetch_catalog(genome)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"jbrowse: UCSC track list for {genome} unavailable: {exc}")
            # Keep serving a stale catalogue rather than nothing.
            return hit[1] if hit else {}
        _cache[genome] = (now, tracks)
        return tracks


def search(genome: str, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Catalogue entries matching ``query`` (name or label), best matches first."""
    q = query.strip().lower()
    entries = list(catalog(genome).values())
    if q:
        entries = [
            t
            for t in entries
            if q in t.name.lower() or q in t.label.lower() or q in t.long_label.lower()
        ]
        entries.sort(
            key=lambda t: (not t.name.lower().startswith(q), q not in t.label.lower(), t.name)
        )
    else:
        entries.sort(key=lambda t: (t.group is None, t.group or "", t.name))
    return [t.summary() for t in entries[: max(1, min(limit, 500))]]


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
