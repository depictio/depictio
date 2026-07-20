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
    # Optional server-side enrichment (from X-* timing headers / task ledger)
    task_duration_ms: Optional[float] = None
    load_ms: Optional[float] = None  # X-Load-Ms: Delta read
    build_ms: Optional[float] = None  # X-Build-Ms: plot/table/frame build
    server_total_ms: Optional[float] = None  # X-Total-Ms: whole endpoint, server-side
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
