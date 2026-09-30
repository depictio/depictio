"""Backend endpoints for the advanced visualisation component family.

Thin endpoints:

* ``POST /advanced_viz/data`` — project a small column subset from a DC,
  apply the dashboard's filter metadata, return rows in a column-oriented
  dict shape the React renderers can consume directly. Heavy filtering /
  scanning re-uses ``load_deltatable_lite``; clustering/dim-reduction is
  handled at ingest by recipes (see depictio/recipes/lib/dimreduction.py),
  not here.

* ``GET /advanced_viz/kinds`` — small metadata payload the React builder
  uses to render the viz-kind picker (label + description + required
  roles), so the TS side never falls out of sync with the Pydantic schema.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any, NamedTuple

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.models.components.advanced_viz.sampling import SamplingPolicy
from depictio.models.components.advanced_viz.schemas import kind_descriptors
from depictio.models.models.base import PyObjectId

logger = logging.getLogger(__name__)

advanced_viz_endpoint_router = APIRouter()


def _assert_dc_access(data_collection_id: ObjectId, current_user) -> None:
    """Raise 404 unless ``current_user`` may read ``data_collection_id``.

    Mirrors ``deltatables_endpoints._build_permission_pipeline``: a project is
    visible if the caller owns it, is a viewer (explicitly or via ``"*"``), the
    project is public, or the caller is an admin (admins — including the
    anonymous-admin used in single-user mode — skip the membership filter as
    they wouldn't appear in the project's permissions list).

    Uses 404 (not 403) to avoid leaking existence of inaccessible DCs, matching
    the ``GET /deltatables/get/{dc_id}`` convention.
    """
    from depictio.api.v1.db import projects_collection

    match_clause: dict = {"workflows.data_collections._id": data_collection_id}
    if not getattr(current_user, "is_admin", False):
        match_clause["$or"] = [
            {"permissions.owners._id": current_user.id},
            {"permissions.viewers._id": current_user.id},
            {"permissions.viewers": "*"},
            {"is_public": True},
        ]
    if not projects_collection.find_one(match_clause, {"_id": 1}):
        raise HTTPException(
            status_code=404,
            detail="Data collection not found or access denied.",
        )


def _resolve_link_filters_for_dc(
    filters: list[dict],
    wf_id: str,
    target_dc_id: str,
    access_token: str | None,
    component_type: str,
) -> list[dict]:
    """Extend React-supplied filters via DC links, looking up project by wf_id.

    Mirrors ``dashboards_endpoints._resolve_link_filters`` but resolves the
    owning project from the workflow id (advanced-viz endpoints don't receive
    a dashboard id in their payload, so we can't fetch project_id off the
    dashboard doc).
    """
    if not filters or not target_dc_id or not access_token:
        return list(filters)

    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _resolve_link_filters,
    )

    try:
        wf_oid = ObjectId(str(wf_id))
    except Exception:
        return list(filters)

    project_doc = projects_collection.find_one({"workflows._id": wf_oid}, {"_id": 1})
    if not project_doc:
        return list(filters)

    return _resolve_link_filters(
        filters=filters,
        target_dc_id=str(target_dc_id),
        project_id=project_doc["_id"],
        access_token=access_token,
        component_type=component_type,
    )


def _apply_link_filters_to_payload(
    payload: dict,
    access_token: str | None,
    component_type: str,
) -> None:
    """Mutate ``payload["filter_metadata"]`` in place with link-resolved filters.

    Called by every advanced-viz compute dispatcher *before* the cache key is
    computed so that link-derived filters participate in the cache namespace
    (different filter state ⇒ different cache entry).
    """
    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    filters = payload.get("filter_metadata") or []
    if not wf_id or not dc_id or not filters:
        return

    resolved = _resolve_link_filters_for_dc(
        filters=filters,
        wf_id=str(wf_id),
        target_dc_id=str(dc_id),
        access_token=access_token,
        component_type=component_type,
    )
    if resolved is not filters:
        payload["filter_metadata"] = resolved


def _resolve_annotation_join(payload: dict) -> None:
    """Turn ``col_annotation_cols`` into a resolved ``annotation_join`` payload entry.

    The component names columns, not a data collection: the source is whichever
    enabled link *targets* this matrix and whose source DC is declared
    ``metatype: Metadata``. That gate is the whole safety story. An rnaseq
    expression matrix is the target of two links, one from the samplesheet and
    one from a derived per-sample stats table; only the first is metadata, so
    the join resolves without the dashboard naming anything.

    Ambiguity is never guessed. Zero or several surviving candidates leave the
    payload untouched (no strip, a log line saying which), and
    ``annotation_source_dc_tag`` is how a dashboard settles it.

    Resolution runs even when no column has been picked yet, because the
    viz-controls picker cannot offer what was never resolved. An empty ``cols``
    therefore still yields a join: the worker reads it to list the options and
    draws nothing. The cost of that is one Mongo read here and, in the worker, a
    load of a samplesheet-sized table.

    Called before ``_compute_cache_key`` so the resolved source and column list
    land in the cache namespace: changing the annotation columns has to miss the
    cache the same way changing ``normalize`` does.
    """
    cols = [str(c) for c in (payload.get("col_annotation_cols") or []) if c]
    wf_id, dc_id = payload.get("wf_id"), payload.get("dc_id")
    if not wf_id or not dc_id:
        return

    from depictio.api.v1.db import projects_collection

    try:
        wf_oid = ObjectId(str(wf_id))
    except Exception:
        return
    project = projects_collection.find_one({"workflows._id": wf_oid}, {"links": 1, "workflows": 1})
    if not project:
        return

    # DC id -> (tag, metatype, owning workflow id). The worker needs the owning
    # workflow to load the Delta table, and it is not on the link itself.
    dcs: dict[str, tuple[str, str | None, str]] = {}
    for wf in project.get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            dcs[str(dc.get("_id"))] = (
                str(dc.get("data_collection_tag") or ""),
                (dc.get("config") or {}).get("metatype"),
                str(wf.get("_id")),
            )

    wanted_tag = payload.get("annotation_source_dc_tag")
    candidates = []
    for link in project.get("links") or []:
        if not link.get("enabled", True) or str(link.get("target_dc_id")) != str(dc_id):
            continue
        src = dcs.get(str(link.get("source_dc_id")))
        if not src or str(src[1] or "").lower() != "metadata":
            continue
        if wanted_tag and src[0] != str(wanted_tag):
            continue
        candidates.append((link, src))

    if len(candidates) != 1:
        logger.info(
            "complex_heatmap annotation join skipped: %d metadata-linked candidates "
            "for dc_id=%s (requested cols=%s, source_tag=%s)",
            len(candidates),
            dc_id,
            cols,
            wanted_tag,
        )
        return

    link, (src_tag, _metatype, src_wf_id) = candidates[0]
    payload["annotation_join"] = {
        "source_dc_id": str(link["source_dc_id"]),
        "source_wf_id": src_wf_id,
        "source_column": str(link.get("source_column") or ""),
        "cols": cols,
    }
    logger.info(
        "complex_heatmap annotation join resolved: %s.%s -> dc_id=%s cols=%s",
        src_tag,
        link.get("source_column"),
        dc_id,
        cols,
    )


@advanced_viz_endpoint_router.get("/kinds")
def list_kinds(current_user=Depends(get_user_or_anonymous)) -> list[dict[str, Any]]:
    """The metadata payload the React builder populates its viz_kind picker from.

    Composed in ``models.components.advanced_viz.schemas`` so the offline
    snapshot Tool Studio ships (``depictio dev catalog kinds --json``) is the
    same payload this endpoint returns — its picker would otherwise be a
    lookalike built from a narrower map.
    """
    return kind_descriptors()


def _hash_sample(scan: Any, projection: list[str], total: int, cap: int) -> Any | None:
    """~``cap`` rows drawn uniformly from ``scan``, or None if the hash collapsed.

    The keep/drop decision hashes a struct of *all* projected columns rather than
    a single column: hashing one column would keep or drop every row sharing a
    value, which takes whole categories in or out (the same reasoning documented
    in ``services/figure/aggregate.py::_build_subsample``).

    That per-value behaviour also means the sample size is only *approximately*
    the cap, and on a coarse projection it degenerates badly. With few distinct
    value tuples the modulus is effectively all-or-nothing per tuple: the result
    is either near-empty or a large fraction of the table, and neither is a
    sample. Both are rejected here — an outcome outside a generous band around
    the cap means the hash did not split the frame, so the caller falls back to
    an ordinary load, the same bail-out ``_build_box`` makes.
    """
    import polars as pl

    stride = -(-total // cap)  # ceil
    frame = scan.filter(pl.struct(projection).hash(seed=0) % stride == 0).collect()
    # Integer strides undershoot, and hashing is only approximately uniform,
    # so the band is deliberately wide — it is here to catch a degenerate
    # split, not to police the sample size.
    if not (cap // 4 <= frame.height <= cap * 4):
        logger.info(
            "advanced_viz/data: hash sample returned %d rows against a target of %d "
            "— the projection's value tuples are too coarse to split on, "
            "loading without sampling",
            frame.height,
            cap,
        )
        return None
    return frame


def _tail_predicate(column: str, direction: str, threshold: float) -> Any:
    """Rows a ``tail`` kind must keep whole: the significant end of ``column``."""
    import polars as pl

    col = pl.col(column)
    if direction == "low":
        return col <= threshold
    if direction == "high":
        return col >= threshold
    return col.abs() >= threshold


def _resolve_tail(
    scan: Any,
    viz_kind: str | None,
    roles: dict[str, str],
    tail: dict | None,
    available: set[str],
) -> tuple[str, str, float] | None:
    """Settle ``(column, direction, threshold)`` for a ``tail`` reduction.

    The renderer knows all three — it draws the threshold lines — so a payload
    that carries ``tail`` is taken at its word, and the plot then keeps exactly
    the rows it would mark as hits. The fallback path exists for callers that
    send only ``viz_kind``: the role table says which column carries the tail
    and the settings supply a conventional cutoff.

    Returns None when the column can't be resolved or isn't on this DC, which
    drops the caller back to a uniform sample.
    """
    from depictio.api.v1.configs.config import settings
    from depictio.models.components.advanced_viz.sampling import (
        resolve_tail_direction,
        tail_role_for_kind,
    )

    if tail:
        column = tail.get("column")
        direction = tail.get("direction") or "both"
        try:
            # A malformed threshold must not raise here: the caller's handler
            # treats any exception as "reduction unavailable" and falls back to
            # an unbounded load, which is a worse answer than a uniform sample.
            threshold = float(tail.get("threshold"))
        except (TypeError, ValueError):
            threshold = None
        if column in available and threshold is not None and direction in ("low", "high", "both"):
            return str(column), str(direction), threshold
        logger.info("advanced_viz/data: ignoring unusable tail spec %s for kind %s", tail, viz_kind)

    spec = tail_role_for_kind(viz_kind)
    if spec is None:
        return None
    role, declared = spec
    column = roles.get(role)
    if not column or column not in available:
        logger.info(
            "advanced_viz/data: kind %s has no column bound to its %r role — sampling uniformly",
            viz_kind,
            role,
        )
        return None

    direction: str = declared
    if declared == "auto":
        # One extra reduction over a single column, and one Polars pushes into
        # the parquet statistics. See resolve_tail_direction for why the range
        # is enough to tell a p-value from its -log10.
        import polars as pl

        bounds = scan.select(
            pl.col(column).min().alias("lo"), pl.col(column).max().alias("hi")
        ).collect()
        direction = resolve_tail_direction(declared, bounds["lo"][0], bounds["hi"][0])

    threshold = (
        settings.performance.advanced_viz_tail_effect_threshold
        if direction == "both"
        else settings.performance.advanced_viz_tail_p_threshold
    )
    if direction == "high":
        # A -log10 column compares against the transformed cutoff, not the raw p.
        import math

        threshold = -math.log10(threshold) if threshold > 0 else 0.0
    return column, direction, float(threshold)


def _tail_sample(
    scan: Any, projection: list[str], total: int, cap: int, spec: tuple[str, str, float]
) -> Any | None:
    """Every row in the tail, plus a uniform sample of the dense middle.

    A volcano's content is its tail. Uniformly sampling 10 000 of 17 M rows keeps
    about six ten-thousandths of the significant features, so the plot that exists
    to show hits shows none of them — the reduction is not coarse, it answers a
    different question. Keeping the tail whole and striding only the undifferentiated
    blob in the middle costs the same single scan and preserves what is being looked at.

    The tail itself is sampled when it alone exceeds the cap: a filter matching
    millions of rows is a threshold that isn't selecting, and truncating it would
    silently drop whichever hits sorted last.
    """
    import polars as pl

    column, direction, threshold = spec
    # Nulls are not tail members and must not be dropped by the negation either:
    # `~(null <= t)` is null, which would filter them out of both branches.
    keep = _tail_predicate(column, direction, threshold).fill_null(False)
    middle = ~keep

    # One reduction, not a second count: the caller already knows ``total``, and
    # the strides below need only how much of it the tail claims.
    n_tail = int(scan.select(keep.sum().alias("n_tail")).collect()["n_tail"][0] or 0)

    hashed = pl.struct(projection).hash(seed=0)
    if n_tail >= cap:
        stride = -(-n_tail // cap)
        predicate = keep & (hashed % stride == 0)
    else:
        budget = max(1, cap - n_tail)
        stride = max(1, -(-(total - n_tail) // budget))
        predicate = keep | (middle & (hashed % stride == 0))

    frame = scan.filter(predicate).collect()
    if frame.height > cap * 4:
        # Same degenerate-hash failure the uniform path guards against, except
        # here the tail is a floor on the result, so only the upper bound means
        # anything.
        logger.info(
            "advanced_viz/data: tail reduction returned %d rows against a target of %d "
            "— falling back to a uniform sample",
            frame.height,
            cap,
        )
        return None
    logger.debug(
        "advanced_viz/data: tail on %s %s %g kept %d of %d rows (%d in the tail)",
        column,
        direction,
        threshold,
        frame.height,
        total,
        n_tail,
    )
    return frame


def _log_rank_sample(scan: Any, roles: dict[str, str], available: set[str], cap: int) -> Any | None:
    """Keep the log-spaced ranks of a rank-ordered curve (the ``log_rank`` policy).

    Rows are kept by rank value, not position, so every sample's curve keeps the
    same ranks and the budget is split across samples. Returns None when the rank
    column is unbound or absent, which drops the caller back to a uniform sample.
    """
    import polars as pl

    from depictio.models.components.advanced_viz.sampling import log_spaced_rank_thin

    rank_col = roles.get("rank")
    if not rank_col or rank_col not in available:
        return None
    sample_col = roles.get("sample")
    n_curves = 1
    if sample_col and sample_col in available:
        n_curves = max(1, int(scan.select(pl.col(sample_col).n_unique()).collect().item()))
    max_rank = scan.select(pl.col(rank_col).max()).collect().item()
    if max_rank is None:
        return None
    keep = [pos + 1 for pos in log_spaced_rank_thin(int(max_rank), max(2, cap // n_curves))]
    return scan.filter(pl.col(rank_col).is_in(keep)).collect()


def _load_reduced(
    wf_oid,
    dc_oid,
    filter_metadata: list[dict] | None,
    projection: list[str],
    init_data: dict[str, dict],
    cap: int,
    policy: SamplingPolicy = "hash",
    viz_kind: str | None = None,
    roles: dict[str, str] | None = None,
    tail: dict | None = None,
) -> tuple[Any | None, int | None, dict | None]:
    """Read the filtered frame, reduced the way ``policy`` allows.

    Returns ``(frame, total_rows, sampling)``, or ``(None, None, None)`` when the
    scan can't be built or a reduction degenerated — the caller then falls back to
    the row loader, exactly like every other ``open_deltatable_scan`` caller.
    ``sampling`` reports the policy that actually ran and whether the frame is the
    whole filtered set (``exact``).

    ``total_rows`` is always the count *before* reduction: it is the "of M" half
    of the renderer's badge, and measuring it after would make the badge agree
    with itself while disagreeing with the table.
    """
    import polars as pl

    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.deltatables_utils import open_deltatable_scan

    # Set when a kind that must not be sampled was sampled anyway, i.e. its
    # renderer's sums and rankings are now estimates. Distinct from `exact`,
    # which is merely "you did not get every row" — true of every volcano and
    # not something the volcano needs to warn about.
    degraded = False

    def _exact(frame, total, name):
        return frame, total, {"policy": name, "exact": True, "sampled": False, "degraded": False}

    def _reduced(frame, total, name, degraded=False):
        return frame, total, {"policy": name, "exact": False, "sampled": True, "degraded": degraded}

    try:
        scan = open_deltatable_scan(
            workflow_id=wf_oid,
            data_collection_id=str(dc_oid),
            metadata=filter_metadata or None,
            init_data=init_data,
            select_columns=projection,
        )
        if scan is None:
            return None, None, None

        total = int(scan.select(pl.len()).collect().item())

        if policy == "none":
            ceiling = settings.performance.advanced_viz_no_sample_max_rows
            if ceiling <= 0 or total <= ceiling:
                return _exact(scan.collect(), total, "none")
            # Serving it whole is what this kind needs and what this process
            # cannot afford. Sample, and say the aggregate is approximate rather
            # than let the renderer present an estimate as a total.
            logger.warning(
                "advanced_viz/data: %s rows exceeds advanced_viz_no_sample_max_rows=%s for "
                "kind %s, whose renderer aggregates client-side — sampling, so its values "
                "are estimates",
                total,
                ceiling,
                viz_kind,
            )
            degraded = True

        if total <= cap:
            # Nothing to reduce; collect the projected frame as-is.
            return _exact(scan.collect(), total, policy)

        if policy == "tail":
            spec = _resolve_tail(scan, viz_kind, roles or {}, tail, set(projection))
            frame = _tail_sample(scan, projection, total, cap, spec) if spec else None
            if frame is not None:
                return _reduced(frame, total, "tail")

        if policy == "log_rank":
            frame = _log_rank_sample(scan, roles or {}, set(projection), cap)
            if frame is not None:
                return _reduced(frame, total, "log_rank")

        if policy == "head":
            # The kind asked for a prefix rather than a sample: its renderer
            # draws one mark per row and stops being legible well before the
            # cap, so "the first N rows" is as faithful as a uniform subset and
            # is a sentence a reader can act on. Not `degraded`: nothing the
            # renderer reports is an estimate, there are simply fewer lines.
            return _reduced(scan.head(cap).collect(), total, "head")

        frame = _hash_sample(scan, projection, total, cap)
        if frame is None:
            if not degraded:
                return None, None, None
            # Every bail-out above lands the caller on an unbounded
            # ``load_deltatable_lite``, which is fine when the frame was merely
            # too big to draw and fatal when it was too big to hold — this
            # branch is only reached past the no-sample ceiling. A prefix is a
            # poor sample, but it is bounded and already flagged as an estimate,
            # which an OOM is not.
            logger.warning(
                "advanced_viz/data: no usable sample past the no-sample ceiling — "
                "returning the first %s rows for kind %s",
                cap,
                viz_kind,
            )
            return _reduced(scan.head(cap).collect(), total, "head", degraded=True)
        return _reduced(frame, total, "hash", degraded)
    except Exception as exc:
        logger.warning(
            "advanced_viz/data: scan-level reduction failed (%s) — falling back to the row loader",
            exc,
        )
        return None, None, None


@advanced_viz_endpoint_router.post("/data")
def fetch_advanced_viz_data(
    response: Response,
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Project requested columns from a DC, apply filter metadata, return rows.

    Input shape:
        {
          "wf_id": str,
          "dc_id": str,
          "columns": [str],          # column names to project
          "filter_metadata": [...],  # optional global filters
          "limit_rows": int | None,  # optional explicit cap (no sampling)
          "full_load": bool,         # optional; bypass sampling, raise scan cap
          "viz_kind": str | None,    # optional; selects the reduction policy
          "roles": {role: column},   # optional; role -> bound column name
          "tail": {                  # optional; the rows a tail kind must keep
            "column": str, "direction": "low"|"high"|"both", "threshold": float
          },
        }

    Output shape:
        {
          "columns": [str],          # echoed back for ordering
          "rows": {col: [values]},   # column-oriented (post-sampling)
          "row_count": int,          # returned rows (== len after sampling)
          "total_rows": int,         # rows before sampling (for the badge)
          "sampled": bool,           # True when the frame was downsampled
          "sampling": {              # `degraded`: a kind that must not be
            "policy": str,           # sampled was, so the renderer's own
            "exact": bool,           # aggregates are estimates
            "degraded": bool,
          },
          "filter_applied": bool,
        }

    How much of the frame a caller gets back depends on its ``viz_kind``: a
    marker cloud can be sampled uniformly, a renderer that sums or ranks the
    rows it is handed cannot be sampled at all, and a volcano needs its tail
    kept whole. The table lives in ``models/components/advanced_viz/sampling.py``.
    A payload with no ``viz_kind`` samples uniformly, which is what every caller
    got before that table existed.
    """
    import time as _time

    _t0 = _time.perf_counter()
    wf_id = payload.get("wf_id")
    dc_id = payload.get("dc_id")
    columns = payload.get("columns") or []
    filter_metadata = payload.get("filter_metadata") or []
    limit_rows = payload.get("limit_rows")
    full_load = bool(payload.get("full_load", False))
    viz_kind = payload.get("viz_kind")
    roles = payload.get("roles") or {}
    tail = payload.get("tail") or None

    if not wf_id or not dc_id:
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")
    if not columns or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="columns must be a non-empty list")

    # Extend the React-supplied filters with any link-resolved filters that
    # target this DC. Without this, a filter set on `metadata` (column `ID`)
    # would silently no-op against a canonical advanced-viz DC keyed on
    # `sample_id`, leaving the plot unfiltered.
    filter_metadata = _resolve_link_filters_for_dc(
        filters=filter_metadata,
        wf_id=str(wf_id),
        target_dc_id=str(dc_id),
        access_token=access_token,
        component_type="advanced_viz/data",
    )

    # Row handling — three cases:
    #   * explicit ``limit_rows`` in the payload → honour it, no sampling (callers
    #     like the ComplexHeatmap preview ask for a specific bound).
    #   * ``full_load`` → raise the scan cap to the figure full-load ceiling and
    #     skip sampling (the user opted into the whole frame via Load-All).
    #   * default → a scan-level reduction down to ``figure_max_points`` so
    #     plotly isn't handed a huge client-side frame, of whichever shape the
    #     kind's renderer can survive (uniform / tail-preserving / none).
    #
    # The default path used to set ``limit_rows = 100_000`` and then
    # ``df.sample()`` the result. That is a *prefix*, not a sample: Polars pushes
    # the limit into the scan, and Delta scan order is ingest order, so "the
    # first 100k rows" is the first few samples (or, on a variant table sorted by
    # position, chromosome 1 alone). Sampling that prefix afterwards dressed a
    # biased subset up as a random one. The scan-level hash sample below is drawn
    # across the whole filtered frame instead — the same mechanism the box and
    # violin figure paths use (``services/figure/aggregate.py``).
    from depictio.api.v1.configs.config import settings
    from depictio.models.components.advanced_viz.sampling import policy_for_kind

    display_cap = settings.performance.figure_max_points
    # None = no scan-level reduction attempted (explicit cap / full load).
    policy: SamplingPolicy | None = None
    if limit_rows is not None:
        limit_rows = int(limit_rows)
    elif full_load:
        limit_rows = settings.performance.figure_max_load_rows
    else:
        limit_rows = None
        if display_cap > 0:
            policy = policy_for_kind(viz_kind)

    try:
        wf_oid = ObjectId(str(wf_id))
        dc_oid = ObjectId(str(dc_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wf_id/dc_id: {exc}")

    # Permission gate: get_user_or_anonymous yields an anonymous (possibly
    # admin-in-public-mode) user, so without this any caller could load any
    # DC's data by supplying its IDs. Mirror the deltatables access check.
    _assert_dc_access(dc_oid, current_user)

    from depictio.api.v1.db import deltatables_collection
    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    # Resolve delta-table location directly from MongoDB and hand it to
    # load_deltatable_lite via init_data so it does NOT take the legacy
    # HTTP fallback (`GET /deltatables/get/{dc_id}`) — that path needs an
    # auth token we don't carry across worker boundaries and 401s here.
    # Mirrors the pattern used by celery_tasks.build_figure_preview.
    init_data: dict[str, dict] = {}
    dt_doc = deltatables_collection.find_one({"data_collection_id": dc_oid})
    if dt_doc and dt_doc.get("delta_table_location"):
        init_data[str(dc_id)] = {
            "delta_location": dt_doc["delta_table_location"],
            "dc_type": "table",
            "size_bytes": (dt_doc.get("flexible_metadata") or {}).get("deltatable_size_bytes", 0),
        }
    else:
        logger.warning("advanced_viz/data: no materialised delta table for dc_id=%s", dc_id)
        raise HTTPException(
            status_code=404,
            detail="Data collection has no materialised Delta table yet.",
        )

    # Merge filter columns into the projection so the scan-level column
    # projection doesn't prune the columns the filters need. Without this,
    # `select_columns=[feature_id, position, category]` would drop `GENE`
    # before `apply_runtime_filters` runs, then the filter on `GENE` would
    # silently no-op because the column isn't present on the projected df.
    #
    # Schema-guarded: filters from link-resolved cross-DC filtering may name
    # columns that don't exist on this DC (e.g. a `habitat` filter coming via
    # metadata applied to sankey_canonical, which only has `Habitat` row+col).
    # Reading the lazy schema once lets us (a) drop the unusable filter from
    # the metadata list and (b) avoid passing missing columns to .select(),
    # which would otherwise fail at collect() with ColumnNotFoundError.
    try:
        from depictio.api.v1.deltatables_utils import _create_delta_scan

        _scan = _create_delta_scan(
            init_data[str(dc_id)]["delta_location"],
            init_data[str(dc_id)].get("dc_type"),
        )
        available_cols = set(_scan.collect_schema().names())
    except Exception as _exc:
        logger.warning("advanced_viz/data: schema introspection failed: %s", _exc)
        available_cols = None

    filter_cols: set[str] = set()
    if filter_metadata:
        kept_filters: list[dict] = []
        for f in filter_metadata:
            nested = f.get("metadata") if isinstance(f, dict) else None
            col = (f.get("column_name") if isinstance(f, dict) else None) or (
                (nested or {}).get("column_name") if nested else None
            )
            # Drop filters that don't carry a column at all — link resolution
            # can synthesise filter dicts where target_column resolves to None
            # (source_filter has no column_name and the link has no target_field
            # override), which would later crash _generate_filter_hash's sort
            # with `'<' not supported between NoneType and str`.
            if not col:
                # Always a resolver bug upstream (filter_links can produce a
                # link_filter with target_column=None when both the resolved
                # value and link_config.target_field are absent). Log at
                # WARNING so it shows up in ops aggregators.
                logger.warning(
                    "advanced_viz/data: dropping filter with no column_name (dc_id=%s)",
                    dc_id,
                )
                continue
            if available_cols is not None and col not in available_cols:
                logger.info(
                    "advanced_viz/data: dropping cross-DC filter on column %r — not in DC %s",
                    col,
                    dc_id,
                )
                continue
            filter_cols.add(col)
            kept_filters.append(f)
        filter_metadata = kept_filters

    projection = list(dict.fromkeys([*columns, *filter_cols]))
    if available_cols is not None:
        projection = [c for c in projection if c in available_cols]

    _t_load = _time.perf_counter()
    total_rows: int | None = None
    sampling: dict | None = None
    df = None
    if policy is not None:
        df, total_rows, sampling = _load_reduced(
            wf_oid,
            dc_oid,
            filter_metadata,
            projection,
            init_data,
            display_cap,
            policy=policy,
            viz_kind=viz_kind,
            roles=roles,
            tail=tail,
        )
    if df is None:
        try:
            df = load_deltatable_lite(
                workflow_id=wf_oid,
                data_collection_id=str(dc_oid),
                metadata=filter_metadata or None,
                limit_rows=limit_rows,
                select_columns=projection,
                init_data=init_data,
            )
        except Exception as exc:
            logger.warning(
                "advanced_viz/data: load_deltatable_lite failed for dc_id=%s: %s",
                dc_id,
                exc,
                exc_info=True,
            )
            # A data problem is not a server fault. The missing-Delta-table case
            # above already answers 502-style failures with a typed 404; do the
            # same here so the renderer can say what went wrong instead of
            # surfacing a bare 500.
            raise HTTPException(
                status_code=422,
                detail=f"Could not read this data collection: {exc}",
            ) from exc
    _load_ms = int((_time.perf_counter() - _t_load) * 1000)

    # ``total_rows`` must be the count *before* any reduction — it is what the
    # renderer's badge reports as the "of M" half. The sampling path measures it
    # with a `pl.len()` pushdown; the other paths have the whole frame in hand.
    if total_rows is None:
        total_rows = int(df.height)
    if sampling is None:
        # The row-loader path: either an explicit cap, a full load, or a
        # reduction that bailed out. A cap the frame actually reached is a
        # truncation, and the renderer is entitled to know it isn't looking at
        # everything.
        truncated = limit_rows is not None and df.height >= limit_rows
        sampling = {
            "policy": "explicit" if limit_rows is not None else "full",
            "exact": not truncated,
            "sampled": False,
            "degraded": False,
        }

    # Drop any requested columns that didn't survive projection (e.g. user
    # bound an optional column the recipe didn't emit). The renderer
    # decides what to do with missing optional columns.
    _t_build = _time.perf_counter()
    present = [c for c in columns if c in df.columns]

    # Round float columns before serialising. This endpoint's cost is dominated
    # by transport, not compute — the benchmark shows ~50 ms of server time
    # against ~500 ms of wall — and full float64 repr is a large share of that
    # JSON: "0.30000000000000004" is 19 bytes to say 0.3. Six significant digits
    # is far below what any plot can resolve, and the reduction compounds with
    # gzip because the shortened values repeat.
    import polars as pl

    float_cols = [c for c in present if df.schema[c] in (pl.Float32, pl.Float64)]
    if float_cols:
        df = df.with_columns([pl.col(c).round_sig_figs(6) for c in float_cols])

    result = {
        "columns": present,
        "rows": {c: df.get_column(c).to_list() for c in present},
        "row_count": int(df.height),
        "total_rows": total_rows,
        "sampled": bool(sampling["sampled"]),
        "sampling": {
            "policy": sampling["policy"],
            "exact": bool(sampling["exact"]),
            "degraded": bool(sampling["degraded"]),
        },
        "filter_applied": bool(filter_metadata),
    }
    # Additive telemetry for the benchmark harness (clients ignore unknown
    # headers). load = Delta read; build = column materialisation.
    response.headers["X-Load-Ms"] = str(_load_ms)
    response.headers["X-Build-Ms"] = str(int((_time.perf_counter() - _t_build) * 1000))
    response.headers["X-Rows-Loaded"] = str(total_rows)
    response.headers["X-Rows-Displayed"] = str(int(df.height))
    response.headers["X-Frame-Bytes"] = str(int(df.estimated_size()))
    response.headers["X-Aggregated"] = "0"
    response.headers["X-Sampling-Policy"] = str(sampling["policy"])
    response.headers["X-Total-Ms"] = f"{(_time.perf_counter() - _t0) * 1000:.1f}"
    return result


_CACHE_KEY_VERSION = "v3"

# A failed computation is retried once its entry is older than this. The short
# backoff stops a tile that re-dispatches on every render from hot-looping on a
# persistent error, while a fixed cause (data re-ingested, code fixed) no longer
# replays the stale error forever.
_FAILED_RETRY_AFTER_S = 60


def _find_reusable_cache_entry(cache, cache_key: str) -> dict | None:
    """Return the cached compute doc for ``cache_key``, or None on a miss.

    ``done`` and ``pending`` entries are reused as-is. A ``failed`` entry is
    never treated as a permanent answer: once it is older than
    ``_FAILED_RETRY_AFTER_S`` it is deleted and the caller re-enqueues the
    computation. A younger failed entry is still returned so rapid re-renders
    see the error instead of spawning a task per render.
    """
    from datetime import datetime, timezone

    existing = cache.find_one({"_id": cache_key})
    if not existing or existing.get("status") != "failed":
        return existing
    stamp = existing.get("completed_at") or existing.get("created_at")
    if isinstance(stamp, datetime):
        if stamp.tzinfo is None:  # pymongo returns naive UTC by default
            stamp = stamp.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - stamp).total_seconds()
        if age_s < _FAILED_RETRY_AFTER_S:
            return existing
    # Only drop it if it is still the failed doc we read (a concurrent retry may
    # already have replaced it with a fresh pending entry).
    cache.delete_one({"_id": cache_key, "status": "failed"})
    return None


def _compute_cache_key(payload: dict, user_id) -> str:
    """Stable key for the compute_results cache.

    Hashes the full payload sort-stably so every tunable (embedding params,
    UpSet sort_by/min_size/colour_by, ComplexHeatmap normalize/cluster_*,
    filter_metadata) participates in the key. Bump ``_CACHE_KEY_VERSION``
    when the task contract changes in a way that invalidates prior entries
    (e.g. fixing a bug that produced stuck "pending" docs).

    ``user_id`` is bound into the hashed blob so that one user can never read
    (or pending-collide with) another user's cached result by guessing the
    job_id — the key is derived purely from server-side inputs, so the job_id
    returned to user A is not reproducible by user B even with an identical
    payload. (Anonymous users sharing one account still share entries among
    themselves, which is acceptable; real users are isolated.)
    """
    import hashlib
    import json as _json

    blob = _json.dumps(
        {"_v": _CACHE_KEY_VERSION, "u": str(user_id), "p": payload},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _assert_job_owner(doc: dict, current_user) -> None:
    """Raise 404 unless ``current_user`` owns the cached compute ``doc``.

    Defence-in-depth companion to the user-bound cache key: even if a job_id
    leaks (logs, network capture), only its owner — or an admin — can poll it.
    The cache key already binds ``user_id`` so keys are not cross-derivable;
    this additionally blocks reads of a *known* foreign job_id. Docs written
    before user binding lack ``user_id`` and are treated as non-owned for
    non-admins (their keys are no longer regenerable anyway).
    """
    if getattr(current_user, "is_admin", False):
        return
    if doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")


@advanced_viz_endpoint_router.post("/compute_embedding")
def dispatch_compute_embedding(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch a clustering / dim-reduction Celery task.

    Cache lookup first — if an identical computation already finished we
    return its result immediately. Otherwise enqueue the task and return a
    ``job_id`` the frontend can poll via ``GET /compute_embedding/{job_id}``.
    """
    import time
    from datetime import datetime, timezone

    from depictio.api.v1.celery_tasks import compute_embedding as compute_task
    from depictio.api.v1.db import db

    method = (payload.get("method") or "").lower()
    if method not in {"pca", "umap", "tsne", "pcoa"}:
        raise HTTPException(status_code=400, detail=f"Unsupported method: {method!r}")
    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    _apply_link_filters_to_payload(payload, access_token, "embedding")

    cache = db["compute_results"]
    cache_key = _compute_cache_key(payload, current_user.id)
    existing = _find_reusable_cache_entry(cache, cache_key)

    # Cache hit (done or pending).
    if existing:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    # Miss → mark pending, dispatch task, return job_id.
    # Race-safe: handle a concurrent dispatch with the same cache_key by
    # falling through to the cache-hit return path.
    from pymongo.errors import DuplicateKeyError

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": method,
                "user_id": str(current_user.id),
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": method,
                    "params": payload.get("params") or {},
                },
            }
        )
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    # Dispatch via apply_async with a callback that updates the cache doc.
    # We use a lightweight inline wrapper so Celery's success / failure
    # handlers don't need a separate task.
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_embedding dispatched: method=%s cache_key=%s task_id=%s (%.2fs to enqueue)",
        method,
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_embedding/{job_id}")
def poll_compute_embedding(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll cache for a previously-dispatched embedding compute.

    Returns ``{status: 'done', result: {...}}`` when ready,
    ``{status: 'pending'}`` while running, or
    ``{status: 'failed', error: '...'}`` on error.
    """
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app
    from depictio.api.v1.db import db

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_owner(doc, current_user)

    # If already terminal (done/failed), short-circuit.
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }

    # Otherwise check Celery's status for the underlying task and update
    # the cache doc if it has completed (Celery's backend isn't necessarily
    # the same Mongo collection so we mirror status here for the frontend).
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}

    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
        # Failed.
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"job_id": job_id, "status": "failed", "error": err}

    return {"job_id": job_id, "status": "pending"}


@advanced_viz_endpoint_router.post("/compute_complex_heatmap")
def dispatch_compute_complex_heatmap(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch a ComplexHeatmap Celery task. Same dispatch + poll +
    cache contract as ``compute_embedding`` — different task name and
    namespace under the same ``compute_results`` collection."""
    import time
    from datetime import datetime, timezone

    _apply_link_filters_to_payload(payload, access_token, "complex_heatmap")
    _resolve_annotation_join(payload)

    from depictio.api.v1.celery_tasks import compute_complex_heatmap as compute_task
    from depictio.api.v1.db import db

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    # Reuse the same cache_key helper — its blob already includes a
    # `method`-style discriminator via the viz-specific payload keys
    # (value_columns, normalize, cluster_method...). We add a fixed
    # method marker to namespace these from embedding entries.
    payload_for_key = dict(payload)
    payload_for_key.setdefault("method", "complex_heatmap")
    cache_key = _compute_cache_key(payload_for_key, current_user.id)
    existing = _find_reusable_cache_entry(cache, cache_key)
    if existing:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    # Race-safe insert: two concurrent dispatches with the same key (e.g.
    # React StrictMode double-mount in dev) both pass the find_one check.
    # Use upsert + insert-only path to dedupe — second caller falls into
    # the find_one branch.
    from pymongo.errors import DuplicateKeyError

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": "complex_heatmap",
                "user_id": str(current_user.id),
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": "complex_heatmap",
                },
            }
        )
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_complex_heatmap dispatched: cache_key=%s task_id=%s (%.2fs to enqueue)",
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_complex_heatmap/{job_id}")
def poll_compute_complex_heatmap(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched ComplexHeatmap compute. Returns
    {status: 'done', result: {figure, row_count, col_count, ...}} or
    {status: 'pending'} / {status: 'failed', error: '...'}."""
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app
    from depictio.api.v1.db import db

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_owner(doc, current_user)
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}
    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"job_id": job_id, "status": "failed", "error": err}
    return {"job_id": job_id, "status": "pending"}


@advanced_viz_endpoint_router.post("/compute_upset")
def dispatch_compute_upset(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch an UpSet-plot Celery task. Same dispatch + poll + cache
    contract as ``compute_complex_heatmap`` (cache namespace = upset_plot)."""
    import time
    from datetime import datetime, timezone

    _apply_link_filters_to_payload(payload, access_token, "upset")

    from depictio.api.v1.celery_tasks import compute_upset as compute_task
    from depictio.api.v1.db import db

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    payload_for_key = dict(payload)
    payload_for_key.setdefault("method", "upset_plot")
    cache_key = _compute_cache_key(payload_for_key, current_user.id)
    existing = _find_reusable_cache_entry(cache, cache_key)
    if existing:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    from pymongo.errors import DuplicateKeyError

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": "upset_plot",
                "user_id": str(current_user.id),
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": "upset_plot",
                },
            }
        )
    except DuplicateKeyError:
        existing = cache.find_one({"_id": cache_key}) or {}
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }
    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "compute_upset dispatched: cache_key=%s task_id=%s (%.2fs)",
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


@advanced_viz_endpoint_router.get("/compute_upset/{job_id}")
def poll_compute_upset(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched UpSet compute."""
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app
    from depictio.api.v1.db import db

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_owner(doc, current_user)
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}
    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"job_id": job_id, "status": "failed", "error": err}
    return {"job_id": job_id, "status": "pending"}


def _dispatch_compute(
    payload: dict,
    method_name: str,
    compute_task,
    current_user,
) -> dict[str, Any]:
    """Shared dispatch helper for Celery-backed advanced viz endpoints.

    Encapsulates the cache-key lookup + race-safe insert + apply_async +
    cache-id mirror pattern used by every compute_*  endpoint here. Kept
    private to this module — the endpoints themselves stay thin wrappers
    so they remain discoverable via FastAPI's normal route registration.
    """
    import time
    from datetime import datetime, timezone

    from pymongo.errors import DuplicateKeyError

    from depictio.api.v1.db import db

    if not payload.get("wf_id") or not payload.get("dc_id"):
        raise HTTPException(status_code=400, detail="wf_id and dc_id are required")

    cache = db["compute_results"]
    cache_key = _compute_cache_key(
        {**payload, "method": payload.get("method", method_name)}, current_user.id
    )

    def _from_cache(existing: dict) -> dict[str, Any]:
        return {
            "job_id": cache_key,
            "status": existing.get("status", "pending"),
            "result": existing.get("result"),
            "error": existing.get("error"),
            "from_cache": True,
        }

    existing = _find_reusable_cache_entry(cache, cache_key)
    if existing:
        return _from_cache(existing)

    try:
        cache.insert_one(
            {
                "_id": cache_key,
                "status": "pending",
                "method": method_name,
                "user_id": str(current_user.id),
                "created_at": datetime.now(timezone.utc),
                "payload": {
                    "wf_id": str(payload["wf_id"]),
                    "dc_id": str(payload["dc_id"]),
                    "method": method_name,
                },
            }
        )
    except DuplicateKeyError:
        return _from_cache(cache.find_one({"_id": cache_key}) or {})

    started = time.monotonic()
    async_result = compute_task.apply_async(args=[payload])
    cache.update_one({"_id": cache_key}, {"$set": {"celery_task_id": async_result.id}})
    logger.info(
        "%s dispatched: cache_key=%s task_id=%s (%.2fs)",
        method_name,
        cache_key,
        async_result.id,
        time.monotonic() - started,
    )
    return {"job_id": cache_key, "status": "pending", "from_cache": False}


def _poll_compute(job_id: str, current_user) -> dict[str, Any]:
    """Shared poll helper — mirror of the per-endpoint poll body."""
    from datetime import datetime, timezone

    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app
    from depictio.api.v1.db import db

    cache = db["compute_results"]
    doc = cache.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_owner(doc, current_user)
    if doc.get("status") in ("done", "failed"):
        return {
            "job_id": job_id,
            "status": doc["status"],
            "result": doc.get("result"),
            "error": doc.get("error"),
        }
    task_id = doc.get("celery_task_id")
    if not task_id:
        return {"job_id": job_id, "status": doc.get("status", "pending")}
    async_result = AsyncResult(task_id, app=celery_app)
    if async_result.ready():
        if async_result.successful():
            result = async_result.result
            cache.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "result": result,
                        "completed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {"job_id": job_id, "status": "done", "result": result}
        err = str(async_result.result)[:500]
        cache.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "failed",
                    "error": err,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"job_id": job_id, "status": "failed", "error": err}
    return {"job_id": job_id, "status": "pending"}


@advanced_viz_endpoint_router.post("/compute_coverage_track")
def dispatch_compute_coverage_track(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch a coverage-track aggregation Celery task."""
    from depictio.api.v1.celery_tasks import compute_coverage_track as compute_task

    _apply_link_filters_to_payload(payload, access_token, "coverage_track")
    return _dispatch_compute(payload, "coverage_track", compute_task, current_user)


@advanced_viz_endpoint_router.get("/compute_coverage_track/{job_id}")
def poll_compute_coverage_track(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched coverage-track compute."""
    return _poll_compute(job_id, current_user)


@advanced_viz_endpoint_router.post("/compute_contact_map")
def dispatch_compute_contact_map(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch one region of a contact matrix, at one resolution.

    Region and resolution are part of the payload, so they are part of the
    cache key: zooming in dispatches a new job and zooming back out lands on
    the one already computed. `resolution: null` lets the server pick the level
    whose bins-per-pixel is closest to the target for the span the client says
    it is showing.
    """
    from depictio.api.v1.celery_tasks import compute_contact_map as compute_task

    _apply_link_filters_to_payload(payload, access_token, "contact_map")
    return _dispatch_compute(payload, "contact_map", compute_task, current_user)


@advanced_viz_endpoint_router.get("/compute_contact_map/{job_id}")
def poll_compute_contact_map(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched contact-map window."""
    return _poll_compute(job_id, current_user)


@advanced_viz_endpoint_router.post("/compute_sankey")
def dispatch_compute_sankey(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch a Sankey / categorical-flow Celery task."""
    from depictio.api.v1.celery_tasks import compute_sankey as compute_task

    _apply_link_filters_to_payload(payload, access_token, "sankey")
    return _dispatch_compute(payload, "sankey", compute_task, current_user)


@advanced_viz_endpoint_router.get("/compute_sankey/{job_id}")
def poll_compute_sankey(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched Sankey compute."""
    return _poll_compute(job_id, current_user)


def _group_selector(raw: Any, side: str) -> dict[str, Any]:
    """Validate one arm of a group comparison, or raise 400.

    A selector is a column plus the values it captured, which is exactly what
    a saved selection group is (``GroupRenderDef``) and what a single value of
    the config's ``group_col`` collapses to. Normalising both into one shape
    here is what lets the worker treat "two lassos" and "two labels" the same.
    """
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail=f"group_{side} must be an object")
    column = str(raw.get("column") or "").strip()
    values = [str(v) for v in (raw.get("values") or []) if v is not None]
    if not column or not values:
        raise HTTPException(
            status_code=400,
            detail=f"group_{side} needs a column and at least one value",
        )
    return {
        "label": str(raw.get("label") or f"Group {side.upper()}"),
        "column": column,
        "values": values,
    }


@advanced_viz_endpoint_router.post("/compute_group_compare")
def dispatch_compute_group_compare(
    payload: dict = Body(...),
    current_user=Depends(get_user_or_anonymous),
    access_token: str | None = Depends(oauth2_scheme_optional),
) -> dict[str, Any]:
    """Dispatch a two-group differential test as a Celery task.

    Same dispatch + poll + cache contract as ``compute_upset``: the cache key
    hashes the whole payload, so the two group definitions and every statistic
    tunable pick their own cache entry, and re-running the identical
    comparison is free.
    """
    from depictio.api.v1.celery_tasks import compute_group_compare as compute_task

    payload["group_a"] = _group_selector(payload.get("group_a"), "a")
    payload["group_b"] = _group_selector(payload.get("group_b"), "b")
    _apply_link_filters_to_payload(payload, access_token, "group_compare")
    return _dispatch_compute(payload, "group_compare", compute_task, current_user)


@advanced_viz_endpoint_router.get("/compute_group_compare/{job_id}")
def poll_compute_group_compare(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Poll a previously-dispatched group comparison."""
    return _poll_compute(job_id, current_user)


# The repo is bind-mounted at /app in the backend container, so any path holding
# a `/depictio/projects/` segment has a container twin at the same suffix.
_CONTAINER_REPO_ROOT = "/app"
_REPO_PROJECTS_MARKER = "/depictio/projects/"


def _container_repo_path(path: str) -> str | None:
    """Map a host repo path onto its in-container twin, or None if not applicable.

    Returns None when the path carries no ``/depictio/projects/`` segment or is
    already the container path, so the caller only ever gets a genuinely new
    candidate to try. Splits on the *last* occurrence, so a checkout that itself
    sits under a directory of that name still resolves.
    """
    idx = path.rfind(_REPO_PROJECTS_MARKER)
    if idx == -1:
        return None
    rewritten = f"{_CONTAINER_REPO_ROOT}{path[idx:]}"
    return rewritten if rewritten != path else None


def _phylogeny_s3_client():
    """boto3 client for the backend's bucket, shared by both Newick reads below.

    Every Newick request tries S3 first, so an unreachable endpoint must fail
    fast and fall through to the stored paths instead of waiting on retries.
    """
    import boto3
    from botocore.config import Config

    from depictio.api.v1.configs.config import settings

    return boto3.client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.aws_access_key_id,
        aws_secret_access_key=settings.s3.aws_secret_access_key,
        verify=settings.s3.verify_tls,
        config=Config(connect_timeout=3, retries={"total_max_attempts": 2}),
    )


@advanced_viz_endpoint_router.get(
    "/phylogeny/{data_collection_id}/newick", response_class=PlainTextResponse
)
def get_phylogeny_newick(
    data_collection_id: PyObjectId,
    current_user=Depends(get_user_or_anonymous),
) -> str:
    """Return the raw Newick string for a phylogeny DC.

    First tries the copy the CLI uploads at ingest, at
    ``s3://<bucket>/phylogeny/<dc_id>/tree.nwk``: it is readable by any backend,
    whichever machine ran the CLI. Any miss there falls through to the stored
    paths below, which is what reference seeds and older ingests rely on.

    Those stored paths are tried in three ways: (1) prefer the file registered
    by the CLI scan in ``files_collection``; (2) for reference datasets
    (seeded via db_init, never CLI-scanned), traverse the project document
    to find the matching DC under ``workflows[].data_collections[]`` and
    read its ``config.scan.scan_parameters.filename``. DCs are stored
    embedded in the project — there is no top-level ``data_collections``
    document for them — so we can't ``find_one({"_id": dc_oid})`` directly.
    (3) as a last resort, each stored path rewritten onto the container's
    ``/app`` bind mount, which is what makes a host-run CLI ingest readable
    from the backend container.

    Returns local file contents directly; stream S3-hosted trees via boto3.
    """
    from depictio.api.v1.db import files_collection, projects_collection

    try:
        dc_oid = ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dc_id: {exc}") from exc

    # Same vulnerability class as /advanced_viz/data: caller-supplied dc_id
    # returning raw data — gate on project-level access before any file read.
    _assert_dc_access(dc_oid, current_user)

    # Ingest-time copy (CLI `process_phylogeny_data_collection`); a miss falls through.
    from depictio.api.v1.configs.config import settings
    from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key

    s3_key = phylogeny_s3_key(str(dc_oid))
    try:
        obj = _phylogeny_s3_client().get_object(Bucket=settings.s3.bucket, Key=s3_key)
        return obj["Body"].read().decode("utf-8")
    except Exception as exc:
        logger.debug(
            "phylogeny newick not read from s3://%s/%s (%s); trying stored paths",
            settings.s3.bucket,
            s3_key,
            exc,
        )

    # Build a list of candidate paths and try each. The CLI scan records the
    # *host* path it saw when the user ran depictio-cli on their laptop
    # (``/Users/.../depictio/...``); the backend in Docker can't read that.
    # The project's scan_parameters.filename is the canonical container path
    # (``/app/depictio/...``), so we prefer files_collection when its path is
    # readable and fall through to the project doc otherwise.
    candidates: list[str] = []

    file_doc = files_collection.find_one({"data_collection_id": dc_oid})
    if file_doc and file_doc.get("file_location"):
        candidates.append(str(file_doc["file_location"]))

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
    )
    if project_doc:
        for wf in project_doc.get("workflows", []) or []:
            for dc in wf.get("data_collections", []) or []:
                dc_id_in_doc = dc.get("_id") or dc.get("id")
                if dc_id_in_doc != dc_oid:
                    continue
                scan_cfg = ((dc.get("config") or {}).get("scan") or {}).get("scan_parameters") or {}
                fname = scan_cfg.get("filename")
                if fname and fname not in candidates:
                    candidates.append(str(fname))

    # Dev-loop fallback: the CLI run on the host stores an absolute host path
    # (``/Users/<me>/Gits/.../depictio/projects/...``) that doesn't exist in the
    # container, and the project doc holds that same host path because the same
    # host CLI wrote it. The repo is bind-mounted at ``/app``, so the identical
    # ``depictio/projects/...`` suffix is readable there. Appended last, after
    # every stored path, so a deploy whose paths resolve normally never sees it.
    rewritten = [_container_repo_path(c) for c in candidates if not c.startswith("s3://")]
    host_rewrites = {c for c in rewritten if c and c not in candidates}
    candidates.extend(sorted(host_rewrites))

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="Phylogeny file not registered (no entry in files_collection and no scan_parameters.filename in the project's DC config).",
        )

    # Resolve to the first existing local path (or any s3:// URL — those go
    # through boto3 below). Records the chosen path for the read block.
    file_path: str | None = None
    for c in candidates:
        if c.startswith("s3://"):
            file_path = c
            break
        try:
            if os.path.exists(c):
                file_path = c
                break
        except OSError:
            continue

    if file_path and file_path in host_rewrites:
        logger.info(
            "phylogeny newick resolved through the %s fallback: the stored path(s) %s are "
            "not readable by the backend (host CLI ingest against a containerised backend), "
            "reading %s instead",
            _CONTAINER_REPO_ROOT,
            [c for c in candidates if c not in host_rewrites],
            file_path,
        )

    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=(
                "Phylogeny file location resolved but none of the candidate paths "
                f"exist on the backend filesystem: {candidates}"
            ),
        )

    try:
        if file_path.startswith("s3://"):
            s3 = _phylogeny_s3_client()
            _, _, rest = file_path.partition("s3://")
            bucket, _, key = rest.partition("/")
            obj = s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8")
        with open(file_path) as fh:
            return fh.read()
    except FileNotFoundError as exc:
        # Don't leak server-side paths in the response — log them instead.
        logger.warning("phylogeny file not found at %s", file_path)
        raise HTTPException(status_code=404, detail="Phylogeny file not found") from exc
    except Exception as exc:
        logger.warning("phylogeny newick read failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read phylogeny") from exc


# ---------------------------------------------------------------------------
# Bioimage store serving (OME-Zarr, SpatialData images, OME-TIFF files)
# ---------------------------------------------------------------------------
#
# A zarr reader in the browser fetches one small object per request (``.zattrs``,
# ``.zarray`` or a v3 ``zarr.json``, then many chunks, or byte ranges of a v3
# shard), and an OME-TIFF reader one byte range per tile, so both the access
# check and the per-DC store lookup are cached briefly instead of hitting Mongo
# on every read.
#
# Where a store is read from (see ``data_collections_types.bioimage``):
# * key-tree formats (ome-zarr, spatialdata): the CLI upload under
#   ``bioimage_s3_prefix``, then the registered store on disk, where a
#   SpatialData store is read at ``<store>/<image_path>``;
# * tiff (labels masks): the OME-Zarr labels image the CLI converted the mask
#   to, under ``bioimage_s3_prefix`` like ome-zarr; never on disk (the
#   registered path is the TIFF itself, and such a DC always uploads);
# * ome-tiff: one file, at ``bioimage_s3_object_key`` or on disk, by byte range;
# * remote stores (the DC's ``remote_stores``): proxied from their URL, only when
#   the bucket or host is allow-listed in ``settings.bioimage``.

_BIOIMAGE_CACHE_TTL_S = 60.0
_BIOIMAGE_CACHE_MAX = 2048
_BIOIMAGE_FORMATS = ("ome-zarr", "ome-tiff", "spatialdata", "tiff")
# zarr v2 (NGFF 0.4) and v3 (NGFF 0.5) metadata documents.
_ZARR_JSON_KEYS = frozenset({".zattrs", ".zgroup", ".zarray", ".zmetadata", "zarr.json"})
# Metadata is revalidated on every read (a re-upload may change it); chunks are
# addressed by the metadata that lists them, so they cache for an hour.
_ZARR_JSON_HEADERS = {"Cache-Control": "no-cache"}
_ZARR_CHUNK_HEADERS = {"Cache-Control": "private, max-age=3600"}
_TIFF_MEDIA_TYPE = "image/tiff"
_TIFF_HEADERS = {"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"}
_S3_MISS_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
_DISK_READ_CHUNK = 1 << 20
# Grants only (a deny re-checks, so a freshly shared project opens at once).
_bioimage_access_cache: dict[tuple[str, str], float] = {}
_bioimage_store_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _bioimage_cache_put(cache: dict, key, value) -> None:
    if len(cache) >= _BIOIMAGE_CACHE_MAX:
        cache.clear()
    cache[key] = value


def _assert_dc_access_cached(dc_oid: ObjectId, current_user) -> None:
    """``_assert_dc_access`` behind a short TTL cache keyed by (user, dc)."""
    import time

    user_id = getattr(current_user, "id", None)
    key = (str(user_id) if user_id is not None else "anon", str(dc_oid))
    now = time.monotonic()
    expiry = _bioimage_access_cache.get(key)
    if expiry is not None and expiry > now:
        return
    _assert_dc_access(dc_oid, current_user)
    _bioimage_cache_put(_bioimage_access_cache, key, now + _BIOIMAGE_CACHE_TTL_S)


def _bioimage_parse_dc_id(data_collection_id: str) -> ObjectId:
    try:
        return ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid dc_id") from exc


def _normalize_zarr_key(key: str) -> str | None:
    """Traversal-safe, store-relative zarr key, or None when it must be rejected.

    Same checks as ``files_endpoints._validate_image_path`` (raw ``..`` / leading
    slash rejected, then re-asserted on the ``posixpath.normpath`` form) minus
    the image-extension filter: zarr keys are ``.zattrs`` / ``zarr.json`` or
    bare chunk and shard names.
    """
    import posixpath

    if not key or ".." in key or key.startswith("/") or "\\" in key or "\x00" in key:
        return None
    normalized = posixpath.normpath(key)
    if (
        normalized in (".", "..")
        or normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized != key.rstrip("/")
    ):
        return None
    return normalized


def _zarr_is_metadata(key: str) -> bool:
    return key.rsplit("/", 1)[-1] in _ZARR_JSON_KEYS


def _zarr_media_type(key: str) -> str:
    return "application/json" if _zarr_is_metadata(key) else "application/octet-stream"


def _zarr_headers(key: str) -> dict[str, str]:
    return dict(_ZARR_JSON_HEADERS if _zarr_is_metadata(key) else _ZARR_CHUNK_HEADERS)


def _same_bioimage_store(a: str, b: str) -> bool:
    """Whether two registered paths name one store (symlink or container twin)."""
    if a == b or _container_repo_path(a) == b or _container_repo_path(b) == a:
        return True
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except (OSError, ValueError):
        return False


def _bioimage_dc_properties(dc_oid: ObjectId) -> tuple[dict[str, Any], str | None]:
    """The DC's ``dc_specific_properties`` and its ``scan_parameters.filename``."""
    from depictio.api.v1.db import projects_collection

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
        {"workflows.data_collections": 1},
    )
    for wf in (project_doc or {}).get("workflows", []) or []:
        for dc in wf.get("data_collections", []) or []:
            if (dc.get("_id") or dc.get("id")) != dc_oid:
                continue
            config = dc.get("config") or {}
            props = config.get("dc_specific_properties") or {}
            fname = ((config.get("scan") or {}).get("scan_parameters") or {}).get("filename")
            return (props if isinstance(props, dict) else {}), (str(fname) if fname else None)
    return {}, None


def _bioimage_store_info(dc_oid: ObjectId) -> dict[str, Any]:
    """Stores of a bioimage DC with its format and ``upload`` flag, cached briefly.

    Returns ``{"format": str, "kind": "image" | "labels", "upload": bool,
    "image_path": str | None, "sample_pattern": str | None,
    "stores": {name: {"file_id": str | None, "roots": [path, ...]}},
    "remote": {name: url}}``. A ``tiff`` (labels) store is registered as its
    mask file but served as the OME-Zarr key tree the CLI converted it to. Local stores come from the CLI scan
    (``files_collection``, one File per store) and, for DCs never CLI-scanned,
    from the project's ``scan_parameters.filename`` (a store, or a folder of
    stores). A root is the store directory, or the file of an OME-TIFF store,
    plus its ``/app`` container twin (see ``_container_repo_path``). Remote
    stores come from the DC's ``remote_stores``, keyed by their last path segment.

    Stores are keyed by name, so two registered paths sharing one name would
    alias each other. The CLI refuses to ingest such a DC; here the first path
    in sorted order wins (deterministic across calls) and the others are logged
    and dropped rather than merged into one store's roots. A remote store whose
    name a local store already uses is dropped the same way.
    """
    import time

    from depictio.api.v1.db import files_collection
    from depictio.models.models.data_collections_types.bioimage import (
        OME_TIFF_SUFFIXES,
        bioimage_store_suffixes,
        check_sample_pattern,
        is_bioimage_store_name,
        is_file_store_format,
        normalize_image_path,
        remote_store_name,
    )

    now = time.monotonic()
    cached = _bioimage_store_cache.get(str(dc_oid))
    if cached is not None and cached[0] > now:
        return cached[1]

    props, fname = _bioimage_dc_properties(dc_oid)
    fmt = str(props.get("format") or "ome-zarr")
    if fmt not in _BIOIMAGE_FORMATS:
        logger.warning(
            "Bioimage DC %s has an unknown format %r; serving it as ome-zarr", dc_oid, fmt
        )
        fmt = "ome-zarr"
    image_path: str | None = None
    if fmt == "spatialdata":
        try:
            image_path = normalize_image_path(str(props.get("image_path") or ""))
        except ValueError as exc:
            logger.warning("Bioimage DC %s: %s", dc_oid, exc)
    # On disk, a file store (OME-TIFF, labels TIFF) is a file, else a directory.
    file_store = is_file_store_format(fmt)
    kind = "labels" if props.get("kind") == "labels" else "image"
    sample_pattern: str | None = None
    if props.get("sample_pattern"):
        try:
            sample_pattern = check_sample_pattern(str(props["sample_pattern"]))
        except ValueError as exc:
            logger.warning("Bioimage DC %s: %s", dc_oid, exc)

    stores: dict[str, dict[str, Any]] = {}
    # The path each store name is bound to; a second path with that name is a clash.
    store_paths: dict[str, str] = {}

    def add_root(path: str, file_id: str | None = None) -> None:
        path = path.rstrip("/")
        name = os.path.basename(path)
        if not is_bioimage_store_name(name, fmt):
            return
        bound = store_paths.setdefault(name, path)
        if not _same_bioimage_store(bound, path):
            logger.warning(
                "Bioimage DC %s: store name %s is registered twice (%s, %s); serving %s",
                dc_oid,
                name,
                bound,
                path,
                bound,
            )
            return
        entry = stores.setdefault(name, {"file_id": None, "roots": []})
        if file_id and not entry["file_id"]:
            entry["file_id"] = file_id
        for candidate in (path, _container_repo_path(path)):
            if candidate and candidate not in entry["roots"]:
                entry["roots"].append(candidate)

    file_docs = [
        doc
        for doc in files_collection.find(
            {"data_collection_id": {"$in": [dc_oid, str(dc_oid)]}},
            {"_id": 1, "file_location": 1},
        )
        if doc.get("file_location") and not str(doc["file_location"]).startswith("s3://")
    ]
    for doc in sorted(file_docs, key=lambda d: str(d["file_location"]).rstrip("/")):
        add_root(str(doc["file_location"]), str(doc["_id"]))

    if fname and not fname.startswith("s3://"):
        fname = fname.rstrip("/")
        if fname.endswith(bioimage_store_suffixes(fmt)):
            add_root(fname)
        else:
            # A folder of stores: register its direct children named like one.
            for folder in (fname, _container_repo_path(fname)):
                if not folder or not os.path.isdir(folder):
                    continue
                try:
                    for entry in sorted(os.scandir(folder), key=lambda e: e.name):
                        is_store = entry.is_file() if file_store else entry.is_dir()
                        # A plain `*.tif` passes as OME-TIFF only after the CLI scan's
                        # header check (a file document); here, only OME names.
                        if fmt == "ome-tiff" and not entry.name.endswith(OME_TIFF_SUFFIXES):
                            continue
                        if is_store and is_bioimage_store_name(entry.name, fmt):
                            add_root(entry.path)
                except OSError:
                    continue

    remote: dict[str, str] = {}
    for url in props.get("remote_stores") or []:
        name = remote_store_name(str(url))
        if not is_bioimage_store_name(name, fmt):
            logger.warning("Bioimage DC %s: remote store %s is not a %s store", dc_oid, url, fmt)
        elif name in stores or name in remote:
            logger.warning("Bioimage DC %s: remote store name %s is already taken", dc_oid, name)
        else:
            remote[name] = str(url)

    info = {
        "format": fmt,
        "kind": kind,
        "upload": props.get("upload") is not False,
        "image_path": image_path,
        "sample_pattern": sample_pattern,
        "stores": stores,
        "remote": remote,
    }
    _bioimage_cache_put(_bioimage_store_cache, str(dc_oid), (now + _BIOIMAGE_CACHE_TTL_S, info))
    return info


@functools.cache
def _bioimage_s3_client():
    """Fast-fail boto3 client, built once: a viewer fetches hundreds of chunks."""
    return _phylogeny_s3_client()


@functools.cache
def _bioimage_http_client():
    """httpx client for remote https stores, built once (keeps connections alive).

    Redirects are never followed: the allow-list is checked on the URL the DC
    names, so a redirect to another host must not be read.
    """
    import httpx

    from depictio.api.v1.configs.config import settings

    return httpx.Client(timeout=settings.bioimage.remote_timeout_s, follow_redirects=False)


def _bioimage_s3_store_names(dc_oid: ObjectId, fmt: str) -> list[str]:
    """Store names uploaded under the DC's S3 prefix (for DCs with no registered path).

    Key-tree stores are prefixes, a single-file store is an object. Only names
    of the DC's format count, which also skips the CLI's ``.uploads/`` marker.
    """
    from depictio.api.v1.configs.config import settings
    from depictio.models.models.data_collections_types.bioimage import (
        bioimage_s3_prefix,
        is_bioimage_store_name,
        is_single_file_format,
    )

    prefix = bioimage_s3_prefix(str(dc_oid))
    single_file = is_single_file_format(fmt)
    names: list[str] = []
    try:
        paginator = _bioimage_s3_client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3.bucket, Prefix=prefix, Delimiter="/"):
            if single_file:
                keys = [obj.get("Key", "") for obj in page.get("Contents", []) or []]
            else:
                keys = [cp.get("Prefix", "") for cp in page.get("CommonPrefixes", []) or []]
            for key in keys:
                name = key[len(prefix) :].rstrip("/")
                if is_bioimage_store_name(name, fmt):
                    names.append(name)
    except Exception as exc:
        logger.debug("bioimage store listing on s3 failed for %s: %s", dc_oid, exc)
    return names


# ---- Reads that may miss, fail upstream, or be refused ---------------------


class _BioimageMiss(Exception):
    """The object does not exist upstream: a genuine 404."""


class _BioimageUpstreamError(Exception):
    """The storage behind a store failed: a 502, never a 404."""


class _Blob(NamedTuple):
    content: bytes
    # The upstream ``bytes a-b/n`` when it served the requested range, else None.
    content_range: str | None = None


class _RemoteTarget(NamedTuple):
    scheme: str  # "s3" or "https"
    bucket: str  # s3 only
    key: str  # s3 only
    url: str


def _bioimage_max_bytes() -> int:
    from depictio.api.v1.configs.config import settings

    return settings.bioimage.remote_max_object_mb * 1024 * 1024


def _bioimage_too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=(
            "Image object is larger than DEPICTIO_BIOIMAGE_REMOTE_MAX_OBJECT_MB; "
            "request it by byte range"
        ),
    )


def _range_not_satisfiable(size: int | None = None) -> HTTPException:
    headers = {"Content-Range": f"bytes */{size}"} if size is not None else None
    return HTTPException(status_code=416, detail="Requested range not satisfiable", headers=headers)


def _bioimage_s3_get(bucket: str, key: str, byte_range: str | None = None) -> dict[str, Any]:
    """``get_object`` with its errors mapped to a miss, a 416 or an upstream failure."""
    from botocore.exceptions import ClientError

    kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if byte_range:
        kwargs["Range"] = byte_range
    try:
        return _bioimage_s3_client().get_object(**kwargs)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _S3_MISS_CODES:
            raise _BioimageMiss(key) from exc
        if code == "InvalidRange":
            raise _range_not_satisfiable() from exc
        raise _BioimageUpstreamError(f"s3 {bucket}/{key}: {code}") from exc
    except Exception as exc:
        raise _BioimageUpstreamError(f"s3 {bucket}/{key}: {exc}") from exc


def _read_s3_body(obj: dict[str, Any], bucket: str, key: str) -> bytes:
    """The whole body: a mid-read failure is then a 502, not a truncated 200."""
    body = obj["Body"]
    try:
        return body.read()
    except Exception as exc:
        raise _BioimageUpstreamError(f"s3 {bucket}/{key}: {exc}") from exc
    finally:
        body.close()


def _bioimage_s3_read(bucket: str, key: str, byte_range: str | None = None) -> _Blob:
    """One object (or byte range of it), whole-read and capped at the relay limit."""
    obj = _bioimage_s3_get(bucket, key, byte_range)
    length = obj.get("ContentLength")
    if isinstance(length, int) and length > _bioimage_max_bytes():
        obj["Body"].close()
        raise _bioimage_too_large()
    content = _read_s3_body(obj, bucket, key)
    if len(content) > _bioimage_max_bytes():
        raise _bioimage_too_large()
    return _Blob(content, obj.get("ContentRange") if byte_range else None)


def _bioimage_s3_whole_response(
    bucket: str, key: str, media_type: str, headers: dict[str, str]
) -> Response:
    """A whole key of the DC's own upload, uncapped.

    Metadata and zarr v2 chunks are small and read whole (502 on a mid-read
    failure). A key past the relay limit, typically a zarr v3 shard fetched
    without Range, is streamed instead of being held in API memory.
    """
    from fastapi.responses import StreamingResponse

    obj = _bioimage_s3_get(bucket, key)
    length = obj.get("ContentLength")
    if not isinstance(length, int) or length <= _bioimage_max_bytes():
        content = _read_s3_body(obj, bucket, key)
        return Response(content=content, media_type=media_type, headers=headers)
    body = obj["Body"]

    def chunks():
        try:
            yield from body.iter_chunks(_DISK_READ_CHUNK)
        finally:
            body.close()

    headers = {**headers, "Content-Length": str(length)}
    return StreamingResponse(chunks(), media_type=media_type, headers=headers)


def _bioimage_s3_size(bucket: str, key: str) -> int:
    from botocore.exceptions import ClientError

    try:
        head = _bioimage_s3_client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _S3_MISS_CODES:
            raise _BioimageMiss(key) from exc
        raise _BioimageUpstreamError(f"s3 {bucket}/{key}: {code}") from exc
    except Exception as exc:
        raise _BioimageUpstreamError(f"s3 {bucket}/{key}: {exc}") from exc
    return int(head["ContentLength"])


def _check_https_status(response, url: str) -> None:
    status = response.status_code
    if status in (404, 410):
        raise _BioimageMiss(url)
    if status == 416:
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers=(
                {"Content-Range": response.headers["content-range"]}
                if "content-range" in response.headers
                else None
            ),
        )
    # Anything else, redirects included, is an upstream failure.
    if status not in (200, 206):
        raise _BioimageUpstreamError(f"GET {url}: HTTP {status}")


def _bioimage_https_read(url: str, byte_range: str | None = None) -> _Blob:
    """One remote object (or byte range of it), streamed in up to the relay limit."""
    import httpx

    headers = {"Accept-Encoding": "identity"}
    if byte_range:
        headers["Range"] = byte_range
    max_bytes = _bioimage_max_bytes()
    try:
        with _bioimage_http_client().stream(
            "GET", url, headers=headers, follow_redirects=False
        ) as response:
            _check_https_status(response, url)
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise _bioimage_too_large()
            content = bytearray()
            for chunk in response.iter_bytes():
                content += chunk
                if len(content) > max_bytes:
                    raise _bioimage_too_large()
            content_range = (
                response.headers.get("content-range") if response.status_code == 206 else None
            )
            return _Blob(bytes(content), content_range)
    except httpx.HTTPError as exc:
        raise _BioimageUpstreamError(f"GET {url}: {exc}") from exc


def _bioimage_https_size(url: str) -> int:
    import httpx

    try:
        response = _bioimage_http_client().head(
            url, headers={"Accept-Encoding": "identity"}, follow_redirects=False
        )
    except httpx.HTTPError as exc:
        raise _BioimageUpstreamError(f"HEAD {url}: {exc}") from exc
    _check_https_status(response, url)
    declared = response.headers.get("content-length", "")
    if not declared.isdigit():
        raise _BioimageUpstreamError(f"HEAD {url}: no Content-Length")
    return int(declared)


def _bioimage_remote_target(url: str) -> _RemoteTarget:
    """The remote store at ``url`` when its bucket or host is allow-listed, else 403.

    s3:// is read on the server's own S3 endpoint, and never from the Depictio
    data bucket: that bucket holds every DC's data, so reading it by URL would
    bypass data-collection access control.
    """
    from urllib.parse import urlparse

    from depictio.api.v1.configs.config import settings

    parsed = urlparse(url)
    allowed = settings.bioimage
    if parsed.scheme == "s3" and parsed.netloc and "@" not in parsed.netloc:
        bucket = parsed.netloc
        if bucket in allowed.remote_s3_buckets and bucket != settings.s3.bucket:
            return _RemoteTarget("s3", bucket, parsed.path.strip("/"), url)
    elif parsed.scheme == "https" and parsed.hostname and "@" not in parsed.netloc:
        if parsed.hostname.lower() in allowed.remote_https_hosts:
            return _RemoteTarget("https", "", "", url.rstrip("/"))
    raise HTTPException(status_code=403, detail="Remote bioimage host not allowed")


def _bioimage_remote_read(url: str, rel: str | None, byte_range: str | None = None) -> _Blob:
    """Read ``rel`` under the remote store at ``url`` (or the store file itself)."""
    from urllib.parse import quote

    target = _bioimage_remote_target(url)
    if target.scheme == "s3":
        key = f"{target.key}/{rel}" if rel else target.key
        return _bioimage_s3_read(target.bucket, key, byte_range)
    full_url = f"{target.url}/{quote(rel, safe='/')}" if rel else target.url
    return _bioimage_https_read(full_url, byte_range)


def _bioimage_remote_size(url: str) -> int:
    target = _bioimage_remote_target(url)
    if target.scheme == "s3":
        return _bioimage_s3_size(target.bucket, target.key)
    return _bioimage_https_size(target.url)


# ---- Byte ranges (OME-TIFF files, zarr v3 shards) --------------------------

_ByteRange = tuple[int | None, int | None]


def _parse_byte_range(header: str | None) -> _ByteRange | None:
    """The one byte range a Range header asks for, or None to serve the whole file.

    ``(start, end)``, ``(start, None)`` for ``a-`` and ``(None, n)`` for the
    suffix ``-n``. A header in another unit is ignored (RFC 9110 allows it).
    Several ranges, or a malformed one, are a 416: viv (OME-TIFF) and zarrita
    (zarr v3 shards) only ever ask for one.
    """
    import re

    if not header:
        return None
    unit, sep, spec = header.strip().partition("=")
    if not sep or unit.strip().lower() != "bytes":
        return None
    # 19 digits covers any real offset and keeps int() clear of its digit limit.
    match = re.fullmatch(r"(\d{0,19})-(\d{0,19})", spec.strip())
    if match is None or not (match[1] or match[2]):
        raise _range_not_satisfiable()
    start = int(match[1]) if match[1] else None
    end = int(match[2]) if match[2] else None
    if (start is None and end == 0) or (start is not None and end is not None and end < start):
        raise _range_not_satisfiable()
    return start, end


def _byte_range_header(requested: _ByteRange | None) -> str | None:
    """The canonical ``Range`` value to forward upstream."""
    if requested is None:
        return None
    start, end = requested
    return f"bytes={'' if start is None else start}-{'' if end is None else end}"


def _resolve_byte_range(requested: _ByteRange, size: int) -> tuple[int, int]:
    """Inclusive ``(start, end)`` offsets of ``requested`` in a ``size``-byte file."""
    start, end = requested
    if start is None:
        # Suffix range: ``end`` is the number of trailing bytes.
        start, end = max(0, size - (end or 0)), size - 1
    else:
        end = size - 1 if end is None else min(end, size - 1)
    if size == 0 or start >= size:
        raise _range_not_satisfiable(size)
    return start, end


def _head_response(size: int, media_type: str, headers: dict[str, str]) -> Response:
    headers = {**headers, "Content-Length": str(size)}
    return Response(status_code=200, media_type=media_type, headers=headers)


def _tiff_head_response(size: int) -> Response:
    return _head_response(size, _TIFF_MEDIA_TYPE, _TIFF_HEADERS)


def _blob_response(
    blob: _Blob, requested: _ByteRange | None, media_type: str, headers: dict[str, str]
) -> Response:
    """The whole blob (200), or the ``requested`` range of it (206)."""
    headers = dict(headers)
    if requested is None:
        return Response(content=blob.content, media_type=media_type, headers=headers)
    headers["Accept-Ranges"] = "bytes"
    if blob.content_range:
        headers["Content-Range"] = blob.content_range
        return Response(
            content=blob.content, status_code=206, media_type=media_type, headers=headers
        )
    # The upstream ignored the Range and sent the whole object: slice it here.
    size = len(blob.content)
    start, end = _resolve_byte_range(requested, size)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(
        content=blob.content[start : end + 1],
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def _disk_response(
    path: str,
    requested: _ByteRange | None,
    media_type: str,
    headers: dict[str, str],
    head: bool = False,
) -> Response:
    """Stream the file, or one range of it. Not a FileResponse: that would apply
    the request's Range header itself (multi-range included) behind our back."""
    from fastapi.responses import StreamingResponse

    size = os.path.getsize(path)
    if head:
        return _head_response(size, media_type, headers)
    headers = dict(headers)
    if requested is None:
        start, end, status = 0, size - 1, 200
    else:
        start, end = _resolve_byte_range(requested, size)
        status = 206
        headers["Accept-Ranges"] = "bytes"
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def chunks():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                data = fh.read(min(_DISK_READ_CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(chunks(), status_code=status, media_type=media_type, headers=headers)


# ---- Routes ------------------------------------------------------------------


@advanced_viz_endpoint_router.get("/bioimage/{data_collection_id}/stores")
def list_bioimage_stores(
    data_collection_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> list[dict[str, Any]]:
    """List the image stores of a bioimage DC, sorted by name.

    Each entry is ``{name, sample, file_id, format, kind, remote}``. ``sample``
    is the DC's ``sample_pattern`` capture on the store name, else the name
    without its suffix; the viewer matches it against upstream filter values,
    and pairs a labels store (``kind: labels``) with the image of its sample. ``file_id`` is None for a store only found on S3 or remote.
    ``format`` is the DC's format. ``remote`` marks a store read in place from
    its URL; it is listed even when its host is not allow-listed, so the tile
    can say why it cannot open it.
    """
    from depictio.models.models.data_collections_types.bioimage import bioimage_sample_name

    dc_oid = _bioimage_parse_dc_id(data_collection_id)
    _assert_dc_access_cached(dc_oid, current_user)

    info = _bioimage_store_info(dc_oid)
    fmt = info["format"]
    local: dict[str, str | None] = {
        name: entry["file_id"] for name, entry in info["stores"].items()
    }
    if not local:
        local = {name: None for name in _bioimage_s3_store_names(dc_oid, fmt)}
    listed = [(name, file_id, False) for name, file_id in local.items()]
    listed += [(name, None, True) for name in info["remote"] if name not in local]
    return [
        {
            "name": name,
            "sample": bioimage_sample_name(name, info["sample_pattern"]),
            "file_id": file_id,
            "format": fmt,
            "kind": info["kind"],
            "remote": remote,
        }
        for name, file_id, remote in sorted(listed)
    ]


@advanced_viz_endpoint_router.get("/bioimage/{data_collection_id}/{store}/{key:path}")
def get_bioimage_key(
    data_collection_id: str,
    store: str,
    key: str,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """Serve one zarr key (metadata JSON or raw chunk / shard bytes) of a key-tree store.

    Metadata is ``.zattrs`` / ``.zarray`` (zarr v2, NGFF 0.4) or ``zarr.json``
    (zarr v3, NGFF 0.5). A zarr v3 reader fetches a sharded array by byte
    range (the shard index, then each chunk), so one ``Range: bytes=a-b`` /
    ``a-`` / ``-n`` gets a 206 with ``Content-Range``, several ranges or one
    past the end a 416, exactly as for an OME-TIFF file. Without a Range the
    key is served whole, as before.

    OME-Zarr stores are read as they are; a SpatialData store at its
    ``image_path``. A remote store is proxied from its URL. A local one is read
    from the CLI upload at ``bioimage_s3_prefix(dc_id, store) + key`` first
    (skipped for ``upload: false`` DCs; a SpatialData upload holds the image
    subtree only, so no ``image_path`` join), then from the registered store
    directory on disk. A missing key is a 404, which zarr readers treat as an
    empty chunk, so only a genuine miss may produce one (ranged or not): a
    storage error with no disk copy is a 502.
    """
    import posixpath

    from fastapi.responses import FileResponse

    from depictio.api.v1.configs.config import settings
    from depictio.models.models.data_collections_types.bioimage import (
        bioimage_s3_prefix,
        is_bioimage_store_name,
        is_single_file_format,
    )

    dc_oid = _bioimage_parse_dc_id(data_collection_id)
    # Gate before any read, and before validating the key, so an unauthorised
    # caller learns nothing about which stores or keys exist.
    _assert_dc_access_cached(dc_oid, current_user)

    info = _bioimage_store_info(dc_oid)
    fmt = info["format"]
    if is_single_file_format(fmt):
        raise HTTPException(
            status_code=400, detail=f"A {fmt} store is one file: fetch it without a key"
        )
    normalized = _normalize_zarr_key(key)
    if not is_bioimage_store_name(store, fmt) or normalized is None:
        raise HTTPException(status_code=400, detail="Invalid store or key")
    image_path = info["image_path"]
    if fmt == "spatialdata" and not image_path:
        raise HTTPException(status_code=500, detail="SpatialData collection has no image_path")
    # The key relative to the store root (a SpatialData store's image lives below it).
    rel_key = posixpath.join(image_path, normalized) if image_path else normalized

    range_header = request.headers.get("range")
    requested = _parse_byte_range(range_header)
    byte_range = _byte_range_header(requested)
    media_type = _zarr_media_type(normalized)
    headers = _zarr_headers(normalized)

    remote_url = info["remote"].get(store)
    if remote_url:
        try:
            blob = _bioimage_remote_read(remote_url, rel_key, byte_range)
        except _BioimageMiss as exc:
            raise HTTPException(status_code=404, detail="Key not found") from exc
        except _BioimageUpstreamError as exc:
            logger.warning("bioimage remote read failed: %s", exc)
            raise HTTPException(status_code=502, detail="Remote image store unavailable") from exc
        return _blob_response(blob, requested, media_type, headers)

    s3_failed = False
    if info["upload"]:
        s3_key = bioimage_s3_prefix(str(dc_oid), store) + normalized
        try:
            if byte_range is None:
                return _bioimage_s3_whole_response(settings.s3.bucket, s3_key, media_type, headers)
            # One range of a shard, capped by its span.
            blob = _bioimage_s3_read(settings.s3.bucket, s3_key, byte_range)
            return _blob_response(blob, requested, media_type, headers)
        except _BioimageMiss:
            pass
        except _BioimageUpstreamError as exc:
            s3_failed = True
            logger.warning("bioimage s3 read failed: %s", exc)

    # Disk fallback: only under a registered root, and the resolved path must
    # stay inside it (symlinks included).
    entry = info["stores"].get(store)
    for root in entry["roots"] if entry else []:
        try:
            real_root = os.path.realpath(root)
            if not os.path.isdir(real_root):
                continue
            candidate = os.path.realpath(os.path.join(real_root, rel_key))
            if os.path.commonpath([real_root, candidate]) != real_root:
                continue
            if os.path.isfile(candidate):
                if range_header:
                    # Any Range header (even one in another unit, ignored as
                    # for OME-TIFF): never let FileResponse interpret it.
                    return _disk_response(candidate, requested, media_type, headers)
                return FileResponse(candidate, media_type=media_type, headers=headers)
        except (OSError, ValueError):
            continue

    if s3_failed:
        raise HTTPException(status_code=502, detail="Image storage unavailable")
    raise HTTPException(status_code=404, detail="Key not found")


@advanced_viz_endpoint_router.api_route(
    "/bioimage/{data_collection_id}/{store}", methods=["GET", "HEAD"]
)
def get_bioimage_file(
    data_collection_id: str,
    store: str,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """Serve a single-file store (OME-TIFF), whole or by one byte range.

    ``Range: bytes=a-b`` / ``a-`` / ``-n`` gets a 206 with ``Content-Range``;
    several ranges, or one past the end, a 416. No Range serves the whole file
    (from S3 or a remote store only up to ``remote_max_object_mb``, else 413).
    HEAD returns the size. Read from the remote URL for a remote store, else the
    CLI upload at ``bioimage_s3_object_key`` (skipped for ``upload: false``),
    then the registered file on disk. As for keys, only a genuine miss is a 404.
    """
    from depictio.api.v1.configs.config import settings
    from depictio.models.models.data_collections_types.bioimage import (
        bioimage_s3_object_key,
        is_bioimage_store_name,
        is_single_file_format,
    )

    dc_oid = _bioimage_parse_dc_id(data_collection_id)
    _assert_dc_access_cached(dc_oid, current_user)

    info = _bioimage_store_info(dc_oid)
    fmt = info["format"]
    if not is_single_file_format(fmt):
        raise HTTPException(
            status_code=400, detail=f"A {fmt} store is a key tree: fetch its keys under {store}/"
        )
    if not is_bioimage_store_name(store, fmt):
        raise HTTPException(status_code=400, detail="Invalid store")
    head = request.method == "HEAD"
    # A Range on HEAD is ignored: HEAD describes the whole file.
    requested = None if head else _parse_byte_range(request.headers.get("range"))
    byte_range = _byte_range_header(requested)

    remote_url = info["remote"].get(store)
    if remote_url:
        try:
            if head:
                return _tiff_head_response(_bioimage_remote_size(remote_url))
            return _blob_response(
                _bioimage_remote_read(remote_url, None, byte_range),
                requested,
                _TIFF_MEDIA_TYPE,
                _TIFF_HEADERS,
            )
        except _BioimageMiss as exc:
            raise HTTPException(status_code=404, detail="Image not found") from exc
        except _BioimageUpstreamError as exc:
            logger.warning("bioimage remote read failed: %s", exc)
            raise HTTPException(status_code=502, detail="Remote image store unavailable") from exc

    s3_failed = False
    if info["upload"]:
        s3_key = bioimage_s3_object_key(str(dc_oid), store)
        try:
            if head:
                return _tiff_head_response(_bioimage_s3_size(settings.s3.bucket, s3_key))
            blob = _bioimage_s3_read(settings.s3.bucket, s3_key, byte_range)
            return _blob_response(blob, requested, _TIFF_MEDIA_TYPE, _TIFF_HEADERS)
        except _BioimageMiss:
            pass
        except _BioimageUpstreamError as exc:
            s3_failed = True
            logger.warning("bioimage s3 read failed: %s", exc)

    entry = info["stores"].get(store)
    for root in entry["roots"] if entry else []:
        try:
            path = os.path.realpath(root)
            if os.path.isfile(path):
                return _disk_response(path, requested, _TIFF_MEDIA_TYPE, _TIFF_HEADERS, head)
        except (OSError, ValueError):
            continue

    if s3_failed:
        raise HTTPException(status_code=502, detail="Image storage unavailable")
    raise HTTPException(status_code=404, detail="Image not found")
