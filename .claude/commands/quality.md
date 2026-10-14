# Quality Check

Run the project gates (CLAUDE.md, Code Quality) and report.

1. `uv run --extra dev ruff format depictio` then `uv run --extra dev ruff check depictio`
2. `uv run --extra dev ty check depictio/models/` (the only gated directory; must be zero errors)
3. `uv run --extra dev pre-commit run --all-files` (mandatory after any code change)
4. If `depictio/viewer` or `packages/` changed: `cd depictio/viewer && pnpm run build` and the relevant `pnpm run check:*`.

On failure show the errors and fix them (`ruff --fix` where safe). `/quality fix` applies fixes and re-runs; `/quality <path>` limits ruff to a path (pre-commit still runs on everything).

$ARGUMENTS
