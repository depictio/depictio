# Test Runner

Run tests for the depictio project.

## Instructions

Run pytest with the specified scope:

1. Parse the arguments to determine what to test
2. Run tests with appropriate flags: `pytest depictio/tests/ -xvs -n auto`
3. If specific module is given, run only those tests
4. Report results clearly with pass/fail counts
5. If tests fail, analyze the failures and suggest fixes

## Test Scopes

- `api` - Run API tests: `pytest depictio/tests/api/ -xvs -n auto`
- `models` - Run model tests: `pytest depictio/tests/models/ -xvs -n auto`
- `cli` - Run CLI tests: `pytest depictio/tests/cli/ -xvs -n auto`
- `dash` - Run Dash tests: `pytest depictio/tests/dash/ -xvs -n auto`
- `all` - Run all tests: `pytest depictio/tests/ -xvs -n auto`
- Specific file - Run tests in that file

## Usage

`/test` - Run all tests
`/test api` - Run API tests only
`/test models` - Run model tests only
`/test <file>` - Run tests in specific file

$ARGUMENTS
