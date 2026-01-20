# Release Workflow

Complete release workflow for Depictio, from development branch to production release.

## Usage

When the user wants to prepare or create a release, guide them through the complete release process.

## Release Types

### Beta Release (Development)
- Version format: `X.Y.Z-bN` (e.g., 0.6.0-b3)
- Purpose: Testing new features before stable release
- Branch: Usually `main` or feature branches
- Docker tag: Uses beta version tag

### Stable Release
- Version format: `X.Y.Z` (e.g., 0.6.0)
- Purpose: Production-ready release
- Branch: `main` only
- Docker tag: Uses version tag + `latest`

## Beta Release Process

1. **Prepare for release**:
   - Ensure all tests pass: `pytest depictio/tests/ -xvs -n auto`
   - Run pre-commit checks: `pre-commit run --all-files`
   - Verify type checking: `ty check depictio/`

2. **Bump beta version**:
   - Use bump-version skill: `/bump-version`
   - Select `beta` to increment beta number
   - Or specify manual version for new beta series

3. **Verify changes**:
   - Check updated files (pyproject.toml, helm charts, etc.)
   - Review git commit and tag

4. **Push to remote**:
   - Pull latest changes: `git pull --rebase`
   - Push commit and tags: `git push && git push --tags`

5. **CI/CD will automatically**:
   - Run tests
   - Build Docker images
   - Tag with version number
   - Deploy to staging (if configured)

## Stable Release Process

1. **Pre-release checklist**:
   - All beta testing complete
   - All tests passing
   - Documentation updated in depictio-docs
   - CHANGELOG updated with release notes
   - No known critical bugs

2. **Create release branch** (optional):
   ```bash
   git checkout -b release/X.Y.Z
   ```

3. **Bump to stable version**:
   - Use bump-version skill
   - Select appropriate part: `major`, `minor`, or `patch`
   - This removes the `-bN` beta suffix

4. **Update documentation**:
   - Update CHANGELOG.md with release notes
   - Update version in documentation
   - Update Obsidian notes with technical details

5. **Create GitHub release**:
   - Go to GitHub releases page
   - Create new release from tag
   - Add release notes from CHANGELOG
   - Attach any binary artifacts if needed

6. **Post-release**:
   - Announce release (if applicable)
   - Update deployment environments
   - Start new development cycle with beta version

## Helm Chart Versioning

The bump2helm script automatically:
- Updates `appVersion` to match application version
- Updates `version` to current date format (YYYYMMDD.1)
- This allows multiple chart releases per day if needed

## Docker Image Tags

After release, Docker images are tagged with:
- Version tag: `depictio/depictio:0.6.0-b3`
- Latest tag (stable only): `depictio/depictio:latest`

## Rollback Process

If a release needs to be rolled back:

1. **Revert the tag**:
   ```bash
   git tag -d vX.Y.Z
   git push origin :refs/tags/vX.Y.Z
   ```

2. **Revert the commit**:
   ```bash
   git revert <commit-hash>
   git push
   ```

3. **Deploy previous version**:
   - Update Helm chart to previous version
   - Or use previous Docker image tag

## Checklist Template

### Pre-Release
- [ ] All tests passing
- [ ] Type checking passing
- [ ] Pre-commit hooks passing
- [ ] Documentation updated
- [ ] CHANGELOG updated
- [ ] No uncommitted changes

### Release
- [ ] Version bumped correctly
- [ ] Git tag created
- [ ] Changes pushed to remote
- [ ] CI/CD pipeline successful
- [ ] Docker images built and tagged

### Post-Release
- [ ] GitHub release created
- [ ] Documentation published
- [ ] Deployment updated
- [ ] Team notified
- [ ] Obsidian notes updated with technical details

## Common Issues

**Non-fast-forward push error**:
```bash
git pull --rebase
git push && git push --tags
```

**Wrong version bumped**:
- Delete tag: `git tag -d vX.Y.Z`
- Reset commit: `git reset --hard HEAD~1`
- Run bump again with correct parameters

**Forgot to update documentation**:
- Documentation can be updated after release
- Create follow-up commit without version bump

## Integration with Documentation

After each significant release:

1. **Update depictio-docs**:
   - User-facing changes
   - API documentation
   - Configuration examples

2. **Update Obsidian notes** (via MCP):
   - Technical implementation details
   - Architecture decisions
   - Performance notes
   - Security considerations
