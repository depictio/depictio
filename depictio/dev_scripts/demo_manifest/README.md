# Data Manifest demo kit

End-to-end manual test of the remote-data-manifest flow (RFC
`docs/design/rfc-remote-data-manifests.md`) without any real data: generate
synthetic CSVs + a manifest, serve them over HTTP, and instantiate the
`generic/manifest-tables/1` template against them — from the UI or the CLI.

## 1. Generate and serve the data

```bash
python depictio/dev_scripts/demo_manifest/generate.py \
  --base-url http://host.docker.internal:8099 \
  --output-dir demo-manifest-data
cd demo-manifest-data && python -m http.server 8099 --bind 0.0.0.0
```

`--base-url` must be the address **as seen from the backend**:

- Backend in docker compose (default dev setup): `http://host.docker.internal:8099`
  (on Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the
  backend/worker services if not already present).
- Backend running directly on the host (pixi stack): `http://localhost:8099`.
- Anything already public over HTTPS (S3 bucket, GitHub raw/gist): use that
  URL and skip the env vars below entirely.

## 2. Open the SSRF gateway for the local server

The remote-fetch gateway only accepts `https://` to public addresses by
default. A local plain-HTTP server needs both of these on the **backend and
celery worker**:

```bash
DEPICTIO_REMOTE_ALLOW_HTTP=true
DEPICTIO_REMOTE_URL_ALLOWLIST=host.docker.internal   # or localhost
```

Caveat: setting the allowlist makes it exclusive — *only* listed hosts are
accepted while it is set. Add any other hosts you want to test alongside.

## 3. Instantiate

**UI**: Projects → Create project → *From Manifest* tab → paste
`http://host.docker.internal:8099/manifest.json`, pick the
*Manifest Tables* template, preview (dry-run coverage report), create. On
success you land on the auto-filled "Manifest Overview" dashboard.

**CLI**:

```bash
depictio run --template generic/manifest-tables/1 \
  --manifest http://host.docker.internal:8099/manifest.json \
  --config admin_config.yaml
```

## 4. What to check

- Both coverage cards show 3 entries (`nunique` of `depictio_manifest_id`).
- The manifest-entry MultiSelect filters both raw tables at once — that's the
  injected `depictio_manifest_id` join key, no join config anywhere.
- Re-run after editing a CSV or removing a manifest entry, then click
  **Refresh manifest** on the project detail page (or
  `POST /projects/refresh_manifest`) to see overwrite-with-report semantics;
  dropping a whole `type` marks that DC failed instead of silently emptying
  it, and the failure reason lands in the notification verbatim.
- Single-URL flavour, no manifest needed: project detail → *Add data
  collection* → Table → **From URL** source → paste any public HTTPS CSV
  (e.g. a seaborn-data raw GitHub URL) — same server-side ingestion, zero
  gateway configuration for public HTTPS hosts.
- Export the project back to a template: project page → *Export as template*
  (or `depictio template export <project_id> -t my-lab/demo/1 -c admin_config.yaml`)
  and diff the bundle against `depictio/projects/generic/manifest-tables/1/`.
