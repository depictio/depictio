# Test Runner

Run tests with `uv run --extra dev` (a plain `uv run` has no test tools).

- `/test` - `uv run --extra dev pytest -xvs -n auto` (all `testpaths` from `pyproject.toml`: api, catalog, models, cli, unit, recipes)
- `/test api|models|cli|unit` - same with `depictio/tests/<scope>/`
- `/test <file or node id>` - just that test
- `/test e2e` - Playwright: `cd depictio/tests/e2e-playwright && npx playwright test` (needs the dev stack up; override target with `PLAYWRIGHT_BASE_URL` / `PLAYWRIGHT_API_URL`). Do not start docker yourself; ask the user if the stack is down.
- `/test viewer` - `cd depictio/viewer && pnpm run check:preview` (and the other `check:*` scripts that match the change); there is no JS unit-test runner.

Report pass/fail counts; for failures read the traceback, find the cause, and propose the fix.

## Known failures in the cloud sandbox

These fail there and not in CI, so do not chase them in an unrelated change:

- Tests that expect an unwritable directory (`test_watch`, `test_local_*`): the sandbox runs as root.
- `test_s3_access` and `TestLoopbackProxy`: they assume a clean proxy environment and a reachable S3.
- API and endpoint tests that need a live mongo, when no stack is running.
- `helm lint` and the `shellcheck` hook on `upload.sh` and `security_audit_compose.sh` (pre-commit).

Other sandbox limits: no docker, a shallow clone (`git log -S` and `git blame` stop early), GraphQL answers 403 so `gh pr checks` fails (use the GitHub MCP tools), `pnpm install` can exceed the 10-minute tool limit (run it in the background and wait with an `until` loop), and a foreground `sleep` is blocked.

$ARGUMENTS
