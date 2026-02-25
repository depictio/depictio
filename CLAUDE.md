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

# E2E (Cypress)
cd depictio/tests/e2e-tests && /Users/tweber/.nvm/versions/node/v20.16.0/bin/npx cypress run --config screenshotsFolder=cypress/screenshots,videosFolder=cypress/videos,trashAssetsBeforeRuns=false,video=true,screenshotOnRunFailure=true
```

### Code Quality
```bash
ruff format . && ruff check .
ty check depictio/models/ depictio/api/    # must pass with zero errors
pre-commit run --all-files                 # mandatory after all code changes
```

## Entry Points & Key Dependencies

- **API**: `depictio/api/main.py` (FastAPI + Beanie ODM)
- **Dash**: `depictio/dash/app.py` (Plotly Dash + DMC 2.0)
- **CLI**: `depictio/cli/depictio_cli.py` (Typer)
- **Models**: `depictio/models/` (Pydantic, shared across all components)
- Key deps: FastAPI, Dash/Plotly, Beanie, Polars, Delta Lake, Pydantic
- Config: `pyproject.toml`, `pixi.toml`, `docker-compose.dev.yaml`

## Conventions & Rules

### Frontend
- Use **DMC 2.0+** for all new components (detail in `depictio/dash/CLAUDE.md`)
- Never hardcode colors — prefer DMC native theming, CSS variables as last resort
- Dash v3: use `app.run()` not `run_server()`

### Environment & Config
- Config source of truth: `depictio/api/v1/configs/settings_models.py`
- Contexts: API, Dash, CLI (set via `DEPICTIO_CONTEXT`)
- Environment files:
  - Not in worktree: read `.env` and `docker-compose/.env`
  - In worktree: read `.env.instance`
- MongoDB URL: `localhost:27018/depictioDB`

### Docker
- Don't run docker commands except `docker logs`

### Code Quality
- **Mandatory**: run `pre-commit run --all-files` after every code change
- Type checking with `ty` must pass with zero errors
- No `# type: ignore` comments

### Documentation
- After significant PRs, update depictio-docs and Obsidian notes

## Architecture Pointers

### Dash Multi-App Architecture (3 apps)
Management (`/dashboards`) | Viewer (`/dashboard/{id}`) | Editor (`/dashboard/{id}/edit`)
- Shared stores in `depictio/dash/layouts/shared_app_shell.py:create_shared_stores()`
- **Detail**: see `depictio/dash/CLAUDE.md`

### Screenshot System
- Component-based composite targeting via `.react-grid-item`
- **Detail**: see `depictio/api/v1/endpoints/utils_endpoints/CLAUDE.md`

### Data Flow
CLI ingests data → Delta/S3/MongoDB → API serves → Dash renders

### Auth & Storage
- JWT tokens, role-based access (users, groups, projects)
- S3-compatible storage (MinIO local, AWS prod), Delta Lake format
- API endpoints at `/depictio/api/v1/`
