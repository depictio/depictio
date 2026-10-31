"""Assemble the payload the React genome browser renders from.

Given a ``jbrowse`` component and the dashboard filters (already extended over
DC links), this decides which tracks the view shows, builds their JBrowse
configuration with signed proxy URLs, and works out the locus.
"""

from __future__ import annotations

import re
from collections.abc import Callable
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
    variant_color_legend,
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


def _bare_chrom(chrom: Any) -> str:
    """A chromosome name compared loosely: ``chr15``, ``Chr15`` and ``15`` are one."""
    text = str(chrom).strip().lower()
    return text[3:] if text.startswith("chr") else text


def rows_in_region(
    rows: list[dict[str, Any]], spec: dict[str, Any], region: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """The ``rows`` with a side (primary or ``mate``) inside ``region``, in their order.

    ``region`` is the genome selection in force (``{chrom, start, end}``, a null
    ``end`` for a whole contig), the one a pick on another tile publishes with
    its value. When the filters narrow ``locus_from`` to several picks (a chord
    whose picks accumulate), the region names the latest one, so the view frames
    it rather than whichever of them sorts first. A chord publishes the end that
    was clicked, so the mate side counts too. Empty when nothing sits inside.
    """
    if not region or region.get("chrom") in (None, ""):
        return []
    chrom = _bare_chrom(region["chrom"])
    try:
        lo = float(region.get("start") or 0)
        hi = float(region["end"]) if region.get("end") is not None else float("inf")
    except (TypeError, ValueError):
        return []
    sides = [(spec["chrom_column"], spec["start_column"])]
    if spec.get("mate"):
        sides.append((spec["mate"]["chrom_column"], spec["mate"]["start_column"]))

    def inside(row: dict[str, Any], chrom_column: str, start_column: str) -> bool:
        if row.get(chrom_column) is None or _bare_chrom(row[chrom_column]) != chrom:
            return False
        try:
            return lo <= float(row.get(start_column)) <= hi  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    return [row for row in rows if any(inside(row, c, s) for c, s in sides)]


def pad_locus(locus: str | None, pad: int) -> str | None:
    """``locus`` (``chrom:start-end``) widened by ``pad`` on both sides, start clamped at 1."""
    match = _GENE_LOCUS.match(locus) if locus else None
    if not match:
        return locus
    return f"{match['chrom']}:{max(int(match['start']) - pad, 1)}-{int(match['end']) + pad}"


def centred_locus_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> str | None:
    """Like ``locus_from_rows``, with the first row in the middle of the frame.

    The opening frames the best call together with its close neighbours
    (``span_top``); framed from the smallest start to the largest end, the best
    call can sit at an edge. Here the window is widened on the short side until
    the first row's midpoint is its centre. Rows on another chromosome than the
    first are ignored.
    """
    if len(rows) < 2:
        return locus_from_rows(rows, spec)
    end_column = spec.get("end_column") or spec["start_column"]
    chrom = rows[0].get(spec["chrom_column"])
    spans: list[tuple[int, int]] = []
    for row in rows:
        if row.get(spec["chrom_column"]) != chrom:
            continue
        try:
            lo = int(float(row.get(spec["start_column"])))  # type: ignore[arg-type]
            hi = int(float(row.get(end_column)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        spans.append((min(lo, hi), max(lo, hi)))
    if not spans or chrom is None:
        return locus_from_rows(rows[:1], spec)
    pad = int(spec.get("padding", 5000))
    mid = (spans[0][0] + spans[0][1]) // 2
    half = max(mid - min(s for s, _ in spans), max(e for _, e in spans) - mid)
    return f"{chrom}:{max(mid - half - pad, 1)}-{mid + half + pad}"


# Genes a name fallback looks up: a handful of rows narrowed by a pick, each a
# round trip to the UCSC search (cached an hour, 5 s timeout).
GENE_FALLBACK_MAX = 3
# An Ensembl stable id (gene, transcript, protein, exon), versioned or not.
# UCSC's search resolves these on human assemblies (GENCODE tracks) as it does
# a symbol, so they are looked up like any name.
_ENSEMBL_ID = re.compile(r"^ENS[A-Z]{0,6}[GTPE]\d{6,}(\.\d+)?$", re.IGNORECASE)
_GENE_LOCUS = re.compile(r"^(?P<chrom>[^:]+):(?P<start>\d+)-(?P<end>\d+)$")


def gene_names_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    """The distinct names of ``rows`` a gene search looks up, first seen first.

    Per row, the ``locate_column`` value (a transcript id, which places the
    picked transcript rather than its whole gene) else the ``label_column``
    one. Empty without either column; blanks and values that cannot be a
    search term (spaces, characters the search endpoint refuses) are skipped.
    """
    columns = [c for c in (spec.get("locate_column"), spec.get("label_column")) if c]
    names: list[str] = []
    for row in rows:
        for column in columns:
            value = row.get(column)
            name = str(value).strip() if value is not None else ""
            if name and name.lower() != "nan" and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
                if name not in names:
                    names.append(name)
                break
    return names


def gene_symbols(
    names: list[str],
    genome: str | None,
    search: Callable[[str, str, int], list[dict[str, str]]] | None = None,
) -> list[str]:
    """``names`` with each Ensembl id replaced by its gene symbol, when UCSC knows it.

    The gene annotation groups a gene's transcripts under its symbol, so a pick
    naming its gene by id (``ENSG…``) would find no gene to star. The symbol is
    the first hit of the search whose label is not an Ensembl id (the search is
    cached: the gene fallback asked it already). Names kept as they are without
    a genome, a hit, or a reachable search.
    """
    if not genome:
        return names
    if search is None:
        from depictio.api.v1.services.jbrowse.assemblies import search_genes

        search = search_genes
    out: list[str] = []
    for name in names:
        symbol = name
        if _ENSEMBL_ID.match(name):
            try:
                hits = search(genome, name, 10)
            except Exception as exc:  # noqa: BLE001 - an unreachable UCSC keeps the id
                logger.info(f"jbrowse: symbol search for {name!r} failed: {exc}")
                hits = []
            symbol = next(
                (h["label"] for h in hits if h.get("label") and not _ENSEMBL_ID.match(h["label"])),
                name,
            )
        if symbol not in out:
            out.append(symbol)
    return out


def gene_fallback_locus(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
    genome: str | None,
    search: Callable[[str, str, int], list[dict[str, str]]] | None = None,
) -> str | None:
    """``chrom:start-end`` of the genes named by ``rows``, for rows with no coordinates.

    A ``locus_from`` collection built without genomic coordinates (an isoform
    table whose extended annotation was not written) still names its gene in
    ``label_column``. Each of the first ``GENE_FALLBACK_MAX`` distinct names is
    looked up in the UCSC ``genome`` through ``search`` (``search_genes`` by
    default); a symbol must match a hit's label exactly, an Ensembl id (which
    the hit's label spells differently) takes the first hit. The loci found on
    the most frequent chromosome are framed like ``locus_from_rows`` does, with
    the same ``padding``. None without a genome, a name, or a hit; a failed
    search is skipped, never raised.
    """
    if not genome:
        return None
    if search is None:
        from depictio.api.v1.services.jbrowse.assemblies import search_genes

        search = search_genes
    spans: dict[str, list[tuple[int, int]]] = {}
    for name in gene_names_from_rows(rows, spec)[:GENE_FALLBACK_MAX]:
        try:
            hits = search(genome, name, 10)
        except Exception as exc:  # noqa: BLE001 - an unreachable UCSC must not fail the view
            logger.info(f"jbrowse: gene fallback search for {name!r} failed: {exc}")
            continue
        if _ENSEMBL_ID.match(name):
            hit = hits[0] if hits else None
        else:
            hit = next((h for h in hits if h.get("label", "").upper() == name.upper()), None)
        match = _GENE_LOCUS.match(hit["locus"]) if hit else None
        if match:
            spans.setdefault(match["chrom"], []).append((int(match["start"]), int(match["end"])))
    if not spans:
        return None
    pad = int(spec.get("padding", 5000))
    chrom = max(spans, key=lambda c: len(spans[c]))
    lo = min(s for s, _ in spans[chrom])
    hi = max(e for _, e in spans[chrom])
    return f"{chrom}:{max(lo - pad, 1)}-{hi + pad}"


def union_locus(focus: str | None, other: str | None) -> str | None:
    """The smallest ``chrom:start-end`` holding both loci, named like ``focus``.

    ``focus`` alone when ``other`` is missing, unreadable or on another
    chromosome (a ``chr`` prefix aside: the gene search speaks UCSC, the rows
    may not).
    """
    a = _GENE_LOCUS.match(focus) if focus else None
    b = _GENE_LOCUS.match(other) if other else None
    if not a or not b:
        return focus
    bare = lambda c: c.removeprefix("chr")  # noqa: E731
    if bare(a["chrom"]) != bare(b["chrom"]):
        return focus
    lo = min(int(a["start"]), int(b["start"]))
    hi = max(int(a["end"]), int(b["end"]))
    return f"{a['chrom']}:{lo}-{hi}"


# Rows a view points at that the viewer colours: a pick is a few rows, the
# table's ``max_rows`` at most.
PICKED_MAX = 20
# Calls picked at the opening among those it frames (``span_top``): the best
# three wear the selection colour and a star.
OPENING_PICKED = 3
# The mark of a top call, in front of its name on the rank track.
TOP_CALL_STAR = "\u2605"
# The rank track's id and the colour of a call nobody picked (Mantine gray.6).
RANK_TRACK_ID = "depictio-ranked-calls"
RANK_TRACK_COLOR = "#868e96"


def picked_from_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any] | None:
    """What the viewer colours for the rows a view points at; None when nothing names them.

    ``loci``: one unpadded ``chrom:start-end`` per row (a variant or a call on a
    variant or rank track). ``names``: the names a feature track matches by
    (``gene_names_from_rows``: the transcript id, else the label). ``genes``,
    with a ``locate_column`` only: the labels (gene symbols) of rows named by a
    transcript, so the viewer finds the gene the picked transcript sits under
    without colouring its other isoforms. ``keys``: per row, the ``locus_from``
    columns that identify it (chromosome and start, the locate column), which a
    table of the same collection matches its rows by.
    """
    rows = rows[:PICKED_MAX]
    unpadded = {**spec, "padding": 0}
    loci: list[str] = []
    for row in rows:
        locus = locus_from_rows([row], unpadded)
        if locus and locus not in loci:
            loci.append(locus)
    key_columns = [
        c
        for c in (spec.get("chrom_column"), spec.get("start_column"), spec.get("locate_column"))
        if c
    ]
    keys = []
    for row in rows:
        key = {c: row[c] for c in key_columns if row.get(c) is not None}
        if key:
            keys.append(key)
    names = gene_names_from_rows(rows, spec)
    if not (loci or names):
        return None
    picked: dict[str, Any] = {"loci": loci, "names": names, "keys": keys}
    if spec.get("locate_column") and spec.get("label_column"):
        genes = gene_names_from_rows(rows, {"label_column": spec["label_column"]})
        if genes := [g for g in genes if g not in names]:
            picked["genes"] = genes
    return picked


def rank_track_config(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
    assembly_name: str,
    picked_rows: list[dict[str, Any]] | None = None,
    category_colors: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """A feature track of ``rows`` (the best calls, best first) named ``#rank label``.

    The first ``OPENING_PICKED`` calls carry a star in front of their name. A
    picked row outside them (``picked_rows``: a riboseq ORF below the top 20)
    is drawn too, named by its label alone, so the pick always has a feature.

    The features live in the config (``FromConfigAdapter``), so the track needs
    no file. Each call takes the category colour of its ``rank_color_by`` value
    (``category_colors``, the dashboard's map), the colour a genome_view coloured
    by that column gives it; grey otherwise. The viewer adds the medals and the
    picked calls. None when no row has usable coordinates.
    """
    end_column = spec.get("end_column") or spec["start_column"]
    label_column = spec.get("label_column")
    color_column = spec.get("rank_color_by")
    palette = (category_colors or {}).get(color_column) if color_column else None
    palette = palette if isinstance(palette, dict) else {}

    def colour(row: dict[str, Any]) -> dict[str, str]:
        hit = palette.get(str(row.get(color_column))) if color_column else None
        return {"color": hit} if isinstance(hit, str) else {}

    def span(row: dict[str, Any]) -> tuple[str, int, int] | None:
        chrom = row.get(spec["chrom_column"])
        try:
            lo, hi = sorted(
                (int(float(row.get(spec["start_column"]))), int(float(row.get(end_column))))  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            return None
        return None if chrom is None else (str(chrom), max(lo - 1, 0), max(hi, lo))

    features = []
    ranked = 0
    for rank, row in enumerate(rows, start=1):
        where = span(row)
        if where is None:
            continue
        ranked += 1
        label = row.get(label_column) if label_column else None
        name = f"#{rank} {label}" if label not in (None, "") else f"#{rank}"
        features.append(
            {
                "uniqueId": f"rank-{rank}",
                "refName": where[0],
                "start": where[1],
                "end": where[2],
                "name": f"{TOP_CALL_STAR} {name}" if rank <= OPENING_PICKED else name,
                "rank": rank,
                **colour(row),
            }
        )
    drawn = {(f["refName"], f["start"], f["end"]) for f in features}
    for i, row in enumerate(picked_rows or []):
        where = span(row)
        if where is None or where in drawn:
            continue
        drawn.add(where)
        label = row.get(label_column) if label_column else None
        features.append(
            {
                "uniqueId": f"picked-{i}",
                "refName": where[0],
                "start": where[1],
                "end": where[2],
                "name": str(label) if label not in (None, "") else "picked",
                **colour(row),
            }
        )
    if not features:
        return None
    return {
        "type": "FeatureTrack",
        "trackId": RANK_TRACK_ID,
        "name": f"Top {ranked} {spec.get('name') or 'calls'}".strip(),
        "category": ["Ranking"],
        "assemblyNames": [assembly_name],
        "adapter": {"type": "FromConfigAdapter", "features": features},
        "displays": [
            {
                "type": "LinearBasicDisplay",
                "displayId": f"{RANK_TRACK_ID}-LinearBasicDisplay",
                "renderer": {
                    "type": "CanvasFeatureRenderer",
                    "color1": f"jexl:get(feature,'color') || '{RANK_TRACK_COLOR}'",
                    "height": 10,
                },
            }
        ],
    }


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


def _opening_tracks(component: dict[str, Any], all_tracks: list[TrackRow]) -> list[TrackRow]:
    """The tracks the view opens with when no dashboard filter narrows the manifest.

    ``initial_categories`` picks them by the manifest's category column: the tracks
    of those categories that belong to the sample of the first such row (rows
    without a sample ride with any). Otherwise the first ``initial_tracks`` rows.
    """
    categories = set(component.get("initial_categories") or [])
    if not categories:
        return all_tracks[: int(component.get("initial_tracks", 5) or 0)]
    wanted = [t for t in all_tracks if t.category in categories]
    lead = next((t.sample for t in wanted if t.sample), None)
    return [t for t in wanted if lead is None or t.sample in (None, lead)]


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
    picked: dict[str, Any] | None = None,
    rank_rows: list[dict[str, Any]] | None = None,
    pick_rows: list[dict[str, Any]] | None = None,
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
        matched = _opening_tracks(component, all_tracks)
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
    # The ranked calls open right under the gene annotation, above the UCSC tracks.
    source = primary_locus_source(component)
    rank_conf = (
        rank_track_config(rank_rows, source, assembly_name, pick_rows, category_colors)
        if rank_rows and source
        else None
    )
    if rank_conf:
        tracks_conf.append(rank_conf)
        shown_ids.insert(at, rank_conf["trackId"])
        track_rows.append(_conf_summary(rank_conf, "ranking"))
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
    picked_rows: dict[str, Any] | None = None
    if locus:
        location, opening = locus, "filter"
        mate_location = mate_locus
        picked_rows = picked
    elif component.get("location"):
        location, opening = component["location"], "yaml"
    elif first_call and first_call.get("locus"):
        location, opening = first_call["locus"], "first_call"
        mate_location = first_call.get("mate_locus")
        picked_rows = first_call.get("picked")
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
        # The rows the view points at (the pick, else the best call): the
        # viewer paints them, and the table rows they name, in one colour.
        "picked": picked_rows,
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
        # What the variant colours stand for (the key to ``variant_color_by``).
        "variant_legend": variant_color_legend(component.get("variant_color_by"), category_colors),
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
