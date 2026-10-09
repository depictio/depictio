#!/usr/bin/env python3
"""Rebuild the penguins_versioned demo from nothing, then prove it time-travels.

Three moving parts that have to agree:

  1. the project, from ``project.yaml`` (two table collections and their
     persisted join);
  2. three Delta histories: the two tables, which move on different
     schedules (one commit per batch that touches each), and the join, which
     ``depictio ingest`` rebuilds after every batch and so moves with either;
  3. one dashboard family carrying five named versions, each saved while its
     own batch was the current data.

The order is the whole point. Batch N is ingested and *then* dashboard
version N is imported, alternating, because a version stamps the Delta version
of every collection it reads **at the moment it is captured**. Ingest
everything first and every version stamps the newest commits: labels, counts
and stamps all look right, and "this version's data" quietly shows the complete
survey. ``verify`` asserts the exact stamp of each collection in each version,
which is the check that cannot pass on that mistake.

Batches 3 and 5 ingest one collection each (``--data-collection-tag``), so the
other one keeps its commit and the two pins diverge. A plain re-ingest would
rewrite both tables with identical rows and a new commit each, and the story
"only one dataset moved" would be false in the one place it is recorded. The
join is rebuilt at those steps too (the CLI runs every persisted join after
processing, whatever ``--data-collection-tag`` names) and commits, because one
of its inputs moved. Had neither moved, its rows would come out the same and
nothing would be written.

Each dashboard version is written by the YAML import endpoint, keyed by a fixed
``source_key`` so the next import replaces the same family even after its title
changes. An import records an ``import`` version itself (it is a
content-changing route, see CLAUDE.md), and ``POST /{id}/versions`` then names
that version rather than writing a second one. That is the same pair of calls
the editor makes for "Bookmark this state".

Idempotent: it deletes the project first (which cascades to its Delta tables,
dashboards and version ledgers), so a second run gives the same result.

Usage, on a host running `depictio local up` (DEPICTIO_LOCAL_HOME exported):

    .venv/bin/python depictio/projects/init/penguins_versioned/rebuild_demo.py --server local
    .venv/bin/python depictio/projects/init/penguins_versioned/rebuild_demo.py --server local --verify

Inside the backend container of a docker compose deployment:

    python /app/depictio/projects/init/penguins_versioned/rebuild_demo.py \\
        --server /app/depictio/.depictio/cli_local.yaml
"""

from __future__ import annotations

import argparse
import array
import base64
import csv
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import stage_batch
import yaml
from penguins_story import (
    BATCHES_DIR,
    DC_IDS,
    DD,
    DEFAULT_DATA_ROOT,
    JOIN,
    JOIN_ID,
    JOIN_NAME,
    PF,
    PROJECT_ID,
    PROJECT_NAME,
    PROJECT_YAML,
    SOURCE_KEY,
    STEPS,
    Step,
    commit_rows,
)

#: Written by the ledger on a family's first tracked save. Not one of ours.
BASELINE_LABEL = "Before first tracked change"


class Fail(Exception):
    """A step did not produce the state the next step needs."""


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _step(msg: str) -> None:
    print(f"\n\033[1m==> {msg}\033[0m", flush=True)


# --------------------------------------------------------------------------
# Server and API
# --------------------------------------------------------------------------


def resolve_server(value: str) -> Path:
    """The CLI configuration file for ``--server``: 'local' or a path."""
    if value.strip().lower() == "local":
        try:
            from depictio.cli.cli.utils.server_target import local_cli_config
        except ImportError as exc:  # pragma: no cover - only without the CLI installed
            raise Fail(f"--server local needs the depictio CLI importable: {exc}") from exc
        return Path(local_cli_config())
    return Path(value).expanduser()


class Api:
    """Thin wrapper over the HTTP API, with the CLI configuration's token."""

    def __init__(self, config_path: Path):
        cfg = yaml.safe_load(config_path.read_text())
        self.url = cfg["api_base_url"].rstrip("/")
        self.base = self.url + "/depictio/api/v1"
        token = cfg["user"]["token"]["access_token"]
        self.client = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=180.0)

    def call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            return self.client.request(method, self.base + path, **kw)
        except httpx.HTTPError as exc:
            raise Fail(f"{method} {path}: {type(exc).__name__}: {exc}") from exc

    def ok(self, r: httpx.Response, what: str) -> Any:
        if r.status_code >= 400:
            raise Fail(f"{what}: HTTP {r.status_code} {r.text[:400]}")
        return r.json()

    def get(self, path: str, what: str, **kw: Any) -> Any:
        return self.ok(self.call("GET", path, **kw), what)

    def post(self, path: str, what: str, **kw: Any) -> Any:
        return self.ok(self.call("POST", path, **kw), what)


def run_cli(args: list[str], cfg: Path, verbose: bool) -> None:
    """Run the depictio CLI as a module.

    ``python -m depictio.cli`` rather than an entry point or an in-process call:
    the module entry is what installs the polars display patch that Delta
    processing relies on.
    """
    cmd = [sys.executable, "-m", "depictio.cli", *args, "--server", str(cfg)]
    _log(f"    $ depictio {' '.join(args)}")
    env = {**os.environ, "COLUMNS": "160"}
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=not verbose, text=True, env=env)
    if proc.returncode != 0:
        tail = "" if verbose else (proc.stdout + proc.stderr)[-3000:]
        raise Fail(f"CLI exited {proc.returncode} ({' '.join(args[:3])}):\n{tail}")
    _log(f"      done in {time.monotonic() - started:.0f}s")


def write_host_project_yaml(directory: Path, data_root: Path) -> Path:
    """A copy of project.yaml whose location is ``data_root``.

    The committed file keeps the container path, like every other init
    project; this copy is what makes the same fixture ingest from a host. The
    committed file is never modified.
    """
    config = yaml.safe_load(PROJECT_YAML.read_text())
    for workflow in config["workflows"]:
        workflow["data_location"]["locations"] = [str(data_root.resolve())]
    target = directory / "project.yaml"
    target.write_text(yaml.safe_dump(config, sort_keys=False))
    return target


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


def find_project(api: Api) -> dict | None:
    for project in api.get("/projects/get/all", "list projects"):
        if (
            str(project.get("id") or project.get("_id")) == PROJECT_ID
            or project.get("name") == PROJECT_NAME
        ):
            return project
    return None


def project_dc_ids(project: dict) -> dict[str, str]:
    found = {
        dc.get("data_collection_tag"): str(dc.get("id") or dc.get("_id"))
        for workflow in project.get("workflows") or []
        for dc in workflow.get("data_collections") or []
    }
    for tag, expected in DC_IDS.items():
        if found.get(tag) != expected:
            raise Fail(f"collection {tag} has id {found.get(tag)}, project.yaml says {expected}")
    return found


def find_dashboard(api: Api) -> str | None:
    """The demo's main dashboard: the one in the project imported under SOURCE_KEY."""
    mains = [
        d
        for d in api.get("/dashboards/list", "list dashboards")
        if str(d.get("project_id")) == PROJECT_ID
    ]
    for dashboard in mains:
        doc = api.get(f"/dashboards/get/{dashboard['dashboard_id']}", "get dashboard")
        if doc.get("source_key") == SOURCE_KEY:
            if len(mains) != 1:
                raise Fail(f"expected one main dashboard in the project, found {len(mains)}")
            return str(dashboard["dashboard_id"])
    return None


def delta_commits(api: Api, dc_id: str) -> list[dict]:
    payload = api.get(f"/deltatables/history/{dc_id}", f"delta history {dc_id}")
    # Mongo-only entries describe aggregations with no Delta commit recorded;
    # there is nothing to travel to for those.
    rows = [r for r in payload["versions"] if r.get("version") is not None]
    return sorted(rows, key=lambda r: r["version"])


# --------------------------------------------------------------------------
# Teardown and build
# --------------------------------------------------------------------------


def teardown(api: Api) -> None:
    """Delete the project, which cascades to everything the demo created.

    Its Delta tables and their S3 objects, its runs and files, its dashboards
    and their version ledgers (see `_cascade_delete_project`). Reusing the
    fixed ids without this would append to the old Delta history and to the
    old version ledger.
    """
    project = find_project(api)
    if project is None:
        _log("    nothing to remove")
        return
    project_id = str(project.get("id") or project.get("_id"))
    api.ok(
        api.call("DELETE", "/projects/delete", params={"project_id": project_id}), "delete project"
    )
    _log(
        f"    deleted project {project.get('name')!r} ({project_id}), with its tables and dashboards"
    )
    leftovers = [
        d
        for d in api.get("/dashboards/list", "list dashboards")
        if str(d.get("project_id")) == project_id
    ]
    if leftovers:
        raise Fail(f"{len(leftovers)} dashboard(s) outlived the project delete")


def ingest(cfg: Path, project_yaml: Path, step: Step, verbose: bool) -> None:
    """One ``depictio ingest`` for one batch.

    From the second batch on the project exists, so ``--update-config``
    refreshes it in place (and implies the overwrite that rewriting an existing
    table needs). ``--no-state-cache`` because a batch changes values inside
    files whose names and runs are the ones already registered. Every ingest
    ends by rebuilding the join from both tables as they now stand.
    """
    args = [
        "ingest",
        "--project-config-path",
        str(project_yaml),
        "--skip",
        "dashboards",
        "--no-state-cache",
    ]
    if step.n > 1:
        args.append("--update-config")
    if set(step.ingest) != {PF, DD}:
        (only,) = step.ingest
        args += ["--data-collection-tag", only]
    run_cli(args, cfg, verbose)


def import_version(api: Api, step: Step) -> tuple[str, str]:
    yaml_text = (Path(__file__).resolve().parent / "dashboards" / step.dashboard).read_text()
    payload = api.post(
        "/dashboards/import/yaml",
        f"import {step.dashboard}",
        content=yaml_text,
        headers={"Content-Type": "text/plain"},
        params={"project_id": PROJECT_ID, "source_key": SOURCE_KEY, "existing": "replace"},
    )
    return str(payload["dashboard_id"]), str(payload.get("status"))


def name_version(api: Api, dashboard_id: str, step: Step) -> str:
    named = api.post(
        f"/dashboards/{dashboard_id}/versions", f"name {step.label!r}", json={"label": step.label}
    )
    if step.pinned:
        api.post(f"/dashboards/versions/{named['version_id']}/pin", f"pin {step.label!r}", json={})
    return str(named["version_id"])


def build(api: Api, cfg: Path, data_root: Path, upto: int, verbose: bool) -> str:
    dashboard_id = ""
    with tempfile.TemporaryDirectory(prefix="penguins_versioned_") as tmp:
        project_yaml = write_host_project_yaml(Path(tmp), data_root)
        _log(f"    project file: {project_yaml} (locations -> {data_root.resolve()})")
        for step in STEPS[:upto]:
            _log(f"\n  batch {step.n}: {step.summary}")
            _log(f"    {stage_batch.stage(step.n, data_root)}")
            ingest(cfg, project_yaml, step, verbose)
            dashboard_id, status = import_version(api, step)
            version_id = name_version(api, dashboard_id, step)
            pin = ", pinned" if step.pinned else ""
            _log(f"    dashboard {status}, version {version_id[:8]} named {step.label!r}{pin}")
    return dashboard_id


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------


def _batch_rows(step: Step, filename: str) -> list[dict[str, str]]:
    """Every row of one file of a batch, with its run (the season) under ``_run``."""
    rows: list[dict[str, str]] = []
    for run in sorted((BATCHES_DIR / step.batch).iterdir()):
        with (run / filename).open() as handle:
            rows.extend({**row, "_run": run.name} for row in csv.DictReader(handle))
    return rows


def expected_commit_values() -> dict[str, list[float]]:
    """What each Delta commit must hold, read from the committed batch files.

    physical_features: mean body mass per commit. demographic_data: how many
    birds have a recorded sex. Computed here rather than hard-coded so the
    verifier compares the API against the files that were ingested.
    """
    mass, sexed = [], []
    for step in STEPS:
        if PF in step.ingest:
            rows = _batch_rows(step, "physical_features.csv")
            mass.append(round(statistics.mean(float(r["body_mass_g"]) for r in rows), 2))
        if DD in step.ingest:
            rows = _batch_rows(step, "demographic_data.csv")
            sexed.append(float(sum(1 for r in rows if r["sex"])))
    return {PF: mass, DD: sexed}


def expected_join_values() -> list[tuple[float, float, float]]:
    """(birds, mean body mass, sex recorded) of each commit of the join.

    The join of the two tables *as they stand* after each step: a step that
    ingests one collection joins it with the other's last ingested state, which
    is what the CLI reads. Inner, on individual_id and the run, keeping the
    measurement's own columns, as ``execute_join`` does.
    """
    values: list[tuple[float, float, float]] = []
    measured: list[dict[str, str]] = []
    census: dict[tuple[str, str], dict[str, str]] = {}
    for step in STEPS:
        if PF in step.ingest:
            measured = _batch_rows(step, "physical_features.csv")
        if DD in step.ingest:
            census = {
                (r["individual_id"], r["_run"]): r
                for r in _batch_rows(step, "demographic_data.csv")
            }
        if JOIN not in step.moves:
            continue
        joined = [
            {**census[key], **row}
            for row in measured
            if (key := (row["individual_id"], row["_run"])) in census
        ]
        values.append(
            (
                float(len(joined)),
                round(statistics.mean(float(r["body_mass_g"]) for r in joined), 2),
                float(sum(1 for r in joined if r["sex"])),
            )
        )
    return values


def labelled_versions(api: Api, dashboard_id: str) -> list[dict]:
    payload = api.get(
        f"/dashboards/{dashboard_id}/versions", "list versions", params={"limit": 200}
    )
    versions = sorted(payload["versions"], key=lambda v: v["seq"])
    return [v for v in versions if v.get("label") and v["label"] != BASELINE_LABEL]


def stamps_of(api: Api, version_id: str) -> dict[str, dict]:
    detail = api.get(f"/dashboards/versions/{version_id}", "version detail")
    return {str(entry.get("dc_id")): entry for entry in detail.get("data_collections") or []}


class Reads:
    """The render endpoints, pinned. All read-only.

    Each probe asks a component a question one of the stored versions defined
    it to ask, and names that version (``definition_version``): the server
    reads the definition from it, since a render takes no definition from the
    request body. A question no version defines is a ``Fail``, never a read
    through whatever the component holds today.
    """

    def __init__(self, api: Api, dashboard_id: str, versions: list[dict]):
        from depictio.models.components.lite import index_from_tag

        self.api = api
        self.dashboard_id = dashboard_id
        doc = api.get(f"/dashboards/get/{dashboard_id}", "get dashboard")
        indices = {str(c.get("index")) for c in doc.get("stored_metadata") or []}
        self.card_pf = index_from_tag("card-birds")
        self.card_mass = index_from_tag("card-mass")
        self.card_dd = index_from_tag("card-sexed")
        self.table_pf = index_from_tag("table-measurements")
        self.fig_pf = index_from_tag("fig-morph")
        self.card_join = index_from_tag("card-joined")
        self.fig_join = index_from_tag("fig-mass-by-sex")
        self.has = {
            i: i in indices
            for i in (
                self.card_pf,
                self.card_mass,
                self.card_dd,
                self.table_pf,
                self.fig_pf,
                self.card_join,
                self.fig_join,
            )
        }
        # The first version, oldest first, to define each card question and to
        # hold each figure: v1 averages body mass where later versions take
        # the median, and plots fig-morph without the trend line v3 adds.
        self.cards: dict[tuple[str, str, str], str] = {}
        self.figures: dict[str, str] = {}
        for version in versions:
            detail = api.get(f"/dashboards/versions/{version['version_id']}", "version detail")
            for tab in detail.get("tabs") or []:
                if str(tab.get("dashboard_id")) != dashboard_id:
                    continue
                for c in tab.get("stored_metadata") or []:
                    index = str(c.get("index"))
                    if c.get("component_type") == "card":
                        question = (index, str(c.get("column_name")), str(c.get("aggregation")))
                        self.cards.setdefault(question, version["version_id"])
                    elif c.get("component_type") == "figure":
                        self.figures.setdefault(index, version["version_id"])

    def card(self, index: str, column: str, aggregation: str, **pins: Any) -> float | None:
        version_id = self.cards.get((index, column, aggregation))
        if version_id is None:
            raise Fail(f"no stored version defines card {index} as {aggregation}({column})")
        body = {
            "filters": [],
            "component_ids": [index],
            "definition_version": version_id,
            **pins,
        }
        result = self.api.post(
            f"/dashboards/bulk_compute_cards/{self.dashboard_id}", "card", json=body
        )
        value = result["values"].get(index)
        return None if value is None else round(float(value), 2)

    def birds(self, **pins: Any) -> float | None:
        return self.card(self.card_pf, "individual_id", "count", **pins)

    def mean_mass(self, **pins: Any) -> float | None:
        return self.card(self.card_mass, "body_mass_g", "average", **pins)

    def sexed(self, **pins: Any) -> float | None:
        return self.card(self.card_dd, "sex", "count", **pins)

    def joined(self, **pins: Any) -> tuple[float | None, float | None, float | None]:
        """(birds, mean body mass, sex recorded) of the join.

        The mean through its card. No card counts the join's birds or sexes,
        so those come from its box plot of body mass by sex, which draws one
        point per row with the bird's sex as its x.
        """
        xs, ys = self._points(self.fig_join, **pins)
        sexed = sum(1 for x in xs if x not in (None, "") and x == x)  # NaN != NaN
        mass = self.card(self.card_join, "body_mass_g", "average", **pins)
        return float(len(ys)), mass, float(sexed)

    def table(self, **pins: Any) -> tuple[int, float]:
        body = {
            "filters": [],
            "start": 0,
            "limit": 500,
            "sort_by": "individual_id",
            "sort_dir": "asc",
            **pins,
        }
        payload = self.api.post(
            f"/dashboards/render_table/{self.dashboard_id}/{self.table_pf}",
            "render_table",
            json=body,
        )
        rows = payload.get("rows") or []
        return int(payload.get("total") or 0), round(sum(float(r["body_mass_g"]) for r in rows), 1)

    def figure(self, index: str | None = None, **pins: Any) -> tuple[int, float]:
        """(points, sum of body mass) of a figure plotting body mass as its y."""
        _, ys = self._points(index or self.fig_pf, **pins)
        return len(ys), round(sum(ys), 1)

    def _points(self, index: str, **pins: Any) -> tuple[list[Any], list[float]]:
        """Every trace's x and y, drawn from the first version holding the figure."""
        version_id = self.figures.get(index)
        if version_id is None:
            raise Fail(f"no stored version holds figure {index}")
        body = {"filters": [], "theme": "light", "definition_version": version_id, **pins}
        spec = self.api.post(
            f"/dashboards/render_figure/{self.dashboard_id}/{index}",
            "render_figure",
            json=body,
        )
        traces = (spec.get("figure") or {}).get("data") or []
        xs = [x for trace in traces for x in _plotly_raw(trace.get("x"))]
        ys = [y for trace in traces for y in _plotly_values(trace.get("y"))]
        return xs, ys


def _plotly_raw(values: Any) -> list[Any]:
    """A trace's ``x`` as given: categories stay strings, typed arrays decode."""
    if isinstance(values, dict) and "bdata" in values:
        return _plotly_values(values)
    return list(values or [])


#: Plotly's typed-array dtypes, as `array` module type codes.
_TYPED_ARRAY_CODES = {
    "f8": "d",
    "f4": "f",
    "i8": "q",
    "u8": "Q",
    "i1": "b",
    "u1": "B",
    "i2": "h",
    "u2": "H",
    "i4": "i",
    "u4": "I",
}


def _plotly_values(values: Any) -> list[float]:
    """A trace's ``x``/``y`` as floats, whether a list or a Plotly typed array.

    Plotly 6 serialises numeric arrays as ``{"dtype": "f8", "bdata": <base64>}``
    (little-endian), which is what the render endpoint returns for a numeric
    column.
    """
    if isinstance(values, dict) and "bdata" in values:
        decoded = array.array(_TYPED_ARRAY_CODES[values["dtype"]])
        decoded.frombytes(base64.b64decode(values["bdata"]))
        if sys.byteorder != "little":
            decoded.byteswap()
        return [float(v) for v in decoded]
    return [float(v) for v in values or []]


def verify(api: Api, upto: int) -> None:
    project = find_project(api)
    if project is None:
        raise Fail(f"project {PROJECT_NAME!r} does not exist")
    project_dc_ids(project)
    steps = STEPS[:upto]

    # -- data ---------------------------------------------------------------
    _log("  Delta commits (rows per commit, oldest first)")
    for tag in (PF, DD, JOIN):
        rows = [c.get("rows_total") for c in delta_commits(api, DC_IDS[tag])]
        want = commit_rows(tag, upto)
        if rows != want:
            raise Fail(f"{tag}: commits hold {rows} rows, the story says {want}")
        listing = "  ".join(f"{i}:{r}" for i, r in enumerate(rows))
        _log(f"    {tag:24} {listing}")

    # -- dashboard versions ---------------------------------------------------
    dashboard_id = find_dashboard(api)
    if dashboard_id is None:
        raise Fail("no dashboard imported under the demo's source_key")
    versions = labelled_versions(api, dashboard_id)
    labels = [v["label"] for v in versions]
    if labels != [s.label for s in steps]:
        raise Fail(f"version labels {labels} != {[s.label for s in steps]}")

    _log("\n  Dashboard versions (each collection's stamped Delta version and rows)")
    join_heading = f"{JOIN_NAME} (join)"
    _log(f"    {'version':32} {'tabs':>4} {'comps':>5}   {PF:20} {DD:20} {join_heading:20}")
    stamps_by_label: dict[str, dict[str, dict]] = {}
    for step, version in zip(steps, versions, strict=True):
        stamps = stamps_of(api, version["version_id"])
        stamps_by_label[step.label] = stamps
        cells = []
        for tag in (PF, DD, JOIN):
            stamp = stamps.get(DC_IDS[tag])
            if tag not in step.reads:
                if stamp is not None:
                    raise Fail(f"{step.label}: stamps {tag}, which none of its components reads")
                cells.append("-")
                continue
            if stamp is None or stamp.get("version_kind") != "delta":
                raise Fail(f"{step.label}: {tag} has no delta stamp ({stamp})")
            got = (stamp.get("delta_version"), stamp.get("row_count"))
            want = (step.stamps[tag], step.rows[tag])
            if got != want:
                raise Fail(
                    f"{step.label}: {tag} stamped delta {got[0]} with {got[1]} rows, the story "
                    f"says delta {want[0]} with {want[1]}. Was a batch ingested out of order?"
                )
            cells.append(f"delta {got[0]}  {got[1]:>3} rows")
        counts = (version.get("tab_count"), version.get("component_count"))
        if counts != (step.tabs, step.components):
            raise Fail(
                f"{step.label}: {counts[0]} tabs / {counts[1]} components, story says {step.tabs} / {step.components}"
            )
        if bool(version.get("pinned")) != step.pinned:
            raise Fail(f"{step.label}: pinned={version.get('pinned')}, story says {step.pinned}")
        name = step.label + (" [pinned]" if step.pinned else "")
        _log(
            f"    {name:32} {counts[0]:>4} {counts[1]:>5}   {cells[0]:20} {cells[1]:20} {cells[2]:20}"
        )

    # The join moves at every step, so each version that reads it stamps a newer
    # commit than the one before: with physical_features at v3, with
    # demographic_data at v5. A join registered without its Delta version would
    # have failed above already, with no delta stamp at all.
    join_stamps = [
        stamps_by_label[s.label][JOIN_ID]["delta_version"] for s in steps if JOIN in s.reads
    ]
    if any(later <= earlier for earlier, later in zip(join_stamps, join_stamps[1:])):
        raise Fail(f"{JOIN_NAME} stamps {join_stamps} do not ascend")
    if len(join_stamps) > 1:
        _log(f"    -> {JOIN_NAME} stamps ascend ({join_stamps}): it moved with either input")

    # -- time travel reads -----------------------------------------------------
    reads = Reads(api, dashboard_id, versions)
    expected = expected_commit_values()
    _check_pinned_commits(reads, expected, upto)
    _check_as_of(reads, steps, versions)
    _check_join_as_of(reads, steps, versions, stamps_by_label)
    _check_render_paths(reads, upto)

    _log(f"\n  dashboard: {api.url}/dashboard-edit/{dashboard_id}")


def _close(a: float | None, b: float | None, tol: float = 0.05) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _check_pinned_commits(reads: Reads, expected: dict[str, list[float]], upto: int) -> None:
    """Every commit of each collection, pinned on its own with ``data_versions``."""
    _log("\n  Pinned reads, one collection at a time (bulk_compute_cards + data_versions)")
    pf_rows, dd_rows = commit_rows(PF, upto), commit_rows(DD, upto)
    for k, rows in enumerate(pf_rows):
        pins = {"data_versions": {DC_IDS[PF]: k}}
        birds, mass = reads.birds(**pins), reads.mean_mass(**pins)
        if birds != rows or not _close(mass, expected[PF][k]):
            raise Fail(
                f"{PF} @ delta {k}: {birds} birds, mean {mass} g; want {rows}, {expected[PF][k]}"
            )
        _log(f"    {PF} @ delta {k}: {birds:>5.0f} birds   mean body mass {mass:8.2f} g")
    if not reads.has[reads.card_dd]:
        _log(f"    {DD}: skipped, the live dashboard has no card on it yet (v1)")
        dd_rows = []
    # Its row counts are the commits' and the stamps' above: no main-tab
    # component counts demographic_data rows, so only its sexes are read here.
    for k, rows in enumerate(dd_rows):
        pins = {"data_versions": {DC_IDS[DD]: k}}
        sexed = reads.sexed(**pins)
        if sexed != expected[DD][k]:
            raise Fail(f"{DD} @ delta {k} ({rows} rows): {sexed} sexed; want {expected[DD][k]}")
        _log(f"    {DD} @ delta {k}: {rows:>5} birds   sex recorded {sexed:5.0f}")
    if len(pf_rows) >= 3 and pf_rows[1] == pf_rows[2]:
        if _close(expected[PF][1], expected[PF][2]):
            raise Fail("batch 3 did not change any body mass")
        _log("    -> physical_features delta 1 and 2: same rows, different body mass")
    if len(dd_rows) >= 4 and dd_rows[2] == dd_rows[3]:
        _log("    -> demographic_data delta 2 and 3: same rows, different sex counts")

    if not reads.has[reads.card_join]:
        _log(f"    {JOIN_NAME}: skipped, the live dashboard has no card on it yet (v1)")
        return
    seen = []
    for k, want in enumerate(expected_join_values()[: len(commit_rows(JOIN, upto))]):
        got = reads.joined(data_versions={JOIN_ID: k})
        if got[0] != want[0] or not _close(got[1], want[1]) or got[2] != want[2]:
            raise Fail(f"{JOIN_NAME} @ delta {k}: {got}; want {want} (birds, mean mass, sexed)")
        seen.append(got)
        _log(
            f"    {JOIN_NAME} @ delta {k}: {got[0]:>5.0f} birds   mean body mass {got[1]:8.2f} g"
            f"   sex recorded {got[2]:5.0f}"
        )
    if len(seen) >= 3:
        if seen[1][0] != seen[2][0] or _close(seen[1][1], seen[2][1]) or seen[1][2] != seen[2][2]:
            raise Fail(
                f"{JOIN_NAME} delta 1 -> 2 should move body mass only: {seen[1]} -> {seen[2]}"
            )
        _log(f"    -> {JOIN_NAME} delta 1 and 2: same rows, body mass moved (physical_features)")
    if len(seen) >= 5:
        if seen[3][:2] != seen[4][:2] or seen[3][2] == seen[4][2]:
            raise Fail(f"{JOIN_NAME} delta 3 -> 4 should move sex only: {seen[3]} -> {seen[4]}")
        _log(f"    -> {JOIN_NAME} delta 3 and 4: same rows, sex counts moved (demographic_data)")


def _check_as_of(reads: Reads, steps: tuple[Step, ...], versions: list[dict]) -> None:
    """Each stored version's own stamps, expanded by the server (``as_of_version``)."""
    _log("\n  as_of_version: each named version's stamps, read back")
    seen: list[tuple[float | None, ...]] = []
    with_dd = reads.has[reads.card_dd]
    for step, version in zip(steps, versions, strict=True):
        pins = {"as_of_version": version["version_id"]}
        got = (
            reads.birds(**pins),
            reads.mean_mass(**pins),
            reads.sexed(**pins) if with_dd else None,
        )
        if got[0] != step.rows[PF]:
            raise Fail(f"as of {step.label}: {got[0]} birds, want {step.rows[PF]}")
        seen.append(got)
        sex = "-" if got[2] is None else f"{got[2]:.0f}"
        _log(
            f"    {step.label:26} birds {got[0]:>4.0f}  mean mass {got[1]:8.2f} g  "
            f"sex recorded {sex:>4}"
        )
    if len(seen) >= 3:
        v2, v3 = seen[1], seen[2]
        if v2[0] != v3[0] or _close(v2[1], v3[1]) or v2[2] != v3[2]:
            raise Fail(f"v2 -> v3 should move body mass only: {v2} -> {v3}")
        _log(
            "    -> v2 -> v3: same birds, body mass moved, sexes identical (demographic_data pin held)"
        )
    if len(seen) >= 5:
        v4, v5 = seen[3], seen[4]
        if v4[:2] != v5[:2] or v4[2] == v5[2]:
            raise Fail(f"v4 -> v5 should move the sex count only: {v4} -> {v5}")
        _log("    -> v4 -> v5: body mass identical (physical_features pin held), sex count moved")

    response = reads.api.call(
        "POST",
        f"/dashboards/bulk_compute_cards/{reads.dashboard_id}",
        json={"filters": [], "as_of_version": "does-not-exist"},
    )
    if response.status_code != 400:
        raise Fail(f"a stale as_of_version answered {response.status_code}, not 400")
    _log("    -> a stale version id is a 400, not a silent read of current data")


def _check_join_as_of(
    reads: Reads,
    steps: tuple[Step, ...],
    versions: list[dict],
    stamps_by_label: dict[str, dict[str, dict]],
) -> None:
    """The join through each version's own stamps: it follows whichever input moved."""
    if not reads.has[reads.card_join]:
        return
    _log(f"\n  as_of_version: {JOIN_NAME} (the join), read back through each version's stamp")
    seen: dict[int, tuple[float | None, ...]] = {}
    for step, version in zip(steps, versions, strict=True):
        if JOIN not in step.reads:
            _log(f"    {step.label:26} does not read the join")
            continue
        got = reads.joined(as_of_version=version["version_id"])
        if got[0] != step.rows[JOIN]:
            raise Fail(f"as of {step.label}: the join holds {got[0]} birds, want {step.rows[JOIN]}")
        seen[step.n] = got
        delta = stamps_by_label[step.label][JOIN_ID]["delta_version"]
        _log(
            f"    {step.label:26} delta {delta}  birds {got[0]:>4.0f}  mean mass {got[1]:8.2f} g"
            f"  sex recorded {got[2]:>4.0f}"
        )
    if 2 in seen and 3 in seen:
        v2, v3 = seen[2], seen[3]
        if v2[0] != v3[0] or _close(v2[1], v3[1]) or v2[2] != v3[2]:
            raise Fail(f"join, v2 -> v3 should move body mass only: {v2} -> {v3}")
        _log("    -> v2 -> v3: the join's body mass moved with physical_features, its sexes held")
    if 4 in seen and 5 in seen:
        v4, v5 = seen[4], seen[5]
        if v4[:2] != v5[:2] or v4[2] == v5[2]:
            raise Fail(f"join, v4 -> v5 should move the sex count only: {v4} -> {v5}")
        _log("    -> v4 -> v5: the join's sexes moved with demographic_data, its body mass held")


def _check_render_paths(reads: Reads, upto: int) -> None:
    """The flat step through the table and figure endpoints too."""
    if upto < 3:
        return
    _log(
        "\n  Same flat step through render_table and render_figure (physical_features delta 1 vs 2,"
        f" then {JOIN_NAME} delta 1 vs 2)"
    )
    for name, render, dc_id, present in (
        ("render_table", reads.table, DC_IDS[PF], reads.has[reads.table_pf]),
        ("render_figure", reads.figure, DC_IDS[PF], reads.has[reads.fig_pf]),
        (
            "  on the join",
            lambda **pins: reads.figure(reads.fig_join, **pins),
            JOIN_ID,
            reads.has[reads.fig_join],
        ),
    ):
        if not present:
            _log(f"    {name}: skipped, the live dashboard has no such component yet")
            continue
        before = render(data_versions={dc_id: 1})
        after = render(data_versions={dc_id: 2})
        if before[0] != after[0] or before[1] == after[1]:
            raise Fail(
                f"{name}: delta 1 {before} vs delta 2 {after}; want same rows, different mass"
            )
        _log(
            f"    {name:13} delta 1: {before[0]} rows, sum mass {before[1]:.1f} g   "
            f"delta 2: {after[0]} rows, sum mass {after[1]:.1f} g"
        )


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--server",
        default=os.environ.get("DEPICTIO_CLI_CONFIG_PATH") or "local",
        help="'local' (the `depictio local up` server of $DEPICTIO_LOCAL_HOME) or a CLI "
        "config file (default: $DEPICTIO_CLI_CONFIG_PATH, else local)",
    )
    ap.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="staging directory the batches are copied into and ingested from "
        "(default: data/ next to this script)",
    )
    ap.add_argument(
        "--upto",
        type=int,
        default=len(STEPS),
        choices=range(1, len(STEPS) + 1),
        help=f"build batches 1..N only (default: all {len(STEPS)}); they only make sense in order",
    )
    ap.add_argument("--verify", action="store_true", help="check the current state, change nothing")
    ap.add_argument("--teardown-only", action="store_true", help="remove the demo and exit")
    ap.add_argument("-v", "--verbose", action="store_true", help="stream the CLI output")
    args = ap.parse_args()

    cfg = resolve_server(args.server)
    if not cfg.exists():
        _log(f"CLI config not found: {cfg}")
        return 2
    api = Api(cfg)

    try:
        if args.verify:
            _step(f"Verifying against {api.url}")
            verify(api, args.upto)
            _log("\n\033[32mOK\033[0m")
            return 0

        _step("Tearing down the existing demo")
        teardown(api)
        if args.teardown_only:
            stage_batch.reset(args.data_root)
            return 0

        _step(f"Ingesting each batch, then saving a dashboard version against it ({api.url})")
        build(api, cfg, args.data_root, args.upto, args.verbose)

        _step("Verifying")
        verify(api, args.upto)
    except Fail as exc:
        _log(f"\n\033[31mFAILED\033[0m {exc}")
        return 1

    _log("\n\033[32mDemo rebuilt.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
