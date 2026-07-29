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

# Frontend typecheck (no JS unit-test runner exists in this repo)
cd depictio/viewer && ./node_modules/.bin/tsc --noEmit

# E2E (Playwright — the suite CI runs)
cd depictio/tests/e2e-playwright && npx playwright test
# targets depictio-viewer-dev; override with PLAYWRIGHT_BASE_URL / PLAYWRIGHT_API_URL
```
`depictio/tests/e2e-tests/` is the **legacy Cypress** suite — not run in CI.

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

> `depictio/react-frontend/` is an **abandoned scaffold** (its README still calls Dash
> production). Not built or served by either compose file — don't edit it.

## Conventions & Rules

### Frontend
- **Mantine 7** for all new components; the Dash/DMC frontend is fully removed.
  Stale comments across the Python codebase still reference `depictio/dash/layouts/*` — ignore them.
- `@iconify/react` for icons (`mdi:*`, `tabler:*`)
- Never hardcode colors — prefer Mantine native theming, CSS variables as last resort
- The whole API client is one file: `packages/depictio-react-core/src/api.ts`.
  Prefer `authFetch` (token refresh + 401 retry) over the older `authHeaders()` helper.
- No react-query and no JS unit tests in this tree — polling is manual `setInterval`,
  frontend coverage is Playwright E2E only

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
- Each route prefix needs a matching handler in `depictio/api/main.py` returning `index.html`;
  the dashboard prefixes are `:path` catch-alls, so query params need no backend change
- Session in `localStorage['local-store']`, theme in `theme-store`

### Dashboard Versioning
- Every save snapshots the whole tab family into `dashboard_versions` (`dashboards_endpoints/versioning.py`)
- **`/save` is not the only route that captures.** `POST /edit`, `PATCH /tab`,
  `DELETE /tab` and `/tabs/reorder` all change content, so each seeds a baseline
  *before* its write and captures *after* it. A tab delete anchors on the parent (the
  deleted tab can no longer resolve its own family) and is `explicit`, so it never
  coalesces into a neighbouring autosave. Adding a new content-mutating route without
  both calls silently makes that change unrecoverable
- Autosaves coalesce within an anchored window; an unchanged save writes nothing, **whatever its kind**
- The first save on a family seeds a baseline first (`ensure_baseline_quietly`), so the
  pre-edit state is restorable — capture otherwise only ever records states already left
- `tab_count`/`component_count` are **stored**, not derived: the list endpoint projects
  `tabs` away, so a timeline row has nothing left to count
- Snapshots are content-only — `permissions`/`is_public`/`project_id` always come from the live doc
- Snapshots stringify ObjectIds to hash deterministically; restore calls `_rehydrate_ids`
  to undo that, or components come back with string `dc_id`s that match no lookup
- Retention is `version_store.prune_family()`, not a TTL index (a TTL cannot exempt pins)
- UI: entry point is in the Settings drawer, not the header. `/dashboard/{id}?version={vid}`
  renders a snapshot read-only in the viewer (`src/versions/preview.ts`)
- Preview **merges** the snapshot onto the live document — a `TabSnapshot` has no
  `project_id`/`permissions` by design, so rendering it alone breaks data resolution.
  Guarded by `npm run check:preview` (no JS test runner in this tree)
- Version history covers **layout, components and data**. `DataCollectionStamp` is read
  back: `as_of_version` expands a version's stamps into per-collection pins, and
  `data_versions: {dc_id: N}` overrides one. A stale version id is a **400**, never a
  silent fall back to current data
- A time-travelling render needs **both halves** in the request body: `as_of_version` /
  `data_versions` for the data, and `component_overrides` for the definition. Sending
  only the pins renders a past version's data through today's chart config and labels it
  as the past. Both halves were missing once, and neither failure raised
- `component_overrides` is narrowed server-side by `_DEFINITION_FIELDS` (per component
  type, presentation fields only). `wf_id`/`dc_id`/`dc_config` are absent from every
  allow-list: they decide *which collection is read*, and honouring them from a request
  body would read data the dashboard does not reference and whose permissions were never
  checked
- Cache keys are salted with the pin, so a historical read is its own entry rather than
  colliding with the live one
- Component ids come from a UUID5 of stable content, **not** regenerated on import.
  Three places must agree; `_regenerate_component_indices` runs on import and will
  silently undo it. Without stable ids no component-level history can match anything
- Time-travel UI is **edit mode only** (timeline, dataset picker, component history) —
  all of it writes or re-points data. The viewer keeps only the `?version=` preview.
  `check_served_bundle.py` asserts that split in the *served bundle*, in both directions
- Deleting a main tab drops its ledger + seq counter; a child tab's versions belong to
  the family and must survive
- `depictio/projects/init/iris_versioned/` is the fixture for exercising any of this:
  4 data versions at 50/100/100/150 rows and 4 dashboard versions. Batch 2 vs 3 have the
  **same row count** and differ only in values, which is what makes a read that silently
  serves current data visible rather than merely plausible. Build it with
  `rebuild_demo.py`; not auto-seeded — see its README
- Batch N must be ingested *before* dashboard version N is saved. Ingest everything first
  and all four versions stamp the newest commit: labels, counts and stamps all look
  right, and "restore v1's data" quietly shows the complete survey. `rebuild_demo.py`
  asserts the stamps ascend

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

### Data Flow
CLI ingests data → Delta/S3/MongoDB → API serves → React viewer renders

### Data Collection Storage Families
Six types (`table`, `jbrowse2`, `multiqc`, `image`, `geojson`, `phylogeny`) with three storage shapes:
- **Delta** — `table`, `image` (manifest only), joined/transformed: Delta table at `s3://{bucket}/{dc_id}`
- **Content-addressed objects** — `multiqc`: `s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`, immutable per ingest
- **Opaque blobs** — `geojson` (fixed S3 key), `phylogeny` (bare filesystem path, never uploaded)

`metatype` is a free-form unvalidated string — never key behaviour on it.

### Auth & Storage
- JWT tokens, role-based access (users, groups, projects); single-user mode via
  `DEPICTIO_AUTH_SINGLE_USER_MODE`
- S3-compatible storage (MinIO local, AWS prod), Delta Lake format
- API endpoints at `/depictio/api/v1/`
