# Check Quality

Run all code quality checks including formatting, linting, type checking, and pre-commit hooks.

## Usage

When the user wants to ensure code quality before committing or creating a PR, run the quality check workflow.

## Quality Checks

### 1. Format Code (ruff format)
```bash
ruff format .
```
- Auto-formats Python code
- Applies consistent style (similar to black)
- Modifies files in-place

### 2. Lint Code (ruff check)
```bash
ruff check .
```
- Checks for code quality issues
- Identifies unused imports, undefined names, etc.
- Some issues can be auto-fixed with `--fix`

### 3. Type Checking (ty)
```bash
ty check depictio/
```
- **CRITICAL**: Must pass with zero errors
- Checks models, API, Dash, CLI
- No `# type: ignore` comments allowed
- Full type safety enforced

### 4. Pre-commit Hooks
```bash
pre-commit run --all-files
```
- Runs all configured hooks
- Includes: ruff, ty, helm lint, nbstripout, shellcheck
- **MANDATORY** before committing

## Complete Quality Check Workflow

Run these steps in order:

1. **Format code**:
   ```bash
   ruff format .
   ```

2. **Fix linting issues**:
   ```bash
   ruff check . --fix
   ```

3. **Check remaining issues**:
   ```bash
   ruff check .
   ```

4. **Type checking**:
   ```bash
   ty check depictio/models/ depictio/api/ depictio/dash/ depictio/cli/
   ```

5. **Run pre-commit hooks**:
   ```bash
   pre-commit run --all-files
   ```

6. **Verify all passed**:
   - If any step fails, fix issues and re-run
   - Must have zero errors before proceeding

## Auto-Fix Workflow

For automated fixing:

```bash
# Format and fix in one go
ruff format . && ruff check . --fix && ruff check .
```

Then manually verify and run:
```bash
ty check depictio/ && pre-commit run --all-files
```

## Type Checking Requirements

**CRITICAL REQUIREMENT**: The codebase maintains perfect type safety.

- All folders must pass ty check with zero errors
- No `# type: ignore` comments allowed
- Use proper type-safe patterns:
  - Explicit field validation for Pydantic models
  - Proper ObjectId/PyObjectId conversions
  - None checks and validation
  - Type guards for Union types

**Common type-safe patterns**:

```python
# ✅ GOOD: Explicit validation
if user_id is not None:
    user = await User.get(user_id)

# ✅ GOOD: Type guards
from typing import cast
value = cast(str, maybe_str)

# ❌ BAD: Type ignore
value = maybe_str  # type: ignore
```

## Pre-commit Hook Configuration

The project uses pre-commit hooks defined in `.pre-commit-config.yaml`:

- **trailing-whitespace**: Remove trailing whitespace
- **end-of-files**: Fix file endings
- **check-yaml**: Validate YAML files
- **check-added-large-files**: Prevent large file commits
- **ruff**: Linting and formatting
- **ty-check**: Type checking for models, API, Dash, CLI
- **helm-lint**: Validate Helm charts
- **nbstripout**: Strip Jupyter notebook outputs
- **shellcheck**: Shell script linting

## Skipping Checks (Use Sparingly)

Some hooks can be skipped for special cases:

```bash
# Skip specific hooks
SKIP=trailing-whitespace,ty-check pre-commit run --all-files

# Skip all hooks (emergency only)
git commit --no-verify
```

**WARNING**: Only skip checks if absolutely necessary and document why.

## Process

1. **Assess current state**:
   - Check git status for modified files
   - Determine scope (all files vs. changed files only)

2. **Run formatting**:
   - `ruff format .`
   - Show files modified

3. **Fix linting issues**:
   - `ruff check . --fix`
   - Show auto-fixed issues

4. **Check remaining issues**:
   - `ruff check .`
   - If issues remain, show them and suggest fixes

5. **Type checking**:
   - `ty check depictio/`
   - **Must pass with zero errors**
   - If fails, help debug type issues

6. **Pre-commit hooks**:
   - `pre-commit run --all-files`
   - If fails, show failures and re-run after fixes

7. **Final verification**:
   - Confirm all checks passed
   - Ready to commit or create PR

## Error Handling

**Ruff formatting conflicts**:
- Usually auto-resolved
- Check for syntax errors if formatting fails

**Type checking errors**:
- Read error messages carefully
- Common issues: missing type hints, incorrect type assertions
- Use explicit type guards and validation
- Never use `# type: ignore`

**Pre-commit hook failures**:
- Read hook output to identify issue
- Fix and re-run: `pre-commit run --all-files`
- Some hooks modify files (e.g., trailing whitespace) - stage changes and re-run

**Helm lint failures**:
- Check `helm-charts/depictio/Chart.yaml` and `values.yaml`
- Validate YAML syntax
- Ensure required fields are present

## Performance Tips

**Check only changed files** (during development):
```bash
# Format only staged files
ruff format $(git diff --name-only --cached | grep '\.py$')

# Check only changed files
ruff check $(git diff --name-only | grep '\.py$')
```

**Run pre-commit on staged files only**:
```bash
pre-commit run
```

**Install pre-commit hook** (auto-run on git commit):
```bash
pre-commit install
```

## Integration with Other Skills

- Run `/run-tests` before quality checks to catch issues early
- Run `/check-quality` after making changes and before `/create-pr`
- Use `/bump-version` only after quality checks pass

## Quick Command Reference

```bash
# Full quality check
ruff format . && ruff check . --fix && ruff check . && ty check depictio/ && pre-commit run --all-files

# Quick check (changed files only)
ruff format . && ruff check . && ty check depictio/

# Pre-commit only
pre-commit run --all-files

# Install pre-commit hook (one-time)
pre-commit install
```
