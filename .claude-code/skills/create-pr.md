# Create PR

Streamlined pull request creation workflow with quality checks and proper formatting.

## Usage

When ready to create a pull request, run this workflow to ensure quality and generate a proper PR.

## Prerequisites

Before creating a PR:

1. **Code quality checks passed** (use `/check-quality`)
2. **Tests passing** (use `/run-tests`)
3. **Changes committed** to feature branch
4. **Branch pushed** to remote

## PR Creation Workflow

### Phase 1: Pre-PR Checks

1. **Run quality checks**:
   ```bash
   ruff format . && ruff check . && ty check depictio/ && pre-commit run --all-files
   ```
   - **MUST pass** before proceeding
   - Fix any issues found

2. **Run tests**:
   ```bash
   pytest depictio/tests/ -xvs -n auto
   ```
   - **MUST pass** before proceeding
   - Fix any test failures

3. **Check git status**:
   ```bash
   git status
   ```
   - Ensure all changes committed
   - Verify on correct branch

### Phase 2: Prepare PR Description

1. **Review commits**:
   ```bash
   git log main..HEAD --oneline
   ```

2. **Check diff against main**:
   ```bash
   git diff main...HEAD --stat
   ```

3. **Generate PR description**:
   - Summarize changes (what and why)
   - List key modifications
   - Note breaking changes (if any)
   - Reference related issues

### Phase 3: Push and Create PR

1. **Ensure branch is up to date**:
   ```bash
   git fetch origin
   git rebase origin/main  # or merge if preferred
   ```

2. **Push to remote**:
   ```bash
   git push origin HEAD
   # or if upstream not set:
   git push -u origin branch-name
   ```

3. **Create PR using GitHub CLI**:
   ```bash
   gh pr create --title "PR Title" --body "PR Description"
   ```

   Or create via GitHub web interface:
   - Navigate to repository on GitHub
   - Click "Compare & pull request"
   - Fill in title and description
   - Select reviewers and labels
   - Create pull request

## PR Title Format

Follow conventional commit style:

```
<type>(<scope>): <description>

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation changes
- refactor: Code refactoring
- test: Test changes
- chore: Build/tooling changes
- perf: Performance improvements
- ci: CI/CD changes

Examples:
- feat(api): add user authentication endpoint
- fix(dash): resolve dashboard layout issue
- docs: update installation guide
- refactor(models): simplify data collection schema
```

## PR Description Template

```markdown
## Summary
Brief description of what this PR does and why.

## Changes
- Change 1
- Change 2
- Change 3

## Breaking Changes
- List any breaking changes (if applicable)
- Migration steps if needed

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] E2E tests pass (if applicable)
- [ ] Manual testing completed

## Related Issues
Closes #123
Related to #456

## Checklist
- [ ] Code quality checks pass (ruff, ty)
- [ ] Pre-commit hooks pass
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] CHANGELOG updated (for significant changes)

## Screenshots (if applicable)
[Add screenshots for UI changes]
```

## Complete Process

1. **Check current branch**:
   ```bash
   git branch --show-current
   ```

2. **Run quality checks** (required):
   ```bash
   /check-quality  # or manually run pre-commit checks
   ```

3. **Run tests** (required):
   ```bash
   /run-tests  # or pytest depictio/tests/ -xvs -n auto
   ```

4. **Review changes**:
   ```bash
   git diff main...HEAD --stat
   git log main..HEAD --oneline
   ```

5. **Update from main** (if needed):
   ```bash
   git fetch origin
   git rebase origin/main
   ```

6. **Push branch**:
   ```bash
   git push -u origin HEAD
   ```

7. **Create PR**:
   ```bash
   gh pr create --title "feat: add feature" --body "Description"
   ```

   Or generate PR body from template and create via web

8. **Add labels and reviewers**:
   - Via GitHub CLI: `gh pr edit --add-label "enhancement" --add-reviewer "username"`
   - Or via GitHub web interface

## GitHub CLI Usage

### Install GitHub CLI

```bash
# macOS
brew install gh

# Verify installation
gh --version
```

### Authenticate

```bash
gh auth login
```

### Create PR

```bash
# Interactive mode
gh pr create

# With title and body
gh pr create --title "feat: add feature" --body "Description"

# From template file
gh pr create --title "feat: add feature" --body-file pr_description.md

# With reviewers and labels
gh pr create --title "feat: add feature" --body "Description" \
  --reviewer username1,username2 \
  --label enhancement,api
```

### Manage PR

```bash
# List PRs
gh pr list

# View PR details
gh pr view 123

# Edit PR
gh pr edit 123 --title "New title" --body "New description"

# Add reviewers
gh pr edit 123 --add-reviewer username

# Add labels
gh pr edit 123 --add-label bug,urgent

# Merge PR
gh pr merge 123 --squash  # or --merge or --rebase
```

## Quality Checks Integration

### Pre-PR Checklist

- [ ] `/check-quality` passed (ruff format, ruff check, ty check, pre-commit)
- [ ] `/run-tests` passed (all unit and integration tests)
- [ ] `/test-e2e` passed (if E2E tests exist for changes)
- [ ] Documentation updated (`/update-docs` if needed)
- [ ] CHANGELOG updated (for significant changes)
- [ ] No merge conflicts with main

### Post-PR Checklist

- [ ] CI/CD pipeline passes
- [ ] Code review completed
- [ ] All comments addressed
- [ ] Approved by required reviewers
- [ ] Ready to merge

## CI/CD Integration

After PR creation, CI will automatically:

1. **Run quality checks**:
   - Ruff formatting
   - Ruff linting
   - Type checking (ty)
   - Pre-commit hooks

2. **Run tests**:
   - Unit tests
   - Integration tests
   - E2E tests (if configured)

3. **Build validation**:
   - Docker image build
   - Helm chart validation

4. **Coverage report**:
   - Test coverage metrics
   - Coverage changes vs main

## Common Scenarios

### Simple Feature PR

```bash
# 1. Quality checks
/check-quality

# 2. Run tests
/run-tests

# 3. Push and create PR
git push -u origin feature/new-feature
gh pr create --title "feat: add new feature" \
  --body "Implements feature X to solve problem Y"
```

### Bug Fix PR

```bash
# 1. Verify fix
/run-tests

# 2. Quality checks
/check-quality

# 3. Create PR with issue reference
gh pr create --title "fix: resolve issue #123" \
  --body "Fixes #123 by correcting the validation logic"
```

### Documentation PR

```bash
# 1. Quality checks (markdown linting)
pre-commit run --all-files

# 2. Create PR
gh pr create --title "docs: update API reference" \
  --body "Updates API documentation with new endpoints"
```

### Large Refactoring PR

```bash
# 1. Comprehensive testing
/run-tests
/test-e2e

# 2. Quality checks
/check-quality

# 3. Update docs
/update-docs

# 4. Create detailed PR
gh pr create --title "refactor: modernize data processing" \
  --body-file refactor_details.md \
  --label refactoring,breaking-change
```

## PR Review Process

### As Author

1. **Self-review**:
   - Review own changes before requesting review
   - Add comments explaining complex logic
   - Ensure CI passes

2. **Request reviews**:
   - Tag appropriate reviewers
   - Provide context in PR description
   - Highlight areas needing special attention

3. **Address feedback**:
   - Respond to all comments
   - Make requested changes
   - Push updates and re-request review

### As Reviewer

1. **Code quality**:
   - Check for code smells
   - Verify tests coverage
   - Review error handling

2. **Architecture**:
   - Ensure follows project patterns
   - Check for proper abstractions
   - Verify maintainability

3. **Provide feedback**:
   - Be constructive
   - Suggest improvements
   - Approve when satisfied

## Error Handling

**Pre-commit hooks fail**:
- Run `/check-quality` to fix issues
- Address all hook failures
- Re-run until all pass

**Tests fail**:
- Run `/run-tests` to identify failures
- Fix failing tests
- Verify fixes locally before pushing

**Merge conflicts**:
- Fetch latest main: `git fetch origin`
- Rebase: `git rebase origin/main`
- Resolve conflicts
- Push: `git push --force-with-lease`

**CI pipeline fails**:
- Check CI logs
- Reproduce locally
- Fix issues
- Push updates

## Integration with Other Skills

- **Before PR**: `/check-quality`, `/run-tests`, `/test-e2e`
- **After PR merge**: `/cleanup-branches`
- **For releases**: `/bump-version` then `/create-pr` for version bump
- **Documentation**: `/update-docs` before or after PR

## Best Practices

1. **Small, focused PRs**: Easier to review and merge
2. **Descriptive titles**: Follow conventional commit format
3. **Detailed descriptions**: Explain what, why, and how
4. **Link issues**: Reference related issues and PRs
5. **Update tests**: Add/update tests for changes
6. **Update docs**: Keep documentation in sync
7. **Clean commits**: Squash or clean up commit history
8. **Respond promptly**: Address review comments quickly
9. **Keep updated**: Rebase/merge main regularly
10. **Celebrate**: Acknowledge merged PRs!

## Quick Reference

```bash
# Full PR workflow
/check-quality && /run-tests && git push -u origin HEAD && gh pr create

# Create PR interactively
gh pr create

# Create PR with details
gh pr create --title "feat: add feature" --body "Description" --label enhancement

# View PR status
gh pr status

# List PRs
gh pr list

# Merge PR
gh pr merge 123 --squash
```
