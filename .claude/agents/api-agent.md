---
name: api-agent
description: Backend work in depictio - FastAPI endpoints, Beanie/Pydantic models, Delta/S3 data paths and the CLI ingest side.
---

# Backend Agent

Read `/CLAUDE.md` first, then `depictio/api/v1/CLAUDE.md` (data flow, storage families, auth) and `depictio/api/v1/endpoints/dashboards_endpoints/CLAUDE.md` (versioning) when the change touches them. This file only says where things live.

## Where things live

- Endpoints: `depictio/api/v1/endpoints/<domain>_endpoints/routes.py`, each router registered in `depictio/api/v1/endpoints/routers.py`.
- Auth dependencies: `get_current_user` and `get_user_or_anonymous` in `depictio/api/v1/endpoints/user_endpoints/routes.py`.
- Mongo collections: `depictio/api/v1/db.py` (names come from `settings.mongodb.collections`).
- Models (shared by API, CLI and worker): `depictio/models/models/`. Base classes and `PyObjectId` are in `base.py`; Beanie documents are `<Name>Beanie(<Name>, Document)` with an inner `Settings.name`.
- Delta/S3: `depictio/api/v1/deltatables_utils.py`, `depictio/api/v1/s3.py`; S3 storage options for Polars in `depictio/models/s3_utils.py`.
- Config: `depictio/api/v1/configs/settings_models.py`. Do not read env vars ad hoc.
- CLI: `depictio/cli/` (Typer, commands in `cli/cli/commands/`).
- Background jobs: `depictio/api/celery_app.py`, `depictio/api/v1/celery_tasks.py`.

## Rules

- A change to a model in `depictio/models/` must pass `uv run --extra dev ty check depictio/models/` (zero errors). Do not add type debt in `api/` or `cli/`.
- A new dashboard field goes into `TabSnapshot` or a `SNAPSHOT_*_FIELDS` set (see `depictio/api/v1/endpoints/dashboards_endpoints/CLAUDE.md`). A new content-mutating dashboard route must seed a baseline before and capture after.
- Use `/api-endpoint` and `/pydantic-model` for scaffolding, `/test` for tests, `/quality` before finishing.
