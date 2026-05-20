"""Reseed a single reference project in-place — no container restart needed.

Reseeds the project document, its data collections, dashboards, and Delta
tables without touching unrelated projects or user-created dashboards. Use
this after editing template.yaml, canonical recipes, or .db_seeds JSON for
one of the bundled reference datasets (iris, penguins, ampliseq,
advanced_viz_showcase, …).

Runs INSIDE the API container so it has MongoDB + MinIO + the depictio
module path.

Usage:
    docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env \
        exec depictio-backend python -m depictio.dev_scripts.reseed_project ampliseq

    # Without re-materialising Delta tables (faster; only dashboard/DC docs):
    docker compose ... exec depictio-backend python -m depictio.dev_scripts.reseed_project ampliseq --no-data

    # Reseed multiple at once:
    docker compose ... exec depictio-backend python -m depictio.dev_scripts.reseed_project ampliseq advanced_viz_showcase

Why this exists:
    ``docker compose down -v && up`` wipes user data, login tokens, dashboards
    a developer is iterating on, and forces a full re-init of every project.
    This script is the targeted alternative for the "I changed template.yaml,
    I need it back in MongoDB" case.

What it does:
    1. Look up the project by dataset-name → static project_id
       (via ReferenceDatasetRegistry.STATIC_IDS).
    2. Cascade-delete the project document, its DC docs, Delta-table docs,
       files docs, and the matching dashboards from MongoDB. Also wipes the
       project's S3 objects from MinIO.
    3. Re-create the project + DCs by calling create_reference_project().
    4. Re-create the project's dashboards by calling create_initial_dashboards()
       (scoped to dashboards whose project_id matches).
    5. Optionally re-materialise the Delta tables by running the same
       ReferenceDatasetProcessor the API uses post-init.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Iterable

from bson import ObjectId

from depictio.api.v1.configs.config import settings  # noqa: F401 — ensures env loads
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    initialization_collection,
    multiqc_collection,
    projects_collection,
    runs_collection,
    tokens_collection,
    users_collection,
)
from depictio.api.v1.db_init import create_initial_dashboards
from depictio.api.v1.db_init_reference_datasets import STATIC_IDS, ReferenceDatasetRegistry
from depictio.api.v1.endpoints.projects_endpoints.routes import _cascade_delete_project
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import UserBeanie


def _resolve_static_ids(dataset_name: str) -> dict:
    ids = STATIC_IDS.get(dataset_name)
    if ids is None:
        raise KeyError(f"Unknown dataset '{dataset_name}'. Known: {sorted(STATIC_IDS)}")
    return ids


def _drop_project_and_dependents(dataset_name: str) -> None:
    """Wipe the project document + its DC / dashboard / Delta-table state.

    Falls back from the ID-based cascade helper to a name-based query when
    the project document is already gone (idempotent reseed)."""
    static_ids = _resolve_static_ids(dataset_name)
    project_id = PyObjectId(static_ids["project"])
    proj = projects_collection.find_one({"_id": ObjectId(str(project_id))})
    if proj is not None:
        _cascade_delete_project(project_id, proj.get("name", dataset_name))
    else:
        logger.info(
            f"reseed: no project document for '{dataset_name}' to delete (skipping cascade)"
        )

    # `_cascade_delete_project` already removes dashboards via project_id but
    # we also clean up any orphans referencing the dashboard-level static IDs
    # (e.g. ampliseq's per-tab child dashboards whose project_id matches the
    # parent — covered by the cascade — plus any stale entry left behind by
    # an earlier broken init).
    dashboard_ids = static_ids.get("dashboards", {}).values()
    for dashboard_id in dashboard_ids:
        dashboards_collection.delete_one({"_id": ObjectId(str(dashboard_id))})

    # Drop any lingering DC docs / Delta-table docs by static ID (some get
    # missed when the cascade above runs without finding the parent project).
    dc_ids = list(static_ids.get("data_collections", {}).values())
    if dc_ids:
        oids = [ObjectId(str(x)) for x in dc_ids]
        str_query = [str(x) for x in dc_ids]
        data_collections_collection.delete_many({"_id": {"$in": oids}})
        deltatables_collection.delete_many({"data_collection_id": {"$in": oids + str_query}})
        files_collection.delete_many({"data_collection_id": {"$in": oids + str_query}})
        runs_collection.delete_many({"data_collection_id": {"$in": oids + str_query}})
        multiqc_collection.delete_many({"data_collection_id": {"$in": oids + str_query}})


async def _admin_user_and_token() -> tuple[UserBeanie, dict]:
    admin = await UserBeanie.find_one({"is_admin": True})
    if admin is None:
        raise RuntimeError("reseed: no admin user found — run a fresh deploy at least once first")
    token = tokens_collection.find_one({"user_id": admin.id, "name": "default_token"})
    if token is None:
        raise RuntimeError("reseed: no default token found for admin user")
    return admin, {
        "token": {
            "user_id": token["user_id"],
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "token_type": token.get("token_type", "bearer"),
            "token_lifetime": token.get("token_lifetime", "short-lived"),
            "expire_datetime": token["expire_datetime"],
            "refresh_expire_datetime": token["refresh_expire_datetime"],
            "name": token.get("name"),
            "created_at": token.get("created_at"),
        },
        "config_path": None,
        "new_token_created": False,
    }


async def _recreate_project(dataset_names: list[str]) -> list[dict]:
    """Re-create only the specified projects via the registry — mirrors what
    create_reference_datasets() does but scoped to the targets."""
    admin, token_payload = await _admin_user_and_token()
    results: list[dict] = []
    for name in dataset_names:
        result = await ReferenceDatasetRegistry.create_reference_project(
            dataset_name=name, admin_user=admin, token_payload=token_payload
        )
        if not result.get("success"):
            raise RuntimeError(f"reseed: create_reference_project failed for {name}: {result}")
        # Build metadata dict matching what create_reference_datasets() emits
        # (`ReferenceDatasetProcessor.process_dataset` reads `data_collections` /
        # `has_joins` / `join_definitions` / `has_links` / `link_definitions`).
        project = result["project"]
        results.append(
            {
                "name": name,
                "project_id": str(project.id),
                "workflow_id": str(project.workflows[0].id),
                "data_collections": [
                    {"id": str(dc.id), "tag": dc.data_collection_tag}
                    for dc in project.workflows[0].data_collections
                ],
                "has_joins": result.get("has_joins", False),
                "join_definitions": result.get("join_definitions", []),
                "has_links": result.get("has_links", False),
                "link_definitions": result.get("link_definitions", []),
            }
        )

    # Refresh reference_datasets_metadata so the background processor can find the
    # newly-created projects when --no-data isn't passed.
    from datetime import datetime, timezone

    existing_meta = initialization_collection.find_one({"_id": "reference_datasets_metadata"}) or {}
    existing_projects = {p["name"]: p for p in existing_meta.get("projects", [])}
    for entry in results:
        existing_projects[entry["name"]] = entry
    initialization_collection.replace_one(
        {"_id": "reference_datasets_metadata"},
        {
            "_id": "reference_datasets_metadata",
            "projects": list(existing_projects.values()),
            "created_at": datetime.now(timezone.utc),
        },
        upsert=True,
    )
    return results


async def _recreate_dashboards(dataset_names: list[str]) -> None:
    """Re-run create_initial_dashboards. It iterates ALL dashboards, but only
    creates those whose JSON file is on disk and whose project_id resolves to
    an existing project — so wiped-then-recreated targets get rebuilt and the
    others are no-ops (idempotent path inside create_dashboard_from_json)."""
    admin = await UserBeanie.find_one({"is_admin": True})
    await create_initial_dashboards(admin_user=admin)


async def _trigger_data_materialisation(dataset_names: Iterable[str]) -> None:
    """Run the same background processor the API uses post-init."""
    from depictio.api.v1.services.process_reference_datasets import (
        ReferenceDatasetProcessor,
    )
    from depictio.models.models.cli import CLIConfig

    admin = users_collection.find_one({"is_admin": True})
    if admin is None:
        raise RuntimeError("reseed: no admin user for data materialisation")
    token = tokens_collection.find_one({"user_id": admin["_id"]})
    if token is None:
        raise RuntimeError("reseed: no token for admin user during data materialisation")

    cli_config = CLIConfig.model_validate(
        {
            "user": {
                "id": str(admin["_id"]),
                "email": admin["email"],
                "is_admin": admin["is_admin"],
                "token": {
                    "user_id": token["user_id"],
                    "access_token": token["access_token"],
                    "refresh_token": token["refresh_token"],
                    "token_type": token.get("token_type", "bearer"),
                    "token_lifetime": token.get("token_lifetime", "short-lived"),
                    "expire_datetime": token["expire_datetime"],
                    "refresh_expire_datetime": token["refresh_expire_datetime"],
                    "name": token.get("name"),
                    "created_at": token.get("created_at"),
                },
            },
            "api_base_url": settings.fastapi.url,
            "s3_storage": settings.minio.model_dump(),
        }
    )
    processor = ReferenceDatasetProcessor(cli_config)

    metadata_doc = initialization_collection.find_one({"_id": "reference_datasets_metadata"})
    if metadata_doc is None:
        logger.warning("reseed: no reference_datasets_metadata — nothing to materialise")
        return

    targets = set(dataset_names)
    for dataset_metadata in metadata_doc.get("projects", []):
        if dataset_metadata["name"] not in targets:
            continue
        logger.info(f"reseed: materialising {dataset_metadata['name']}")
        await processor.process_dataset(dataset_metadata)


async def _replace_dashboards_only(dataset_names: list[str]) -> None:
    """Dashboard-only reseed: delete only the dashboard documents for the
    targeted projects, then re-run create_initial_dashboards() to re-upsert
    them from the .db_seeds JSON files.

    Does NOT touch project / DC / Delta-table state — safe to use after a
    pure dashboard-JSON edit (layout shifts, tile width changes, new tiles
    binding to already-materialised DCs)."""
    for name in dataset_names:
        ids = _resolve_static_ids(name)
        for dashboard_id in ids.get("dashboards", {}).values():
            dashboards_collection.delete_one({"_id": ObjectId(str(dashboard_id))})
    admin = await UserBeanie.find_one({"is_admin": True})
    if admin is None:
        raise RuntimeError("reseed: no admin user — run a fresh deploy first")
    await create_initial_dashboards(admin_user=admin)


async def reseed(
    dataset_names: list[str], materialise_data: bool = True, dashboards_only: bool = False
) -> None:
    for name in dataset_names:
        _ = _resolve_static_ids(name)  # validate up-front

    # Initialise Motor + Beanie ODM — required for UserBeanie/ProjectBeanie/
    # TokenBeanie queries used downstream. The API process does this on
    # startup; standalone scripts have to do it themselves.
    from depictio.api.v1.services.lifespan import init_motor_beanie

    await init_motor_beanie()

    if dashboards_only:
        logger.info(f"reseed: dashboards-only refresh for {dataset_names}")
        await _replace_dashboards_only(dataset_names)
        logger.info(f"reseed: done for {dataset_names}")
        return

    logger.info(f"reseed: dropping existing state for {dataset_names}")
    for name in dataset_names:
        _drop_project_and_dependents(name)

    logger.info(f"reseed: recreating project + DC documents for {dataset_names}")
    await _recreate_project(dataset_names)

    logger.info(f"reseed: recreating dashboards for {dataset_names}")
    await _recreate_dashboards(dataset_names)

    if materialise_data:
        logger.info(f"reseed: materialising Delta tables for {dataset_names}")
        await _trigger_data_materialisation(dataset_names)
    else:
        logger.info("reseed: --no-data passed; skipping Delta materialisation")

    logger.info(f"reseed: done for {dataset_names}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reseed one or more reference projects in-place (no container restart)."
    )
    parser.add_argument(
        "datasets",
        nargs="+",
        help="Dataset names from ReferenceDatasetRegistry.STATIC_IDS (e.g. ampliseq).",
    )
    parser.add_argument(
        "--no-data",
        action="store_true",
        help=(
            "Skip Delta-table re-materialisation. WARNING: the cascade still wipes S3 — "
            "tiles binding to canonical DCs will 500 until you reseed without --no-data. "
            "Only useful when you're about to invoke a real CLI ingest run afterwards."
        ),
    )
    parser.add_argument(
        "--dashboards-only",
        action="store_true",
        help=(
            "Refresh ONLY the dashboard documents (preserves project / DCs / Delta tables). "
            "Use this after editing only .db_seeds/dashboard_*.json — layout shifts, tile "
            "widths, added/removed tiles binding to already-materialised DCs."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        asyncio.run(
            reseed(
                args.datasets,
                materialise_data=not args.no_data,
                dashboards_only=args.dashboards_only,
            )
        )
    except Exception as exc:
        logger.exception(f"reseed failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
