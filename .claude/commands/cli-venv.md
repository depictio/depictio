# CLI Venv

Create or refresh the CLI virtualenv at `depictio/cli/.venv` via `uv sync`.

## Usage

`/cli-venv`

No arguments. Idempotent — safe to re-run after pulling changes that touched `pyproject.toml` or `uv.lock`.

## Why a per-worktree CLI venv

The CLI is the root `depictio` package without its `[server]` extra (`depictio/cli/pyproject.toml` only defines the `depictio-cli` alias published to PyPI). A scoped `.venv` holding just the base and `[multiqc]` matches what `pip install depictio` users get, and lets each worktree target its own allocated API ports without polluting the global `depictio-cli` install.

## Steps

1. **Locate the CLI package**:
   - From the repo root, confirm `pyproject.toml`, `uv.lock` and `depictio/cli/` all exist. If any is missing, **stop and ask** — wrong directory or unexpected repo layout.

2. **Run `uv sync`**:
   ```bash
   UV_PROJECT_ENVIRONMENT=depictio/cli/.venv uv sync --frozen --extra multiqc
   ```
   - Run it from the repo root: it installs the root project (editable) from the root `uv.lock` into `depictio/cli/.venv`.
   - Do not `pip install -e .` as a fallback — the lockfile is authoritative. Do not run `uv sync` inside `depictio/cli/` either: that installs the alias, which makes `depictio` a namespace package.
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
- The venv has no server packages (FastAPI, Celery, Playwright): that is intended, it is the CLI install users get.
- The CLI venv is gitignored (`.venv` pattern) — never commit it.
