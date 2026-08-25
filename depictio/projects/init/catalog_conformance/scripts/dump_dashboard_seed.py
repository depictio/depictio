"""Dump the imported conformance dashboard into its boot seed.

    uv run python -m depictio.projects.init.catalog_conformance.scripts.dump_dashboard_seed

Run after editing `dashboards/overview.yaml` and importing it:

    depictio-cli dashboard import \
        depictio/projects/init/catalog_conformance/dashboards/overview.yaml \
        --config ~/.depictio/CLI.<instance>.yaml --overwrite

The YAML is the source and the import is what tests it, so the seed is always
*derived* from a real import rather than hand-written or built offline. Building
it offline would mean reimplementing what the importer does to a component, and
`dashboard import` re-mints component indices, so an offline copy drifts from the
document users actually get.

The one thing the dump rewrites is the dashboard id: the importer mints a fresh
one per run, while boot seeding needs the stable id from `static_ids.json` so a
reseed updates the dashboard instead of accumulating copies. Data collection ids
need no remapping here, unlike the nf-core reference seeds, because this
project's ids are derived from the catalog and are already stable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bson import ObjectId, json_util

PROJECT_DIR = Path(__file__).resolve().parents[1]
SEED = PROJECT_DIR / ".db_seeds" / "dashboard.json"
DASHBOARD_KEY = "catalog_conformance_overview"


def mongo_uri() -> str:
    """Point at the instance the CLI just imported into.

    A worktree runs Mongo on its own port, so the compose defaults are wrong
    here; `.env.instance` is the file that knows. Same lookup the dev scripts do.
    """
    host = os.environ.get("DEPICTIO_MONGODB_SERVICE_NAME", "localhost")
    port = os.environ.get("DEPICTIO_MONGODB_SERVICE_PORT")
    if not port:
        env_file = PROJECT_DIR.parents[2].parent / ".env.instance"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("MONGO_PORT="):
                    port = line.split("=", 1)[1].strip()
                    break
    return f"mongodb://{host}:{port or 27018}/depictioDB"


def main() -> None:
    from pymongo import MongoClient

    ids = json.loads((PROJECT_DIR / "static_ids.json").read_text())
    project_id = ObjectId(ids["project"])
    static_dashboard_id = ids["dashboards"][DASHBOARD_KEY]

    db = MongoClient(mongo_uri()).get_database("depictioDB")
    dashboards = list(db.dashboards.find({"project_id": project_id}))
    if len(dashboards) != 1:
        raise SystemExit(
            f"Expected exactly one dashboard on the conformance project, found {len(dashboards)}. "
            "Import overview.yaml with --overwrite first."
        )

    doc = dashboards[0]
    doc["_id"] = ObjectId(static_dashboard_id)
    doc["dashboard_id"] = static_dashboard_id
    # `permissions` stays: `DashboardData` requires it, so a seed without one
    # fails `from_mongo` at boot. Its contents do not matter — the seeder
    # replaces them with the deployment's admin.

    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(json_util.dumps(doc, indent=2) + "\n")
    print(f"wrote {SEED.relative_to(PROJECT_DIR.parents[2].parent)}")
    print(f"  {len(doc.get('stored_metadata', []))} components, dashboard_id={static_dashboard_id}")


if __name__ == "__main__":
    main()
