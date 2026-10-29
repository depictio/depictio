"""Build the JBrowse (linear genome view) configuration for a component.

Every file location handed to the browser is an explicit ``UriLocation``: the
adapters' ``uri`` shorthand derives index URLs by appending ``.tbi``/``.bai``
to the data URL, which breaks signed query strings.

Merge order, lowest to highest precedence:
    format defaults → built-in or DC preset → DC ``display_defaults`` →
    manifest row (name, colour, category) → component ``config_overrides``.
"""

from __future__ import annotations

import copy
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.jbrowse.assemblies import (
    PresetUrlFor,
    get_assembly_preset,
    preset_annotation_track,
    preset_assembly_config,
)
from depictio.api.v1.services.jbrowse.tracks import LOCAL_ABSOLUTE, TrackRow, display_uri
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

# role → URL for one track (data / index)
UrlFor = Callable[[TrackRow, str], str]
AssemblyUrlFor = Callable[[str, str], str]
# Does the index a track declares exist? (None: not checked, the index is trusted)
IndexExists = Callable[[TrackRow], bool]

# Default per-track download limit (MB) of the whole-file formats, applied when
# the component sets no ``fetch_size_limit_mb``. JBrowse's own 1 MB stops a
# plain VCF / BED / bedGraph at "Force load" long before a useful region is in.
# Indexed and bigWig/BAM/CRAM tracks read byte ranges and keep JBrowse's default.
DEFAULT_FETCH_SIZE_LIMIT_MB = 20
DEFAULT_FETCH_SIZE_LIMIT_FORMATS = frozenset(
    {"vcf", "bed", "narrowpeak", "broadpeak", "bedgraph", "gff3", "gtf"}
)

# Formats whose tabix index can be absent: they fall back to the plain adapter.
_TABIX_FORMATS = frozenset({"bedgraph", "bed", "narrowpeak", "broadpeak", "vcf", "gff3"})

NARROWPEAK_COLUMNS = [
    "chrom",
    "chromStart",
    "chromEnd",
    "name",
    "score",
    "strand",
    "signalValue",
    "pValue",
    "qValue",
    "peak",
]

# Colour of a feature: an explicit ``itemRgb`` ("R,G,B"), else a ``color``
# column (hex or CSS name, e.g. Strand-seq SV calls), else the track colour.
FEATURE_COLOR_JEXL = (
    "jexl:get(feature,'itemRgb') && get(feature,'itemRgb') != '0' "
    "? 'rgb(' + get(feature,'itemRgb') + ')' "
    ": (get(feature,'color') || '{fallback}')"
)

# JBrowse's own colour for a feature (CanvasFeatureRenderer ``color1`` default).
DEFAULT_FEATURE_COLOR = "goldenrod"

BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "sv-calls": {
        "description": "Structural-variant calls: one thin row per call, coloured per call",
        "formats": {
            fmt: {
                "displays": [
                    {
                        "type": "LinearBasicDisplay",
                        "height": 44,
                        "renderer": {
                            "type": "CanvasFeatureRenderer",
                            "height": 12,
                            "showLabels": False,
                            "showDescriptions": False,
                            "displayMode": "compact",
                        },
                    }
                ]
            }
            for fmt in ("bed", "bigbed", "vcf")
        },
    },
    "signal": {
        "description": "Coverage / ChIP signal: short filled wiggles, local autoscale",
        "formats": {
            "bigwig": {
                "displays": [
                    {
                        "type": "LinearWiggleDisplay",
                        "height": 60,
                        "autoscale": "local",
                        "defaultRendering": "xyplot",
                    }
                ]
            },
            "bedgraph": {
                "displays": [{"type": "LinearWiggleDisplay", "height": 60, "autoscale": "local"}]
            },
        },
    },
    "compact": {
        "description": "Everything small: compact features, 40 px wiggles, no labels",
        "view": {"trackLabels": "overlapping"},
        "formats": {
            "bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 40}]},
            "bedgraph": {"displays": [{"type": "LinearWiggleDisplay", "height": 40}]},
            **{
                fmt: {
                    "displays": [
                        {
                            "type": "LinearBasicDisplay",
                            "height": 40,
                            "renderer": {
                                "type": "CanvasFeatureRenderer",
                                "displayMode": "compact",
                                "showLabels": False,
                            },
                        }
                    ]
                }
                for fmt in ("bed", "bigbed", "narrowpeak", "broadpeak", "gff3", "gtf")
            },
        },
    },
    "peaks": {
        "description": "Peak calls (narrowPeak/broadPeak/BED): compact, labelled by name",
        "formats": {
            fmt: {
                "displays": [
                    {
                        "type": "LinearBasicDisplay",
                        "height": 36,
                        "renderer": {
                            "type": "CanvasFeatureRenderer",
                            "displayMode": "compact",
                            "showLabels": False,
                        },
                    }
                ]
            }
            for fmt in ("narrowpeak", "broadpeak", "bed", "bigbed")
        },
    },
}


def list_builtin_presets() -> list[dict[str, str]]:
    return [
        {"name": k, "description": v.get("description", "")} for k, v in BUILTIN_PRESETS.items()
    ]


def deep_merge(base: Any, override: Any) -> Any:
    """Merge ``override`` into ``base``.

    Dicts merge recursively. A list of display dicts merges item by item on
    ``type`` (so a preset can tweak ``LinearWiggleDisplay`` without restating
    the rest); any other value from ``override`` replaces the base.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    if (
        isinstance(base, list)
        and isinstance(override, list)
        and all(isinstance(x, dict) and "type" in x for x in base + override)
    ):
        merged = [dict(x) for x in base]
        for item in override:
            match = next((m for m in merged if m["type"] == item["type"]), None)
            if match is None:
                merged.append(copy.deepcopy(item))
            else:
                merged[merged.index(match)] = deep_merge(match, item)
        return merged
    return copy.deepcopy(override)


def _jexl_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _concrete_colors(colors: dict[str, Any]) -> dict[str, str]:
    """The ``category_colors`` entries that are a colour, in order.

    The wildcard (``*``) and the ``auto`` / ``auto:<column>`` sentinels are not
    colours: a sentinel is turned into palette colours when a dashboard is
    imported, and a feature matching no entry keeps the wildcard's colour.
    """
    return {
        str(k): v.strip()
        for k, v in colors.items()
        if isinstance(v, str) and v.strip() and v.strip() != "auto" and not v.startswith("auto:")
    }


def variant_color_jexl(
    spec: dict[str, Any] | None, category_colors: dict[str, dict[str, str]] | None
) -> str | None:
    """Jexl for the colour of a variant, from ``category_colors`` and an INFO field.

    ``spec`` is the component's ``variant_color_by`` (``column``, ``info_field``).
    The colours of ``column`` are tested in order against the whole INFO value
    (``ANN`` is an array: its entries are joined with ``|``) and the first
    category found in it wins, else the ``*`` colour, else JBrowse's default.
    A substring test, not a parse of one field: a variant can carry several
    annotations and the dashboard's category (e.g. viralrecon's ``EFFECT``) is
    not always the first one, so a variant with an annotation of two
    categories takes the one listed first. Returns None when there is no
    colour to apply.
    """
    if not spec or not spec.get("column"):
        return None
    colors = (category_colors or {}).get(spec["column"])
    if not isinstance(colors, dict):
        return None
    fallback = _concrete_colors({"*": colors.get("*")}).get("*", DEFAULT_FEATURE_COLOR)
    by_category = {k: v for k, v in _concrete_colors(colors).items() if k != "*"}
    if not by_category:
        return None
    info_field = spec.get("info_field") or "ANN"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", info_field):
        raise ValueError(f"Invalid INFO field name '{info_field}'")
    # ``join`` drops a missing field and flattens an array into one string.
    value = f"join('|', get(feature,'INFO').{info_field})"
    expression = _jexl_quote(fallback)
    for category, color in reversed(list(by_category.items())):
        expression = (
            f"includes({value}, {_jexl_quote(category)}) ? {_jexl_quote(color)} : {expression}"
        )
    return "jexl:" + expression


def variant_label_jexl(spec: dict[str, Any] | None) -> str | None:
    """Jexl naming a variant by one ``|`` part of an INFO field, else its ID.

    ``spec`` is the component's ``variant_label_by`` (``info_field``, ``part``).
    An array field (``CSQ``, ``ANN``) is joined first, so the part is read from
    its first annotation.
    """
    if not spec:
        return None
    info_field = spec.get("info_field") or "CSQ"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", info_field):
        raise ValueError(f"Invalid INFO field name '{info_field}'")
    part = int(spec.get("part", 3))
    value = f"join('|', get(feature,'INFO').{info_field})"
    return f"jexl:split({value}, '|')[{part}] || get(feature,'name') || get(feature,'id')"


# --------------------------------------------------------------------------
# Index existence (a manifest can declare an index that was never produced)
# --------------------------------------------------------------------------

_INDEX_CACHE_TTL_S = 300.0
_INDEX_ERROR_TTL_S = 30.0  # a failed check is retried soon, not on every render
_index_cache: dict[tuple[str, str], tuple[float, bool]] = {}
_index_cache_lock = threading.Lock()


def clear_index_exists_cache() -> None:
    with _index_cache_lock:
        _index_cache.clear()


def _probe_index(uri: str, base_folder: str) -> bool:
    """True when the object at ``uri`` exists; raises when that cannot be told."""
    from depictio.api.v1.services import remote_read

    if "://" not in uri and LOCAL_ABSOLUTE.match(uri):
        return os.path.exists(uri)
    try:
        remote_read.source_size(remote_read.resolve_location(uri, base_folder))
    except remote_read.RemoteReadError as exc:
        if exc.status == 404:
            return False
        raise
    return True


def cached_index_exists(
    uri: str, base_folder: str = "", probe: Callable[[str, str], bool] = _probe_index
) -> bool:
    """Existence of the index at ``uri``, cached per URI for a few minutes.

    A check that fails (network, credentials, a location the proxy would refuse
    anyway) never drops the index: the answer is "exists", remembered only for
    ``_INDEX_ERROR_TTL_S`` so a down storage does not stall every render.
    """
    key = (base_folder, uri)
    now = time.monotonic()
    with _index_cache_lock:
        cached = _index_cache.get(key)
        if cached and now < cached[0]:
            return cached[1]
    try:
        found = probe(uri, base_folder)
        expires = now + _INDEX_CACHE_TTL_S
    except Exception as exc:  # noqa: BLE001 - any failure of the check itself
        logger.debug(f"jbrowse: could not check index {uri}: {exc}")
        found, expires = True, now + _INDEX_ERROR_TTL_S
    with _index_cache_lock:
        if len(_index_cache) > 4096:
            _index_cache.clear()
        _index_cache[key] = (expires, found)
    return found


def storage_index_checker(
    base_folder: str, probe: Callable[[str, str], bool] | None = None
) -> IndexExists:
    """An ``IndexExists`` checking a track's index in storage (``base_folder`` for relative ones)."""

    def check(track: TrackRow) -> bool:
        if not track.index_uri:
            return False
        return cached_index_exists(track.index_uri, base_folder, probe or _probe_index)

    return check


def prefetch_index_checks(
    tracks: Iterable[TrackRow], index_exists: IndexExists, max_workers: int = 16
) -> None:
    """Warm the cache for every track that declares a checkable index, in parallel."""
    todo = [t for t in tracks if t.index_uri and t.bgzipped and t.fmt in _TABIX_FORMATS]
    if len(todo) < 2:
        return
    with ThreadPoolExecutor(max_workers=min(max_workers, len(todo))) as pool:
        list(pool.map(index_exists, todo))


def _loc(uri: str) -> dict[str, str]:
    return {"uri": uri, "locationType": "UriLocation"}


def _index_type(index_uri: str | None, default: str) -> str:
    return "CSI" if index_uri and index_uri.split("?", 1)[0].endswith(".csi") else default


def _base_track(
    track: TrackRow, assembly_name: str, index_exists: IndexExists | None = None
) -> tuple[str, dict[str, Any]]:
    """Track type and adapter for ``track`` (locations filled in by the caller).

    A bgzipped file whose declared index does not exist (per ``index_exists``)
    gets the plain whole-file adapter, as if it declared none.
    """
    fmt = track.fmt
    indexed = track.bgzipped and bool(track.index_uri)
    if indexed and index_exists is not None and fmt in _TABIX_FORMATS and not index_exists(track):
        logger.warning(
            f"jbrowse: index {track.index_uri} of track {track.track_id} does not exist; "
            "reading the whole file instead"
        )
        indexed = False
    if fmt == "bigwig":
        return "QuantitativeTrack", {"type": "BigWigAdapter", "bigWigLocation": "@data"}
    if fmt == "bedgraph":
        if indexed:
            return "QuantitativeTrack", {
                "type": "BedGraphTabixAdapter",
                "bedGraphGzLocation": "@data",
                "index": {"indexType": _index_type(track.index_uri, "TBI"), "location": "@index"},
            }
        return "QuantitativeTrack", {"type": "BedGraphAdapter", "bedGraphLocation": "@data"}
    if fmt in ("bed", "narrowpeak", "broadpeak"):
        extra: dict[str, Any] = {}
        if fmt == "narrowpeak":
            extra["columnNames"] = NARROWPEAK_COLUMNS
        elif fmt == "broadpeak":
            extra["columnNames"] = NARROWPEAK_COLUMNS[:-1]
        if indexed:
            return "FeatureTrack", {
                "type": "BedTabixAdapter",
                "bedGzLocation": "@data",
                "index": {"indexType": _index_type(track.index_uri, "TBI"), "location": "@index"},
                **extra,
            }
        return "FeatureTrack", {"type": "BedAdapter", "bedLocation": "@data", **extra}
    if fmt == "bigbed":
        return "FeatureTrack", {"type": "BigBedAdapter", "bigBedLocation": "@data"}
    if fmt == "vcf":
        if indexed:
            return "VariantTrack", {
                "type": "VcfTabixAdapter",
                "vcfGzLocation": "@data",
                "index": {"indexType": _index_type(track.index_uri, "TBI"), "location": "@index"},
            }
        return "VariantTrack", {"type": "VcfAdapter", "vcfLocation": "@data"}
    if fmt == "bam":
        return "AlignmentsTrack", {
            "type": "BamAdapter",
            "bamLocation": "@data",
            "index": {"indexType": _index_type(track.index_uri, "BAI"), "location": "@index"},
        }
    if fmt == "cram":
        return "AlignmentsTrack", {
            "type": "CramAdapter",
            "cramLocation": "@data",
            "craiLocation": "@index",
        }
    if fmt == "gff3":
        if indexed:
            return "FeatureTrack", {
                "type": "Gff3TabixAdapter",
                "gffGzLocation": "@data",
                "index": {"indexType": _index_type(track.index_uri, "TBI"), "location": "@index"},
            }
        return "FeatureTrack", {"type": "Gff3Adapter", "gffLocation": "@data"}
    if fmt == "gtf":
        return "FeatureTrack", {"type": "GtfAdapter", "gtfLocation": "@data"}
    raise ValueError(f"Format '{fmt}' cannot be shown as a track")


def _fill_locations(node: Any, track: TrackRow, url_for: UrlFor) -> Any:
    if node == "@data":
        return _loc(url_for(track, "data"))
    if node == "@index":
        return _loc(url_for(track, "index"))
    if isinstance(node, dict):
        return {k: _fill_locations(v, track, url_for) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill_locations(v, track, url_for) for v in node]
    return node


def _color_displays(
    track_type: str,
    color: str | None,
    variant_color: str | None = None,
    variant_label: str | None = None,
) -> list[dict[str, Any]]:
    if track_type == "QuantitativeTrack":
        if not color:
            return []
        return [
            {
                "type": "LinearWiggleDisplay",
                "renderers": {
                    "XYPlotRenderer": {"color": color},
                    "LinePlotRenderer": {"color": color},
                    "DensityRenderer": {"color": color},
                },
            }
        ]
    if track_type == "FeatureTrack":
        return [
            {
                "type": "LinearBasicDisplay",
                "renderer": {
                    "type": "CanvasFeatureRenderer",
                    "color1": FEATURE_COLOR_JEXL.replace("{fallback}", color or "goldenrod"),
                },
            }
        ]
    if track_type == "VariantTrack" and (variant_color or variant_label):
        renderer: dict[str, Any] = {"type": "CanvasFeatureRenderer"}
        if variant_color:
            renderer["color1"] = variant_color
        if variant_label:
            renderer["labels"] = {"name": variant_label}
        return [{"type": "LinearVariantDisplay", "renderer": renderer}]
    return []


_DISPLAY_FOR_TRACK = {
    "QuantitativeTrack": "LinearWiggleDisplay",
    "FeatureTrack": "LinearBasicDisplay",
    "VariantTrack": "LinearVariantDisplay",
    "AlignmentsTrack": "LinearAlignmentsDisplay",
}


def _alignment_displays(show_junctions: bool) -> list[dict[str, Any]]:
    """Display settings of an alignments track from the component's flags.

    ``show_junctions`` turns on the sashimi arcs: ``LinearAlignmentsDisplay``
    nests a ``LinearSNPCoverageDisplay`` (``snpCoverageDisplay``), and the arcs
    are the ``showArcs`` setting of that display's ``SNPCoverageRenderer``.

    The initial lower panel (pileup, read arcs, read cloud) is *not* a config
    setting in JBrowse 4.3: ``lowerPanelType`` is display state, so the viewer
    passes it when it opens the track (``showTrack``'s display snapshot).
    """
    if not show_junctions:
        return []
    return [
        {
            "type": "LinearAlignmentsDisplay",
            "snpCoverageDisplay": {
                "type": "LinearSNPCoverageDisplay",
                "renderers": {
                    "SNPCoverageRenderer": {"type": "SNPCoverageRenderer", "showArcs": True}
                },
            },
        }
    ]


_ALIGNMENT_SUBDISPLAYS = {
    "pileupDisplay": "LinearPileupDisplay",
    "snpCoverageDisplay": "LinearSNPCoverageDisplay",
}


# JBrowse also hides a feature track behind "Force load" when it holds more
# than ``maxFeatureScreenDensity`` features per pixel (0.3 by default): a
# cluster of a few hundred calls in a 100 kb window already trips it, although
# the canvas renderers draw thousands without trouble. A tile that raised the
# download limit wants its features drawn, so it raises this one with it.
_DENSE_DISPLAYS = {"LinearVariantDisplay", "LinearBasicDisplay"}
DENSE_SCREEN_DENSITY = 5


def apply_fetch_size_limit(
    conf: dict[str, Any], limit_bytes: int | None, override: bool = True
) -> dict[str, Any]:
    """Raise (or lower) JBrowse's per-track download limit on every display.

    JBrowse stops at ``fetchSizeLimit`` bytes (1 MB by default) and shows a
    "Force load" button instead of the features. The limit is a display setting,
    so the track's default display is created when the config has none; an
    alignments display carries it on its pileup and SNP-coverage sub-displays.
    ``override=False`` keeps a limit a display already sets (a default must not
    replace a value from a preset or an override).
    """
    if not limit_bytes:
        return conf
    display_type = _DISPLAY_FOR_TRACK.get(conf.get("type", ""))
    displays = list(conf.get("displays") or [])
    if display_type and not any(d.get("type") == display_type for d in displays):
        displays.append({"type": display_type})
    for display in displays:
        if display.get("type") == "LinearAlignmentsDisplay":
            for slot, sub_type in _ALIGNMENT_SUBDISPLAYS.items():
                sub = dict(display.get(slot) or {})
                sub.setdefault("type", sub_type)
                sub.setdefault("displayId", f"{conf['trackId']}-{sub_type}")
                if override or "fetchSizeLimit" not in sub:
                    sub["fetchSizeLimit"] = limit_bytes
                display[slot] = sub
        else:
            if override or "fetchSizeLimit" not in display:
                display["fetchSizeLimit"] = limit_bytes
            if display.get("type") in _DENSE_DISPLAYS:
                display.setdefault("maxFeatureScreenDensity", DENSE_SCREEN_DENSITY)
    conf["displays"] = displays
    return conf


def _finalize_displays(conf: dict[str, Any]) -> dict[str, Any]:
    """Give every display a ``displayId`` (JBrowse requires one per display)."""
    for display in conf.get("displays", []) or []:
        display.setdefault("displayId", f"{conf['trackId']}-{display['type']}")
    return conf


def _display_metadata(track: TrackRow, display: Callable[[str], str | None]) -> dict[str, Any]:
    """The manifest row with its URI and absolute-path cells sanitized."""
    uris = {track.uri, track.index_uri}
    out: dict[str, Any] = {}
    for key, value in track.row.items():
        if value is None:
            continue
        if isinstance(value, str) and (
            "://" in value or value.strip() in uris or LOCAL_ABSOLUTE.match(value.strip())
        ):
            out[key] = display(value.strip()) or ""
        else:
            out[key] = value
    return out


def build_track_config(
    track: TrackRow,
    assembly_name: str,
    url_for: UrlFor,
    format_overrides: list[dict[str, Any]],
    fetch_size_limit: int | None = None,
    variant_color: str | None = None,
    display: Callable[[str], str | None] | None = None,
    show_junctions: bool = False,
    index_exists: IndexExists | None = None,
    variant_label: str | None = None,
) -> dict[str, Any]:
    """One JBrowse track configuration for a manifest row.

    ``variant_color`` (see ``variant_color_jexl``) colours a variant track's
    features and ``variant_label`` (see ``variant_label_jexl``) names them; the format layers merge into that display, so a height set there
    stays. ``display`` maps a URI cell of the row to what the client may be
    shown (default: ``display_uri``); only ``metadata`` goes through it, the
    adapter locations keep the URLs JBrowse fetches. ``show_junctions`` draws
    splice-junction arcs on an alignments track (see ``_alignment_displays``).
    ``index_exists`` tells whether the index a track declares is really there
    (see ``_base_track``). ``fetch_size_limit`` unset gives the whole-file
    formats ``DEFAULT_FETCH_SIZE_LIMIT_MB`` (a limit set by a preset or override
    on the display wins over that default).
    """
    track_type, adapter = _base_track(track, assembly_name, index_exists)
    conf: dict[str, Any] = {
        "type": track_type,
        "trackId": track.track_id,
        "name": track.name,
        "assemblyNames": [assembly_name],
        "category": [track.category] if track.category else [track.fmt],
        "adapter": _fill_locations(adapter, track, url_for),
        "metadata": _display_metadata(track, display or display_uri),
    }
    colored = _color_displays(track_type, track.color, variant_color, variant_label)
    if track_type == "AlignmentsTrack":
        colored = _alignment_displays(show_junctions)
    if colored:
        conf["displays"] = colored
    for override in format_overrides:
        fmt_conf = override.get(track.fmt)
        if fmt_conf:
            conf = deep_merge(conf, fmt_conf)
    if fetch_size_limit:
        conf = apply_fetch_size_limit(conf, fetch_size_limit)
    elif track.fmt in DEFAULT_FETCH_SIZE_LIMIT_FORMATS:
        conf = apply_fetch_size_limit(
            conf, int(DEFAULT_FETCH_SIZE_LIMIT_MB * 1024 * 1024), override=False
        )
    return _finalize_displays(conf)


def build_assembly_config(
    assembly: str | CustomAssembly,
    assembly_url_for: AssemblyUrlFor,
    preset_url_for: PresetUrlFor | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """Return (assembly config, annotation track or None, default location).

    ``preset_url_for`` maps a preset file to the URL the browser reads (the API's
    preset proxy); left out, the browser reads UCSC directly.
    """
    if isinstance(assembly, str):
        preset = get_assembly_preset(assembly)
        if preset is None:
            raise ValueError(f"Unknown assembly preset '{assembly}'")
        if preset_url_for is None:
            return (
                preset_assembly_config(preset),
                preset_annotation_track(preset),
                preset.default_location,
            )
        return (
            preset_assembly_config(preset, preset_url_for),
            preset_annotation_track(preset, preset_url_for),
            preset.default_location,
        )

    sequence: dict[str, Any]
    if assembly.twobit_uri:
        adapter: dict[str, Any] = {
            "type": "TwoBitAdapter",
            "twoBitLocation": _loc(assembly_url_for(assembly.twobit_uri, "twobit")),
        }
        if assembly.chrom_sizes_uri:
            adapter["chromSizesLocation"] = _loc(
                assembly_url_for(assembly.chrom_sizes_uri, "chrom_sizes")
            )
    else:
        assert assembly.fasta_uri
        fai = assembly.fai_uri or f"{assembly.fasta_uri}.fai"
        if assembly.fasta_uri.split("?", 1)[0].endswith(".gz"):
            adapter = {
                "type": "BgzipFastaAdapter",
                "fastaLocation": _loc(assembly_url_for(assembly.fasta_uri, "fasta")),
                "faiLocation": _loc(assembly_url_for(fai, "fai")),
                "gziLocation": _loc(
                    assembly_url_for(assembly.gzi_uri or f"{assembly.fasta_uri}.gzi", "gzi")
                ),
            }
        else:
            adapter = {
                "type": "IndexedFastaAdapter",
                "fastaLocation": _loc(assembly_url_for(assembly.fasta_uri, "fasta")),
                "faiLocation": _loc(assembly_url_for(fai, "fai")),
            }
    sequence = {
        "type": "ReferenceSequenceTrack",
        "trackId": f"{assembly.name}-ReferenceSequenceTrack",
        "adapter": adapter,
    }
    conf: dict[str, Any] = {
        "name": assembly.name,
        "displayName": assembly.display_name or assembly.name,
        "aliases": list(assembly.aliases),
        "sequence": sequence,
    }
    if assembly.refname_aliases_uri:
        conf["refNameAliases"] = {
            "adapter": {
                "type": "RefNameAliasAdapter",
                "location": _loc(assembly_url_for(assembly.refname_aliases_uri, "aliases")),
            }
        }
    return conf, None, None


def resolve_preset(
    name: str | None, dc_presets: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    if not name:
        return None
    return dc_presets.get(name) or BUILTIN_PRESETS.get(name)
