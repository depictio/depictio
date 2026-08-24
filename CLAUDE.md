# CLAUDE.md

## Commands

### Docker Setup
```bash
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up
```
Services: `mongo` (27018), `redis` (6379), `minio`, `depictio-backend` (8058),
`depictio-viewer-dev` (Vite HMR, default viewer), `depictio-celery-worker`.
Profile-gated: `depictio-viewer` (nginx + built bundle, `ci`), `flower` (`monitoring`).

### Python Environment
Managed with **uv** (`uv.lock`). No venv is checked in — CI does
`uv venv --python 3.12.9 venv && uv pip install -e ".[dev]"`. Prefix commands with `uv run`.
`pixi.toml` offers an alternative Docker-free stack (`pixi run start-infra`, `pixi run api`).

### Testing
```bash
uv run pytest -xvs -n auto     # testpaths (pyproject.toml) = tests/{api,models,cli,unit}

# E2E (Playwright — the suite CI runs)
cd depictio/tests/e2e-playwright && npx playwright test
# targets depictio-viewer-dev; override with PLAYWRIGHT_BASE_URL / PLAYWRIGHT_API_URL
```
Playwright is the only e2e suite; the legacy Cypress suite has been removed.

### Code Quality
```bash
ruff format depictio && ruff check depictio
uv run ty check depictio/models/   # only gated dir; must pass with zero errors
pre-commit run --all-files         # mandatory after all code changes
```

## Entry Points & Key Dependencies

- **API**: `depictio/api/main.py` (FastAPI + Beanie ODM); also serves the built SPA
- **Worker**: `depictio/api/celery_app.py` (Celery + Redis)
- **Frontend**: `depictio/viewer/` — React 18 + Vite + Mantine 7 SPA (`src/main.tsx`)
- **CLI**: `depictio/cli/depictio_cli.py` (Typer)
- **Models**: `depictio/models/` (Pydantic, shared across all components)
- **Catalog**: `depictio/catalog/` (tool-specific dashboard/DC definitions + `payload.py`)
- Shared JS packages (pnpm workspace): `packages/depictio-components`,
  `packages/depictio-react-core`, `packages/plotly-complexheatmap`, `packages/plotly-upset`
- Key deps: FastAPI, Beanie, Celery, Polars, Delta Lake, Pydantic, Plotly, Playwright
- Config: `pyproject.toml`, `pixi.toml`, `docker-compose.dev.yaml`

## Conventions & Rules

### Frontend
- **Mantine 7** for all new components; the Dash/DMC frontend is fully removed
- Never hardcode colors — prefer Mantine native theming, CSS variables as last resort

### Environment & Config
- Config source of truth: `depictio/api/v1/configs/settings_models.py`
- `DEPICTIO_CONTEXT`: `server` (default) or `cli`
- Environment files:
  - Not in worktree: read `.env` and `docker-compose/.env`
  - In worktree: read `.env.instance`
- Default MongoDB URL (unless overridden by `.env` / `.env.instance`): `localhost:27018/depictioDB`

### Docker
- Don't run docker commands except `docker logs`

### Code Quality
- **Mandatory**: run `pre-commit run --all-files` after every code change
- `ty` gate is narrowed to `depictio/models/`, with per-file excludes in
  `[tool.ty.src]`. `depictio/api/` and `depictio/cli/` carry known type-debt and are
  off the gate — don't widen the gate casually, don't add new debt

### Documentation
- After significant PRs, update depictio-docs and Obsidian notes

## Architecture Pointers

### SPA Routes (served by FastAPI from `depictio/viewer` build)
| Route | App |
| --- | --- |
| `/dashboards` | management |
| `/dashboard/{id}` | viewer |
| `/dashboard-edit/{id}` | editor (`+ /component/add/{id}`, `/component/edit/{id}`) |
| `/about`, `/admin`, `/profile`, `/cli-agents` | supporting pages |

Route dispatch is plain regex in `depictio/viewer/src/main.tsx` +
`src/builder/routeMatch.ts` — no router lib.

### Screenshot System
- Playwright drives the React SPA; composite targeting via `.react-grid-item`
- **Detail**: see `depictio/api/v1/endpoints/utils_endpoints/CLAUDE.md`

### Dashboard YAML ↔ JSON Seeds
- Fresh deployments load from `.db_seeds/*.json` (via `db_init.py`), **not** from YAML
- **After modifying dashboard YAML**: regenerate the matching `.db_seeds/*.json` or new
  components won't appear in fresh deployments
- Project dir `depictio/projects/{group}/{project}[/{version}]/` holds both
  `dashboards/*.yaml` and `.db_seeds/*.json`
- Multi-tab dashboards: one JSON per tab (e.g. nf-core `dashboard_multiqc.json`)
- Reseed a running instance in place: `depictio/dev_scripts/reseed_project.py` (`/reseed`)
- nf-core template versions: seeding/CLI/CI/docs auto-resolve the **highest** version dir
  (`nf-core/<pipeline>/latest` works as a template id). New version = run
  `scripts/bump_template_version.py` + follow the checklist it prints

### Data Flow
CLI ingests data → Delta/S3/MongoDB → API serves → React viewer renders

### Auth & Storage
- JWT tokens, role-based access (users, groups, projects); single-user mode via
  `DEPICTIO_AUTH_SINGLE_USER_MODE`
- S3-compatible storage (MinIO local, AWS prod), Delta Lake format
- API endpoints at `/depictio/api/v1/`
