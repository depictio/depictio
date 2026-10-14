# Architecture Explorer

Explain part of the depictio architecture, grounded in the code (read it, do not answer from memory). Overview and conventions: `/CLAUDE.md`.

## Map

- `depictio/api/` - FastAPI + Beanie; endpoints in `v1/endpoints/<domain>_endpoints/`, Celery worker in `celery_app.py`. Also serves the built SPA.
- `depictio/viewer/` - React 18 + Vite + Mantine 7 SPA; shared packages in `packages/`.
- `depictio/cli/` - Typer CLI (ingest, dashboard import/validate/export, local server, templates).
- `depictio/models/` - Pydantic models shared by all components.
- `depictio/catalog/`, `depictio/projects/`, `depictio/recipes/` - tool catalog, reference projects (YAML + `.db_seeds`), recipes.
- Data flow: CLI ingests -> Delta/S3 + MongoDB -> API serves -> React viewer renders.

## Usage

- `/arch` - overview of the map above, verified against the tree
- `/arch <topic>` - deep dive (`api`, `viewer`, `models`, `auth`, `ingestion`, `storage`, `versioning`, `catalog`)
- `/arch flow <feature>` - trace a feature from the viewer through the API to storage

Cite `file:line` for every claim.

$ARGUMENTS
