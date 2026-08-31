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

import logging
import os
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse

from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.advanced_viz.data import (
    _available_columns,
    _prune_filters,
    _resolve_init_data,
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

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    # Resolve the delta-table location, read the DC's schema, and drop filters
    # this DC cannot satisfy. Shared with the export service, which needs the
    # same three steps without going back through HTTP — see
    # services/advanced_viz/data.py for why each one exists.
    init_data = _resolve_init_data(dc_oid, str(dc_id))
    available_cols = _available_columns(init_data[str(dc_id)])
    filter_metadata, filter_cols = _prune_filters(
        list(filter_metadata or []), available_cols, str(dc_id)
    )

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
    existing = cache.find_one({"_id": cache_key})

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
    existing = cache.find_one({"_id": cache_key})
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
    existing = cache.find_one({"_id": cache_key})
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

    existing = cache.find_one({"_id": cache_key})
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


@advanced_viz_endpoint_router.get(
    "/phylogeny/{data_collection_id}/newick", response_class=PlainTextResponse
)
def get_phylogeny_newick(
    data_collection_id: PyObjectId,
    current_user=Depends(get_user_or_anonymous),
) -> str:
    """Return the raw Newick string for a phylogeny DC.

    Resolves the file location in three ways: (1) prefer the file registered
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
            import boto3

            from depictio.api.v1.configs.config import settings

            s3 = boto3.client(
                "s3",
                endpoint_url=settings.minio.endpoint_url,
                aws_access_key_id=settings.minio.aws_access_key_id,
                aws_secret_access_key=settings.minio.aws_secret_access_key,
                verify=settings.minio.verify_tls,
            )
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
