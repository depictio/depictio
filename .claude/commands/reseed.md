# Reseed a reference project (in-place, no container restart)

Reseeds one or more bundled reference projects (iris, penguins, ampliseq,
advanced_viz_showcase, …) **without** wiping the whole MongoDB / MinIO state.
Use after editing `template.yaml`, a canonical recipe, or a `.db_seeds/*.json`
on the project, when you want the changes reflected in the running app.

Backed by `dev/reseed_project.py`. Runs **inside the API container** so it has
MongoDB + MinIO + the depictio module path.

## When to use

- Edited `depictio/projects/.../template.yaml` (DC config, recipe paths, links).
- Edited `depictio/projects/.../recipes/*.py` AND regenerated the
  canonical TSV seeds at `depictio/projects/.../{dc_tag}.tsv`.
- Edited `depictio/projects/.../.db_seeds/dashboard_*.json` (added / removed
  tiles, reorganised tabs).
- Renamed a dashboard JSON file and updated `db_init.py`'s registration list.

## When NOT to use

- For a fresh full-state wipe: use `docker compose ... down -v && up`.
- For non-reference projects (user-created via the CLI / API): use the
  project-delete + re-import flow.
- For a runtime model / Pydantic schema change in `configs.py` / `schemas.py`:
  reseed alone won't pick that up; the API container needs a restart
  (`docker compose ... restart depictio`).

## Usage

```bash
# Reseed ampliseq end-to-end (default — re-materialises Delta tables from TSV seeds)
/reseed ampliseq

# Skip Delta-table re-materialisation (fastest; only project + DCs + dashboards rebuilt)
/reseed ampliseq --no-data

# Multiple at once
/reseed ampliseq advanced_viz_showcase
```

## What the underlying script does

1. Look up the project by name via `ReferenceDatasetRegistry.STATIC_IDS`.
2. Cascade-delete the project + DC docs + Delta-table docs + files docs +
   matching dashboards from MongoDB. Wipes S3 objects from MinIO too
   (best-effort).
3. Re-run `create_reference_project()` → fresh project + DC documents with
   the same static IDs.
4. Re-run `create_initial_dashboards()` → reads every dashboard JSON in
   `db_init.py` and recreates the ones whose `project_id` resolves.
5. (Default) Re-run `ReferenceDatasetProcessor.process_dataset()` for each
   target → scans the canonical TSV seeds and writes the Delta tables.
6. Bumps `reference_datasets_metadata` so subsequent background-processor
   runs see the refreshed projects.

## Instructions for Claude

When the user invokes `/reseed <dataset> [<dataset> ...] [--no-data]`:

1. Confirm the dataset name(s) appear in `ReferenceDatasetRegistry.STATIC_IDS`
   (`depictio/api/v1/db_init_reference_datasets.py:33`). If not, list valid
   options and stop.

2. Run inside the API container:

   ```bash
   docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env \
     exec depictio-backend python -m depictio.dev_scripts.reseed_project $ARGUMENTS
   ```

3. Stream the container logs (`docker logs depictio-api -f --tail 0 &`) so the
   user sees the resolver / scan progress. Stop the log follower when the
   exec call returns.

4. After it succeeds, remind the user:
   - Hard-refresh the browser (`Cmd+Shift+R`) — the React viewer caches API
     responses by DC ID and dashboard ID.
   - For dashboard-layout changes the React viewer may also need
     `pnpm dev` to be running for HMR; if the prod bundle is served from
     `/dashboard-beta`, build with `pnpm build` then `touch
     depictio/api/main.py` to remount routes (per
     `project_viewer_dist_route_mount` memory).

## Safety

- The cascade is scoped to the named projects' static IDs — it cannot
  accidentally drop unrelated projects or user-created dashboards.
- If the MinIO bucket is unreachable, the script logs a warning and
  continues — MongoDB cascade still runs so the next `--no-data` reseed
  isn't blocked.
- The script is idempotent: running it on a project that's already deleted
  just re-creates it.

$ARGUMENTS
