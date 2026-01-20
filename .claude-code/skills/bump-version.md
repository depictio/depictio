# Bump Version

Bump the project version using the bump2helm script, which handles version updates across multiple files and creates git tags.

## Usage

When the user requests a version bump, ask for the version bump type or specific version, then execute the bump process.

## Process

1. **Determine version bump type**:
   - Ask the user which part to bump: `major`, `minor`, `patch`, or `beta`
   - Or ask if they want to specify a manual version (e.g., "0.6.0-b4")

2. **Validate current state**:
   - Check current branch (usually should be on `main`)
   - Check git status to see if there are uncommitted changes
   - Show current version from `.bumpversion.cfg`

3. **Execute bump**:
   - If manual version: `./bump-with-helm.sh --new-version <VERSION> <PART>`
     - For beta versions: use `beta` as the part
     - For release versions: use the appropriate part (major/minor/patch)
   - If automatic: `./bump-with-helm.sh <PART>` (major/minor/patch/beta)

4. **Push changes**:
   - Pull remote changes first: `git pull --rebase`
   - Push commit: `git push`
   - Push tags: `git push --tags`

5. **Confirm success**:
   - Show the new version number
   - Show the created git tag
   - Confirm remote push status

## What the bump2helm script does

- Updates version in:
  - `.bumpversion.cfg`
  - `VERSION` file
  - `pyproject.toml`
  - `depictio/cli/pyproject.toml`
  - `helm-charts/depictio/Chart.yaml` (appVersion)
  - `helm-charts/depictio/values.yaml` (tag)
- Updates helm chart version with datestamp (YYYYMMDD.1)
- Creates git commit with message "Bump version: X.Y.Z → A.B.C"
- Creates git tag (e.g., v0.6.0-b3)
- Runs pre-commit hooks (with some checks skipped via SKIP env var)

## Version Format

The project uses semantic versioning with optional beta suffix:
- Release: `X.Y.Z` (e.g., 0.6.0)
- Beta: `X.Y.Z-bN` (e.g., 0.6.0-b3)

## Examples

**Bump beta version**:
```bash
./bump-with-helm.sh beta
```

**Set specific beta version**:
```bash
./bump-with-helm.sh --new-version 0.6.0-b3 beta
```

**Bump patch version**:
```bash
./bump-with-helm.sh patch
```

**Bump minor version**:
```bash
./bump-with-helm.sh minor
```

## Error Handling

- If git push fails due to non-fast-forward, run `git pull --rebase` first
- If uncommitted changes exist, script automatically adds `--allow-dirty` flag
- Show clear error messages if bump fails

## Notes

- Always confirm with user before pushing to remote
- The script automatically amends the commit to include helm chart changes
- Pre-commit hooks run but some type checks are skipped (defined in SKIP env var)
