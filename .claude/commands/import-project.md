# Import Project

Run `depictio-cli run` on a project's `project.yaml`, then `depictio-cli dashboard import` on every dashboard YAML in the project's `dashboards/` folder. Uses the per-worktree CLI venv at `depictio/cli/.venv`.

## Usage

`/import-project <project-folder> [<cli-config-path>]`

- `<project-folder>`: path to a project directory containing `project.yaml` and a `dashboards/` subfolder (e.g. `depictio/projects/init/iris`, `depictio/projects/test/map_demo`).
- `<cli-config-path>` *(optional)*: path to the depictio CLI config YAML. Defaults to `~/.depictio/CLI.yaml`. In a worktree with a non-default API port, you'll usually want a worktree-scoped CLI config that points at the right `FASTAPI_PORT` from `.env.instance`.

If the project folder argument is missing, ask the user before proceeding.

$ARGUMENTS

## Steps

1. **Validate the project folder**:
   - Resolve `<project-folder>` to an absolute path. If it doesn't exist, **stop and ask**.
   - Require `<project-folder>/project.yaml` — this is the input for `depictio-cli run`. If missing, **stop and ask**.
   - List dashboard YAMLs: `<project-folder>/dashboards/*.yaml`. If `dashboards/` is missing or empty, warn and ask the user whether to proceed with `run` only (importing zero dashboards is rarely intentional).

2. **Ensure the CLI venv exists** at `depictio/cli/.venv`:
   - Check `depictio/cli/.venv/bin/depictio-cli`. If it doesn't exist, **stop and tell the user to run `/cli-venv` first**. Do not silently `uv sync` here — keep the venv lifecycle in one place so failures surface against the right skill.
   - Quick smoke check: `depictio/cli/.venv/bin/depictio-cli --version` should exit 0.

3. **Resolve the CLI config**:
   - If `<cli-config-path>` was passed, use it as-is (after `~` expansion).
   - Otherwise default to `~/.depictio/CLI.yaml`.
   - If the file doesn't exist, **stop and ask** — the CLI config carries the API URL and auth token; we won't synthesize one.
   - In a worktree (`.env.instance` exists at the worktree root), surface the worktree's `FASTAPI_PORT` from `.env.instance` and ask the user to confirm the CLI config's `api_base_url` points at it. Mismatched ports silently target the wrong instance.

4. **Activate the venv and run the project**:

   ```bash
   source depictio/cli/.venv/bin/activate
   depictio-cli run \
     --CLI-config-path "<cli-config>" \
     --project-config-path "<project-folder>/project.yaml"
   ```

   - Run as a chained command in a single Bash invocation (activation does not persist across shell calls).
   - If `run` fails, **stop and surface the error** before attempting any dashboard imports — importing dashboards against a project that didn't sync is wasted churn.

5. **Import each dashboard YAML**:

   For every file in `<project-folder>/dashboards/*.yaml`:

   ```bash
   depictio-cli dashboard import "<dashboard-yaml>" --config "<cli-config>" --overwrite
   ```

   - `--overwrite` is included because re-running `/import-project` is the common case (iterate on a YAML, re-import). If the user explicitly asks for a non-overwriting run, drop the flag.
   - Run imports sequentially, not in parallel — they hit the same API and ordering surfaces clearer errors.
   - If any import fails, report which file failed and **stop**. Don't keep going through the rest silently.

6. **Verify and report**:
   - Print: project folder, CLI config used, API URL (extracted from the CLI config's `api_base_url`), `run` outcome, and a list of dashboards imported (filename + reported dashboard ID/title from CLI output).

## Stop conditions (ask, don't guess)

- `<project-folder>` argument missing or path doesn't exist
- No `project.yaml` in the project folder
- `depictio/cli/.venv` missing (tell user to run `/cli-venv`)
- Resolved CLI config file doesn't exist
- `depictio-cli run` exits non-zero
- Any `depictio-cli dashboard import` exits non-zero

## Notes

- The CLI venv is per-worktree by design — running `/import-project` in a worktree uses that worktree's CLI build, not the main checkout's. This matters when you've edited the CLI source on a feature branch.
- For projects with `.db_seeds/*.json`, those are loaded by `db_init.py` on a fresh deployment — `/import-project` is the live-server equivalent and writes through the API instead of seeding the DB.
- Example: `/import-project depictio/projects/init/iris` (uses `~/.depictio/CLI.yaml`, imports `dashboards/petal_analysis.yaml` and `dashboards/overview.yaml`).
