# Quality Check

Run comprehensive code quality checks on the depictio codebase.

## Instructions

Execute the following quality checks in order:

1. **Ruff Format Check**: `ruff format --check depictio/`
2. **Ruff Lint Check**: `ruff check depictio/`
3. **Type Check with ty**: `ty check depictio/models/ depictio/api/ depictio/dash/ depictio/cli/`
4. **Pre-commit hooks**: `pre-commit run --all-files`

If any check fails:
- Show the specific errors found
- Suggest fixes for each issue
- Offer to auto-fix issues where possible (ruff --fix)

If all checks pass, confirm success and show a summary.

## Usage

`/quality` - Run all quality checks
`/quality fix` - Run checks and auto-fix what's possible
`/quality <path>` - Run checks on specific path (e.g., `/quality depictio/api/`)

$ARGUMENTS
