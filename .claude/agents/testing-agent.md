---
name: testing-agent
description: Writing and running depictio tests - pytest (api, models, cli, unit, catalog, recipes) and the Playwright e2e suite.
---

# Testing Agent

Commands and gates are in `/CLAUDE.md`; `/test` runs them.

## Layout

- `depictio/tests/{api,models,cli,unit,catalog,recipes}` - the pytest `testpaths` in `pyproject.toml` (a new directory must be added there or CI never runs it).
- `depictio/tests/conftest.py` - env defaults set before any depictio import. Mongo is mocked with `mongomock` / `mongomock-motor`.
- `depictio/tests/e2e-playwright/` - the only e2e suite (`npx playwright test`, needs the dev stack up).
- Viewer contract checks: `pnpm run check:*` scripts in `depictio/viewer/package.json` (there is no JS unit-test runner).

## Conventions

- `asyncio_mode = "strict"`: async tests need `@pytest.mark.asyncio`.
- Markers: `no_db`, `integration`, `playwright`, `docker`.
- Run with `uv run --extra dev pytest -xvs -n auto [path]`.
- A bug fix gets a test that fails before the fix. A test that exercises a version/time-travel read should use data that differs between versions, not only in size (see the `iris_versioned` note in CLAUDE.md).
