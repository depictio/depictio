# CLAUDE.md

## Commands

### Docker Setup
```bash
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up
```

### Python Environment
Default: `depictio-venv-dash-v3/bin/python`

### Testing
```bash
pytest depictio/tests/ -xvs -n auto

# Frontend typecheck (no JS unit-test runner exists in this repo)
cd depictio/viewer && ./node_modules/.bin/tsc --noEmit

# E2E — Playwright is the current suite; Cypress is legacy and being migrated away from
cd depictio/tests/e2e-playwright && npx playwright test
```

### Code Quality
```bash
ruff format . && ruff check .
ty check depictio/models/ depictio/api/    # must pass with zero errors
pre-commit run --all-files                 # mandatory after all code changes
```

## Entry Points & Key Dependencies

- **API**: `depictio/api/main.py` (FastAPI + Beanie ODM)
- **Frontend**: `depictio/viewer/` (React SPA) + `packages/depictio-react-core/` (shared components + API client)
- **CLI**: `depictio/cli/depictio_cli.py` (Typer)
- **Models**: `depictio/models/` (Pydantic, shared across all components)
- Key deps: FastAPI, React, Mantine, Plotly, Beanie, Polars, Delta Lake, Pydantic
- Config: `pyproject.toml`, `pixi.toml`, `docker-compose.dev.yaml`

## Conventions & Rules

### Frontend
- **The Dash app is gone.** `depictio/dash/` no longer exists; the frontend is a React SPA.
  Stale comments across the Python codebase still reference `depictio/dash/layouts/*` — ignore them.
- **Mantine 7.14+** for all components; `@iconify/react` for icons (`mdi:*`, `tabler:*`)
- Never hardcode colors — prefer Mantine theming, CSS variables as last resort
- The whole API client is one file: `packages/depictio-react-core/src/api.ts`.
  Prefer `authFetch` (token refresh + 401 retry) over the older `authHeaders()` helper.
- No react-query and no JS unit tests in this tree — polling is manual `setInterval`,
  frontend coverage is Playwright E2E only
- `depictio/react-frontend/` is a dead scaffold — ignore it

### Environment & Config
- Config source of truth: `depictio/api/v1/configs/settings_models.py`
- Contexts: API, Dash, CLI (set via `DEPICTIO_CONTEXT`)
- Environment files:
  - Not in worktree: read `.env` and `docker-compose/.env`
  - In worktree: read `.env.instance`
- Default MongoDB URL (if not modified by .env and .env.instance): `localhost:27018/depictioDB`

### Docker
- Don't run docker commands except `docker logs`

### Code Quality
- **Mandatory**: run `pre-commit run --all-files` after every code change
- Type checking with `ty` must pass with zero errors
- No `# type: ignore` comments

### Documentation
- After significant PRs, update depictio-docs and Obsidian notes

## Architecture Pointers

### React SPA (one bundle, three surfaces)
Management (`/dashboards`) | Viewer (`/dashboard/{id}`) | Editor (`/dashboard-edit/{id}`)
- Routing is `pathname.startsWith` dispatch in `depictio/viewer/src/main.tsx:resolveTree()` — no react-router
- Each route prefix needs a matching handler in `depictio/api/main.py` returning `index.html`;
  the dashboard prefixes are `:path` catch-alls, so query params need no backend change
- Session in `localStorage['local-store']`, theme in `theme-store`

### Dashboard Versioning
- Every save snapshots the whole tab family into `dashboard_versions` (`dashboards_endpoints/versioning.py`)
- Autosaves coalesce within an anchored window; an unchanged save writes nothing
- Snapshots are content-only — `permissions`/`is_public`/`project_id` always come from the live doc
- Retention is `version_store.prune_family()`, not a TTL index (a TTL cannot exempt pins)

### Screenshot System
- Component-based composite targeting via `.react-grid-item`
- **Detail**: see `depictio/api/v1/endpoints/utils_endpoints/CLAUDE.md`

### Dashboard YAML ↔ JSON Seeds
- Fresh deployments load from `.db_seeds/*.json` files (via `db_init.py`), **not** from YAML
- **After modifying dashboard YAML**: regenerate the corresponding `.db_seeds/*.json` or new components won't appear in fresh deployments
- Path: `depictio/projects/{project}/dashboards/*.yaml` → `.db_seeds/*.json`
- Multi-tab dashboards: main tab = `dashboard_multiqc.json`, child tabs = separate JSON files

### Data Flow
CLI ingests data → Delta/S3/MongoDB → API serves → React renders

### Data Collection Storage Families
Six types (`table`, `jbrowse2`, `multiqc`, `image`, `geojson`, `phylogeny`) with three storage shapes:
- **Delta** — `table`, `image` (manifest only), joined/transformed: Delta table at `s3://{bucket}/{dc_id}`
- **Content-addressed objects** — `multiqc`: `s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`, immutable per ingest
- **Opaque blobs** — `geojson` (fixed S3 key), `phylogeny` (bare filesystem path, never uploaded)

`metatype` is a free-form unvalidated string — never key behaviour on it.

### Auth & Storage
- JWT tokens, role-based access (users, groups, projects)
- S3-compatible storage (MinIO local, AWS prod), Delta Lake format
- API endpoints at `/depictio/api/v1/`
