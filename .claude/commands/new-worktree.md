# New Worktree

Create a new git worktree for depictio under `../depictio-worktrees/<branch>`, allocate ports, and ensure single-user auth mode.

## Usage

`/new-worktree <branch>` — `<branch>` is required (e.g. `feat/foo`, `fix/bar`).

If the argument is missing, ask the user for the branch name and stop.

$ARGUMENTS

## Steps

1. **Validate inputs and current location**:
   - The current working directory must be the depictio repo root (or any worktree of it). Run `git rev-parse --show-toplevel` and use that as `$REPO_ROOT`.
   - Compute `$WT_PARENT="$(dirname "$REPO_ROOT")/depictio-worktrees"` (resolves to `.../depictio-workspace/depictio-worktrees`).
   - Worktree directory name = the branch name with `/` replaced by `-` (matches existing convention, e.g. `feat/foo` → `feat-foo`). Path = `$WT_PARENT/<sanitized>`.
   - If `$WT_PARENT/<sanitized>` already exists, **stop and ask** — don't clobber.

2. **Create the worktree**:
   - If the branch already exists locally:
     ```bash
     git worktree add "$WT_PARENT/<sanitized>" <branch>
     ```
   - If the branch is new:
     ```bash
     git worktree add -b <branch> "$WT_PARENT/<sanitized>"
     ```
   - Use `git show-ref --verify --quiet refs/heads/<branch>` to decide which form.

3. **Allocate ports + set single-user mode**:
   - `cd` into the new worktree.
   - Source the allocate script with `DEPICTIO_AUTH_SINGLE_USER_MODE=true` exported, so the generated `.env.instance` and `docker-compose.override.yaml` pick it up:
     ```bash
     cd "$WT_PARENT/<sanitized>"
     export DEPICTIO_AUTH_SINGLE_USER_MODE=true
     source .devcontainer/scripts/allocate-ports.sh
     ```
   - The script uses `${DEPICTIO_AUTH_SINGLE_USER_MODE:-true}` so it defaults to `true` even if the export is missing — exporting it explicitly removes any ambiguity.
   - **Source, don't execute** (`source` / `.`), so the exported `COMPOSE_PROJECT_NAME`, `*_PORT`, etc. land in the parent shell — though for a one-shot Bash invocation they're only useful insofar as the script wrote `.env.instance` and `docker-compose.override.yaml`.

4. **Set up the depictio-cli venv** at `depictio/cli/.venv`:
   - `(cd depictio/cli && uv sync)` — creates an isolated CLI environment scoped to this worktree, so `depictio-cli run` / `dashboard import` can target the worktree's API/Mongo ports without colliding with sibling worktrees.
   - Verify `depictio/cli/.venv/bin/depictio-cli` exists after the sync. If `uv sync` fails, **stop and ask** — don't `pip install` as a fallback (the lockfile is the source of truth).
   - This duplicates the `/cli-venv` skill; running it again later is safe and idempotent.

5. **Verify** and report:
   - `cat .env.instance | grep -E '^(COMPOSE_PROJECT_NAME|.*_PORT|DEPICTIO_AUTH_SINGLE_USER_MODE)='`
   - Confirm `DEPICTIO_AUTH_SINGLE_USER_MODE=true` is present.
   - Print: worktree path, branch, allocated FastAPI/Dash/Mongo/Minio ports, and the path to the CLI venv.

## Stop conditions (ask, don't guess)

- Branch argument missing
- Target worktree directory already exists
- `git worktree add` fails (e.g. branch already checked out elsewhere)
- `allocate-ports.sh` exits non-zero or `.env.instance` doesn't end up with `DEPICTIO_AUTH_SINGLE_USER_MODE=true`
- `uv sync` in `depictio/cli/` fails (missing `uv`, lockfile mismatch, network error)
