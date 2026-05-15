# CLI Venv

Create or refresh the `depictio-cli` virtualenv at `depictio/cli/.venv` via `uv sync`.

## Usage

`/cli-venv`

No arguments. Idempotent — safe to re-run after pulling changes that touched `depictio/cli/pyproject.toml` or `depictio/cli/uv.lock`.

## Why a per-worktree CLI venv

The CLI is a separate package (`depictio/cli/pyproject.toml`) with its own pinned deps and lockfile. Installing it into the main `depictio-venv-dash-v3` would mix unrelated dependency trees. A scoped `.venv` next to the package keeps it isolated and lets each worktree target its own allocated API ports without polluting the global `depictio-cli` install.

## Steps

1. **Locate the CLI package**:
   - From the repo root (the one with the top-level `pyproject.toml`), confirm `depictio/cli/pyproject.toml` and `depictio/cli/uv.lock` both exist. If either is missing, **stop and ask** — wrong directory or unexpected repo layout.

2. **Run `uv sync`**:
   ```bash
   (cd depictio/cli && uv sync)
   ```
   - Do not `pip install -e .` as a fallback — the lockfile is authoritative and `uv sync` is what CI uses.
   - If `uv` is missing, **stop and ask**. Don't silently fall back to `pip` or a globally-installed `depictio-cli` (it would point at the wrong source tree).

3. **Verify**:
   - `depictio/cli/.venv/bin/depictio-cli --help` should exit 0 and print the Typer help. If not, **stop and ask** — the venv is broken.
   - Print the venv path and the resolved `depictio-cli --version` for sanity.

## Stop conditions (ask, don't guess)

- Not at the depictio repo root (no `depictio/cli/pyproject.toml`)
- `uv` not on PATH
- `uv sync` exits non-zero (lockfile mismatch, resolver error, network failure)
- `depictio-cli --help` fails after sync

## Notes

- `/new-worktree` runs this same `uv sync` step automatically when scaffolding a new worktree. Use `/cli-venv` standalone to refresh after pulling lockfile changes, or to recover after deleting `.venv`.
- The CLI venv is gitignored (`.venv` pattern) — never commit it.
