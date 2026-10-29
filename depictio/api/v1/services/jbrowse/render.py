"""Assemble the payload the React genome browser renders from.

Given a ``jbrowse`` component and the dashboard filters (already extended over
DC links), this decides which tracks the view shows, builds their JBrowse
configuration with signed proxy URLs, and works out the locus.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.jbrowse import probe, signing, ucsc
from depictio.api.v1.services.jbrowse.config_builder import (
    apply_fetch_size_limit,
    build_assembly_config,
    build_track_config,
    deep_merge,
    prefetch_index_checks,
    resolve_preset,
    storage_index_checker,
    variant_color_jexl,
    variant_label_jexl,
)
from depictio.api.v1.services.jbrowse.tracks import (
    TrackRow,
    TracksDC,
    display_base_uri,
    display_uri,
    manifest_rows,
    s3_base_folder,
    tracks_by_key,
)
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

API_PREFIX = "/depictio/api/v1"
# Tracks carried in the view's config (and so offered in its track menus): the
# ones matching the filters, or every track with ``track_mode: all``. Only
# ``max_tracks`` of them open; a manifest can hold thousands of cells.
MAX_CONFIG_TRACKS = 500


def _is_https(uri: str | None) -> bool:
    return uri is not None and uri.lower().startswith("https://")


def _absolute(uri: str | None, props: Any) -> str | None:
    """A relative location made absolute against an https ``remote_base_uri``."""
    if uri and "://" not in uri and _is_https(props.remote_base_uri):
        return props.remote_base_uri.rstrip("/") + "/" + uri.lstrip("/")
    return uri


def _storage_of(uri: str, props: Any) -> str:
    """Where a track location is read from: ``direct``, ``remote`` or ``depictio``."""
    if _direct_url(uri, props):
        return "direct"
    if "://" not in uri:
        return "remote" if props.remote_base_uri else "depictio"
    if uri.lower().startswith(f"s3://{settings.s3.bucket}/"):
        return "depictio"
    return "remote"


def _shown_uri(uri: str | None, props: Any, anonymous: bool) -> tuple[str | None, str]:
    """(what the client may be shown of ``uri``, its storage). Display only."""
    if not uri:
        return None, "depictio"
    storage = _storage_of(uri, props)
    shown = _absolute(uri, props) if storage == "direct" else uri
    return display_uri(shown, storage, anonymous), storage


def _direct_url(uri: str | None, props: Any) -> str | None:
    """The https URL JBrowse may fetch itself (``direct_access``), else None."""
    absolute = _absolute(uri, props)
    if props.direct_access and absolute and _is_https(absolute):
        return absolute
    return None


def _url_factory(tdc: TracksDC, uid: str, delta_version: int | None = None):
    def track_url(track: TrackRow, role: str) -> str:
        direct = _direct_url(track.uri if role == "data" else track.index_uri, tdc.props)
        if direct:
            return direct
        query = signing.signed_query("track", tdc.dc_id, track.key, role, uid, delta_version)
        return f"{API_PREFIX}/jbrowse/tracks/{tdc.dc_id}/{track.key}/{role}?{query}"

    def assembly_url(uri: str, role: str) -> str:
        direct = _direct_url(uri, tdc.props)
        if direct:
            return direct
        query = signing.signed_query("assembly", tdc.dc_id, "assembly", role, uid)
        return f"{API_PREFIX}/jbrowse/assembly/{tdc.dc_id}/{role}?{query}"

    return track_url, assembly_url


def _preset_url(preset: Any, role: str) -> str:
    """Preset files through the API: one origin for the browser, cached small files."""
    return f"{API_PREFIX}/jbrowse/preset/{preset.name}/{role}"


def _selection_column(component: dict[str, Any], tdc: TracksDC) -> str | None:
    return component.get("selection_column") or tdc.props.sample_column


def _track_summary(
    track: TrackRow,
    selection_column: str | None,
    props: Any,
    anonymous: bool = False,
    group_column: str | None = None,
) -> dict[str, Any]:
    value = track.row.get(selection_column) if selection_column else None
    uri, storage = _shown_uri(track.uri, props, anonymous)
    # The group a track's colour stands for (the legend, and the lanes of a
    # genome view on the same samples): the tile's `color_by` column, else the
    # manifest's `group`.
    group = track.row.get(group_column or "group")
    return {
        "track_id": track.track_id,
        "name": track.name,
        "format": track.fmt,
        "sample": track.sample,
        "selection_value": None if value is None else str(value),
        "category": track.category,
        "color": track.color,
        "group": None if group in (None, "") else str(group),
        "source": "manifest",
        "uri": uri,
        "index_uri": _shown_uri(track.index_uri, props, anonymous)[0],
        "storage": storage,
    }


def _conf_summary(conf: dict[str, Any], source: str) -> dict[str, Any]:
    """Menu row of a track that is not in the manifest (annotation, UCSC, extra)."""
    category = conf.get("category")
    return {
        "track_id": conf["trackId"],
        "name": str(conf.get("name") or conf["trackId"]),
        "format": str((conf.get("adapter") or {}).get("type") or conf.get("type") or ""),
        "sample": None,
        "selection_value": None,
        "category": category[-1] if isinstance(category, list) and category else None,
        "color": None,
        "group": None,
        "source": source,
    }


def locus_sources(component: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``locus_from`` sources of a component (one dict or a list), each with its ``name``.

    The name is ``name``, else the collection tag, like the viewer's
    ``locusSources``. The first source is the primary one.
    """
    raw = component.get("locus_from")
    items = raw if isinstance(raw, list) else [raw]
    return [
        {**item, "name": str(item.get("name") or item.get("data_collection_tag") or "").strip()}
        for item in items
        if isinstance(item, dict) and item
    ]


def primary_locus_source(component: dict[str, Any]) -> dict[str, Any] | None:
    """The first ``locus_from`` source: it frames the view, carries the mate, feeds "Use this region"."""
    sources = locus_sources(component)
    return sources[0] if sources else None


def locus_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> str | None:
    """``chrom:start-end`` framing the span of ``rows``, padded; None when unusable.

    The rows that sit on the most frequent chromosome (ties: the one seen
    first) are framed from their smallest start to their largest end, with
    ``padding`` on both sides and the start clamped at 1. Rows with an
    unreadable chromosome or coordinate are ignored.
    """
    pad = int(spec.get("padding", 5000))
    end_column = spec.get("end_column") or spec["start_column"]
    spans: dict[Any, list[tuple[int, int]]] = {}
    for row in rows:
        chrom = row.get(spec["chrom_column"])
        if chrom is None:
            continue
        try:
            start_i = int(float(row.get(spec["start_column"])))  # type: ignore[arg-type]
            end_i = int(float(row.get(end_column)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        spans.setdefault(chrom, []).append(tuple(sorted((start_i, end_i))))  # type: ignore[arg-type]
    if not spans:
        return None
    # max() returns the first maximal key, and dicts keep insertion order.
    chrom = max(spans, key=lambda c: len(spans[c]))
    lo = min(s for s, _ in spans[chrom])
    hi = max(e for _, e in spans[chrom])
    return f"{chrom}:{max(lo - pad, 1)}-{hi + pad}"


def opening_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The calls the view opens on: the first one, or the first ``span_top`` when they sit together.

    ``rows`` are the first calls in ``sort_by`` order. With ``span_top`` set they
    are all kept when they lie on one chromosome and their span (smallest start to
    largest end) is at most ``max_span`` bases; otherwise only the first call is
    kept, so a far-apart second call never drags the view away from the best one.
    """
    if not rows or not spec.get("span_top") or len(rows) < 2:
        return rows[:1]
    end_column = spec.get("end_column") or spec["start_column"]
    chroms = set()
    starts: list[int] = []
    ends: list[int] = []
    for row in rows:
        try:
            lo = int(float(row.get(spec["start_column"])))  # type: ignore[arg-type]
            hi = int(float(row.get(end_column)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return rows[:1]
        chroms.add(str(row.get(spec["chrom_column"])))
        starts.append(min(lo, hi))
        ends.append(max(lo, hi))
    if len(chroms) > 1 or max(ends) - min(starts) > int(spec.get("max_span", 1_000_000)):
        return rows[:1]
    return rows


def mate_locus_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> str | None:
    """Locus of the second side of the ``rows`` framed by ``locus_from_rows``.

    Same framing and padding as the primary locus, on the ``locus_from.mate``
    columns; None when the component declares no mate or the cells are unusable.
    """
    mate = spec.get("mate")
    if not mate:
        return None
    return locus_from_rows(
        rows,
        {
            "chrom_column": mate["chrom_column"],
            "start_column": mate["start_column"],
            "end_column": mate.get("end_column"),
            "padding": spec.get("padding", 5000),
        },
    )


def build_jbrowse_payload(
    component: dict[str, Any],
    tdc: TracksDC,
    filtered_rows: list[TrackRow] | None,
    uid: str,
    locus: str | None = None,
    delta_version: int | None = None,
    category_colors: dict[str, dict[str, str]] | None = None,
    anonymous: bool = False,
    mate_locus: str | None = None,
    first_call: dict[str, str | None] | None = None,
    locus_source: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """The render payload.

    ``filtered_rows`` is the manifest after dashboard filters, or None when no
    filter applies to the tracks (then the view starts with ``initial_tracks``).
    ``delta_version`` is the manifest commit a pinned view reads; the track
    URLs carry it, so the proxy serves the files of that same manifest.
    ``category_colors`` is the dashboard's effective map (see
    ``effective_category_colors``): the component's ``variant_color_by`` reads
    its colours from it. ``anonymous`` (a public-link viewer) hides the
    ``remote_base_uri`` and shows remote files by name only. Every URI the
    payload shows (``track_rows``, ``tracks[].metadata``, ``remote_base``)
    goes through ``display_uri``; the adapter locations are the URLs JBrowse
    fetches and are left as built. ``locus_source`` names the ``locus_from``
    collection and columns (``{dc_id, chrom_column, start_column, end_column}``)
    the tile's "Use this region" filters on (the primary source); None when it has
    no ``locus_from``.
    """
    props = tdc.props
    all_tracks = list(tracks_by_key(tdc, delta_version).values())
    selection_column = _selection_column(component, tdc)
    track_url, assembly_url = _url_factory(tdc, uid, delta_version)

    max_tracks = int(component.get("max_tracks") or 20)
    default_ids = list(component.get("default_tracks") or [])
    by_id = {t.track_id: t for t in all_tracks}

    filter_applied = filtered_rows is not None
    if filtered_rows is not None:
        matched = filtered_rows
    else:
        matched = all_tracks[: int(component.get("initial_tracks", 5) or 0)]
    shown = [by_id[i] for i in default_ids if i in by_id]
    shown += [t for t in matched if t.track_id not in default_ids]
    shown = [t for t in shown if t.fmt != "fasta"]
    truncated = len(shown) > max_tracks
    shown = shown[:max_tracks]

    # Every track the view may open, shown ones first: filtered mode offers the
    # tracks matching the filters (all of them when nothing filters), ``all``
    # mode the whole manifest. Capped, the shown ones always carried.
    offered = all_tracks if component.get("track_mode") == "all" or not filter_applied else matched
    carried = {t.track_id: t for t in shown}
    for t in [*(by_id[i] for i in default_ids if i in by_id), *offered]:
        if len(carried) >= MAX_CONFIG_TRACKS:
            break
        if t.fmt != "fasta":
            carried.setdefault(t.track_id, t)
    config_tracks = list(carried.values())
    limit_mb = component.get("fetch_size_limit_mb")
    fetch_size_limit = int(float(limit_mb) * 1024 * 1024) if limit_mb else None
    show_junctions = bool(component.get("show_junctions", False))

    # Assembly (component override wins over the DC's)
    assembly_spec: str | CustomAssembly = component.get("assembly") or props.assembly
    assembly_conf, annotation, preset_location = build_assembly_config(
        assembly_spec,
        assembly_url,
        _preset_url if settings.jbrowse.preset_access == "proxy" else None,
    )
    assembly_name = assembly_conf["name"]

    overrides: dict[str, Any] = component.get("config_overrides") or {}
    preset = resolve_preset(component.get("preset"), props.presets) or {}
    format_layers = [
        preset.get("formats") or {},
        props.display_defaults,
        overrides.get("formats") or overrides.get("displays") or {},
    ]
    per_track = overrides.get("tracks") or {}
    variant_color = variant_color_jexl(component.get("variant_color_by"), category_colors)
    variant_label = variant_label_jexl(component.get("variant_label_by"))

    # Indexes the manifest declares but storage lacks fall back to plain adapters.
    index_exists = None
    try:
        index_exists = storage_index_checker(s3_base_folder(tdc.dc_id, props))
    except Exception as exc:  # noqa: BLE001 - a refused base folder is reported by the proxy
        logger.debug(f"jbrowse: index check skipped: {exc}")
    if index_exists is not None:
        prefetch_index_checks(config_tracks, index_exists)

    tracks_conf: list[dict[str, Any]] = []
    for track in config_tracks:
        try:
            conf = build_track_config(
                track,
                assembly_name,
                track_url,
                format_layers,
                fetch_size_limit,
                variant_color,
                display=lambda uri: _shown_uri(uri, props, anonymous)[0],
                show_junctions=show_junctions,
                index_exists=index_exists,
                variant_label=variant_label,
            )
        except ValueError as exc:
            logger.info(f"jbrowse: skipping track {track.track_id}: {exc}")
            continue
        if track.track_id in per_track:
            conf = deep_merge(conf, per_track[track.track_id])
        tracks_conf.append(conf)

    built = {c["trackId"] for c in tracks_conf}
    shown_ids = [t.track_id for t in shown if t.track_id in built]
    # A ``color_scale`` column plays the legend/group role ``color_by`` does.
    group_column = component.get("color_by") or (component.get("color_scale") or {}).get("column")
    track_rows = [
        _track_summary(t, selection_column, props, anonymous, group_column)
        for t in config_tracks
        if t.track_id in built
    ]
    if annotation and component.get("show_annotation", True):
        tracks_conf.insert(0, annotation)
        shown_ids.insert(0, annotation["trackId"])
        track_rows.insert(0, _conf_summary(annotation, "annotation"))
    ucsc_confs, ucsc_missing = ucsc.track_configs(
        ucsc.ucsc_genome(assembly_spec),
        list(component.get("ucsc_tracks") or []),
        assembly_name,
        ucsc.proxy_url(API_PREFIX),
    )
    # Reference tracks open first: the gene annotation, then the UCSC tracks.
    at = 1 if annotation and component.get("show_annotation", True) else 0
    for i, conf in enumerate(ucsc_confs):
        tracks_conf.append(apply_fetch_size_limit(conf, fetch_size_limit))
        shown_ids.insert(at + i, conf["trackId"])
        track_rows.append(_conf_summary(conf, "ucsc"))
    for extra in overrides.get("extra_tracks") or []:
        if isinstance(extra, dict) and extra.get("trackId"):
            extra = {"assemblyNames": [assembly_name], **extra}
            tracks_conf.append(extra)
            shown_ids.append(extra["trackId"])
            track_rows.append(_conf_summary(extra, "extra"))

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

    circular_categories = component.get("circular_categories")
    circular = set(["sv"] if circular_categories is None else circular_categories)
    sv_track_ids = [
        t.track_id for t in config_tracks if t.track_id in built and t.category in circular
    ]

    # Where the view opens, first level that yields a locus wins: the filter
    # narrowing ``locus_from``, the YAML ``location``, the first call (best row
    # of ``locus_from``), the first region holding data in the first tracks
    # shown (read from their index), the preset's default.
    mate_location: str | None = None
    if locus:
        location, opening = locus, "filter"
        mate_location = mate_locus
    elif component.get("location"):
        location, opening = component["location"], "yaml"
    elif first_call and first_call.get("locus"):
        location, opening = first_call["locus"], "first_call"
        mate_location = first_call.get("mate_locus")
    else:
        probed = probe.first_region(tdc, shown, delta_version)
        location, opening = (probed, "data") if probed else (preset_location, "preset")

    return {
        "assembly": assembly_conf,
        "tracks": tracks_conf,
        "shown_track_ids": shown_ids,
        "location": location,
        "opening": opening,
        "mate_location": mate_location,
        "view": view,
        "configuration": configuration,
        "track_rows": track_rows,
        "selection_column": selection_column,
        "tracks_dc_id": tdc.dc_id,
        "filter_applied": filter_applied,
        "total_tracks": len(all_tracks),
        "matched_tracks": len(filtered_rows) if filtered_rows is not None else len(all_tracks),
        "truncated": truncated,
        "max_tracks": max_tracks,
        "force_load": bool(component.get("force_load", False)),
        "ucsc_missing": ucsc_missing,
        "data_version": delta_version,
        "remote_base": display_base_uri(props.remote_base_uri, anonymous),
        "assembly_kind": "custom" if isinstance(assembly_spec, CustomAssembly) else "preset",
        "sv_track_ids": sv_track_ids,
        "read_pairs_display": component.get("read_pairs_display") or "pileup",
        "display": {k: v for k, v in (component.get("display") or {}).items() if v is not None}
        or None,
        "locus_source": locus_source,
    }


def filtered_track_rows(
    tdc: TracksDC, filter_metadata: list[dict[str, Any]], delta_version: int | None = None
) -> list[TrackRow] | None:
    """Manifest rows left after the filters, or None when nothing narrows them.

    ``delta_version`` reads the manifest as of that commit (a pinned view).
    """
    if not filter_metadata:
        return None
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    df = load_deltatable_lite(
        workflow_id=ObjectId(tdc.wf_id),
        data_collection_id=tdc.dc_id,
        metadata=filter_metadata,
        init_data=tdc.init_data(),
        delta_version=delta_version,
    )
    rows = manifest_rows(df, tdc.props)
    if len(rows) == len(tracks_by_key(tdc, delta_version)):
        # Filters that do not touch this manifest (no shared column, no link)
        # leave every row: treat that as "no filter" rather than showing a
        # truncated first page of everything.
        return None
    return rows
