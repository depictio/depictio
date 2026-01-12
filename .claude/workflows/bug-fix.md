# Bug Fix Workflow

A structured workflow for fixing bugs in depictio.

## Phase 1: Diagnosis

1. **Reproduce the bug**
   - Understand the expected vs actual behavior
   - Identify steps to reproduce
   - Check relevant logs: `/logs <service>`

2. **Locate the source**
   - Search for related code
   - Check recent changes: `git log --oneline -20`
   - Review error messages and stack traces

3. **Understand the context**
   - Review related tests
   - Check model definitions
   - Understand data flow

## Phase 2: Analysis

1. **Root cause analysis**
   - Identify the exact cause
   - Check for related issues
   - Consider edge cases

2. **Impact assessment**
   - List affected components
   - Check for side effects
   - Identify regression risks

3. **Plan the fix**
   - Design minimal change
   - Consider backwards compatibility
   - Plan test coverage

## Phase 3: Implementation

1. **Write the fix**
   - Make minimal, focused changes
   - Add comments for complex fixes
   - Follow existing patterns

2. **Add/update tests**
   - Write test that reproduces the bug
   - Verify test fails before fix
   - Verify test passes after fix
   - Add edge case tests

3. **Verify fix**
   - Run related tests
   - Test manually if needed
   - Check for regressions

## Phase 4: Validation

1. **Code quality checks**
   ```bash
   ruff format depictio/
   ruff check depictio/ --fix
   ty check depictio/models/ depictio/api/ depictio/dash/ depictio/cli/
   ```

2. **Test suite**
   ```bash
   pytest depictio/tests/ -xvs -n auto
   ```

3. **Pre-commit**
   ```bash
   pre-commit run --all-files
   ```

## Phase 5: Commit

1. **Stage changes**
   - Include fix and tests
   - Exclude unrelated changes

2. **Commit message format**
   ```
   fix: <brief description>

   - Root cause: <what caused the bug>
   - Solution: <what was changed>

   Fixes #<issue-number>
   ```

## Debugging Tips

### API Issues
- Check logs: `docker compose logs backend --tail=100`
- Test endpoint: `curl -X GET http://localhost:8058/depictio/api/v1/...`
- Check MongoDB: `/db query <collection> <query>`

### Dash Issues
- Check browser console for errors
- Review callback chains
- Check component IDs

### Data Issues
- Verify model validation
- Check database state
- Review data transformations

## Checklist

- [ ] Bug reproduced and understood
- [ ] Root cause identified
- [ ] Minimal fix implemented
- [ ] Test added that catches the bug
- [ ] All tests passing
- [ ] Type checking passes
- [ ] Linting passes
- [ ] Pre-commit hooks pass
- [ ] Fix verified in dev environment
- [ ] Committed with proper message
