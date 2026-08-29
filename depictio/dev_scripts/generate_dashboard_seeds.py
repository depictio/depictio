"""Generate ``.db_seeds`` dashboards offline, from their lite YAML.

Covers the three shipped projects whose dashboards bind to already-materialised
collections and so need no ingest to rebuild: ``advanced_viz_showcase``
(23 tabs), ``nfcore_megatests_showcase`` (10) and ``catalog_conformance`` (1).
All three used to keep their seeds as hand-written or Mongo-dumped JSON, which
meant the shipped dashboards had no authorable source: adding a filter or a
caption meant editing a MongoDB document.

The nf-core reference projects are NOT here, and should not be: their YAML
leans on ``use:`` catalog bindings that only the importer resolves, so their
seeds stay derived from a real ``depictio run`` (see each project's
``generate_seeds.sh``). None of the three below writes a single ``use:``.

This is the offline half of the seed pipeline, deliberately so. The CLI import
path is not usable for these three:

* ``import_dashboard_from_yaml`` ignores the ``dashboard_id`` written in the
  YAML — it reuses the id of a dashboard found by ``(title, project_id)`` and
  mints a fresh ObjectId otherwise. Every id here is referenced from
  ``STATIC_IDS``, ``db_init.dashboards_config`` and the e2e specs, so a mint is
  a broken deployment.
* ``nfcore_megatests_showcase``'s fixtures are not in the repository and are
  gitignored, so nothing can be ingested locally to import against, and
  ``catalog_conformance`` is opt-in: a machine that has not set
  ``DEPICTIO_SEED_EXTRA_PROJECTS`` has no project to import into.

Every id, description and DC binding is read from the project's own
``project.yaml`` rather than duplicated here, and cross-checked against
``STATIC_IDS`` where the project has an entry.

Usage:
    venv/bin/python -m depictio.dev_scripts.generate_dashboard_seeds
    venv/bin/python -m depictio.dev_scripts.generate_dashboard_seeds advanced_viz_showcase
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from bson import json_util

from depictio.api.v1.db_init_reference_datasets import STATIC_IDS
from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[2]

ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"
ADMIN_EMAIL = "admin@example.com"

# `to_full` stamps every component with `datetime.now()`. In a checked-in seed
# that is pure churn, so both timestamps are pinned: an unchanged YAML has to
# regenerate byte-identically or the diff stops meaning anything.
FROZEN_TIMESTAMP = "2026-05-12 00:00:00"
FROZEN_LAST_UPDATED = "2026-05-12T00:00:00.000000"

# Projects handled here. `static_ids_key` is the STATIC_IDS entry to cross-check
# against, or None for a project that is deliberately not registered for boot
# seeding (see the megatests README).
PROJECTS: dict[str, dict[str, Any]] = {
    "advanced_viz_showcase": {
        "dir": "depictio/projects/init/advanced_viz_showcase",
        "config": "project.yaml",
        "static_ids_key": "advanced_viz_showcase",
        "is_public": True,
    },
    "nfcore_megatests_showcase": {
        "dir": "depictio/projects/init/nfcore_megatests_showcase",
        "config": "project.yaml",
        "static_ids_key": None,
        "is_public": True,
    },
    "catalog_conformance": {
        "dir": "depictio/projects/init/catalog_conformance",
        # A template rather than a plain project config, but the shape this
        # generator reads — project id, workflow id, DC ids and descriptions —
        # is identical.
        "config": "template.yaml",
        # Not in STATIC_IDS: the conformance project's ids are generated from
        # the catalog and live in its own static_ids.json.
        "static_ids_key": None,
        "static_ids_file": "static_ids.json",
        "is_public": False,
        # One dashboard, and `dump_dashboard_seed` / `db_init` both expect it at
        # the unsuffixed path.
        "seed_names": {"overview": "dashboard.json"},
        # Fields the conformance seed carries that a freshly built one does not.
        # Kept so the seed stays a faithful copy of a saved dashboard.
        "extra_envelope": {
            "creation_time": "2026-08-29 00:00:00",
            "screenshot_ts": "",
            "project_realtime": None,
        },
        "owner_is_admin": False,
    },
}


def _oid(value: str) -> dict[str, str]:
    return {"$oid": value}


def _load_project(project_dir: Path, config_name: str) -> dict[str, Any]:
    """Project id, workflow id/tag and the DC table, straight from the config."""
    doc = yaml.safe_load((project_dir / config_name).read_text())
    workflows = doc["workflows"]
    if len(workflows) != 1:
        raise ValueError(f"{project_dir.name}: expected exactly one workflow, got {len(workflows)}")
    wf = workflows[0]
    dc_ids: dict[str, str] = {}
    dc_descriptions: dict[str, str] = {}
    for dc in wf["data_collections"]:
        tag = dc["data_collection_tag"]
        dc_ids[tag] = dc["id"]
        dc_descriptions[tag] = dc.get("description") or ""
    return {
        "project_id": doc["id"],
        "workflow_id": wf["id"],
        # The tag the React viewer shows, e.g. `python/advanced_viz_demo`.
        "wf_tag": f"{wf['engine']['name']}/{wf['name']}",
        "workflow_tag": wf["name"],
        "dc_ids": dc_ids,
        "dc_descriptions": dc_descriptions,
    }


def _check_static_ids(
    static: dict[str, Any], key: str, project: dict[str, Any], dashboards: dict[str, str]
) -> None:
    """Fail loudly when project.yaml and STATIC_IDS have drifted apart.

    Both are hand-maintained lists of the same ObjectIds, and a mismatch is
    invisible until a fresh deployment 404s on a tile.
    """
    if static["project"] != project["project_id"]:
        raise ValueError(
            f"{key}: project id {project['project_id']} != STATIC_IDS {static['project']}"
        )
    for tag, dc_id in project["dc_ids"].items():
        expected = static["data_collections"].get(tag)
        if expected is None:
            raise ValueError(f"{key}: data collection '{tag}' is missing from STATIC_IDS")
        if expected != dc_id:
            raise ValueError(f"{key}: '{tag}' is {dc_id} in project.yaml, {expected} in STATIC_IDS")
    declared = set(static.get("dashboards", {}).values())
    for slug, dashboard_id in dashboards.items():
        if dashboard_id not in declared:
            raise ValueError(
                f"{key}: dashboard '{slug}' ({dashboard_id}) is not in the project's "
                f"static id table — add it, or `reseed_project --dashboards-only` "
                f"silently skips the tab"
            )


def _enrich(
    components: list[dict[str, Any]],
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    """Inject the runtime bindings a lite component deliberately omits."""
    enriched: list[dict[str, Any]] = []
    for comp in components:
        new = dict(comp)
        new["wf_id"] = _oid(project["workflow_id"])
        new["wf_tag"] = project["wf_tag"]
        dc_tag = new.get("data_collection_tag") or ""

        if new.get("component_type") == "text" or not dc_tag:
            # A text tile binds to nothing. Leaving the fields null is what makes
            # it safe to fan out across tabs reading other collections.
            new["dc_id"] = None
            new["dc_config"] = {}
            enriched.append(new)
            continue

        dc_id = project["dc_ids"].get(dc_tag)
        if dc_id is None:
            raise KeyError(
                f"Unknown data_collection_tag '{dc_tag}' on component "
                f"{new.get('index')!r}; project.yaml declares: {sorted(project['dc_ids'])}"
            )
        new["dc_id"] = _oid(dc_id)
        new["dc_config"] = {
            "type": None,
            "metatype": None,
            "description": project["dc_descriptions"][dc_tag],
            "data_collection_tag": dc_tag,
            "dc_specific_properties": None,
            "_id": _oid(dc_id),
        }
        enriched.append(new)
    return enriched


def _build_seed(
    raw: dict[str, Any],
    project: dict[str, Any],
    dashboards: dict[str, str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    parent_tag = raw.pop("parent_dashboard_tag", None)
    dashboard_id = raw["dashboard_id"]

    lite = DashboardDataLite.model_validate(raw)
    full = lite.to_full()
    full["stored_metadata"] = _enrich(full["stored_metadata"], project)

    full["_id"] = _oid(dashboard_id)
    full["dashboard_id"] = _oid(dashboard_id)
    full["project_id"] = _oid(project["project_id"])
    # A child tab points at the main tab; the main tab points at nothing.
    # `_resolve_tab_family` matches on this field, so a parent id no document
    # carries leaves every tab a family of one.
    if parent_tag is None:
        full["parent_dashboard_id"] = None
    else:
        if parent_tag not in dashboards:
            raise KeyError(f"parent_dashboard_tag '{parent_tag}' names no dashboard YAML")
        full["parent_dashboard_id"] = _oid(dashboards[parent_tag])
    full["parent_dashboard_title"] = None
    full["is_public"] = spec["is_public"]
    full["notes_content"] = ""
    full["description"] = None
    full["flexible_metadata"] = None
    full["hash"] = None
    full["stored_edit_dashboard_mode_button"] = []
    # `to_full` leaves this one out; DashboardData defaults it, but a saved
    # dashboard carries it, so the seed should look like one.
    full["stored_add_button"] = {"count": 0}
    full["permissions"] = {
        "owners": [
            {
                "_id": _oid(ADMIN_USER_ID),
                "description": None,
                "flexible_metadata": None,
                "hash": None,
                "email": ADMIN_EMAIL,
                "is_admin": spec.get("owner_is_admin", True),
                "is_anonymous": False,
                "is_temporary": False,
                "expiration_time": None,
            }
        ],
        "editors": [],
        "viewers": [],
    }
    full["last_saved_ts"] = FROZEN_TIMESTAMP
    full.update(spec.get("extra_envelope") or {})
    for comp in full["stored_metadata"]:
        comp["last_updated"] = FROZEN_LAST_UPDATED
    return full


# Field order of the shipped seeds. Only cosmetic, but a stable order is what
# keeps `git diff` on a regenerated seed readable.
_FIELD_ORDER = [
    "_id",
    "description",
    "flexible_metadata",
    "hash",
    "dashboard_id",
    "version",
    "stored_metadata",
    "tmp_children_data",
    "stored_layout_data",
    "stored_children_data",
    "stored_edit_dashboard_mode_button",
    "left_panel_layout_data",
    "right_panel_layout_data",
    "buttons_data",
    "stored_add_button",
    "title",
    "subtitle",
    "icon",
    "icon_color",
    "icon_variant",
    "workflow_system",
    "notes_content",
    "permissions",
    "is_public",
    "last_saved_ts",
    "project_id",
    "is_main_tab",
    "parent_dashboard_id",
    "tab_order",
    "main_tab_name",
    "tab_icon",
    "tab_icon_color",
    "parent_dashboard_title",
    "creation_time",
    "screenshot_ts",
    "project_realtime",
    "filter_sections",
    "grid_sections",
    "funnel_filtering",
    "brand_theme",
]


def _ordered(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: doc[k] for k in _FIELD_ORDER if k in doc}
    out.update({k: v for k, v in doc.items() if k not in out})
    return out


def generate(project_key: str) -> int:
    spec = PROJECTS[project_key]
    project_dir = REPO_ROOT / spec["dir"]
    project = _load_project(project_dir, spec["config"])

    yaml_dir = project_dir / "dashboards"
    yaml_files = sorted(yaml_dir.glob("*.yaml"))
    if not yaml_files:
        raise FileNotFoundError(f"no dashboard YAML under {yaml_dir}")

    raws = {p.stem: yaml.safe_load(p.read_text()) for p in yaml_files}
    dashboards = {slug: raw["dashboard_id"] for slug, raw in raws.items()}
    duplicates = [i for i in dashboards.values() if list(dashboards.values()).count(i) > 1]
    if duplicates:
        raise ValueError(f"{project_key}: duplicate dashboard_id(s) {sorted(set(duplicates))}")
    if spec["static_ids_key"]:
        _check_static_ids(
            STATIC_IDS[spec["static_ids_key"]], spec["static_ids_key"], project, dashboards
        )
    elif spec.get("static_ids_file"):
        _check_static_ids(
            json.loads((project_dir / spec["static_ids_file"]).read_text()),
            project_key,
            project,
            dashboards,
        )

    seeds_dir = project_dir / ".db_seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)
    for slug, raw in raws.items():
        doc = _build_seed(raw, project, dashboards, spec)
        path = seeds_dir / (spec.get("seed_names", {}).get(slug) or f"dashboard_{slug}.json")
        path.write_text(json_util.dumps(_ordered(doc), indent=2) + "\n")
        print(f"  {path.relative_to(REPO_ROOT)} ({len(doc['stored_metadata'])} components)")
    return len(raws)


def main(argv: list[str]) -> int:
    keys = argv[1:] or list(PROJECTS)
    unknown = [k for k in keys if k not in PROJECTS]
    if unknown:
        print(f"unknown project(s): {unknown}; known: {list(PROJECTS)}", file=sys.stderr)
        return 1
    for key in keys:
        print(f"{key}:")
        total = generate(key)
        print(f"  {total} dashboard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
