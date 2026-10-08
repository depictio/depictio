# Data Manifest demo kit

End-to-end manual test of the remote-data-manifest flow (RFC
`docs/design/rfc-remote-data-manifests.md`) without any real data: generate
synthetic CSVs plus a manifest, serve them over HTTP, and instantiate the
`generic/manifest-tables/1` template against them, from the UI or the CLI.

## 1. Generate and serve the data

```bash
python depictio/dev_scripts/demo_manifest/generate.py \
  --base-url http://host.docker.internal:8099 \
  --output-dir demo-manifest-data
cd demo-manifest-data && python -m http.server 8099 --bind 0.0.0.0
```

`--base-url` must be the address **as seen from the backend**:

- Backend in docker compose (default dev setup): `http://host.docker.internal:8099`.
  On Linux that name does not resolve inside containers and
  `docker-compose.dev.yaml` declares no `extra_hosts`, so you always have to
  add `extra_hosts: ["host.docker.internal:host-gateway"]` to both the
  `depictio-backend` and `depictio-celery-worker` services (Docker Desktop on
  macOS and Windows provides the name by itself).
- Backend running directly on the host (pixi stack): `http://localhost:8099`.
- Anything already public over HTTPS (S3 bucket, GitHub raw/gist): use that
  URL and skip step 2 entirely.

## 2. Open the SSRF gateway for the local server

The remote-fetch gateway only accepts `https://` to public addresses by
default. A local plain-HTTP server needs the backend **and** the celery worker
to see two variables. Put them in `docker-compose/.env`: it is the `env_file`
of both `depictio-backend` and `depictio-celery-worker`, so one edit reaches
both containers. (The compose `environment:` blocks also pass every
`DEPICTIO_REMOTE_*` variable through with a default, so exporting them in the
shell that runs `docker compose up` works as well; the env file is simply the
place the shared dev defaults already live.)

```bash
# docker-compose/.env
DEPICTIO_REMOTE_ALLOW_HTTP=true
DEPICTIO_REMOTE_URL_ALLOWLIST=host.docker.internal   # or localhost
```

The shared dev file already sets `DEPICTIO_REMOTE_ALLOW_HTTP=true` and keeps
the allowlist commented out on purpose: the allowlist is **exclusive** while
set (only the listed hosts are accepted), so uncomment it locally and list
every other host you want to test alongside. Recreate the two services after
editing the file so they pick up the new environment.

## 3. Instantiate

**UI**: Projects, then Create project, then the *From Manifest* tab. Paste
`http://host.docker.internal:8099/manifest.json`, pick the *Manifest Tables*
template, preview (dry-run coverage report), create. On success you land on
the auto-filled "Manifest Overview" dashboard.

**CLI**:

```bash
depictio run --template generic/manifest-tables/1 \
  --manifest http://host.docker.internal:8099/manifest.json \
  --config admin_config.yaml
```

## 4. What to check

- Both coverage cards show 3 entries (`nunique` of `depictio_manifest_id`).
- The manifest-entry MultiSelect filters both raw tables at once: that is the
  injected `depictio_manifest_id` join key, with no join config anywhere.
- Re-run after editing a CSV or removing a manifest entry, then refresh the
  project's manifest-backed collections through the API. There is no refresh
  button on the project page yet (a follow-up PR adds it); the CLI and the
  endpoint are the only refresh paths for now:

  ```bash
  # $DEPICTIO_TOKEN: user.token.access_token from your CLI config (admin_config.yaml)
  curl -X POST http://localhost:8058/depictio/api/v1/projects/refresh_manifest \
    -H "Authorization: Bearer $DEPICTIO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"project_id": "<project_id>", "dry_run": false, "async_run": false}'
  ```

  Optional body fields: `data_collection_tag` restricts the refresh to one
  collection, `dry_run: true` reports the per-DC entry counts without touching
  any data, and `async_run: true` fans the per-DC re-ingestion out to Celery
  workers and returns a `run_id` to poll:

  ```bash
  curl http://localhost:8058/depictio/api/v1/projects/refresh_manifest/<run_id> \
    -H "Authorization: Bearer $DEPICTIO_TOKEN"
  ```

  Both calls return the same report: `refreshed[]` with one row per DC
  (`data_collection_tag`, `entries`, `status`, `message`) plus a top-level
  `success`. Statuses are `ingested` / `failed` for a synchronous refresh and
  `dispatched` / `running` / `ingested` / `failed` while polling, with
  `success` flipping once every worker finished green. This is the
  overwrite-with-report semantics: dropping a whole `type` from the manifest
  marks that DC `failed` instead of silently emptying it.
- Export the project back to a template: project page, *Export as template*
  (or `depictio template export <project_id> -t my-lab/demo/1 -c admin_config.yaml`)
  and diff the bundle against `depictio/projects/generic/manifest-tables/1/`.
