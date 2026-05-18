# Bump Version

Bump a new version of depictio using `bump-with-helm.sh`, then push commit + tags.

## Usage

`/bump-version <new-version> <bump-type>`

- `<new-version>`: target version (e.g. `0.9.1`, `0.10.0-b1`)
- `<bump-type>`: one of `patch`, `minor`, `beta` (no `major` planned)

If either argument is missing, ask the user before proceeding.

$ARGUMENTS

## Instructions

1. **Verify branch + clean fetch from main**:
   - `git rev-parse --abbrev-ref HEAD` — must be `main`. If not, **stop and ask**.
   - `git fetch origin main`
   - `git pull --ff-only origin main`
   - If pull fails (non-fast-forward, conflicts, dirty tree blocking the merge, network error, etc.) — **stop and ask the user how to proceed**. Do NOT attempt destructive recovery (reset --hard, stash + force, etc.) without explicit instruction.

2. **Run the bump script** from the repo root:

   ```bash
   ./bump-with-helm.sh --verbose --new-version <new-version> <bump-type>
   ```

   The script handles `bump2version`, helm chart version, `uv lock`, and amends the bump commit. Don't substitute commands.

3. **Push commit + tags**:

   ```bash
   git push origin main
   git push origin --tags
   ```

   For non-beta releases, the script also moves the `stable` tag locally — push it with:

   ```bash
   git push origin refs/tags/stable --force
   ```

   Only force-push the `stable` tag (it is intentionally moveable). Never force-push `main` or version tags.

4. **Confirm** the new version + tag landed on origin and report back briefly.

## Stop conditions (ask, don't guess)

- Not on `main`
- `git pull` fails for any reason
- Working tree has unrelated uncommitted changes that the bump would sweep into the amended commit
- `bump-with-helm.sh` exits non-zero
