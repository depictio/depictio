"""Result-row schema + metric helpers (percentiles, monitoring-ledger enrichment).

The canonical per-render metric is **HTTP wall-clock + the ``X-Celery-Path``
header** — the only signal available for inline renders. Offloaded renders can be
enriched with the durable ``duration_ms`` from the Mongo ``task_events`` ledger
via ``GET /monitoring/tasks`` (admin token). Both can be enriched with the
``load_ms``/``build_ms`` split scraped from the API/worker stdout log.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class RenderResult:
    """One row of the benchmark results table (appended to results.jsonl)."""

    # Matrix cell identity
    cell_slug: str
    size: str
    size_bytes: int
    n_components: int
    n_dcs: int
    connect: str
    # Component identity
    component_type: str
    component_index: str
    visu: str = ""
    dc_tag: str = ""
    # Server config (stamped per matrix half)
    server_mode: str = ""  # "celery_off" | "celery_on" | custom
    # Measurements
    wall_ms: float = 0.0  # end-to-end HTTP round-trip
    celery_path: str = ""  # "inline" | "offloaded" | "n/a"
    http_status: int = 0
    ok: bool = False
    filtered: bool = False  # was a cross-filter payload applied?
    # Cache regime. The frame cache makes the first read of a DC far slower than
    # every later one, so mixing them yields a bimodal distribution whose mean
    # describes neither. ``dc_first_touch`` marks the render that paid the cold
    # read; ``iteration`` counts full passes over the cell (0 = first pass).
    dc_first_touch: bool = False
    iteration: int = 0
    # True when this render was fired simultaneously with every other component
    # of its dashboard (see ``dashboard_load``): the latency then includes
    # server-side contention, which sequential rendering never exposes.
    concurrent: bool = False
    # Which phase produced this row. ``concurrent`` alone is not enough: a cold
    # open fires every component at once *unfiltered*, a filter round fires them
    # through the viewer's bounded queue *filtered*. Both set ``concurrent``, and
    # averaging them together describes neither.
    #
    # ``dashboard_load_cold`` and ``dashboard_load`` are the same concurrent
    # open before and after the server's caches are populated — first visit
    # versus revisit.
    phase: str = "sequential"
    # "sequential" | "dashboard_load_cold" | "dashboard_load" | "filter_round"
    # Filter-round rows only: where the filter originated and how far it had to
    # travel. Without these the propagated and native sweeps are indistinguishable
    # once the rows are aggregated — ``iteration`` collides between them.
    filter_dc_tag: str = ""
    hops: int = 0
    # Optional server-side enrichment (from X-* timing headers / task ledger)
    task_duration_ms: Optional[float] = None
    load_ms: Optional[float] = None  # X-Load-Ms: Delta read
    build_ms: Optional[float] = None  # X-Build-Ms: plot/table/frame build
    server_total_ms: Optional[float] = None  # X-Total-Ms: whole endpoint, server-side
    # What the render had to touch. A latency figure on its own doesn't say
    # whether it was fast because the work was small or because the work was
    # avoided; these separate the two.
    rows_loaded: Optional[int] = None  # X-Rows-Loaded: rows materialised (0 if aggregated)
    rows_displayed: Optional[int] = None  # X-Rows-Displayed: marks/rows in the payload
    frame_bytes: Optional[int] = None  # X-Frame-Bytes: in-memory footprint
    aggregated: bool = False  # X-Aggregated: served by a scan-level reduction
    cache: str = ""  # X-Cache: "hit" | "miss" | ""
    peak_rss_mb: Optional[float] = None  # X-Peak-RSS-MB: process high-water mark
    # How much cross-DC translation this render paid for: the number of values a
    # link resolution injected (X-Link-Values) and how far the filter travelled
    # (X-Link-Hops). None when the render applied no link-resolved filter.
    link_values: Optional[int] = None
    link_hops: Optional[int] = None
    # Hardware profile this measurement was taken under (see benchmark/profile.py).
    # Without it a number cannot be compared to anything, including a later run.
    profile_label: str = ""
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def overhead_ms(self) -> Optional[float]:
        """Client wall minus server total = network + (de)serialization + queue.

        The bottleneck bucket that is neither Delta load nor plot build — e.g.
        template setup, JSON transport, or Celery broker round-trip.
        """
        if self.wall_ms and self.server_total_ms is not None:
            return max(0.0, self.wall_ms - self.server_total_ms)
        return None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IngestResult:
    """Timing + throughput for one cell's ingestion (CLI ``run``) + import."""

    cell_slug: str
    ingest_wall_ms: float
    import_wall_ms: float
    ok: bool
    dashboard_id: str = ""
    error: str = ""
    # Throughput inputs (from the dataset manifest + post-ingest Delta size).
    n_dcs: int = 0
    rows_per_dc: int = 0
    rows_total: int = 0  # rows_per_dc * n_dcs (all DCs ingested)
    input_bytes: int = 0  # raw CSV bytes across all DCs
    delta_bytes: int = 0  # materialized Delta bytes across all DCs (0 if unknown)
    # Per-DC-kind ingestion breakdown (table / multiqc / images).
    dc_kind: str = "table"  # DCKind value
    magnitude: str = ""  # size key (table) | file count (multiqc) | image count (images)
    n_units: int = 0  # rows (table) | files (multiqc) | images (images)
    # Per-phase wall from the CLI ``DEPICTIO_INGEST_TIMINGS`` marker (ms), summed
    # across DCs: parse / collect / write / upsert / upload. Empty if not captured.
    phase_ms: dict[str, float] = field(default_factory=dict)
    peak_rss_mb: Optional[float] = None  # process peak RSS during ingest
    streaming: Optional[bool] = None  # table: was the sink_delta streaming path used?
    profile_label: str = ""
    # True when the cell reused an already-ingested project (``--reuse-ingest``):
    # nothing was ingested, so ``ingest_wall_ms`` is 0 and must not be read as a
    # throughput figure. The dataset shape below is still real.
    reused: bool = False
    # Linked topology only: distinct join-key values and rows per collection.
    # The join-key cardinality is the property the realistic dataset exists to
    # hold down, so it is recorded rather than inferred from the tier.
    join_key_cardinality: int = 0
    rows_by_dc: dict[str, int] = field(default_factory=dict)

    @property
    def rows_per_s(self) -> float:
        secs = self.ingest_wall_ms / 1000.0
        return self.rows_total / secs if secs > 0 else 0.0

    @property
    def input_mb_per_s(self) -> float:
        secs = self.ingest_wall_ms / 1000.0
        return (self.input_bytes / 1024**2) / secs if secs > 0 else 0.0

    @property
    def compression_ratio(self) -> float:
        """input / delta — >1 means Delta is smaller than raw CSV."""
        return self.input_bytes / self.delta_bytes if self.delta_bytes > 0 else 0.0


@dataclass
class FilterRoundResult:
    """One *filter change* on an already-open dashboard.

    The other two render phases each describe half of this and neither describes
    it on its own: the sequential filtered pass measures one component on an idle
    server, and ``dashboard_load`` measures every component at once but
    *unfiltered*. What a user actually waits for is every component re-rendering
    together under a filter they just changed — which is what this row times.

    ``time_to_last_ms`` is the number the user experiences; ``time_to_first_ms``
    says whether the dashboard feels responsive while it catches up. The
    per-component detail is emitted separately as ``RenderResult`` rows stamped
    ``filtered=True, concurrent=True``, so this row stays an aggregate.

    Rounds apply *different* filter values on purpose (see
    ``configgen.FilterPlan.values``): re-applying the same value would be
    answered by the filtered frame cache and would measure the cache, not the
    filter. The runner caps the round count at the number of distinct values.
    """

    # Matrix cell identity
    cell_slug: str
    size: str
    size_bytes: int
    n_components: int
    n_dcs: int
    connect: str
    server_mode: str = ""
    # What was applied
    round_index: int = 0  # 0 = first filter change; later rounds use new values
    filter_column: str = ""
    filter_values: list[str] = field(default_factory=list)
    # The client-side concurrency cap this round modelled. The viewer bounds
    # in-flight render fetches (packages/depictio-react-core/src/fetchQueue.ts),
    # so firing N components with unbounded parallelism would measure a client
    # that doesn't exist.
    concurrency: int = 0
    # Measurements
    n_fired: int = 0  # timed components (passive ones excluded)
    n_ok: int = 0
    time_to_first_ms: float = 0.0
    time_to_last_ms: float = 0.0
    ok: bool = False
    # Where the filter started and how far it had to travel. A filter on the
    # collection the components read costs nothing to propagate; one that must
    # be translated across one or two links does. Averaging the two would
    # describe neither.
    filter_dc_tag: str = ""
    hops: int = 0
    # Timed components the filter can actually narrow — its own collection plus
    # everything reachable through the declared links. Links are directed, so a
    # filter on the leaf collection reaches nothing else and the rest of the
    # dashboard re-renders unfiltered. Without this, two origins doing different
    # amounts of work would look like a like-for-like comparison.
    n_affected: int = 0
    profile_label: str = ""
    error: str = ""

    @property
    def catch_up_ms(self) -> float:
        """Spread between the first and last component repainting."""
        return max(0.0, self.time_to_last_ms - self.time_to_first_ms)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LinkResolutionResult:
    """One link translation, measured directly against ``/links/{id}/resolve``.

    This is the number that says whether a cross-filter benchmark is describing
    normal usage or a pathology. A filter on a 3-value column translating into
    hundreds of join-key values is a real topology; the same filter translating
    into millions means the join key is near-unique per row — the dataset is
    wrong, not the code — and the row is flagged ``pathological`` so the report
    can label it instead of quietly averaging it in.
    """

    cell_slug: str
    connect: str
    source_tag: str
    target_tag: str
    hops: int
    filter_column: str
    filter_values: list[str] = field(default_factory=list)
    n_source_values: int = 0
    n_resolved_values: int = 0
    wall_ms: float = 0.0
    ok: bool = False
    pathological: bool = False
    server_mode: str = ""
    profile_label: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100]). Empty -> nan."""
    if not values:
        return math.nan
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def summarize(values: list[float]) -> dict[str, float]:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return {"n": 0, "mean": math.nan, "p50": math.nan, "p95": math.nan, "max": math.nan}
    return {
        "n": len(vals),
        "mean": sum(vals) / len(vals),
        "p50": percentile(vals, 50),
        "p95": percentile(vals, 95),
        "max": max(vals),
    }


def query_task_durations(
    api_base_url: str,
    headers: dict,
    *,
    kind: str,
    since_seconds: int,
    http_get,
) -> list[float]:
    """Best-effort: pull recent ``duration_ms`` for a task ``kind`` from the ledger.

    Requires an admin token; on any failure returns ``[]`` (enrichment is
    optional — the wall-clock metric always stands on its own). ``http_get`` is
    injected so this stays trivially testable and reuses the runner's client.
    """
    try:
        resp = http_get(
            f"{api_base_url}/depictio/api/v1/monitoring/tasks",
            params={"kind": kind, "since_seconds": since_seconds, "limit": 500},
            headers=headers,
        )
        if resp.status_code != 200:
            return []
        rows = resp.json()
        if isinstance(rows, dict):
            rows = rows.get("tasks") or rows.get("items") or []
        return [
            float(r["duration_ms"])
            for r in rows
            if isinstance(r, dict) and r.get("duration_ms") is not None
        ]
    except Exception:
        return []
