# Run Tests

Smart test runner for Depictio that detects test type and runs appropriate test suites.

## Usage

When the user wants to run tests, determine the scope and execute the appropriate test command.

## Test Types

### 1. All Tests (Default)
```bash
pytest depictio/tests/ -xvs -n auto
```
- Runs all unit and integration tests
- Parallel execution with `-n auto`
- Verbose output with stack traces
- Stops on first failure with `-x`

### 2. Specific Module/File
```bash
pytest depictio/tests/path/to/test_file.py -xvs
```
- Run tests from specific file or directory
- Useful for focused testing

### 3. Test by Pattern
```bash
pytest depictio/tests/ -k "pattern" -xvs
```
- Filter tests by name pattern
- Example: `-k "user"` runs all tests with "user" in the name

### 4. Test by Marker
```bash
pytest depictio/tests/ -m "marker_name" -xvs
```
- Run tests with specific markers
- Common markers: `slow`, `integration`, `unit`

### 5. Failed Tests Only
```bash
pytest depictio/tests/ --lf -xvs
```
- `--lf` (last failed): Only run tests that failed last time
- Useful for iterative debugging

### 6. Coverage Report
```bash
pytest depictio/tests/ --cov=depictio --cov-report=html -xvs
```
- Generate coverage report
- HTML report in `htmlcov/` directory

## Process

1. **Determine test scope**:
   - Ask user what to test (all, specific file, pattern, etc.)
   - Or detect from context (e.g., if user just edited a file)

2. **Set Python environment**:
   - Use default Python: `/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python`
   - Or use pixi: `pixi run test`

3. **Run tests**:
   - Execute appropriate pytest command
   - Show progress and output

4. **Handle results**:
   - If all pass: Confirm success
   - If failures: Show failed test names and suggest next steps
   - If errors: Help debug the issue

## Smart Detection

**Auto-detect test scope from context**:
- If user just edited `depictio/api/v1/models/user.py` → suggest running `pytest depictio/tests/ -k "user"`
- If user says "test the API" → run `pytest depictio/tests/api/`
- If user says "run all tests" → run full suite

## Common Options

- `-x`: Stop on first failure
- `-v`: Verbose output
- `-s`: Show print statements
- `-n auto`: Parallel execution (number of CPUs)
- `--lf`: Last failed only
- `--ff`: Failed first, then others
- `-k EXPRESSION`: Filter by test name
- `-m MARKER`: Filter by marker
- `--cov=MODULE`: Coverage for specific module
- `--pdb`: Drop into debugger on failure

## Examples

**Run all tests**:
```bash
pytest depictio/tests/ -xvs -n auto
```

**Run API tests only**:
```bash
pytest depictio/tests/api/ -xvs
```

**Run tests matching "user"**:
```bash
pytest depictio/tests/ -k "user" -xvs
```

**Re-run failed tests**:
```bash
pytest depictio/tests/ --lf -xvs
```

**Run with coverage**:
```bash
pytest depictio/tests/ --cov=depictio --cov-report=term-missing -xvs
```

**Debug test failure**:
```bash
pytest depictio/tests/test_file.py::test_function --pdb -xvs
```

## Error Handling

**Import errors**:
- Check Python environment is activated
- Verify dependencies installed: `pip list | grep depictio`

**Test collection errors**:
- Check for syntax errors in test files
- Verify test file naming (must start with `test_` or end with `_test.py`)

**Fixture errors**:
- Check fixture scope and dependencies
- Verify conftest.py is properly set up

**Database/service errors**:
- Ensure required services are running (MongoDB, Redis)
- Check environment variables are set

## Performance Tips

- Use `-n auto` for parallel execution (faster for large test suites)
- Use `-x` to stop on first failure (faster feedback during debugging)
- Use `--lf` when iterating on fixes (only re-run failures)
- Use specific paths/patterns to avoid running unnecessary tests

## Integration with Other Skills

- Run `/check-quality` after tests pass to ensure code quality
- Use `/test-e2e` for end-to-end browser tests
- Use `/create-pr` after all tests pass to create pull request
