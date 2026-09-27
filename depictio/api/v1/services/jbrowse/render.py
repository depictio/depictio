"""Assemble the payload the React genome browser renders from.

Given a ``jbrowse`` component and the dashboard filters (already extended over
DC links), this decides which tracks the view shows, builds their JBrowse
configuration with signed proxy URLs, and works out the locus.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.jbrowse import signing
from depictio.api.v1.services.jbrowse.config_builder import (
    build_assembly_config,
    build_track_config,
    deep_merge,
    resolve_preset,
)
from depictio.api.v1.services.jbrowse.tracks import (
    TrackRow,
    TracksDC,
    manifest_rows,
    tracks_by_key,
)
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

API_PREFIX = "/depictio/api/v1"
# Tracks carried in the config when ``track_mode: all``; beyond this the view
# only receives the shown tracks (the manifest can hold thousands of cells).
MAX_CONFIG_TRACKS = 500


def _is_https(uri: str | None) -> bool:
    return uri is not None and uri.lower().startswith("https://")


def _url_factory(tdc: TracksDC, uid: str):
    def track_url(track: TrackRow, role: str) -> str:
        target = track.uri if role == "data" else track.index_uri
        if tdc.props.direct_access and _is_https(target):
            assert target
            return target
        query = signing.signed_query("track", tdc.dc_id, track.key, role, uid)
        return f"{API_PREFIX}/jbrowse/tracks/{tdc.dc_id}/{track.key}/{role}?{query}"

    def assembly_url(uri: str, role: str) -> str:
        if tdc.props.direct_access and _is_https(uri):
            return uri
        query = signing.signed_query("assembly", tdc.dc_id, "assembly", role, uid)
        return f"{API_PREFIX}/jbrowse/assembly/{tdc.dc_id}/{role}?{query}"

    return track_url, assembly_url


def _selection_column(component: dict[str, Any], tdc: TracksDC) -> str | None:
    return component.get("selection_column") or tdc.props.sample_column


def _track_summary(track: TrackRow, selection_column: str | None) -> dict[str, Any]:
    value = track.row.get(selection_column) if selection_column else None
    return {
        "track_id": track.track_id,
        "name": track.name,
        "format": track.fmt,
        "sample": track.sample,
        "selection_value": None if value is None else str(value),
    }


def locus_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> str | None:
    """``chrom:start-end`` around the first row, padded; None when unusable."""
    if not rows:
        return None
    row = rows[0]
    chrom = row.get(spec["chrom_column"])
    start = row.get(spec["start_column"])
    end = row.get(spec.get("end_column") or spec["start_column"])
    try:
        start_i, end_i = int(float(start)), int(float(end))
    except (TypeError, ValueError):
        return None
    if chrom is None:
        return None
    pad = int(spec.get("padding", 5000))
    lo, hi = sorted((start_i, end_i))
    return f"{chrom}:{max(lo - pad, 1)}-{hi + pad}"


def build_jbrowse_payload(
    component: dict[str, Any],
    tdc: TracksDC,
    filtered_rows: list[TrackRow] | None,
    uid: str,
    locus: str | None = None,
) -> dict[str, Any]:
    """The render payload.

    ``filtered_rows`` is the manifest after dashboard filters, or None when no
    filter applies to the tracks (then the view starts with ``initial_tracks``).
    """
    props = tdc.props
    all_tracks = list(tracks_by_key(tdc).values())
    selection_column = _selection_column(component, tdc)
    track_url, assembly_url = _url_factory(tdc, uid)

    max_tracks = int(component.get("max_tracks") or 20)
    default_ids = list(component.get("default_tracks") or [])
    by_id = {t.track_id: t for t in all_tracks}

    filter_applied = filtered_rows is not None
    if filter_applied:
        assert filtered_rows is not None
        matched = filtered_rows
    else:
        matched = all_tracks[: int(component.get("initial_tracks", 5) or 0)]
    shown = [by_id[i] for i in default_ids if i in by_id]
    shown += [t for t in matched if t.track_id not in default_ids]
    truncated = len(shown) > max_tracks
    shown = shown[:max_tracks]

    if component.get("track_mode") == "all":
        carried = {t.track_id: t for t in all_tracks[:MAX_CONFIG_TRACKS]}
        for t in shown:
            carried.setdefault(t.track_id, t)
        config_tracks = list(carried.values())
    else:
        config_tracks = shown

    # Assembly (component override wins over the DC's)
    assembly_spec: str | CustomAssembly = component.get("assembly") or props.assembly
    assembly_conf, annotation, preset_location = build_assembly_config(assembly_spec, assembly_url)
    assembly_name = assembly_conf["name"]

    overrides: dict[str, Any] = component.get("config_overrides") or {}
    preset = resolve_preset(component.get("preset"), props.presets) or {}
    format_layers = [
        preset.get("formats") or {},
        props.display_defaults,
        overrides.get("formats") or overrides.get("displays") or {},
    ]
    per_track = overrides.get("tracks") or {}

    tracks_conf: list[dict[str, Any]] = []
    for track in config_tracks:
        try:
            conf = build_track_config(track, assembly_name, track_url, format_layers)
        except ValueError as exc:
            logger.info(f"jbrowse: skipping track {track.track_id}: {exc}")
            continue
        if track.track_id in per_track:
            conf = deep_merge(conf, per_track[track.track_id])
        tracks_conf.append(conf)

    shown_ids = [t.track_id for t in shown if any(c["trackId"] == t.track_id for c in tracks_conf)]
    if annotation and component.get("show_annotation", True):
        tracks_conf.insert(0, annotation)
        shown_ids.insert(0, annotation["trackId"])
    for extra in overrides.get("extra_tracks") or []:
        if isinstance(extra, dict) and extra.get("trackId"):
            extra = {"assemblyNames": [assembly_name], **extra}
            tracks_conf.append(extra)
            shown_ids.append(extra["trackId"])

    if overrides.get("assembly"):
        assembly_conf = deep_merge(assembly_conf, overrides["assembly"])

    view = {
        "hideHeader": not component.get("show_header", True),
        "hideHeaderOverview": not component.get("show_overview", True),
        "trackLabels": component.get("track_labels") or "offset",
    }
    view = deep_merge(view, preset.get("view") or {})
    view = deep_merge(view, overrides.get("view") or {})
    configuration = deep_merge(
        preset.get("configuration") or {}, overrides.get("configuration") or {}
    )

    location = locus or component.get("location") or preset_location

    return {
        "assembly": assembly_conf,
        "tracks": tracks_conf,
        "shown_track_ids": shown_ids,
        "location": location,
        "view": view,
        "configuration": configuration,
        "track_rows": [_track_summary(t, selection_column) for t in config_tracks],
        "selection_column": selection_column,
        "tracks_dc_id": tdc.dc_id,
        "filter_applied": filter_applied,
        "total_tracks": len(all_tracks),
        "matched_tracks": len(filtered_rows) if filtered_rows is not None else len(all_tracks),
        "truncated": truncated,
    }


def filtered_track_rows(
    tdc: TracksDC, filter_metadata: list[dict[str, Any]]
) -> list[TrackRow] | None:
    """Manifest rows left after the filters, or None when nothing narrows them."""
    if not filter_metadata:
        return None
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    init_data: dict[str, dict] = {}
    if tdc.delta_location:
        init_data[tdc.dc_id] = {
            "delta_location": tdc.delta_location,
            "dc_type": "genomic_tracks",
            "size_bytes": 0,
        }
    df = load_deltatable_lite(
        workflow_id=ObjectId(tdc.wf_id),
        data_collection_id=tdc.dc_id,
        metadata=filter_metadata,
        init_data=init_data,
    )
    rows = manifest_rows(df, tdc.props)
    if len(rows) == len(tracks_by_key(tdc)):
        # Filters that do not touch this manifest (no shared column, no link)
        # leave every row: treat that as "no filter" rather than showing a
        # truncated first page of everything.
        return None
    return rows
