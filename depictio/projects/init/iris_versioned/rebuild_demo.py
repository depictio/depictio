#!/usr/bin/env python3
"""Rebuild the iris_versioned demo from nothing: project, data, dashboard history.

The demo has three moving parts that have to agree with each other, and until
now only the first two had a repeatable setup:

  1. the project, registered from ``project.yaml``;
  2. four Delta commits at 50 / 100 / 100 / 150 rows, one per ingested batch;
  3. **one** dashboard carrying four named versions in its history.

Part 3 is why this script exists. The README told you to import v1 and then
hand-edit it into v2/v3/v4 in the browser, which is fine as a demonstration but
useless as setup: it cannot be repeated, cannot be verified, and any stray save
in between leaves anonymous autosaves interleaved with the named versions. What
you end up with looks like history but is not the history the demo describes.

So the version history is built the way the editor builds it — ``POST
/dashboards/save`` followed by ``POST /{id}/versions`` to name the state — just
driven from here. Same endpoints, same ledger, same stamps; the only thing
missing is the mouse.

Order matters and is not arbitrary. Batch N is ingested and *then* dashboard
version N is saved, alternating, because each version stamps the Delta version
of every collection it referenced **at save time**. Ingesting all four batches
first and then saving all four dashboards produces four versions that every
stamp says were built on batch 4 — which is what the first draft of this script
did, and it verified green, because row counts and labels were all correct. The
demo's central claim ("this layout was built on that data") was simply false.
``verify`` now asserts the stamps ascend, so that cannot pass again.

The dashboard is deleted and re-imported rather than overwritten, because the
version ledger is keyed on the dashboard family and survives an overwrite.
Reusing the id would append four new versions to whatever was already there.

Idempotent by construction: it tears down what it finds before rebuilding, so
running it twice gives the same result as running it once.

Usage (from inside the backend container, where ``project.yaml``'s paths
resolve):

    python rebuild_demo.py             # full rebuild
    python rebuild_demo.py --verify    # check the current state, change nothing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
PROJECT_YAML = HERE / "project.yaml"
DASHBOARD_YAMLS = [
    ("v1_survey.yaml", "v1 Survey"),
    ("v2_extended.yaml", "v2 Extended"),
    ("v3_recalibrated.yaml", "v3 Recalibrated"),
    ("v4_complete.yaml", "v4 Complete"),
]
PROJECT_NAME = "Iris Versioned Demo"
DC_TAG = "iris_versioned_table"

# Written by the ledger itself on the first save, holding the pre-write state.
# Kept in sync with versioning.ensure_baseline_quietly.
BASELINE_LABEL = "Before first tracked change"

# What the finished demo must look like. Asserted at the end, and by --verify.
EXPECTED_ROWS = [50, 100, 100, 150]
EXPECTED_COMPONENTS = [5, 8, 8, 9]


class Fail(Exception):
    """A step did not produce the state the next step needs."""


def _log(msg: str) -> None:
    print(msg, flush=True)


def _step(msg: str) -> None:
    print(f"\n\033[1m==> {msg}\033[0m", flush=True)


class Api:
    """Thin wrapper over the HTTP API, using the CLI config's token."""

    def __init__(self, config_path: Path):
        cfg = yaml.safe_load(config_path.read_text())
        self.base = cfg["api_base_url"].rstrip("/") + "/depictio/api/v1"
        token = cfg["user"]["token"]["access_token"]
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.get(self.base + path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.post(self.base + path, **kw)

    def delete(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.delete(self.base + path, **kw)

    def ok(self, r: httpx.Response, what: str) -> Any:
        if r.status_code >= 400:
            raise Fail(f"{what}: HTTP {r.status_code} {r.text[:400]}")
        return r.json()


def run_cli(args: list[str], cfg: Path) -> None:
    """Run a depictio CLI command, streaming failures with their output.

    The CLI is used rather than the API for sync and ingestion because that is
    how a user sets this up, and because ingestion is the CLI's job: it scans,
    aggregates and writes the Delta commit whose metadata the version stamps
    later read.
    """
    cmd = ["depictio", *args, "--CLI-config-path", str(cfg)]
    _log(f"    $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-2000:]
        raise Fail(f"CLI failed ({' '.join(args[:2])}):\n{tail}")


def stage_batch(n: int) -> None:
    proc = subprocess.run([str(HERE / "stage_batch.sh"), str(n)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Fail(f"stage_batch.sh {n} failed: {proc.stderr[-500:]}")
    _log(f"    {proc.stdout.splitlines()[0]}")


def find_project(api: Api) -> dict | None:
    projects = api.ok(api.get("/projects/get/all"), "list projects")
    for p in projects:
        if p.get("name") == PROJECT_NAME:
            return p
    return None


def find_dc_id(project: dict) -> str:
    for wf in project.get("workflows", []):
        for dc in wf.get("data_collections", []):
            if dc.get("data_collection_tag") == DC_TAG:
                return dc["id"]
    raise Fail(f"data collection '{DC_TAG}' not found in project")


def find_dashboards(api: Api, project_id: str) -> list[dict]:
    all_dash = api.ok(api.get("/dashboards/list"), "list dashboards")
    return [d for d in all_dash if str(d.get("project_id")) == str(project_id)]


def delta_history(api: Api, dc_id: str) -> list[dict]:
    payload = api.ok(api.get(f"/deltatables/history/{dc_id}"), "delta history")
    rows = payload["versions"] if isinstance(payload, dict) else payload
    # Mongo-only entries describe aggregations whose Delta commit is outside
    # the window or predates version recording. They carry no `version`, so
    # they are not commits to travel to.
    rows = [r for r in rows if r.get("version") is not None]
    return sorted(rows, key=lambda r: r["version"])


# --------------------------------------------------------------------------
# Teardown
# --------------------------------------------------------------------------


def teardown(api: Api) -> None:
    """Remove the demo's dashboards, then the project itself.

    Deleting the project cascades to the Delta table, which is what resets the
    commit history. Both are required: dashboards outlive their project's data
    otherwise, and the version ledger is keyed on the dashboard family, so
    reusing an id would append to whatever history was already there.
    """
    project = find_project(api)
    if project is None:
        _log("    nothing to remove")
        return

    for d in find_dashboards(api, project["id"]):
        did = d.get("dashboard_id")
        r = api.delete(f"/dashboards/delete/{did}")
        if r.status_code >= 400:
            raise Fail(f"delete dashboard {did}: HTTP {r.status_code} {r.text[:200]}")
        _log(f"    deleted dashboard {d.get('title')!r} ({did})")

    r = api.delete("/projects/delete", params={"project_id": project["id"]})
    if r.status_code >= 400:
        raise Fail(f"delete project: HTTP {r.status_code} {r.text[:200]}")
    _log(f"    deleted project {PROJECT_NAME!r} (cascades to the Delta table)")


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def sync_project(cfg: Path) -> None:
    run_cli(["config", "sync", "--project-config-path", str(PROJECT_YAML)], cfg)


def ingest_batch(cfg: Path, n: int) -> None:
    """Stage batch ``n`` and ingest it, producing one new Delta commit.

    ``--overwrite`` from the second batch onward: the S3 destination exists by
    then and the CLI refuses to replace it silently. Each run writes a new
    Delta commit regardless, which is what produces the four versions.
    """
    stage_batch(n)
    args = ["run", "--project-config-path", str(PROJECT_YAML), "--skip-sync"]
    if n > 1:
        args.append("--overwrite")
    run_cli(args, cfg)


def import_v1(api: Api, project_id: str) -> str:
    yaml_text = (HERE / "dashboards" / DASHBOARD_YAMLS[0][0]).read_text()
    payload = api.ok(
        api.post(
            "/dashboards/import/yaml",
            content=yaml_text,
            headers={"Content-Type": "text/plain"},
            params={"project_id": project_id},
        ),
        "import v1",
    )
    return payload["dashboard_id"]


def write_dashboard(api: Api, yaml_name: str) -> None:
    """Replace the dashboard document with one YAML's contents.

    The import endpoint is reused rather than hand-building the payload
    because it resolves workflow and data-collection tags to ids and
    regenerates the derived component fields. Reimplementing tag resolution
    here is exactly how a component ends up pointing at no collection at all.

    This writes the document but does **not** feed the version ledger — only
    ``/dashboards/save`` does. See ``save_and_name``.
    """
    yaml_text = (HERE / "dashboards" / yaml_name).read_text()
    api.ok(
        api.post(
            "/dashboards/import/yaml",
            content=yaml_text,
            headers={"Content-Type": "text/plain"},
            params={"overwrite": True},
        ),
        f"write {yaml_name}",
    )


def save_and_name(api: Api, dashboard_id: str, label: str) -> None:
    """Capture the current state as a version and give it a name.

    Two calls, because that is what the editor does and what the ledger
    expects: ``/save`` writes the document and captures a version (stamping the
    data provenance as it goes), ``/versions`` labels it. Naming a state that
    is already the newest version relabels it rather than duplicating, so this
    stays one version per step.
    """
    doc = api.ok(api.get(f"/dashboards/get/{dashboard_id}"), "reload dashboard")
    api.ok(api.post(f"/dashboards/save/{dashboard_id}", json=doc), "save dashboard")
    api.ok(
        api.post(f"/dashboards/{dashboard_id}/versions", json={"label": label}),
        f"name version {label!r}",
    )
    _log(f"    saved and named {label!r}")


def build_dashboard_history(api: Api, project_id: str, cfg: Path) -> str:
    """Ingest batch N then save dashboard version N, four times over.

    The interleaving is the whole point. A version's data stamp is taken when
    the version is captured, so v1 must be saved while the table still holds
    only batch 1. Doing all the ingestion first gives four versions that all
    claim to have been built on the complete survey.
    """
    dashboard_id: str | None = None

    for n, (yaml_name, label) in enumerate(DASHBOARD_YAMLS, start=1):
        _log(f"  batch {n} -> {label}")
        ingest_batch(cfg, n)

        if dashboard_id is None:
            dashboard_id = import_v1(api, project_id)
            _log(f"    imported v1 as {dashboard_id}")
        else:
            # A version is only captured when the content hash moves, and the
            # ledger coalesces rapid saves from the same author into one
            # entry. Without a gap the four steps can fold into fewer
            # versions — the demo would then be correct and still look broken.
            time.sleep(1.5)
            write_dashboard(api, yaml_name)

        save_and_name(api, dashboard_id, label)

    assert dashboard_id is not None
    return dashboard_id


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------


def _setosa_petal_mean(api: Api, dc_id: str, version: int) -> float | None:
    """Mean Setosa petal length at one Delta commit.

    Read via ``/deltatables/preview?version=``, which scans the commit
    directly. ``limit`` is raised past the row count so the mean covers the
    whole commit rather than the first page — a truncated read would still
    differ between the two versions and would still pass, for the wrong reason.
    """
    payload = api.ok(
        api.get(
            f"/deltatables/preview/{dc_id}",
            params={"version": version, "limit": 1000},
        ),
        f"preview v{version}",
    )
    recs = payload["rows"]
    setosa = [r["petal.length"] for r in recs if str(r.get("variety")).lower() == "setosa"]
    if payload.get("total_rows") and len(recs) < payload["total_rows"]:
        raise Fail(
            f"preview v{version} returned {len(recs)} of {payload['total_rows']} rows; "
            "the mean would be computed on a partial read"
        )
    return round(sum(setosa) / len(setosa), 3) if setosa else None


def verify(api: Api) -> None:
    """Assert the demo matches what the README promises.

    Checks the two things a broken rebuild actually gets wrong: the row
    progression (including the flat 100 → 100 step, which is the whole point of
    batch 3) and one dashboard carrying four named versions with real data
    stamps.
    """
    project = find_project(api)
    if project is None:
        raise Fail(f"project {PROJECT_NAME!r} does not exist")
    dc_id = find_dc_id(project)

    hist = delta_history(api, dc_id)
    rows = [h["rows_total"] for h in hist]
    if rows != EXPECTED_ROWS:
        raise Fail(f"delta rows {rows} != expected {EXPECTED_ROWS}")
    _log(f"  ✓ delta commits: {' / '.join(str(r) for r in rows)} rows")

    # Versions 1 and 2 are the pair that matters: same row count, different
    # values. If they are identical, batch 3 was not really re-measured and the
    # hard half of time travel is untested.
    means = [_setosa_petal_mean(api, dc_id, v) for v in (1, 2)]
    if means[0] is not None and means[0] == means[1]:
        raise Fail(
            f"delta v1 and v2 have identical Setosa petal means ({means[0]}); "
            "batch 3 did not change any values"
        )
    _log(f"  ✓ setosa petal mean moved across the flat step: {means[0]} -> {means[1]}")

    dashboards = find_dashboards(api, project["id"])
    if len(dashboards) != 1:
        raise Fail(
            f"expected exactly 1 dashboard in the project, found {len(dashboards)}: "
            f"{[d.get('title') for d in dashboards]}"
        )
    did = dashboards[0]["dashboard_id"]

    payload = api.ok(api.get(f"/dashboards/{did}/versions"), "list versions")
    versions = sorted(payload["versions"], key=lambda v: v["seq"])
    # The ledger seeds a `Before first tracked change` baseline on the first
    # save, holding the as-imported state. It is labelled, but it is not one of
    # ours — it is what makes the imported layout restorable at all.
    labelled = [v for v in versions if v.get("label") and v["label"] != BASELINE_LABEL]
    labels = [v["label"] for v in labelled]
    expected_labels = [lbl for _, lbl in DASHBOARD_YAMLS]
    if labels != expected_labels:
        raise Fail(f"version labels {labels} != expected {expected_labels}")
    _log(f"  ✓ dashboard versions: {' -> '.join(labels)}")

    counts = [v["component_count"] for v in labelled]
    if counts != EXPECTED_COMPONENTS:
        raise Fail(f"component counts {counts} != expected {EXPECTED_COMPONENTS}")
    _log(f"  ✓ component counts: {counts} (replaces and removes, not a superset)")

    # A version whose stamp says `none` recorded no data provenance, so
    # "use this data" has nothing to travel to. That was a real bug once; it
    # presented as the feature silently doing nothing.
    for v in labelled:
        kinds = v.get("data_version_kinds") or {}
        if not kinds or set(kinds) == {"none"}:
            raise Fail(
                f"version {v['label']!r} has no delta stamp (kinds={kinds}); "
                "time travel from it would have nothing to resolve"
            )
    _log("  ✓ every named version stamps a delta data version")

    # And the stamps must *differ*, ascending with the batches. Every check
    # above passes when all four versions were saved after all four
    # ingestions — labels, counts and kinds are all still correct — while
    # "restore v1's data" silently shows the complete survey. This is the
    # assertion that distinguishes a demo that works from one that only looks
    # like it does.
    stamps = [_delta_stamp(api, v["version_id"], dc_id) for v in labelled]
    if stamps != sorted(stamps) or len(set(stamps)) != len(stamps):
        raise Fail(
            f"version delta stamps {stamps} are not strictly ascending; "
            "each dashboard version must be saved while its own batch is the "
            "current data, or every version claims the same commit"
        )
    _log(f"  ✓ delta stamps ascend with the versions: {stamps}")
    _log(f"\n  dashboard_id: {did}")


def _delta_stamp(api: Api, version_id: str, dc_id: str) -> int:
    """The Delta commit one dashboard version recorded for one collection."""
    detail = api.ok(api.get(f"/dashboards/versions/{version_id}"), f"version {version_id}")
    for entry in detail.get("data_collections") or []:
        if str(entry.get("dc_id")) == str(dc_id):
            stamp = entry.get("delta_version")
            if stamp is None:
                raise Fail(f"version {version_id} stamped dc {dc_id} with no delta_version")
            return int(stamp)
    raise Fail(f"version {version_id} has no stamp for dc {dc_id}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config",
        default="/app/depictio/.depictio/cli_local.yaml",
        help="CLI config with the API url and token",
    )
    ap.add_argument(
        "--verify",
        action="store_true",
        help="check the current state and exit without changing anything",
    )
    args = ap.parse_args()

    cfg = Path(args.config)
    if not cfg.exists():
        _log(f"CLI config not found: {cfg}")
        return 2

    api = Api(cfg)

    try:
        if args.verify:
            _step("Verifying")
            verify(api)
            _log("\n\033[32mOK\033[0m")
            return 0

        _step("Tearing down the existing demo")
        teardown(api)

        _step("Registering the project")
        sync_project(cfg)

        project = find_project(api)
        if project is None:
            raise Fail("project missing after sync")

        _step("Ingesting each batch, saving a dashboard version against it")
        build_dashboard_history(api, project["id"], cfg)

        _step("Verifying")
        verify(api)
    except Fail as e:
        _log(f"\n\033[31mFAILED\033[0m {e}")
        return 1

    _log("\n\033[32mDemo rebuilt.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
