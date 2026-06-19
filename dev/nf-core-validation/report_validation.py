#!/usr/bin/env python
"""Read-only reporter for the nf-core per-run validation harness.

Run AFTER ``validate_per_run.sh``. For every validation project it reports, by
combining the depictio API (project + data-collection metadata) with direct
read-only MongoDB queries (per-DC ingestion success + dashboard tabs/components):

    project | run | exit code | expected | DCs ok/skipped/failed |
    dashboard tabs rendered | data components | URL to open

Out-of-scope projects (the two divergent sub-workflow runs) must fail loud
(non-zero exit) and build NO usable dashboard. Because ``--update-config`` syncs
the project config before processing, an empty project *shell* may exist — the
reporter checks "no dashboard with data components", not project absence.

Nothing is written or mutated. Connects to the local dev stack defined by the
CLI config (API base URL + bearer token) and Mongo on ``--mongo-uri``.

Usage:
    depictio/cli/.venv/bin/python dev/nf-core-validation/report_validation.py
    # overrides:
    #   --results-tsv <path>  --cli-config <path>  --mongo-uri <uri>  --db <name>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from bson import ObjectId
from pymongo import MongoClient

# Component types that represent rendered DATA (not interactive filters / text).
DATA_COMPONENT_TYPES = {"figure", "card", "table", "multiqc", "image", "map", "graph"}

DEFAULT_CLI_CONFIG = Path.home() / ".depictio" / "CLI.chore-amplicon-viralrecon-validation-100.yaml"


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--results-tsv", default=str(here / "validation_results" / "validation_results.tsv")
    )
    p.add_argument("--cli-config", default=str(DEFAULT_CLI_CONFIG))
    p.add_argument("--mongo-uri", default="mongodb://localhost:27100")
    p.add_argument("--db", default="depictioDB")
    p.add_argument("--viewer-port", default="5600", help="Vite dev viewer port (fallback URL)")
    return p.parse_args()


def load_cli_config(path: str) -> tuple[str, str]:
    """Return (api_base_url, bearer_token) from the CLI config yaml."""
    cfg = yaml.safe_load(Path(path).read_text())
    api = cfg["api_base_url"].rstrip("/")
    token = cfg["user"]["token"]["access_token"]
    return api, token


def api_get(api: str, token: str, path: str) -> tuple[int, object]:
    """GET a JSON endpoint. Returns (status_code, parsed_json_or_None)."""
    url = f"{api}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  WARN: API request failed ({url}): {e}", file=sys.stderr)
        return -1, None


def get_project(api: str, token: str, name: str) -> dict | None:
    """Fetch a project by name via the API; None if it does not exist."""
    status, body = api_get(api, token, f"/depictio/api/v1/projects/get/from_name/{name}")
    if status == 200 and isinstance(body, dict):
        return body
    return None


def extract_dcs(project: dict) -> list[dict]:
    """Flatten workflows[].data_collections[] into [{tag, id, optional, type}, ...]."""
    dcs: list[dict] = []
    for wf in project.get("workflows", []) or []:
        for dc in wf.get("data_collections", []) or []:
            dc_type = (dc.get("config") or {}).get("type")
            dcs.append(
                {
                    "tag": dc.get("data_collection_tag"),
                    "id": dc.get("id") or dc.get("_id"),
                    "optional": bool(dc.get("optional", False)),
                    "type": dc_type,
                }
            )
    return dcs


def as_object_ids(value: str | None) -> list:
    """Candidate match values for a stored id: ObjectId and raw string."""
    out: list = []
    if not value:
        return out
    try:
        out.append(ObjectId(value))
    except Exception:
        pass
    out.append(value)
    return out


def dc_has_delta(db, dc_id: str | None) -> bool:
    """True if a deltatable document exists for this data-collection id."""
    candidates = as_object_ids(dc_id)
    if not candidates:
        return False
    return db.deltatables.count_documents({"data_collection_id": {"$in": candidates}}, limit=1) > 0


def dc_has_multiqc(db, dc_id: str | None) -> bool:
    """True if a MultiQC report document exists for this DC.

    MultiQC DCs do NOT get a `deltatables` document (verified on this stack) —
    their report lives in the `multiqc` collection, where `data_collection_id`
    is usually a string but some write paths store an ObjectId, so match both.
    """
    candidates = as_object_ids(dc_id)
    if not candidates:
        return False
    return db.multiqc.count_documents({"data_collection_id": {"$in": candidates}}, limit=1) > 0


def dashboards_for_project(db, project_id: str | None) -> list[dict]:
    """All dashboard documents (main tab + child tabs) for a project."""
    candidates = as_object_ids(project_id)
    if not candidates:
        return []
    return list(db.dashboards.find({"project_id": {"$in": candidates}}))


def count_components(dash: dict) -> tuple[int, int]:
    """Return (total_components, data_components) for one dashboard doc."""
    meta = dash.get("stored_metadata") or []
    total = len(meta)
    data = sum(1 for m in meta if (m.get("component_type") in DATA_COMPONENT_TYPES))
    return total, data


def probe_url(api: str, viewer_port: str, dashboard_id: str) -> str:
    """Return the first dashboard URL that responds 200 (API dist or Vite dev)."""
    candidates = [
        f"{api}/dashboard/{dashboard_id}",
        f"http://localhost:{viewer_port}/dashboard/{dashboard_id}",
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    # Nothing responded 200 — still hand back the most likely route for the user.
    return candidates[0]


def main() -> int:
    args = parse_args()
    api, token = load_cli_config(args.cli_config)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[args.db]

    rows = list(csv.DictReader(Path(args.results_tsv).open(), delimiter="\t"))

    print("\n" + "=" * 110)
    print("VALIDATION REPORT")
    print("=" * 110)
    header = (
        f"{'project':28} {'exit':>4} {'expect':>6} {'DC ok/skip/fail':>16} "
        f"{'tabs':>4} {'data comp':>9}  url"
    )
    print(header)
    print("-" * 110)

    problems: list[str] = []

    for r in rows:
        project_name = r["project"]
        exit_code = int(r["exit_code"])
        expected = r["expected"]  # "ok" | "fail"
        harness_result = r["result"]

        project = get_project(api, token, project_name)

        # Out-of-scope (divergent sub-workflow): the run must fail loud (non-zero
        # exit) and produce NO usable self-adapting dashboard. Note that
        # `--update-config` syncs the project config to the server BEFORE data
        # processing, so an empty project *shell* may exist even though
        # processing aborted — that is expected. The meaningful criterion is
        # "no dashboard with data components was built".
        if expected == "fail":
            project_id = (project.get("id") or project.get("_id")) if project else None
            dashes = dashboards_for_project(db, project_id) if project else []
            data_comp = sum(count_components(d)[1] for d in dashes)
            shell = "no project" if project is None else "empty shell"
            if exit_code != 0 and data_comp == 0:
                verdict = f"PASS (fail-loud, {shell}, 0 dashboards)"
            else:
                verdict = f"FAIL (exit={exit_code}, dashboards data_comp={data_comp})"
                problems.append(
                    f"{project_name}: out-of-scope run did not fail loud "
                    f"(exit={exit_code}, dashboard data_components={data_comp})"
                )
            print(
                f"{project_name:28} {exit_code:>4} {expected:>6} "
                f"{'-':>16} {len(dashes):>4} {data_comp:>9}  {verdict}"
            )
            continue

        # In-scope: project must exist with ingested DCs + a non-empty dashboard.
        if project is None:
            print(
                f"{project_name:28} {exit_code:>4} {expected:>6}  MISSING (API has no such project)"
            )
            problems.append(f"{project_name}: in-scope run produced no project")
            continue

        project_id = project.get("id") or project.get("_id")
        dcs = extract_dcs(project)
        ok = skipped = failed = 0
        for dc in dcs:
            is_multiqc = (dc.get("type") or "").lower() == "multiqc"
            # MultiQC DCs store their report in the `multiqc` collection, not
            # `deltatables` — check the right collection for "ingested".
            ingested = dc_has_multiqc(db, dc["id"]) if is_multiqc else dc_has_delta(db, dc["id"])
            if ingested:
                ok += 1
            elif dc["optional"]:
                skipped += 1
            else:
                failed += 1

        dashes = dashboards_for_project(db, project_id)
        tabs = len(dashes)
        data_comp = sum(count_components(d)[1] for d in dashes)
        # Pick the main-tab dashboard id for the URL (fallback: first doc).
        main = next((d for d in dashes if d.get("is_main_tab")), dashes[0] if dashes else None)
        dash_id = str(main.get("dashboard_id") or main.get("_id")) if main is not None else None
        url = probe_url(api, args.viewer_port, dash_id) if dash_id else "(no dashboard)"

        print(
            f"{project_name:28} {exit_code:>4} {expected:>6} "
            f"{f'{ok}/{skipped}/{failed}':>16} {tabs:>4} {data_comp:>9}  {url}"
        )

        if harness_result == "FAIL":
            problems.append(
                f"{project_name}: harness exit-code expectation FAILED (exit={exit_code})"
            )
        if tabs == 0 or data_comp == 0:
            problems.append(
                f"{project_name}: empty dashboard (tabs={tabs}, data_components={data_comp})"
            )
        if failed > 0:
            problems.append(f"{project_name}: {failed} required DC(s) without ingested data")

    print("-" * 110)
    print(
        "Notes: 'DC ok' = data-collections with a deltatable (ingested); 'skip' = optional & absent;"
    )
    print("       'fail' = required & not ingested. 'data comp' = figure/card/table/multiqc/etc.")
    print("       (MultiQC DCs are counted via the `multiqc` collection, not `deltatables`.)")
    print("=" * 110)

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
