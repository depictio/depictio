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
from collections.abc import Callable
from typing import Any

from depictio.api.v1.services.jbrowse.assemblies import (
    PresetUrlFor,
    get_assembly_preset,
    preset_annotation_track,
    preset_assembly_config,
)
from depictio.api.v1.services.jbrowse.tracks import TrackRow
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

# role → URL for one track (data / index)
UrlFor = Callable[[TrackRow, str], str]
AssemblyUrlFor = Callable[[str, str], str]

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


def _loc(uri: str) -> dict[str, str]:
    return {"uri": uri, "locationType": "UriLocation"}


def _index_type(index_uri: str | None, default: str) -> str:
    return "CSI" if index_uri and index_uri.split("?", 1)[0].endswith(".csi") else default


def _base_track(track: TrackRow, assembly_name: str) -> tuple[str, dict[str, Any]]:
    """Track type and adapter for ``track`` (locations filled in by the caller)."""
    fmt = track.fmt
    indexed = track.bgzipped and bool(track.index_uri)
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


def _color_displays(track_type: str, color: str | None) -> list[dict[str, Any]]:
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
    return []


_DISPLAY_FOR_TRACK = {
    "QuantitativeTrack": "LinearWiggleDisplay",
    "FeatureTrack": "LinearBasicDisplay",
    "VariantTrack": "LinearVariantDisplay",
    "AlignmentsTrack": "LinearAlignmentsDisplay",
}


def _finalize_displays(conf: dict[str, Any]) -> dict[str, Any]:
    """Give every display a ``displayId`` (JBrowse requires one per display)."""
    for display in conf.get("displays", []) or []:
        display.setdefault("displayId", f"{conf['trackId']}-{display['type']}")
    return conf


def build_track_config(
    track: TrackRow,
    assembly_name: str,
    url_for: UrlFor,
    format_overrides: list[dict[str, Any]],
) -> dict[str, Any]:
    """One JBrowse track configuration for a manifest row."""
    track_type, adapter = _base_track(track, assembly_name)
    conf: dict[str, Any] = {
        "type": track_type,
        "trackId": track.track_id,
        "name": track.name,
        "assemblyNames": [assembly_name],
        "category": [track.category] if track.category else [track.fmt],
        "adapter": _fill_locations(adapter, track, url_for),
        "metadata": {k: v for k, v in track.row.items() if v is not None},
    }
    colored = _color_displays(track_type, track.color)
    if colored:
        conf["displays"] = colored
    for override in format_overrides:
        fmt_conf = override.get(track.fmt)
        if fmt_conf:
            conf = deep_merge(conf, fmt_conf)
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
