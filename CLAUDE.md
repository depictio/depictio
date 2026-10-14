# CLAUDE.md

## Commands

- Python is managed with **uv**: prefix commands with `uv run --extra dev` (a plain `uv run` has only the base install; a plain `uv sync` removes the extras). Extras: `multiqc`, `server`, `local` (`depictio local up`), `dev`. Docker-free stack: `pixi.toml`.
- Dev stack: `docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up` (backend 8058, mongo 27018, redis 6379, s3 9000, Vite viewer). **Run no docker command except `docker logs`.**
- Tests: `uv run --extra dev pytest -xvs -n auto` (`tests/{api,models,cli,unit}`); e2e: `cd depictio/tests/e2e-playwright && npx playwright test` (the only e2e suite).
- Quality: `ruff format depictio && ruff check depictio`; `uv run --extra dev ty check depictio/models/` (the only gated dir, zero errors; don't widen the gate or add type debt in `api/` and `cli/`); **`pre-commit run --all-files` after every code change.**

## Layout

- `depictio/api/main.py` FastAPI + Beanie (also serves the built SPA); worker `api/celery_app.py`; CLI `cli/depictio_cli.py` (Typer); `models/` Pydantic, shared by all; `catalog/` tool definitions.
- Frontend `depictio/viewer/`: React 18 + Vite + Mantine 7, routes dispatched by regex in `src/main.tsx` + `src/builder/routeMatch.ts` (no router lib). Shared JS in `packages/` (pnpm workspace).
- Config source of truth: `depictio/api/v1/configs/settings_models.py`. Env files: `.env` and `docker-compose/.env`, or `.env.instance` in a worktree. Default Mongo `localhost:27018/depictioDB`. API at `/depictio/api/v1/`.

## Rules

- Mantine 7 for new UI. Never hardcode colors: Mantine theming, CSS variables as a last resort. The Dash/DMC frontend is gone.
- Fresh deployments load `.db_seeds/*.json`, **not** dashboard YAML: after editing a `depictio/projects/**/dashboards/*.yaml`, regenerate the matching `.db_seeds/*.json`. Reseed a running instance with `depictio/dev_scripts/reseed_project.py`. nf-core template versions: see `scripts/bump_template_version.py`.
- Before touching dashboard saves, versions, restore or the editor's writes, read `depictio/api/v1/endpoints/dashboards_endpoints/CLAUDE.md`. For data collections, storage and auth: `depictio/api/v1/CLAUDE.md`. Screenshots: `depictio/api/v1/endpoints/utils_endpoints/CLAUDE.md`.
- After a significant PR, update depictio-docs and the Obsidian notes.
