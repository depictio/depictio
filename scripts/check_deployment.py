#!/usr/bin/env python3
"""Check that every dashboard on a live Depictio deployment still renders.

Walks every dashboard and every tab the API returns, then replays, per component,
the exact data fetch the React viewer issues for that component type. Reports
which components fail and attributes each failure to a root cause.

Run it after a deployment. No browser needed. The only dependency is rich, which
is already pinned in pyproject, so use the project interpreter:

    ./depictio-venv-dash-v3/bin/python scripts/check_deployment.py --host demo.depictio.embl.org
    uv run python scripts/check_deployment.py --host dev.demo.depictio.embl.org --strict
    uv run python scripts/check_deployment.py --host localhost:5080 --scheme http

Auth defaults to sending no Authorization header. On a deployment running in
public mode that is equivalent to the temporary-user session the browser creates,
so the run reproduces what an ordinary visitor sees. Pass --token-file with an
admin bearer token to also cover private dashboards. On a K8s deployment, mint
one from the backend pod's per-admin config (note the file is named
{username}_config.yaml, not admin_config.yaml)::

    NS=datasci-depictio-project-demo-dev
    POD=$(kubectl -n $NS get pods -o name | grep -m1 depictio-backend | sed 's|pod/||')
    kubectl -n $NS exec $POD -c depictio-backend -- python3 -c \
      "import yaml;print(yaml.safe_load(open('/app/depictio/.depictio/thomas.weber_config.yaml'))['user']['token']['access_token'])" \
      > /tmp/demo_admin_token

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
    verdict: str = ""
    reply: Reply = field(default_factory=Reply)

    @property
    def key(self) -> tuple:
        """Requests sharing this key are issued once and the reply reused."""
        return (self.method, self.path, json.dumps(self.body, sort_keys=True))

    @property
    def label(self) -> str:
        return f"{self.component_type}/{self.subtype}" if self.subtype else self.component_type

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


def plan_checks(dash: dict, family_title: str) -> list[Check]:
    """Build the probe list for one dashboard from its stored_metadata."""
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
                        probe="advanced_viz/data",
                        method="POST",
                        path="/advanced_viz/data",
                        body={
                            "wf_id": meta.get("wf_id"),
                            "dc_id": meta.get("dc_id"),
                            "columns": columns,
                            "filter_metadata": [],
                            "limit_rows": 200,
                        },
                        validate="advviz",
                    )
                )
            secondary = _plan_secondary(new, meta, config, columns)
            checks.extend(secondary)
            if kind in NO_DATA_LEG and not secondary:
                # coverage_track only reaches the API through an async compute job,
                # which this script does not dispatch. Say so rather than let the
                # component's absence from the report read as a pass.
                checks.append(new(meta, subtype=kind, probe="none", verdict="NOT_PROBED"))

        else:
            checks.append(new(meta, probe="none", validate="none", verdict="UNSUPPORTED_TYPE"))

    return checks


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
            probe=f"advanced_viz/data ({dc_key})",
            method="POST",
            path="/advanced_viz/data",
            body={
                "wf_id": config.get(wf_key) or meta.get("wf_id"),
                "dc_id": dc,
                "columns": columns,
                "filter_metadata": [],
                "limit_rows": 200,
            },
            validate="advviz",
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
WARNING = {"EMPTY_RESULT", "PREPARING", "UNSUPPORTED_TYPE", "UNKNOWN_SUBTYPE", "NOT_PROBED"}


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
        return "OK" if ((payload.get("figure") or {}).get("data") or []) else "EMPTY_RESULT"
    if kind == "table":
        return "OK" if payload.get("rows") else "EMPTY_RESULT"
    if kind == "advviz":
        return "OK" if payload.get("row_count") else "EMPTY_RESULT"
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


def run_checks(client: Client, checks: list[Check], concurrency: int, multiqc_retries: int) -> None:
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
            "detail": c.reply.detail or c.reply.error,
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
                reason = (check.reply.detail or check.reply.error)[:150]
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


def print_summary(checks: list[Check], contexts: dict[str, ProjectContext]) -> int:
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
    console.print(
        "[dim]Async advanced-viz compute jobs (embedding, upset, complex heatmap, coverage "
        "track, sankey) are not dispatched. For most kinds the /advanced_viz/data leg is still "
        "checked; coverage_track has no such leg and is reported NOT_PROBED.[/dim]"
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
    ap.add_argument("--only", nargs="*", help="Restrict to these dashboard ids")
    ap.add_argument("--concurrency", type=int, default=4, help="Parallel in-flight requests")
    ap.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout in seconds")
    ap.add_argument(
        "--multiqc-retries", type=int, default=3, help="Re-polls for a 202 MultiQC render"
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
        wanted = set(args.only)
        dashboards = [d for d in dashboards if str(d.get("dashboard_id")) in wanted]
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

            checks = plan_checks(reply.payload, family_title)
            by_dashboard[did] = checks
            all_checks.extend(checks)

            project_id = str(reply.payload.get("project_id") or did)
            if project_id not in contexts:
                contexts[project_id] = fetch_project_context(client, did)
            ctx_by_dashboard[did] = contexts[project_id]

    with console.status(
        f"Probing {len(all_checks)} components (concurrency {args.concurrency})..."
    ):
        run_checks(client, all_checks, args.concurrency, args.multiqc_retries)

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
    failures = print_summary(all_checks, contexts)

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
