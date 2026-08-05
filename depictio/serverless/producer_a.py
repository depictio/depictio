"""Producer A — export a static dashboard bundle from a RUNNING instance.

RFC §3.3: the full-fidelity producer. Input is a dashboard that lives in Mongo
(with its Delta tables in S3/MinIO); output is one self-contained HTML file
(phase 2: ``single-file`` mode only), sharing the manifest contract and the
emission machinery with producer B (``producer_b.py``).

Everything runs **in-process** — no HTTP round-trips to the API:

- Live tiers (cards / interactive / text) bundle their data collections the
  same way producer B does: ``load_deltatable_lite(..., init_data=...)`` →
  prune to the union of consuming components' columns (plus every interactive
  filter column that exists in the schema, mirroring the server's
  ``_effective_projection`` fold) → companion columns / codebooks → re-export
  as fresh snappy Parquet with 250k row groups. The Delta part-files are never
  globbed (RFC §6 / errata: tombstones double-count rows).
- Frozen tiers call the *real* endpoint bodies with the default (empty)
  filter state: ``bulk_compute_cards`` (fallback card payloads),
  ``render_table_endpoint`` (paged to the producer-B row cap),
  ``build_figure_preview`` (the Celery task *function*, called directly — the
  same code path preview and render share), ``fetch_advanced_viz_data`` (its
  ``sampling`` block is kept verbatim), ``render_multiqc*``, and the map
  service with the basemap forced to ``white-bg`` (zero-network single-file).
- Staleness: each DataRef records the server's ``_get_aggregation_hash`` for
  its DC (RFC errata #8), so a rebuilt bundle can be compared against the
  instance state it was cut from.

Figures are frozen in producer A (both ui and code mode) until the phase-5
binding module lands — see the TODO hook in :func:`_freeze_figure`.

Permissions (RFC §8): ``--check`` needs *viewer* on the dashboard's project;
the build itself needs *owner* — a bundle is bulk data exfiltration.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.serverless import (
    BundleManifest,
    BundleMode,
    ColumnSpec,
    ComponentTier,
    DashboardSection,
    DataRef,
    FrozenPayload,
    Producer,
    TierEntry,
    TierReason,
)
from depictio.serverless.preflight import _CELERY_VIZ_KINDS, TierRow
from depictio.serverless.producer_b import (
    PARQUET_COMPRESSION,
    PARQUET_ROW_GROUP_SIZE,
    TABLE_FROZEN_MAX_ROWS,
    _companion_targets,
    _depictio_version,
    render_bundle_html,
)
from depictio.serverless.pruning import component_columns

# Component types whose data ships in the bundle (live in the static runtime).
# Figures are NOT here: producer A freezes them until bindings exist (phase 5).
LIVE_DATA_TYPES = frozenset({"card", "interactive"})

# render_table_endpoint clamps ``limit`` to 500 per request; page up to the
# shared producer cap (``TABLE_FROZEN_MAX_ROWS``).
_TABLE_PAGE_LIMIT = 500

# Dashboard-document keys stripped before embedding: Mongo internals, the
# permission ACL (a shared bundle must not carry user identities), and the
# realtime config (errata #5 — omitting ``project_realtime`` keeps
# ``useDataCollectionUpdates`` inert, so the bundle never opens a WebSocket).
_DOC_STRIP_KEYS = frozenset({"_id", "permissions", "project_realtime"})


class ProducerAError(Exception):
    """Raised when a dashboard cannot be exported to a bundle."""


# ---------------------------------------------------------------------------
# Lazy server-module accessors.
#
# Producer A's dependencies (Mongo client, endpoint bodies, the Celery task
# function) live in modules that are heavy to import and need DEPICTIO_CONTEXT
# set; resolving them through their module objects at call time keeps
# ``import depictio.serverless.producer_a`` cheap and lets tests monkeypatch
# the module attributes (``routes.bulk_compute_cards = fake``) without any
# seam of our own.
# ---------------------------------------------------------------------------


def _db():
    from depictio.api.v1 import db

    return db


def _dtu():
    from depictio.api.v1 import deltatables_utils

    return deltatables_utils


def _routes():
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    return routes


def _av_routes():
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes

    return routes


def _celery():
    from depictio.api.v1 import celery_tasks

    return celery_tasks


def _response():
    """A throwaway ``fastapi.Response`` for endpoint bodies that set headers."""
    from fastapi import Response

    return Response()


# ---------------------------------------------------------------------------
# User resolution + permissions
# ---------------------------------------------------------------------------


@dataclass
class ExportUser:
    """The minimal user surface ``check_project_permission`` and the endpoint
    bodies read (``id`` / ``is_admin`` / ``is_anonymous``)."""

    id: Any
    email: str = ""
    is_admin: bool = False
    is_anonymous: bool = False


def resolve_user(user: Any = None) -> ExportUser:
    """Normalise the ``user`` argument into an :class:`ExportUser`.

    Accepts a User-like object (anything with ``id``/``is_admin``), an email
    string (looked up in ``users_collection``), or ``None`` — which falls back
    to the instance's first admin account, matching how operator-run exports
    are expected to be invoked.
    """
    if user is not None and not isinstance(user, str):
        return ExportUser(
            id=getattr(user, "id", None),
            email=getattr(user, "email", "") or "",
            is_admin=bool(getattr(user, "is_admin", False)),
            is_anonymous=bool(getattr(user, "is_anonymous", False)),
        )

    query: dict[str, Any] = {"email": user} if isinstance(user, str) else {"is_admin": True}
    doc = _db().users_collection.find_one(query)
    if not doc:
        target = f"user {user!r}" if isinstance(user, str) else "an admin user"
        raise ProducerAError(f"cannot resolve {target} in users_collection")
    return ExportUser(
        id=doc.get("_id"),
        email=doc.get("email") or "",
        is_admin=bool(doc.get("is_admin", False)),
        is_anonymous=bool(doc.get("is_anonymous", False)),
    )


# ---------------------------------------------------------------------------
# Tier classification (stored_metadata components)
# ---------------------------------------------------------------------------


def classify_stored_component(
    comp: dict[str, Any],
) -> tuple[ComponentTier, TierReason | None, str | None]:
    """Planned (data-free) tier verdict for one ``stored_metadata`` component.

    Mirrors producer B's ``classify_component`` where the logic transfers,
    diverging where producer A *can* compute a frozen payload with the real
    server code (multiqc, maps, advanced_viz data-path kinds).
    """
    ctype = comp.get("component_type") or ""

    if ctype in ("card", "interactive", "text"):
        return ComponentTier.LIVE, None, None

    if ctype == "table":
        return (
            ComponentTier.FROZEN,
            TierReason.UNSUPPORTED,
            "live tables land in phase 3; frozen at the default filter state",
        )

    if ctype == "figure":
        if comp.get("mode", "ui") == "code":
            return (
                ComponentTier.FROZEN,
                TierReason.CODE_MODE,
                "code-mode transpiler lands in phase 6; frozen via the server "
                "figure pipeline (RestrictedPython) at the default filter state",
            )
        return (
            ComponentTier.FROZEN,
            TierReason.BINDING_MISS,
            "no binding table yet (phase 5 bind-and-refill); frozen via the "
            "server figure pipeline at the default filter state",
        )

    if ctype == "multiqc":
        return (
            ComponentTier.FROZEN,
            TierReason.MULTIQC,
            "MultiQC renders server-side; frozen at the default filter state",
        )
    if ctype == "map":
        return (
            ComponentTier.FROZEN,
            TierReason.MAP_TILES,
            "frozen at the default filter state with the basemap forced to "
            "'white-bg' — network tiles are unavailable in a zero-network "
            "single-file bundle",
        )
    if ctype == "image":
        return (
            ComponentTier.OMITTED,
            TierReason.IMAGE,
            "image galleries read from S3; no object store in a static bundle",
        )
    if ctype == "jbrowse":
        return (
            ComponentTier.OMITTED,
            TierReason.JBROWSE,
            "JBrowse sessions need a genome-data backend",
        )
    if ctype == "advanced_viz":
        kind = comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or ""
        if kind in _CELERY_VIZ_KINDS:
            # TODO(producer-A follow-up): freeze the Celery computes by calling
            # their task functions (compute_embedding & co.) directly, the way
            # figures call build_figure_preview — the static runtime already
            # serves frozen 'compute' payloads through its finishedJob shim.
            return (
                ComponentTier.OMITTED,
                TierReason.CELERY_COMPUTE,
                f"advanced_viz '{kind}' is a server-side Celery compute; "
                "freezing it is a producer-A follow-up",
            )
        return (
            ComponentTier.FROZEN,
            TierReason.UNSUPPORTED,
            f"advanced_viz '{kind or '?'}' data-path kinds go live in phase 4; "
            "frozen /advanced_viz/data response at the default filter state",
        )

    return (
        ComponentTier.OMITTED,
        TierReason.UNSUPPORTED,
        f"component type '{ctype or '?'}' is not supported by producer A",
    )


def classify_stored_metadata(stored_metadata: list[dict[str, Any]]) -> list[TierRow]:
    """The planned tier table for a dashboard document, in component order."""
    rows: list[TierRow] = []
    for i, comp in enumerate(stored_metadata):
        tier, reason, detail = classify_stored_component(comp)
        rows.append(
            TierRow(
                component_id=str(comp.get("index") or f"component-{i}"),
                title=comp.get("title") or "",
                component_type=comp.get("component_type") or "?",
                tier=tier,
                reason=reason,
                detail=detail,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Dashboard document + data references
# ---------------------------------------------------------------------------


def sanitize_dashboard_doc(dashboard_data: dict[str, Any]) -> dict[str, Any]:
    """The dashboard document the static runtime mounts.

    The real Mongo document, JSON-ready (ObjectId/datetime → str via the same
    ``convert_objectid_to_str`` the API responses use) with Mongo internals,
    the permission ACL and the realtime config stripped (see
    ``_DOC_STRIP_KEYS``). NaN/Infinity safety is the injector's concern
    (``inject.json_safe``).
    """
    doc = {k: v for k, v in dashboard_data.items() if k not in _DOC_STRIP_KEYS}
    return convert_objectid_to_str(doc)


def _dc_init_entry(comp: dict[str, Any]) -> dict[str, Any] | None:
    """One ``init_data`` entry for a component's DC — ``dc_config`` first, the
    ``deltatables_collection`` lookup as fallback (the exact pattern of every
    render endpoint)."""
    dc_id = comp.get("dc_id")
    if not dc_id:
        return None
    dc_config = comp.get("dc_config") or {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        dt = _db().deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if not delta_loc:
        return None
    return {
        "delta_location": delta_loc,
        "dc_type": dc_config.get("type") or "table",
        "size_bytes": dc_config.get("size_bytes", 0),
    }


def live_column_sets(stored_metadata: list[dict[str, Any]]) -> dict[str, set[str] | None]:
    """Per-DC column sets for the *live* components (cards + interactive).

    Thin translation of ``pruning.compute_column_sets`` onto stored_metadata:
    the components ARE dicts of the shape ``component_columns`` reads
    (``column_name`` / ``breakdown_col`` / ``filter_expr`` / ``dict_kwargs``),
    but producer A keys DCs by their real Mongo ``dc_id`` and only bundles DCs
    that a live component consumes (frozen payloads carry their own data).

    Every interactive filter column that exists in a DC's schema is folded in
    later (see :func:`_bundle_data_refs`) to mirror the server's
    ``_effective_projection`` — cross-DC filters bind by column *name*.
    """
    sets: dict[str, set[str] | None] = {}
    for comp in stored_metadata:
        if comp.get("component_type") not in LIVE_DATA_TYPES:
            continue
        dc_id = comp.get("dc_id")
        if not dc_id:
            continue
        key = str(dc_id)
        cols = component_columns(comp)
        if key in sets and sets[key] is None:
            continue
        if cols is None:
            sets[key] = None
        else:
            sets[key] = (sets.get(key) or set()) | cols
    return sets


def interactive_filter_columns(stored_metadata: list[dict[str, Any]]) -> set[str]:
    """Column names any interactive component filters on (cross-DC candidates)."""
    return {
        comp["column_name"]
        for comp in stored_metadata
        if comp.get("component_type") == "interactive" and comp.get("column_name")
    }


# ---------------------------------------------------------------------------
# Frozen payload builders (in-process endpoint bodies, empty filter state)
# ---------------------------------------------------------------------------


def split_bulk_cards(bulk: dict[str, Any], card_indexes: list[str]) -> dict[str, dict[str, Any]]:
    """Per-component slices of a ``bulk_compute_cards`` response.

    The static runtime's ``bulkComputeCards`` shim merges every frozen
    card-kind payload into one response, so each slice keeps the bulk shape.
    """
    out: dict[str, dict[str, Any]] = {}
    values = bulk.get("values") or {}
    secondary = bulk.get("secondary_values") or {}
    aggregations = bulk.get("aggregations") or {}
    for idx in card_indexes:
        if idx not in values:
            continue
        payload: dict[str, Any] = {
            "values": {idx: values[idx]},
            "filter_applied": False,
            "filter_count": 0,
        }
        if idx in secondary:
            payload["secondary_values"] = {idx: secondary[idx]}
        if idx in aggregations:
            payload["aggregations"] = {idx: aggregations[idx]}
        out[idx] = payload
    return out


def _freeze_cards(
    dashboard_oid: ObjectId, cards: list[dict[str, Any]], user: ExportUser
) -> dict[str, dict[str, Any]]:
    """Fallback card payloads (bulk response shape) at the default filter state.

    Cards are live in the bundle; the frozen snapshot is the value the shim
    shows if the in-browser computation fails (live results win on merge).
    """
    indexes = [str(c.get("index")) for c in cards]
    bulk = _routes().bulk_compute_cards(
        dashboard_oid,
        {"filters": [], "component_ids": indexes},
        current_user=user,
        access_token=None,
    )
    return split_bulk_cards(bulk, indexes)


def _freeze_table(
    dashboard_oid: ObjectId,
    component_id: str,
    user: ExportUser,
    max_rows: int = TABLE_FROZEN_MAX_ROWS,
) -> dict[str, Any]:
    """The renderTable response shape, paged up to the shared row cap."""
    routes = _routes()
    rows: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    total = 0
    start = 0
    while start < max_rows:
        limit = min(_TABLE_PAGE_LIMIT, max_rows - start)
        page = routes.render_table_endpoint(
            dashboard_oid,
            component_id,
            {"filters": [], "start": start, "limit": limit},
            _response(),
            current_user=user,
            access_token=None,
        )
        if start == 0:
            columns = page.get("columns") or []
            total = int(page.get("total") or 0)
        page_rows = page.get("rows") or []
        rows.extend(page_rows)
        start += limit
        if not page_rows or len(rows) >= total:
            break
    return {"columns": columns, "rows": rows[:max_rows], "total": total}


def _freeze_figure(comp: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Freeze a figure by calling the Celery task *function* directly.

    ``build_figure_preview`` is the single worker code path preview and render
    share (RFC errata #4); calling the function (not ``.delay()``) runs it
    in-process. The payload mirrors ``render_figure_endpoint``'s task payload
    with the default (empty) filter state.

    TODO(phase 5): when ``depictio.serverless.binding.build_binding`` lands,
    ui-mode figures whose traces all match a binding become live — this
    function then only serves as the scaffold builder / fallback freeze.

    Returns ``(payload, was_sampled)``.
    """
    payload = {
        "metadata": {
            "wf_id": str(comp.get("wf_id")),
            "dc_id": str(comp.get("dc_id")),
            "dc_config": convert_objectid_to_str(comp.get("dc_config") or {}),
            "visu_type": comp.get("visu_type", "scatter"),
            "dict_kwargs": comp.get("dict_kwargs") or {},
            "mode": comp.get("mode", "ui"),
            "code_content": comp.get("code_content", ""),
            "selection_enabled": bool(comp.get("selection_enabled", False)),
            "selection_column": comp.get("selection_column"),
            "max_points": comp.get("max_points"),
        },
        "filter_metadata": [],
        "theme": "light",
        "full_load": False,
    }
    result = _celery().build_figure_preview(payload)
    meta = result.get("metadata") or {}
    if meta.get("error"):
        raise ProducerAError(f"figure code failed: {meta['error']}")
    return result, bool(meta.get("was_sampled", False))


def advanced_viz_request(comp: dict[str, Any]) -> dict[str, Any] | None:
    """The ``/advanced_viz/data`` request an advanced_viz component implies.

    Columns and roles are derived from the component's persisted ``config``
    blob (``<role>_col`` scalars plus sunburst's ``rank_cols`` list) — the
    same convention ``buildAdvancedVizConfigBlob`` writes and the catalog
    preview reads. Returns ``None`` when no columns can be derived.
    """
    if not comp.get("wf_id") or not comp.get("dc_id"):
        return None
    config = comp.get("config") or {}
    kind = comp.get("viz_kind") or config.get("viz_kind") or ""
    columns: list[str] = []
    roles: dict[str, str] = {}
    for key, value in config.items():
        if key == "rank_cols" and isinstance(value, list):
            columns.extend(v for v in value if isinstance(v, str))
        elif key.endswith("_col") and isinstance(value, str) and value:
            roles[key[: -len("_col")]] = value
            columns.append(value)
    columns = list(dict.fromkeys(columns))
    if not columns:
        return None
    return {
        "wf_id": str(comp["wf_id"]),
        "dc_id": str(comp["dc_id"]),
        "columns": columns,
        "filter_metadata": [],
        "viz_kind": kind or None,
        "roles": roles,
    }


def _freeze_advanced_viz(comp: dict[str, Any], user: ExportUser) -> dict[str, Any]:
    """Freeze a data-path advanced_viz via the real ``/advanced_viz/data`` body.

    The response's ``sampling`` block is kept verbatim — it is what the
    renderer's badge reads, and pinning it is what makes a reduced frozen
    frame honest about being reduced.
    """
    request = advanced_viz_request(comp)
    if request is None:
        raise ProducerAError(
            "advanced_viz component has no derivable columns (config carries no '*_col' bindings)"
        )
    av = _av_routes()
    payload = av.fetch_advanced_viz_data(
        _response(), payload=request, current_user=user, access_token=None
    )
    # Phylogenetic kind: its renderer also needs the tree; merge the Newick in
    # (frozen payloads are one slot per component — the shim reads the same
    # payload object for both lookups).
    tree_dc_id = (comp.get("config") or {}).get("tree_dc_id")
    if tree_dc_id:
        try:
            payload["newick"] = av.get_phylogeny_newick(ObjectId(str(tree_dc_id)), user)
        except Exception:
            pass  # best-effort — the tabular payload is still worth shipping
    return payload


def _freeze_multiqc(
    dashboard_oid: ObjectId, comp: dict[str, Any], user: ExportUser
) -> tuple[str, dict[str, Any]]:
    """Freeze a MultiQC component via the endpoint its renderer would call.

    Returns ``(kind, payload)`` — General Stats components render through
    ``render_multiqc_general_stats``, everything else through
    ``render_multiqc`` (one of the two per component, mirroring
    ``MultiQCDispatch``).
    """
    routes = _routes()
    component_id = str(comp.get("index"))
    request = {"filters": [], "theme": "light"}
    _, _, _, is_gs = routes._resolve_selected_keys(comp)
    if is_gs:
        payload = routes.render_multiqc_general_stats_endpoint(
            dashboard_oid, component_id, request, current_user=user
        )
        return "multiqc-general-stats", payload
    payload = routes.render_multiqc_endpoint(
        dashboard_oid, component_id, request, current_user=user
    )
    return "multiqc", payload


def _freeze_map(comp: dict[str, Any], user: ExportUser) -> dict[str, Any]:
    """Freeze a map at the default filter state with a zero-network basemap.

    Mirrors ``render_map_endpoint``'s body, but forces ``map_style`` to
    ``white-bg``: MapLibre tile styles fetch from the network, which a
    single-file bundle must never do (RFC §2.4). The endpoint itself cannot be
    reused verbatim because it reads the component from Mongo — the style
    override has to reach ``render_map``'s ``trigger_data``.
    """
    import json as _json

    from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates
    from depictio.api.v1.services.map.render import render_map

    init_entry = _dc_init_entry(comp)
    if init_entry is None:
        raise ProducerAError("map component's DC has no materialised Delta table")
    dc_id = str(comp["dc_id"])
    df = _dtu().load_deltatable_lite(
        workflow_id=ObjectId(str(comp["wf_id"])),
        data_collection_id=dc_id,
        metadata=None,
        init_data={dc_id: init_entry},
    )
    ensure_mantine_templates()
    trigger_data = {**comp, "map_style": "white-bg"}
    fig, data_info = render_map(
        df=df,
        trigger_data=trigger_data,
        theme="light",
        existing_metadata=None,
        active_selection_values=None,
        access_token=None,
    )
    fig_dict = _json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")
    return {
        "figure": fig_dict,
        "metadata": {
            "map_type": comp.get("map_type", "scatter_map"),
            "filter_applied": False,
            "displayed_count": data_info.get("displayed_count"),
            "total_count": data_info.get("total_count"),
        },
    }


# ---------------------------------------------------------------------------
# Data refs (live tier)
# ---------------------------------------------------------------------------


def _bundle_data_refs(
    stored_metadata: list[dict[str, Any]],
) -> tuple[dict[str, DataRef], dict[str, str], dict[str, str]]:
    """Bundle every DC a live component consumes.

    Returns ``(data_refs, inline_blobs, failures)`` where ``failures`` maps
    ``dc_id`` → error string for DCs that could not be loaded (their live
    components are downgraded by the caller).
    """
    dtu = _dtu()
    column_sets = live_column_sets(stored_metadata)
    filter_cols = interactive_filter_columns(stored_metadata)
    interactive_comps = [c for c in stored_metadata if c.get("component_type") == "interactive"]
    live_comps_by_dc: dict[str, list[dict[str, Any]]] = {}
    for comp in stored_metadata:
        if comp.get("component_type") in LIVE_DATA_TYPES and comp.get("dc_id"):
            live_comps_by_dc.setdefault(str(comp["dc_id"]), []).append(comp)

    data_refs: dict[str, DataRef] = {}
    inline_blobs: dict[str, str] = {}
    failures: dict[str, str] = {}

    for dc_id, comps in live_comps_by_dc.items():
        rep = comps[0]
        wf_id = rep.get("wf_id")
        init_entry = _dc_init_entry(rep)
        if not wf_id or init_entry is None:
            failures[dc_id] = "no materialised Delta table (missing delta_location)"
            continue

        cols = column_sets.get(dc_id)
        try:
            schema = dtu.schema_deltatable_lite(
                workflow_id=ObjectId(str(wf_id)),
                data_collection_id=dc_id,
                init_data={dc_id: init_entry},
            )
            available = list(schema.keys())
            if cols is None:
                select: list[str] | None = None
            else:
                # Fold every interactive filter column that exists in this DC's
                # schema (cross-DC name binding — RFC §5) before intersecting.
                wanted = cols | filter_cols
                select = [c for c in available if c in wanted]
            df = dtu.load_deltatable_lite(
                workflow_id=ObjectId(str(wf_id)),
                data_collection_id=dc_id,
                metadata=None,
                select_columns=select,
                init_data={dc_id: init_entry},
            )
        except Exception as exc:
            failures[dc_id] = f"Delta load failed: {exc}"
            continue

        if "depictio_aggregation_time" in df.columns:
            df = df.drop("depictio_aggregation_time")

        # Companion columns for every interactive filter column present in this
        # frame — including cross-DC ones, which is why *all* interactive
        # components are passed (``_companion_targets`` schema-guards).
        categorical_cols, datetime_cols = _companion_targets(interactive_comps, df)
        from depictio.serverless.companions import build_companions

        result = build_companions(df, categorical_cols, datetime_cols)

        buf = io.BytesIO()
        result.df.write_parquet(
            buf, compression=PARQUET_COMPRESSION, row_group_size=PARQUET_ROW_GROUP_SIZE
        )
        parquet_bytes = buf.getvalue()

        blob_key = f"dc_{dc_id}"
        inline_blobs[blob_key] = base64.b64encode(parquet_bytes).decode("ascii")
        data_refs[dc_id] = DataRef(
            uri=f"inline:{blob_key}",
            rows=result.df.height,
            size_bytes=len(parquet_bytes),
            columns=[
                ColumnSpec(name=name, dtype=str(dtype)) for name, dtype in result.df.schema.items()
            ],
            companions=result.companions,
            codebooks=result.codebooks,
            aggregation_hash=dtu._get_aggregation_hash(dc_id)
            or hashlib.sha256(parquet_bytes).hexdigest(),
        )

    return data_refs, inline_blobs, failures


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@dataclass
class ExportResult:
    """A validated manifest plus the tier table that produced it.

    ``manifest`` is ``None`` for ``check=True`` (preflight writes nothing).
    """

    manifest: BundleManifest | None
    tier_rows: list[TierRow]


def _fetch_dashboard(dashboard_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(str(dashboard_id))
    except Exception as exc:
        raise ProducerAError(f"invalid dashboard id {dashboard_id!r}: {exc}") from exc
    doc = _db().dashboards_collection.find_one({"dashboard_id": oid})
    if not doc:
        raise ProducerAError(f"dashboard '{dashboard_id}' not found")
    return doc


def _check_permission(dashboard_data: dict[str, Any], user: ExportUser, required: str) -> None:
    project_id = dashboard_data.get("project_id")
    if not project_id or not _routes().check_project_permission(project_id, user, required):
        raise ProducerAError(
            f"permission denied: exporting needs '{required}' on the dashboard's project "
            "(RFC §8 — a bundle is bulk data exfiltration)"
        )


def export_manifest(dashboard_id: str, user: ExportUser) -> ExportResult:
    """Assemble and validate the full ``BundleManifest`` for one dashboard."""
    dashboard_data = _fetch_dashboard(dashboard_id)
    _check_permission(dashboard_data, user, "owner")

    stored_metadata: list[dict[str, Any]] = dashboard_data.get("stored_metadata") or []
    tier_rows = classify_stored_metadata(stored_metadata)
    tier_by_id = {row.component_id: row for row in tier_rows}
    dashboard_oid = ObjectId(str(dashboard_data["dashboard_id"]))

    # Live tier: bundle the DCs cards/interactive read.
    data_refs, inline_blobs, dc_failures = _bundle_data_refs(stored_metadata)
    for comp in stored_metadata:
        if comp.get("component_type") not in LIVE_DATA_TYPES:
            continue
        dc_id = str(comp.get("dc_id") or "")
        if dc_id in dc_failures:
            row = tier_by_id[str(comp.get("index"))]
            row.tier = ComponentTier.OMITTED
            row.reason = TierReason.UNSUPPORTED
            row.detail = f"data collection {dc_id} not bundled: {dc_failures[dc_id]}"

    # Frozen tier: real endpoint bodies, default (empty) filter state.
    frozen: dict[str, FrozenPayload] = {}

    cards = [
        c
        for c in stored_metadata
        if c.get("component_type") == "card"
        and tier_by_id[str(c.get("index"))].tier is ComponentTier.LIVE
    ]
    if cards:
        try:
            for idx, payload in _freeze_cards(dashboard_oid, cards, user).items():
                frozen[idx] = FrozenPayload(kind="card", payload=payload)
        except Exception as exc:
            # Fallback payloads only — cards stay live off the bundled data.
            import logging

            logging.getLogger(__name__).warning("producer A: frozen card fallback failed: %s", exc)

    for comp in stored_metadata:
        component_id = str(comp.get("index"))
        row = tier_by_id[component_id]
        if row.tier is not ComponentTier.FROZEN:
            continue
        ctype = comp.get("component_type")
        try:
            if ctype == "table":
                frozen[component_id] = FrozenPayload(
                    kind="table",
                    payload=_freeze_table(dashboard_oid, component_id, user),
                )
            elif ctype == "figure":
                payload, sampled = _freeze_figure(comp)
                if sampled:
                    row.tier = ComponentTier.PARTIAL
                    row.reason = TierReason.MAX_POINTS
                    row.detail = (
                        "build-time sampling before filtering (FIGURE_MAX_POINTS); "
                        "the frozen figure shows a downsampled default view"
                    )
                frozen[component_id] = FrozenPayload(kind="figure", payload=payload)
            elif ctype == "advanced_viz":
                frozen[component_id] = FrozenPayload(
                    kind="advanced-viz-data",
                    payload=_freeze_advanced_viz(comp, user),
                )
            elif ctype == "multiqc":
                kind, payload = _freeze_multiqc(dashboard_oid, comp, user)
                frozen[component_id] = FrozenPayload(kind=kind, payload=payload)
            elif ctype == "map":
                frozen[component_id] = FrozenPayload(kind="map", payload=_freeze_map(comp, user))
        except Exception as exc:
            row.tier = ComponentTier.OMITTED
            row.reason = row.reason or TierReason.UNSUPPORTED
            row.detail = f"frozen payload could not be computed: {exc}"

    manifest = BundleManifest(
        mode=BundleMode.SINGLE_FILE,
        producer=Producer.EXPORT_FROM_INSTANCE,
        built_at=datetime.now(timezone.utc).isoformat(),
        depictio_version=_depictio_version(),
        dashboard=DashboardSection(
            id=str(dashboard_data["dashboard_id"]),
            title=dashboard_data.get("title") or "",
            doc=sanitize_dashboard_doc(dashboard_data),
        ),
        data_refs=data_refs,
        tiers={
            row.component_id: TierEntry(tier=row.tier, reason=row.reason, detail=row.detail)
            for row in tier_rows
        },
        frozen=frozen,
        inline_blobs=inline_blobs,
    )
    return ExportResult(manifest=manifest, tier_rows=tier_rows)


def export_static(
    dashboard_id: str,
    out_path: str | Path | None = None,
    mode: BundleMode | str = BundleMode.SINGLE_FILE,
    check: bool = False,
    user: Any = None,
) -> ExportResult:
    """End-to-end: dashboard in Mongo → self-contained HTML at ``out_path``.

    Args:
        dashboard_id: The dashboard's real Mongo ObjectId string.
        out_path: Where to write the bundle (ignored with ``check=True``;
            required otherwise).
        mode: Bundle delivery mode — phase 2 supports ``single-file`` only.
        check: Preflight — classify tiers (viewer permission), write nothing.
        user: A User-like object, an email string, or ``None`` (falls back to
            the instance's admin account). Building needs *owner* on the
            dashboard's project; ``--check`` needs viewer.
    """
    bundle_mode = BundleMode(mode) if not isinstance(mode, BundleMode) else mode
    if bundle_mode is not BundleMode.SINGLE_FILE:
        raise ProducerAError(f"phase 2 supports only single-file mode, got {bundle_mode.value!r}")

    export_user = resolve_user(user)

    if check:
        dashboard_data = _fetch_dashboard(dashboard_id)
        _check_permission(dashboard_data, export_user, "viewer")
        return ExportResult(
            manifest=None,
            tier_rows=classify_stored_metadata(dashboard_data.get("stored_metadata") or []),
        )

    if out_path is None:
        raise ProducerAError("out_path is required unless check=True")

    result = export_manifest(dashboard_id, export_user)
    assert result.manifest is not None
    html = render_bundle_html(result.manifest)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return result
