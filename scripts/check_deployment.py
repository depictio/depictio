#!/usr/bin/env python3
"""Check that every dashboard on a live Depictio deployment still renders.

Walks every dashboard and every tab the API returns, then replays, per component,
the exact data fetch the React viewer issues for that component type. Reports
which components fail and attributes each failure to a root cause.

Run it after a deployment. No browser needed. The only dependency is rich, which
is already pinned in pyproject, so use the project interpreter:

    ./depictio-venv-dash-v3/bin/python scripts/check_deployment.py --host demo.depictio.embl.org
    uv run python scripts/check_deployment.py --host trec-demo.depictio.embl.org --strict
    uv run python scripts/check_deployment.py --host localhost:5080 --scheme http

Auth defaults to sending no Authorization header. On a deployment running in
public mode that is equivalent to the temporary-user session the browser creates,
so the run reproduces what an ordinary visitor sees. Pass --token-file with an
admin bearer token to also cover private dashboards. On a Kubernetes deployment
that token lives in the backend pod, in the per-admin config under
/app/depictio/.depictio/ at user.token.access_token. The file is named after the
admin account (<username>_config.yaml), not admin_config.yaml, so glob for
*_config.yaml rather than assuming a fixed name.

A 2xx is not proof of a render, so figure probes also read the payload: an error
figure (a code-mode figure the sandbox rejected comes back as HTTP 200 with the
message in ``metadata.error`` and in an annotation) is FIGURE_ERROR, and a figure
that carries traces but no plotted point is EMPTY_RESULT, with the counts.

Async advanced-viz compute jobs (complex heatmap, upset, embedding in live mode,
sankey, coverage track) only fail inside a Celery worker, so the default run cannot
see them. Pass --dispatch-compute to enqueue each one through the endpoints the
viewer uses, poll it to completion and report COMPUTE_FAILED with the worker's
error (for example a ZeroDivisionError). It needs a running worker.

Exit code is 0 unless the deployment is unreachable or preflight fails. Pass
--strict to also exit 1 when any component fails.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

API_PREFIX = "/depictio/api/v1"

# A real terminal reports its own width. When the output is piped (CI logs, a
# file), rich would fall back to 80 columns and shred the tables, so widen it.
console = Console(width=None if sys.stdout.isatty() else 130)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


@dataclass
class Reply:
    """One HTTP response, with failures folded into the same shape as successes."""

    status: int | None = None
    payload: Any = None
    detail: str = ""
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class Client:
    def __init__(
        self,
        host: str,
        scheme: str = "https",
        token: str | None = None,
        timeout: float = 60.0,
        insecure: bool = False,
    ) -> None:
        host = host.strip().rstrip("/")
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                scheme = prefix[:-3]
                host = host[len(prefix) :]
        self.host = host
        self.base = f"{scheme}://{host}{API_PREFIX}"
        self.token = token
        self.timeout = timeout
        self.ctx: ssl.SSLContext | None = None
        if insecure:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def call(self, method: str, path: str, body: dict | None = None) -> Reply:
        data = json.dumps(body).encode() if body is not None else None
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                raw = resp.read()
                return Reply(
                    status=resp.status,
                    payload=_decode(raw),
                    elapsed=time.monotonic() - started,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            payload = _decode(raw)
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return Reply(
                status=exc.code,
                payload=payload,
                detail=str(detail) if detail else _text(raw),
                elapsed=time.monotonic() - started,
            )
        except Exception as exc:  # noqa: BLE001 - every transport failure belongs in the report
            return Reply(
                error=f"{type(exc).__name__}: {exc}",
                elapsed=time.monotonic() - started,
            )


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001 - a non-JSON body is itself a finding
        return None


def _text(raw: bytes) -> str:
    return raw.decode(errors="replace").strip()[:200]


# --------------------------------------------------------------------------- #
# Probe planning
#
# Mirrors the viewer's dispatch in
# packages/depictio-react-core/src/components/ComponentRenderer.tsx and the
# request payloads in packages/depictio-react-core/src/api.ts.
# --------------------------------------------------------------------------- #

# Interactive components that read precomputed column specs.
SPECS_INTERACTIVE = {"Slider", "RangeSlider", "DatePicker", "DateRangePicker", "Timeline"}
# Interactive components that read the distinct values of their column.
UNIQUE_VALUES_INTERACTIVE = {"MultiSelect", "Select", "SegmentedControl"}
# Interactive components that issue no request at all.
NO_REQUEST_INTERACTIVE = {"Checkbox", "Switch"}

# Advanced-viz configs name their columns with these suffixes. Verified against
# every viz_kind live on the reference deployments; what this misses is display
# settings (colorscale, normalize, y_scale), not columns.
COLUMN_KEY_SUFFIXES = ("_col", "_column", "_columns", "_cols")
# The two column-bearing config keys that lack one of those suffixes.
EXTRA_COLUMN_KEYS = {"metric_options", "annotation_strips"}

# Secondary data collections some advanced-viz kinds pull alongside their main one.
SECONDARY_DC_KEYS = {
    "matrix_dc_id": "matrix_wf_id",
    "metadata_dc_id": "metadata_wf_id",
}

# Two kinds never call /advanced_viz/data with their own dc_id, so probing it
# would report a failure the viewer never sees:
#   phylogenetic  reads its tree from /advanced_viz/phylogeny/{tree_dc_id}/newick,
#                 and that dc has no Delta table by design (PhylogeneticRenderer.tsx).
#                 Its only data-leg call is for metadata_dc_id, covered separately.
#   coverage_track dispatches compute_coverage_track and nothing else
#                 (CoverageTrackRenderer.tsx).
NO_DATA_LEG = {"phylogenetic", "coverage_track"}


@dataclass
class Check:
    """One component probe: what to request, and how to judge the answer."""

    dashboard_id: str
    dashboard_title: str
    family_title: str
    index: str
    component_type: str
    subtype: str = ""
    dc_id: str | None = None
    dc_tag: str = ""
    probe: str = ""
    method: str = ""
    path: str = ""
    body: dict | None = None
    validate: str = ""
    column: str = ""
    # Base path of the GET endpoint that reports a dispatched job, for compute probes.
    poll_path: str = ""
    verdict: str = ""
    # Why the verdict is what it is, when the reply alone does not say (an error
    # carried inside a 200 payload, the trace counts of an empty figure).
    note: str = ""
    reply: Reply = field(default_factory=Reply)

    @property
    def key(self) -> tuple:
        """Requests sharing this key are issued once and the reply reused."""
        return (self.method, self.path, json.dumps(self.body, sort_keys=True))

    @property
    def label(self) -> str:
        return f"{self.component_type}/{self.subtype}" if self.subtype else self.component_type

    @property
    def reason(self) -> str:
        """The most specific explanation available for the verdict."""
        return self.note or self.reply.detail or self.reply.error

    @property
    def dc_label(self) -> str:
        """Tag first since that is the actionable part, id underneath, kept unbroken."""
        if not self.dc_id:
            return ""
        return (
            f"{self.dc_tag}\n[dim]{self.dc_id}[/dim]" if self.dc_tag else f"[dim]{self.dc_id}[/dim]"
        )


def is_general_stats(meta: dict) -> bool:
    """Port of readMultiqcSelection().isGeneralStats (utils/multiqcSelection.ts)."""
    module = meta.get("selected_module") or meta.get("multiqc_module")
    plot = meta.get("selected_plot") or meta.get("multiqc_plot")
    return (
        module == "general_stats" or plot == "general_stats" or bool(meta.get("is_general_stats"))
    )


def harvest_columns(config: dict) -> list[str]:
    """Collect the column names an advanced-viz component sends to /advanced_viz/data."""
    columns: list[str] = []
    for key, value in config.items():
        if not (key.endswith(COLUMN_KEY_SUFFIXES) or key in EXTRA_COLUMN_KEYS):
            continue
        if isinstance(value, str):
            columns.append(value)
        elif isinstance(value, list):
            columns.extend(v for v in value if isinstance(v, str))
    # Preserve order, drop duplicates. The endpoint caps the projection anyway.
    seen: set[str] = set()
    return [c for c in columns if c and not (c in seen or seen.add(c))][:12]


def plan_checks(dash: dict, family_title: str, dispatch_compute: bool = False) -> list[Check]:
    """Build the probe list for one dashboard from its stored_metadata.

    With ``dispatch_compute`` the async advanced-viz compute kinds also get a probe
    that enqueues the job and polls it to completion (see ``compute_probe``).
    """
    did = dash["dashboard_id"]
    title = dash.get("title") or did
    checks: list[Check] = []

    def new(meta: dict, **kw) -> Check:
        return Check(
            dashboard_id=did,
            dashboard_title=title,
            family_title=family_title,
            index=str(meta.get("index")),
            component_type=str(meta.get("component_type")),
            dc_id=str(meta["dc_id"]) if meta.get("dc_id") else None,
            # The component carries its own tag, which is the only place to get one
            # for a data collection the project no longer declares.
            dc_tag=str(
                meta.get("data_collection_tag")
                or (meta.get("dc_config") or {}).get("data_collection_tag")
                or ""
            ),
            **kw,
        )

    for meta in dash.get("stored_metadata") or []:
        ctype = meta.get("component_type")
        cid = meta.get("index")

        if ctype == "text":
            checks.append(new(meta, probe="none", validate="none", verdict="OK"))

        elif ctype == "card":
            checks.append(
                new(
                    meta,
                    probe="bulk_compute_cards",
                    method="POST",
                    path=f"/dashboards/bulk_compute_cards/{did}",
                    body={"filters": [], "component_ids": None},
                    validate="card",
                )
            )

        elif ctype == "figure":
            checks.append(
                new(
                    meta,
                    probe="render_figure",
                    method="POST",
                    path=f"/dashboards/render_figure/{did}/{cid}",
                    body={"filters": [], "theme": "light"},
                    validate="figure",
                )
            )

        elif ctype == "table":
            checks.append(
                new(
                    meta,
                    probe="render_table",
                    method="POST",
                    path=f"/dashboards/render_table/{did}/{cid}",
                    body={
                        "filters": [],
                        "start": 0,
                        "limit": 100,
                        "sort_by": None,
                        "sort_dir": "desc",
                    },
                    validate="table",
                )
            )

        elif ctype == "map":
            checks.append(
                new(
                    meta,
                    probe="render_map",
                    method="POST",
                    path=f"/dashboards/render_map/{did}/{cid}",
                    body={"filters": [], "theme": "light"},
                    validate="figure",
                )
            )

        elif ctype == "image":
            checks.append(
                new(
                    meta,
                    probe="render_image_paths",
                    method="POST",
                    path=f"/dashboards/render_image_paths/{did}/{cid}",
                    body={"filters": [], "max": 50, "sort_by": None, "sort_dir": "desc"},
                    validate="none",
                )
            )

        elif ctype == "jbrowse":
            checks.append(
                new(
                    meta,
                    probe="render_jbrowse",
                    method="POST",
                    path=f"/dashboards/render_jbrowse/{did}/{cid}",
                    body={"filters": []},
                    validate="none",
                )
            )

        elif ctype == "multiqc":
            if is_general_stats(meta):
                checks.append(
                    new(
                        meta,
                        subtype="general_stats",
                        probe="render_multiqc_general_stats",
                        method="POST",
                        path=f"/dashboards/render_multiqc_general_stats/{did}/{cid}",
                        body={"filters": []},
                        validate="none",
                    )
                )
            else:
                checks.append(
                    new(
                        meta,
                        probe="render_multiqc",
                        method="POST",
                        path=f"/dashboards/render_multiqc/{did}/{cid}",
                        body={"filters": [], "theme": "light"},
                        validate="figure",
                    )
                )

        elif ctype == "interactive":
            sub = str(meta.get("interactive_component_type") or "")
            column = str(meta.get("column_name") or "")
            dc = meta.get("dc_id")
            if sub in NO_REQUEST_INTERACTIVE:
                checks.append(new(meta, subtype=sub, probe="none", validate="none", verdict="OK"))
            elif sub in UNIQUE_VALUES_INTERACTIVE:
                query = urllib.parse.urlencode({"column": column})
                checks.append(
                    new(
                        meta,
                        subtype=sub,
                        probe="unique_values",
                        method="GET",
                        path=f"/deltatables/unique_values/{dc}?{query}",
                        validate="unique_values",
                        column=column,
                    )
                )
            elif sub in SPECS_INTERACTIVE:
                checks.append(
                    new(
                        meta,
                        subtype=sub,
                        probe="specs",
                        method="GET",
                        path=f"/deltatables/specs/{dc}",
                        validate="specs",
                        column=column,
                    )
                )
            else:
                checks.append(
                    new(meta, subtype=sub, probe="none", validate="none", verdict="UNKNOWN_SUBTYPE")
                )

        elif ctype == "advanced_viz":
            config = meta.get("config") or {}
            kind = str(meta.get("viz_kind") or config.get("viz_kind") or "")
            columns = harvest_columns(config)
            if kind not in NO_DATA_LEG:
                checks.append(
                    new(
                        meta,
                        subtype=kind,
                        **_data_probe(meta.get("wf_id"), meta.get("dc_id"), columns),
                    )
                )
            secondary = _plan_secondary(new, meta, config, columns)
            checks.extend(secondary)
            compute = compute_probe(kind, meta, config) if dispatch_compute else None
            if compute:
                checks.append(new(meta, subtype=kind, **compute))
            elif kind in NO_DATA_LEG and not secondary:
                # coverage_track only reaches the API through an async compute job,
                # which only --dispatch-compute runs. Say so rather than let the
                # component's absence from the report read as a pass.
                checks.append(new(meta, subtype=kind, probe="none", verdict="NOT_PROBED"))

        else:
            checks.append(new(meta, probe="none", validate="none", verdict="UNSUPPORTED_TYPE"))

    return checks


# Advanced-viz kinds computed by a Celery job: kind -> endpoint under /advanced_viz.
COMPUTE_ENDPOINTS = {
    "complex_heatmap": "compute_complex_heatmap",
    "upset_plot": "compute_upset",
    "embedding": "compute_embedding",
    "sankey": "compute_sankey",
    "coverage_track": "compute_coverage_track",
}
# Not dispatched, because the viewer only issues them from a user action or a
# viewport: compute_group_compare needs two selected groups, compute_contact_map a
# region and a pixel width.


def compute_payload(kind: str, meta: dict, config: dict) -> dict | None:
    """The body the viewer's renderer sends to dispatch this kind, at its defaults.

    Mirrors the ``payload`` built in the matching ``advanced_viz/*Renderer.tsx``
    (ComplexHeatmapRenderer, UpsetRenderer, EmbeddingRenderer, SankeyRenderer,
    CoverageTrackRenderer) with every user control left at the saved config.
    Returns None when the component cannot dispatch in the viewer either.
    """
    wf_id, dc_id = meta.get("wf_id"), meta.get("dc_id")
    if not wf_id or not dc_id:
        return None
    base: dict[str, Any] = {"wf_id": wf_id, "dc_id": dc_id}

    if kind == "complex_heatmap":
        body = {
            **base,
            "index_column": config.get("index_column") or "sample_id",
            "value_columns": config.get("value_columns"),
            "row_annotation_cols": config.get("row_annotation_cols") or [],
            "col_annotations": config.get("col_annotations"),
            "col_annotation_cols": config.get("col_annotation_cols") or [],
            "annotation_source_dc_tag": config.get("annotation_source_dc_tag"),
            "col_annotation_colors": config.get("col_annotation_colors"),
            "cluster_rows": config.get("cluster_rows", True),
            "cluster_cols": config.get("cluster_cols", True),
            "cluster_method": config.get("cluster_method") or "ward",
            "cluster_metric": config.get("cluster_metric") or "euclidean",
            "normalize": config.get("normalize") or "none",
            "colorscale": config.get("colorscale"),
            "filter_metadata": [],
        }
        if config.get("value_columns_pattern"):
            body["value_columns_pattern"] = config["value_columns_pattern"]
        return body

    if kind == "upset_plot":
        annotation_cols = config.get("default_annotation_cols") or []
        body = {
            **base,
            "set_columns": config.get("set_columns"),
            "set_colors": config.get("set_colors"),
            "annotation_cols": annotation_cols or None,
            "sort_by": config.get("sort_by") or "cardinality",
            "sort_order": config.get("sort_order") or "descending",
            "min_size": config.get("min_size", 1),
            "max_degree": config.get("max_degree"),
            "show_set_sizes": config.get("show_set_sizes", True),
            "show_values": config.get("show_values", False),
            "color_intersections_by": config.get("color_intersections_by") or "none",
            "filter_metadata": [],
        }
        if config.get("set_columns_pattern"):
            body["set_columns_pattern"] = config["set_columns_pattern"]
        return body

    if kind == "embedding":
        method = config.get("compute_method")
        if not method:
            return None  # precomputed coordinates: the data leg is the whole render
        params: dict[str, Any] = {"n_components": 3 if config.get("view_3d") else 2}
        if method == "umap":
            params["n_neighbors"] = config.get("umap_n_neighbors", 15)
            params["min_dist"] = config.get("umap_min_dist", 0.1)
        elif method == "tsne":
            params["perplexity"] = config.get("tsne_perplexity", 30)
            params["n_iter"] = config.get("tsne_n_iter", 1000)
        elif method == "pcoa":
            params["distance"] = config.get("pcoa_distance") or "bray_curtis"
        extra = [c for c in (config.get("cluster_col"), config.get("color_col")) if c]
        extra += [c for c in (config.get("hover_cols") or []) if c and c not in extra]
        return {
            **base,
            "feature_id_col": config.get("sample_id_col") or "sample_id",
            "method": method,
            "params": params,
            "filter_metadata": [],
            "extra_cols": list(dict.fromkeys(extra)),
        }

    if kind == "sankey":
        steps = [c for c in (config.get("step_cols") or []) if isinstance(c, str)]
        depth = config.get("depth")
        if isinstance(depth, int) and depth >= 2:
            steps = steps[:depth]
        if len(steps) < 2:
            return None
        return {
            **base,
            "step_cols": steps,
            "value_col": config.get("value_col"),
            "sort_mode": config.get("sort_mode") or "total_flow",
            "min_link_value": config.get("min_link_value", 0),
            "step_filters": {},
            "option_cols": [c for c in (config.get("available_step_cols") or steps) if c],
            "filter_metadata": [],
        }

    if kind == "coverage_track":
        needed = ("chromosome_col", "position_col", "value_col")
        if not all(config.get(k) for k in needed):
            return None
        return {
            **base,
            "chromosome_col": config["chromosome_col"],
            "position_col": config["position_col"],
            "value_col": config["value_col"],
            "end_col": config.get("end_col"),
            "sample_col": config.get("sample_col"),
            "category_col": config.get("category_col"),
            "chromosomes_filter": config.get("chromosomes_filter") or None,
            "samples_filter": config.get("samples_filter") or None,
            "smoothing_window": config.get("smoothing_window") or 1,
            "max_bins_per_track": 4000,
            "filter_metadata": [],
        }
    return None


def compute_probe(kind: str, meta: dict, config: dict) -> dict | None:
    """Request fields that dispatch one compute job, or None for a kind that has none."""
    endpoint = COMPUTE_ENDPOINTS.get(kind)
    body = compute_payload(kind, meta, config) if endpoint else None
    if not endpoint or body is None:
        return None
    return {
        "probe": f"advanced_viz/{endpoint}",
        "method": "POST",
        "path": f"/advanced_viz/{endpoint}",
        "body": body,
        "validate": "compute",
        "poll_path": f"/advanced_viz/{endpoint}",
    }


def _data_probe(wf_id: Any, dc_id: Any, columns: list[str], label: str = "") -> dict:
    """Request fields for an advanced-viz data probe.

    With no column found in the config there is nothing to project, and
    /advanced_viz/data answers an empty ``columns`` with a 400 the viewer never
    gets. That happens when the config names no columns at all: an upset_plot
    with no ``set_columns`` reads the schema and leaves the sets to
    compute_upset (UpsetRenderer.tsx). Probing the schema then checks what the
    viewer reads, that the Delta table exists and opens.
    """
    suffix = f" ({label})" if label else ""
    if not columns:
        return {
            "probe": f"datacollections/polars_schema{suffix}",
            "method": "GET",
            "path": f"/datacollections/polars_schema/{dc_id}",
            "validate": "schema",
        }
    return {
        "probe": f"advanced_viz/data{suffix}",
        "method": "POST",
        "path": "/advanced_viz/data",
        "body": {
            "wf_id": wf_id,
            "dc_id": dc_id,
            "columns": columns,
            "filter_metadata": [],
            "limit_rows": 200,
        },
        "validate": "advviz",
    }


def _plan_secondary(new, meta: dict, config: dict, columns: list[str]) -> list[Check]:
    """Probe the extra data collections complex_heatmap, upset_plot and phylogenetic pull."""
    extra: list[Check] = []
    kind = str(meta.get("viz_kind") or "")

    for dc_key, wf_key in SECONDARY_DC_KEYS.items():
        dc = config.get(dc_key)
        if not dc:
            continue
        check = new(
            meta,
            subtype=kind,
            **_data_probe(config.get(wf_key) or meta.get("wf_id"), dc, columns, dc_key),
        )
        # A secondary dc has its own tag, so drop the component's and let the
        # project context supply the right one.
        check.dc_id, check.dc_tag = str(dc), ""
        extra.append(check)

    tree_dc = config.get("tree_dc_id")
    if tree_dc:
        check = new(
            meta,
            subtype=kind,
            probe="phylogeny/newick",
            method="GET",
            path=f"/advanced_viz/phylogeny/{tree_dc}/newick",
            validate="none",
        )
        check.dc_id, check.dc_tag = str(tree_dc), ""
        extra.append(check)

    return extra


# --------------------------------------------------------------------------- #
# Project context and verdicts
# --------------------------------------------------------------------------- #


@dataclass
class ProjectContext:
    """Which data collections a dashboard's project actually declares and has ingested."""

    registered: set[str] = field(default_factory=set)
    delta_locations: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    error: str = ""


def fetch_project_context(client: Client, dashboard_id: str) -> ProjectContext:
    reply = client.call("GET", f"/projects/get/from_dashboard_id/{dashboard_id}")
    if not reply.ok or not isinstance(reply.payload, dict):
        return ProjectContext(error=reply.detail or reply.error or f"HTTP {reply.status}")
    project = reply.payload.get("project") or {}
    ctx = ProjectContext(delta_locations=reply.payload.get("delta_locations") or {})
    for workflow in project.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            dc_id = str(dc.get("_id"))
            ctx.registered.add(dc_id)
            ctx.tags[dc_id] = str(dc.get("data_collection_tag") or "")
    return ctx


# Verdicts that mean the component is fine.
PASSING = {"OK"}
# Verdicts that are worth surfacing but are not hard failures.
WARNING = {
    "EMPTY_RESULT",
    "PREPARING",
    "UNSUPPORTED_TYPE",
    "UNKNOWN_SUBTYPE",
    "NOT_PROBED",
    "COMPUTE_TIMEOUT",
}
# A figure payload whose annotation reads like one of these is an error figure,
# not a chart: create_error_figure() prefixes its message with a warning sign, and
# the map renderer writes "Map error: ...".
ERROR_ANNOTATION_MARKERS = (
    "\u26a0",
    "code execution error",
    "code validation failed",
    "execution error",
    "syntax error",
    "map error",
)
# Trace keys that hold plotted values, whatever the trace type.
POINT_KEYS = (
    "x", "y", "z", "values", "lat", "lon", "locations", "r", "theta", "labels",
    "a", "b", "c", "open", "high", "low", "close", "u", "v", "w",
)  # fmt: skip


def _size(value: Any) -> int:
    """Number of non-null leaf values in a (possibly nested) trace array."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return sum(_size(v) for v in value)
    if isinstance(value, dict):
        # Plotly 6 ships typed arrays as {"dtype": ..., "bdata": "<base64>"}.
        return 1 if value.get("bdata") else 0
    return 1


def trace_points(trace: dict) -> int:
    """How many values one trace plots; a trace of an unknown shape counts as 1."""
    kind = trace.get("type")
    if kind == "sankey":
        return _size((trace.get("link") or {}).get("value"))
    if kind == "table":
        return _size((trace.get("cells") or {}).get("values"))
    if kind in ("parcats", "parcoords", "splom"):
        dims = trace.get("dimensions") or []
        return sum(_size(d.get("values")) for d in dims if isinstance(d, dict))
    if kind == "indicator":
        return 1
    present = [k for k in POINT_KEYS if k in trace]
    if not present:
        return 1
    return max(_size(trace[k]) for k in present)


def figure_stats(figure: Any) -> tuple[int, int]:
    """(traces, plotted values) of a Plotly figure dict."""
    traces = [t for t in ((figure or {}).get("data") or []) if isinstance(t, dict)]
    return len(traces), sum(trace_points(t) for t in traces)


def figure_annotations(figure: Any) -> list[str]:
    layout = (figure or {}).get("layout") or {}
    annotations = layout.get("annotations") or []
    return [str(a.get("text") or "") for a in annotations if isinstance(a, dict)]


def figure_error(payload: dict) -> str:
    """The error a figure render carries inside an HTTP 200, or an empty string.

    render_figure answers a failed code-mode figure with status 200: the figure is a
    blank chart with the message as an annotation, and the same text in
    ``metadata.error``. The UI-mode and map paths write only the annotation.
    """
    error = (payload.get("metadata") or {}).get("error")
    if error:
        return str(error)
    for text in figure_annotations(payload.get("figure")):
        if any(marker in text.lower() for marker in ERROR_ANNOTATION_MARKERS):
            return text.strip()
    return ""


def validate_figure(check: Check, payload: dict) -> str:
    error = figure_error(payload)
    if error:
        check.note = error[:300]
        return "FIGURE_ERROR"
    figure = payload.get("figure") or {}
    traces, points = figure_stats(figure)
    if traces and points:
        return "OK"
    notes = [t.strip() for t in figure_annotations(figure) if t.strip()]
    counts = "no traces" if not traces else f"{traces} trace(s), 0 plotted points"
    check.note = f"{counts}" + (f" ({'; '.join(notes)[:120]})" if notes else "")
    return "EMPTY_RESULT"


def validate_compute(check: Check, payload: dict) -> str:
    """Judge a polled compute job: did the worker finish, and did it produce anything."""
    status = payload.get("status")
    if status == "failed":
        check.note = str(payload.get("error") or "compute task failed")[:300]
        return "COMPUTE_FAILED"
    if status != "done":
        check.note = f"job still {status or 'unknown'} when polling stopped"
        return "COMPUTE_TIMEOUT"
    result = payload.get("result")
    if not isinstance(result, dict):
        check.note = "job finished with no result"
        return "EMPTY_RESULT"
    figure = result.get("figure")
    if figure is not None:
        error = figure_error({"figure": figure})
        if error:
            check.note = error[:300]
            return "FIGURE_ERROR"
        traces, points = figure_stats(figure)
        if not (traces and points):
            check.note = "no traces" if not traces else f"{traces} trace(s), 0 plotted points"
            return "EMPTY_RESULT"
    emptiness = {
        "embedding": len(result.get("sample_ids") or []),
        "sankey": result.get("link_count"),
        "coverage_track": result.get("row_count"),
        "complex_heatmap": result.get("row_count"),
        "upset_plot": result.get("row_count"),
    }
    count = emptiness.get(check.subtype)
    if count is not None and not count:
        check.note = f"{check.subtype} computed over 0 rows"
        return "EMPTY_RESULT"
    return "OK"


def validate_payload(check: Check, payload: Any) -> str:
    """A 2xx is not proof of a render. Cards in particular return 200 with null values."""
    kind = check.validate
    if kind == "none":
        return "OK"
    if not isinstance(payload, dict):
        return "EMPTY_RESULT"

    if kind == "card":
        values = payload.get("values") or {}
        return "OK" if values.get(check.index) is not None else "CARD_NO_VALUE"
    if kind == "figure":
        return validate_figure(check, payload)
    if kind == "compute":
        return validate_compute(check, payload)
    if kind == "table":
        return "OK" if payload.get("rows") else "EMPTY_RESULT"
    if kind == "advviz":
        return "OK" if payload.get("row_count") else "EMPTY_RESULT"
    if kind == "schema":
        return "OK" if payload else "EMPTY_RESULT"
    if kind == "unique_values":
        return "OK" if payload.get("values") else "EMPTY_RESULT"
    return "OK"


def validate_specs(check: Check, payload: Any) -> str:
    """Specs came back; confirm the column the control binds to is actually in them.

    A renamed or dropped column renders an inert control rather than an error,
    so the status code alone would not catch it.
    """
    if not check.column:
        return "OK"
    names: set[str] = set()
    if isinstance(payload, list):
        names = {str(entry.get("name")) for entry in payload if isinstance(entry, dict)}
    elif isinstance(payload, dict):
        names = {str(k) for k in payload}
    if not names:
        return "EMPTY_RESULT"
    return "OK" if check.column in names else "COLUMN_MISSING"


def classify(check: Check, ctx: ProjectContext | None) -> str:
    """Turn one reply into a verdict, using project context to explain failures."""
    reply = check.reply
    if reply.status is None:
        return "NETWORK_ERROR"
    if reply.status == 202:
        return "PREPARING"
    if reply.ok:
        if check.validate == "specs":
            return validate_specs(check, reply.payload)
        return validate_payload(check, reply.payload)

    detail = (reply.detail or "").lower()
    # The API distinguishes these cases explicitly; prefer its own account.
    if "no deltatable found" in detail or "no materialised delta table" in detail:
        return "DC_NOT_INGESTED"
    if "no aggregation data" in detail:
        return "DC_NO_AGGREGATION"

    # Otherwise fall back to what the project document says about this dc_id.
    # This is what separates a genuine permission denial from a dashboard bound
    # to a data collection that was never seeded.
    if ctx and not ctx.error and check.dc_id:
        if check.dc_id not in ctx.registered:
            return "DC_NOT_REGISTERED"
        if not ctx.delta_locations.get(check.dc_id):
            return "DC_NOT_INGESTED"

    if reply.status in (401, 403):
        return "UNAUTHORIZED"
    if reply.status == 503:
        return "SERVICE_UNAVAILABLE"
    if reply.status == 404:
        return "NOT_FOUND"
    if reply.status >= 500:
        return "SERVER_ERROR"
    return f"HTTP_{reply.status}"


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #


def preflight(client: Client) -> dict:
    """Confirm the deployment is actually serving Depictio, and report its health."""
    info: dict[str, Any] = {"host": client.host}

    status = client.call("GET", "/utils/status")
    if status.status is None:
        raise SystemExit(
            f"[fatal] {client.host} is unreachable: {status.error}\n"
            f"        If this is a TLS error, the host may not be routed to Depictio "
            f"(a default ingress certificate). Re-run with --insecure to confirm."
        )
    if not status.ok or not isinstance(status.payload, dict):
        raise SystemExit(
            f"[fatal] {client.host} did not return a Depictio status payload "
            f"(HTTP {status.status}: {status.detail or 'non-JSON body'}).\n"
            f"        The host is answering but is not routed to a Depictio API."
        )
    info["version"] = status.payload.get("version")

    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="dim")
    facts.add_column()
    facts.add_row("Host", f"[bold]{client.host}[/bold]")
    facts.add_row("Version", f"[bold]{info['version']}[/bold]")

    auth = client.call("GET", "/auth/me/optional")
    if auth.ok and isinstance(auth.payload, dict):
        info["auth"] = {
            k: auth.payload.get(k)
            for k in ("is_public_mode", "is_demo_mode", "is_single_user_mode")
        }
        modes = [k.removeprefix("is_").removesuffix("_mode") for k, v in info["auth"].items() if v]
        facts.add_row("Auth mode", ", ".join(modes) or "standard")
    if client.token:
        me = client.call("GET", "/auth/me")
        if me.ok and isinstance(me.payload, dict):
            facts.add_row(
                "Token", f"{me.payload.get('email')} (admin={me.payload.get('is_admin')})"
            )
        else:
            facts.add_row(
                "Token", f"[yellow]rejected (HTTP {me.status}), continuing anonymously[/yellow]"
            )
            client.token = None

    health = client.call("GET", "/utils/health/initialization")
    pending: list[dict] = []
    if health.ok and isinstance(health.payload, dict):
        info["initialization"] = health.payload
        dcs = health.payload.get("data_collections") or {}
        state = str(health.payload.get("status"))
        colour = "green" if state == "healthy" else ("yellow" if state == "degraded" else "red")
        pending = dcs.get("pending") or []
        facts.add_row(
            "Initialization",
            f"[{colour}]{state}[/{colour}]  "
            f"{dcs.get('registered')}/{dcs.get('expected')} data collections registered",
        )
    console.print(Panel(facts, title="Deployment", title_align="left", border_style="dim"))

    if pending:
        # Not every pending entry is a fault: tree and MultiQC data collections
        # have no Delta table by design and still render. Shown for context only.
        table = Table(
            title="Data collections reported pending",
            box=box.SIMPLE_HEAVY,
            header_style="bold",
            title_justify="left",
        )
        table.add_column("Project")
        table.add_column("Tag")
        table.add_column("Data collection ID", style="dim")
        for entry in pending:
            table.add_row(str(entry.get("project")), str(entry.get("tag")), str(entry.get("id")))
        console.print(table)
    return info


def enumerate_dashboards(client: Client) -> list[dict]:
    path = "/dashboards/list_all" if client.token else "/dashboards/list"
    reply = client.call("GET", f"{path}?include_child_tabs=true")
    if not reply.ok or not isinstance(reply.payload, list):
        raise SystemExit(
            f"[fatal] could not list dashboards (HTTP {reply.status}: {reply.detail or reply.error})"
        )
    return reply.payload


def group_families(dashboards: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Order dashboards as main tab followed by its child tabs.

    A child whose parent is not in the set (which --only makes easy to do) is
    promoted to top level rather than dropped, so filtering can never silently
    check nothing.
    """
    children: dict[str, list[dict]] = defaultdict(list)
    parents = []
    present = {str(d.get("dashboard_id")) for d in dashboards}
    for dash in dashboards:
        parent_id = str(dash.get("parent_dashboard_id") or "")
        if dash.get("is_main_tab") or not parent_id or parent_id not in present:
            parents.append(dash)
        else:
            children[parent_id].append(dash)
    families = []
    for parent in parents:
        kids = sorted(
            children.get(str(parent["dashboard_id"]), []), key=lambda d: d.get("tab_order") or 0
        )
        families.append((parent, kids))
    return families


def poll_job(
    client: Client, poll_path: str, reply: Reply, timeout: float, interval: float = 2.0
) -> Reply:
    """Follow a dispatched compute job until it is done, failed or the budget runs out.

    The dispatch reply names the job (``job_id``) and may already be terminal, when an
    identical computation is cached. Any other answer is returned unchanged so the
    classifier reports the HTTP error itself.
    """
    job = reply.payload
    if not reply.ok or not isinstance(job, dict) or not job.get("job_id"):
        return reply
    job_id = job["job_id"]
    deadline = time.monotonic() + timeout
    while job.get("status") not in ("done", "failed") and time.monotonic() < deadline:
        time.sleep(interval)
        polled = client.call("GET", f"{poll_path}/{job_id}")
        if not polled.ok or not isinstance(polled.payload, dict):
            return polled
        reply, job = polled, polled.payload
    return reply


def run_checks(
    client: Client,
    checks: list[Check],
    concurrency: int,
    multiqc_retries: int,
    compute_timeout: float = 120.0,
) -> None:
    """Issue every distinct request once, then hand the reply to each check sharing it."""
    pending = [c for c in checks if c.method]
    grouped: dict[tuple, list[Check]] = defaultdict(list)
    for check in pending:
        grouped[check.key].append(check)

    def issue(key: tuple) -> tuple[tuple, Reply]:
        group = grouped[key]
        method, path, body_json = key
        body = json.loads(body_json) if body_json != "null" else None
        reply = client.call(method, path, body)
        # MultiQC figures are prepared by a Celery worker; 202 means "come back".
        attempts = multiqc_retries if group[0].component_type == "multiqc" else 0
        while reply.status == 202 and attempts > 0:
            time.sleep(5)
            reply = client.call(method, path, body)
            attempts -= 1
        if group[0].poll_path:
            reply = poll_job(client, group[0].poll_path, reply, compute_timeout)
        return key, reply

    if not grouped:
        return
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for key, reply in pool.map(issue, list(grouped)):
            for check in grouped[key]:
                check.reply = reply


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def component_rows(checks: list[Check]) -> list[dict]:
    return [
        {
            "dashboard_id": c.dashboard_id,
            "dashboard_title": c.dashboard_title,
            "family": c.family_title,
            "index": c.index,
            "component_type": c.component_type,
            "subtype": c.subtype,
            "dc_id": c.dc_id,
            "dc_tag": c.dc_tag,
            "probe": c.probe,
            "method": c.method,
            "path": c.path,
            "status": c.reply.status,
            "detail": c.reason,
            "verdict": c.verdict,
        }
        for c in checks
    ]


def _severity(verdict: str) -> str:
    if verdict in PASSING:
        return "ok"
    return "warn" if verdict in WARNING else "fail"


STYLE = {"ok": "green", "warn": "yellow", "fail": "red"}


def print_report(
    families: list[tuple[dict, list[dict]]], by_dashboard: dict[str, list[Check]]
) -> None:
    """One row per dashboard, then one row per failing probe."""
    overview = Table(
        title="Dashboards", box=box.SIMPLE_HEAVY, header_style="bold", title_justify="left"
    )
    overview.add_column("Status", width=6)
    overview.add_column("Dashboard", style="bold", max_width=44)
    overview.add_column("Dashboard ID", style="dim")
    overview.add_column("Probes", justify="right")
    overview.add_column("OK", justify="right", style="green")
    overview.add_column("Fail", justify="right", style="red")
    overview.add_column("Warn", justify="right", style="yellow")

    # One detail table per affected dashboard. Grouping this way drops the
    # repeated dashboard column and leaves room for the columns that matter.
    details: list[Table] = []

    for parent, kids in families:
        for dash in [parent, *kids]:
            did = str(dash["dashboard_id"])
            checks = by_dashboard.get(did) or []
            flagged = [c for c in checks if c.verdict not in PASSING]
            hard = [c for c in flagged if c.verdict not in WARNING]
            warn = [c for c in flagged if c.verdict in WARNING]
            sev = "fail" if hard else ("warn" if warn else "ok")
            colour = STYLE[sev]
            title = str(dash.get("title") or did)
            if dash is not parent:
                title = f"  └ {title}"
            overview.add_row(
                f"[{colour}]{sev.upper()}[/{colour}]",
                title,
                did,
                str(len(checks)),
                str(len(checks) - len(flagged)),
                str(len(hard)) if hard else "",
                str(len(warn)) if warn else "",
            )
            if not flagged:
                continue
            table = Table(
                title=f"[{colour}]{sev.upper()}[/{colour}]  {dash.get('title')}  [dim]{did}[/dim]",
                box=box.SIMPLE_HEAVY,
                header_style="bold",
                title_justify="left",
                padding=(0, 1),
            )
            table.add_column("Component", max_width=26, overflow="fold")
            table.add_column("Type", max_width=24)
            table.add_column("Verdict")
            table.add_column("Data collection", max_width=26, overflow="fold")
            table.add_column("Request", overflow="fold")
            for check in flagged:
                vcol = STYLE[_severity(check.verdict)]
                http = check.reply.status
                request = check.probe + (f" -> {http}" if http is not None else "")
                reason = check.reason[:150]
                table.add_row(
                    check.index,
                    check.label,
                    f"[{vcol}]{check.verdict}[/{vcol}]",
                    check.dc_label,
                    request + (f"\n[dim]{reason}[/dim]" if reason else ""),
                )
            details.append(table)

    console.print()
    console.print(overview)
    for table in details:
        console.print(table)


def print_summary(
    checks: list[Check], contexts: dict[str, ProjectContext], dispatched: bool = False
) -> int:
    failed = [c for c in checks if c.verdict not in PASSING]
    buckets = Counter(c.verdict for c in failed)
    dashboards = {c.dashboard_id for c in checks}
    # A component can carry more than one probe (an advanced viz that also pulls
    # a matrix or tree data collection), so count the two separately.
    components = {(c.dashboard_id, c.index) for c in checks}
    broken = {(c.dashboard_id, c.index) for c in failed if c.verdict not in WARNING}
    warned = {(c.dashboard_id, c.index) for c in failed if c.verdict in WARNING} - broken
    healthy = len(components) - len(broken) - len(warned)

    table = Table(title="Summary", box=box.SIMPLE_HEAVY, header_style="bold", title_justify="left")
    table.add_column("Verdict")
    table.add_column("Probes", justify="right")
    table.add_column("Components", justify="right")
    table.add_column("Dashboards", justify="right")
    table.add_column("Data collections", overflow="fold")

    for verdict, count in buckets.most_common():
        rows = [c for c in failed if c.verdict == verdict]
        colour = STYLE[_severity(verdict)]
        # Prefer the tag the component itself carries; fall back to the project
        # document for secondary data collections that have no component tag.
        labels = {}
        for c in rows:
            if not c.dc_id:
                continue
            tag = c.dc_tag or next(
                (ctx.tags.get(c.dc_id) for ctx in contexts.values() if ctx.tags.get(c.dc_id)), ""
            )
            labels[c.dc_id] = f"{tag}  [dim]{c.dc_id}[/dim]" if tag else f"[dim]{c.dc_id}[/dim]"
        table.add_row(
            f"[{colour}]{verdict}[/{colour}]",
            str(count),
            str(len({(c.dashboard_id, c.index) for c in rows})),
            str(len({c.dashboard_id for c in rows})),
            "\n".join(sorted(labels.values())),
        )

    headline = (
        f"[bold]{len(dashboards)}[/bold] dashboards   "
        f"[bold]{len(components)}[/bold] components ({len(checks)} probes)   "
        f"[green]{healthy} ok[/green]   "
        f"[red]{len(broken)} failing[/red]   "
        f"[yellow]{len(warned)} warning[/yellow]"
    )
    console.print()
    console.print(Panel(headline, title="Result", title_align="left", border_style="dim"))
    if buckets:
        console.print(table)
    if dispatched:
        console.print(
            "[dim]Async advanced-viz compute jobs (embedding in live mode, upset, complex "
            "heatmap, coverage track, sankey) were dispatched and polled. Group comparison and "
            "windowed contact maps need a user action and are not.[/dim]"
        )
    else:
        console.print(
            "[dim]Async advanced-viz compute jobs (embedding, upset, complex heatmap, coverage "
            "track, sankey) are not dispatched; re-run with --dispatch-compute to run them. For "
            "most kinds the /advanced_viz/data leg is still checked; coverage_track has no such "
            "leg and is reported NOT_PROBED.[/dim]"
        )
    return len(broken)


def write_markdown(path: str, host: str, info: dict, rows: list[dict]) -> None:
    failing = [r for r in rows if r["verdict"] not in PASSING]
    lines = [
        f"# Deployment check: {host}",
        "",
        f"- Version: `{info.get('version')}`",
        f"- Initialization: `{(info.get('initialization') or {}).get('status')}`",
        f"- Components: {len(rows)} checked, {len(failing)} failing",
        "",
    ]
    if failing:
        lines += [
            "| Dashboard | Component | Type | Probe | Verdict | Status | Data collection | Detail |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in failing:
            detail = (r["detail"] or "").replace("|", "\\|")[:120]
            subtype = f"/{r['subtype']}" if r["subtype"] else ""
            dc = r["dc_id"] or ""
            if dc and r.get("dc_tag"):
                dc = f"`{dc}` ({r['dc_tag']})"
            elif dc:
                dc = f"`{dc}`"
            lines.append(
                f"| {r['dashboard_title']} | `{r['index']}` | {r['component_type']}{subtype} "
                f"| {r['probe']} | `{r['verdict']}` | {r['status']} | {dc} | {detail} |"
            )
    else:
        lines.append("All components rendered.")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--host", required=True, help="Viewer or API host, with or without scheme")
    ap.add_argument("--scheme", default="https", choices=["https", "http"])
    ap.add_argument("--token-file", help="File holding an admin bearer token (one line)")
    ap.add_argument(
        "--only",
        nargs="*",
        help="Restrict to these dashboard ids (a main tab id includes its child tabs)",
    )
    ap.add_argument("--concurrency", type=int, default=4, help="Parallel in-flight requests")
    ap.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout in seconds")
    ap.add_argument(
        "--multiqc-retries", type=int, default=3, help="Re-polls for a 202 MultiQC render"
    )
    ap.add_argument(
        "--dispatch-compute",
        action="store_true",
        help="Also enqueue the async advanced-viz compute jobs (complex heatmap, upset, "
        "embedding, sankey, coverage track) and report the errors their worker raises",
    )
    ap.add_argument(
        "--compute-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for each compute job before reporting COMPUTE_TIMEOUT",
    )
    ap.add_argument("--insecure", action="store_true", help="Skip TLS verification")
    ap.add_argument("--json", dest="json_out", help="Write the per-component report as JSON")
    ap.add_argument("--markdown", dest="md_out", help="Write a paste-able Markdown report")
    ap.add_argument("--strict", action="store_true", help="Exit 1 if any component fails")
    ap.add_argument("--dry-run", action="store_true", help="List dashboards and exit")
    args = ap.parse_args()

    token = None
    if args.token_file:
        token = open(args.token_file).read().strip() or None
        if not token:
            raise SystemExit(f"Empty token in {args.token_file}")

    client = Client(
        args.host, scheme=args.scheme, token=token, timeout=args.timeout, insecure=args.insecure
    )

    info = preflight(client)
    dashboards = enumerate_dashboards(client)
    if args.only:
        # A main tab id selects its whole family: the child tabs hold most of the
        # components, and have ids of their own that nobody copies from a URL.
        wanted = set(args.only)
        dashboards = [
            d
            for d in dashboards
            if str(d.get("dashboard_id")) in wanted or str(d.get("parent_dashboard_id")) in wanted
        ]
    families = group_families(dashboards)

    if args.dry_run:
        table = Table(
            title=f"{len(dashboards)} dashboards in {len(families)} families",
            box=box.SIMPLE_HEAVY,
            header_style="bold",
            title_justify="left",
        )
        table.add_column("Dashboard", style="bold", max_width=48)
        table.add_column("Dashboard ID", style="dim")
        table.add_column("Child tabs", justify="right")
        for parent, kids in families:
            table.add_row(
                str(parent.get("title")), str(parent["dashboard_id"]), str(len(kids)) or ""
            )
            for kid in kids:
                table.add_row(f"  └ {kid.get('title')}", str(kid["dashboard_id"]), "")
        console.print(table)
        return 0
    console.print(f"[dim]{len(dashboards)} dashboards in {len(families)} families[/dim]")

    # Fetch each dashboard document, plan its probes, and resolve its project once.
    all_checks: list[Check] = []
    by_dashboard: dict[str, list[Check]] = {}
    contexts: dict[str, ProjectContext] = {}
    ctx_by_dashboard: dict[str, ProjectContext] = {}

    for parent, kids in families:
        family_title = str(parent.get("title") or parent["dashboard_id"])
        for dash in [parent, *kids]:
            did = str(dash["dashboard_id"])
            reply = client.call("GET", f"/dashboards/get/{did}")
            if not reply.ok or not isinstance(reply.payload, dict):
                check = Check(
                    dashboard_id=did,
                    dashboard_title=str(dash.get("title") or did),
                    family_title=family_title,
                    index="-",
                    component_type="dashboard",
                    probe="dashboards/get",
                    verdict="DASHBOARD_UNREADABLE",
                )
                check.reply = reply
                all_checks.append(check)
                by_dashboard[did] = [check]
                continue

            checks = plan_checks(reply.payload, family_title, args.dispatch_compute)
            by_dashboard[did] = checks
            all_checks.extend(checks)

            project_id = str(reply.payload.get("project_id") or did)
            if project_id not in contexts:
                contexts[project_id] = fetch_project_context(client, did)
            ctx_by_dashboard[did] = contexts[project_id]

    with console.status(
        f"Probing {len(all_checks)} components (concurrency {args.concurrency})..."
    ):
        run_checks(client, all_checks, args.concurrency, args.multiqc_retries, args.compute_timeout)

    for check in all_checks:
        ctx = ctx_by_dashboard.get(check.dashboard_id)
        if not check.verdict:
            check.verdict = classify(check, ctx)
        if not check.dc_tag and ctx and check.dc_id:
            check.dc_tag = ctx.tags.get(check.dc_id, "")

    # A data collection referenced as a secondary (matrix, tree, metadata) carries
    # no tag of its own, but another component may name the same one. Pool every
    # tag seen anywhere so each data collection is reported by name, not just id.
    tag_by_dc = {c.dc_id: c.dc_tag for c in all_checks if c.dc_id and c.dc_tag}
    for check in all_checks:
        if check.dc_id and not check.dc_tag:
            check.dc_tag = tag_by_dc.get(check.dc_id, "")

    print_report(families, by_dashboard)
    failures = print_summary(all_checks, contexts, args.dispatch_compute)

    rows = component_rows(all_checks)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"host": client.host, "info": info, "components": rows}, fh, indent=2)
        console.print(f"[dim]JSON report written to {args.json_out}[/dim]")
    if args.md_out:
        write_markdown(args.md_out, client.host, info, rows)
        console.print(f"[dim]Markdown report written to {args.md_out}[/dim]")

    return 1 if (failures and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
