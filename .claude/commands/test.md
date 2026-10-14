# Test Runner

Run tests with `uv run --extra dev` (a plain `uv run` has no test tools).

- `/test` - `uv run --extra dev pytest -xvs -n auto` (all `testpaths` from `pyproject.toml`: api, catalog, models, cli, unit, recipes)
- `/test api|models|cli|unit` - same with `depictio/tests/<scope>/`
- `/test <file or node id>` - just that test
- `/test e2e` - Playwright: `cd depictio/tests/e2e-playwright && npx playwright test` (needs the dev stack up; override target with `PLAYWRIGHT_BASE_URL` / `PLAYWRIGHT_API_URL`). Do not start docker yourself; ask the user if the stack is down.
- `/test viewer` - `cd depictio/viewer && pnpm run check:preview` (and the other `check:*` scripts that match the change); there is no JS unit-test runner.

Report pass/fail counts; for failures read the traceback, find the cause, and propose the fix.

$ARGUMENTS
