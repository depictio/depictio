# Bump Docs Version (mike)

Deploy a new versioned docs build in `../depictio-docs` using `mike`, pushing to the `gh-pages` branch.

## Usage

`/bump-docs-version <version>`

- `<version>`: the depictio version this docs build corresponds to (e.g. `0.10.0`, `0.10.0-b1`). The leading `v` is added automatically — pass either form.

If the argument is missing, ask the user before proceeding.

$ARGUMENTS

## Alias rules (decided from the version string)

Both release types update the `latest` alias — it tracks the most recently deployed build, regardless of stability.

- **Stable** (no `-b` suffix): aliases = `stable latest`
  ```bash
  uv run mike deploy v<version> stable latest --update-aliases --push --allow-empty
  ```
- **Beta** (contains `-b`, e.g. `0.10.0-b1`): aliases = `dev latest`
  ```bash
  uv run mike deploy v<version> dev latest --update-aliases --push --allow-empty
  ```

`uv run` is used because depictio-docs declares `mike` as a project dep in `pyproject.toml`. If `uv` is unavailable the user will see it immediately — don't silently fall back to a globally-installed `mike`.

## Steps

1. **Locate the docs repo**:
   - Compute `$DOCS_DIR="$(dirname "$(git rev-parse --show-toplevel)")/depictio-docs"`.
   - If it doesn't exist → **stop and ask** (don't clone or guess).

2. **Validate state inside `$DOCS_DIR`** (run from there):
   - `git rev-parse --abbrev-ref HEAD` must be `main`. If not, **stop and ask** — the docs CI is gated on `main` and a versioned deploy from a feature branch is almost certainly a mistake.
   - Working tree must be clean: `git diff --quiet && git diff --cached --quiet`. Untracked files are OK (mike ignores them). If dirty, **stop and ask** — don't auto-stash. (Differs from `/bump-version` because docs work is sometimes long-lived in the worktree.)
   - `git fetch origin main && git pull --ff-only origin main`. If pull fails for any reason, **stop and ask**.

3. **Verify changelog coverage** in `$DOCS_DIR/docs/changelog/README.md`:
   - Strip a leading `v` if present from the argument to get the bare version (e.g. `0.10.1`, `0.10.0-b1`).
   - Grep for the version string with a `v` prefix: `grep -F "v<bare_version>" $DOCS_DIR/docs/changelog/README.md`. The expected form is a heading like `## **[v<bare_version>](https://github.com/depictio/depictio/releases/tag/v<bare_version>)**` (stable) or `### **[v<bare_version>]...**` (beta, nested under a stable section).
   - If no match → **stop and ask**. Publishing a docs build for a version with no changelog entry leaves users without release notes; do not silently proceed. Suggest the user add the entry to `docs/changelog/README.md` first.
   - If a match exists, briefly confirm what was found (the heading line) so the user can sanity-check it's the right entry, not a stray mention.

4. **Decide alias set** from `<version>`:
   - Strip a leading `v` if present, then check for `-b` substring.
   - Stable → aliases = `stable latest`
   - Beta → aliases = `dev latest`
   - Re-add the `v` prefix when forming the mike argument.

5. **Run the deploy**:

   ```bash
   # stable
   uv run mike deploy v<version> stable latest --update-aliases --push --allow-empty

   # beta
   uv run mike deploy v<version> dev latest --update-aliases --push --allow-empty
   ```

   `--push` writes to `origin/gh-pages` directly — this is the published artifact, not a branch you can revert with a fast-forward. Treat as a publish action: do NOT swap the alias set, do NOT add `set-default` unless the user asks.

6. **Verify** and report:
   - `uv run mike list` — confirm the new version appears with the expected alias.
   - Print: docs repo path, deployed version, alias set used, and the public URL: `https://depictio.github.io/depictio-docs/v<version>/`.

## Stop conditions (ask, don't guess)

- Version argument missing
- `$DOCS_DIR` doesn't exist
- Not on `main` in the docs repo
- Working tree dirty (tracked changes)
- `git pull --ff-only` fails
- Version not found in `docs/changelog/README.md` (no changelog entry yet)
- `mike deploy` exits non-zero (likely auth issue on the `gh-pages` push or a network failure)

## Notes

- The depictio-docs CI workflow `.github/workflows/deploy-docs.yaml` runs the same logic on push-to-main and on `workflow_dispatch`. Running this skill locally is the manual equivalent — useful when you want to redeploy a tag, fix a botched alias, or bypass the CI's auto-trigger on `docs/**` paths.
- For stable releases the CI also runs `mike set-default --push stable`. This skill intentionally does not, matching the user's preferred command form. If the root redirect needs updating, do it explicitly:
  ```bash
  uv run mike set-default --push stable
  ```
