# Import a template-based project (run + dashboard import)

Runs `depictio-cli run --template <id> --data-root <path>` to ingest data and
sync a template project (e.g. `nf-core/viralrecon/3.0.0`,
`nf-core/ampliseq/2.16.0`), then re-imports each of the template's dashboard
YAMLs via `depictio-cli dashboard import --overwrite`. Uses the per-worktree
CLI venv at `depictio/cli/.venv`.

This is the **template** counterpart to `/import-project` — the latter targets
non-template projects with a static `project.yaml`. Use this skill when the
project ships a `template.yaml` (everything under
`depictio/projects/nf-core/<pipeline>/<version>/`).

## Usage

```
/import-template <template-id> --data-root <path> [options]
```

Required:

- `<template-id>`: e.g. `nf-core/viralrecon/3.0.0`, `nf-core/ampliseq/2.16.0`.
  Looked up by walking `depictio/projects/` for a matching `template.yaml`
  where `template.template_id` equals the argument.
- `--data-root <path>`: directory containing the pipeline output the template
  expects (e.g. `~/Data/viralrecon/viralrecon-testdata/run_1`). Tilde-expand
  and resolve to an absolute path before passing through.

Optional flags (mirror the underlying CLI flags 1-to-1):

- `--var KEY=VALUE` *(repeatable)*: extra template variables (passed straight
  to `depictio-cli run --var`).
- `--project-name <name>`: override the auto-generated project name.
- `--overwrite`: pass `--overwrite` to `run` (re-process the workflow if it
  already exists). Common when iterating on a recipe.
- `--update-config`: pass `--update-config` to `run` (push the resolved
  project config to the server, replacing what's there).
- `--dashboards-only`: skip `run` entirely; only import dashboards. Use after
  hand-editing a `dashboards/*.yaml` when the data hasn't changed.
- `--no-dashboards`: also skip step 5 (the explicit `dashboard import`
  loop). Use when you want to iterate on data only and re-import dashboards
  manually later. (`run` itself is already always called with
  `--skip-dashboard-import` — see step 4 — so this flag specifically
  controls the post-run dashboard loop.)
- `--dashboard <path>` *(repeatable)*: override the template's default
  dashboard YAMLs with explicit file paths (forwarded to `run --dashboard`
  AND used for the post-run `dashboard import` calls).
- `--cli-config <path>`: path to the CLI config YAML. Default behaviour is
  **worktree-aware** — see "Worktree handling" below. Use this flag when you
  want to force a specific config file and skip auto-detection.

## Examples

```bash
# First-time upload of viralrecon against the bundled test data
/import-template nf-core/viralrecon/3.0.0 \
  --data-root ~/Data/viralrecon/viralrecon-testdata/run_1

# Re-iterate on viralrecon after editing template.yaml + a recipe
/import-template nf-core/viralrecon/3.0.0 \
  --data-root ~/Data/viralrecon/viralrecon-testdata/run_1 \
  --overwrite --update-config

# Just re-push the dashboards after editing base.yaml (no data churn)
/import-template nf-core/viralrecon/3.0.0 \
  --data-root ~/Data/viralrecon/viralrecon-testdata/run_1 \
  --dashboards-only

# Ampliseq with an extra template var
/import-template nf-core/ampliseq/2.16.0 \
  --data-root ~/Data/ampliseq/run_x \
  --var GROUP_COL=habitat
```

$ARGUMENTS

## Steps

1. **Resolve and validate inputs**:
   - Tilde-expand and absolute-resolve `--data-root`. If it doesn't exist or
     isn't a directory, **stop and ask**.
   - Locate the template directory by grepping `depictio/projects/` for a
     `template.yaml` whose `template.template_id` matches `<template-id>`. If
     zero or multiple matches, **stop and ask**.
   - Read the matched `template.yaml`'s `template.dashboards:` list to know
     which dashboard YAML(s) the template ships (resolve relative to the
     template directory). If `--dashboard <path>` was passed, that overrides
     the list.
   - Validate that every resolved dashboard YAML exists on disk; **stop and
     ask** if any are missing.

2. **Ensure the CLI venv exists** at `depictio/cli/.venv`:
   - Check `depictio/cli/.venv/bin/depictio-cli`. If it doesn't exist, **stop
     and tell the user to run `/cli-venv` first**.
   - Smoke check: `depictio/cli/.venv/bin/depictio-cli --version` should exit
     0.

3. **Resolve the CLI config** (worktree-aware — see below for details):
   - If `--cli-config <path>` was passed, use it verbatim (after `~`
     expansion). **Do not auto-rewrite.** If the file doesn't exist, **stop
     and ask**.
   - Otherwise: run the worktree-detection logic in "Worktree handling"
     below. It either returns the user's default `~/.depictio/CLI.yaml`
     unchanged (no worktree / ports already match), or returns a freshly
     written `~/.depictio/CLI.<INSTANCE_ID>.yaml` whose `api_base_url`
     points at the worktree's `FASTAPI_PORT`.
   - Echo the resolved CLI config path + its `api_base_url` so the user can
     sanity-check before the network calls fly.

4. **Pick the dashboard-import path** based on YAML shape:

   - **Multi-tab template format** (`version: 1` + `main_dashboard:` + `tabs:`
     at top level — what `nf-core/*` templates ship): the only working path
     is `depictio-cli run`'s built-in template importer (step 8 of `run`).
     The standalone `depictio-cli dashboard import` cannot handle the
     multi-tab layout — it consumes one `DashboardDataLite` per YAML and
     silently ignores the `tabs:` block. So: **don't pass
     `--skip-dashboard-import`** and rely on `run` to do the import.
   - **Single-dashboard format** (no `tabs:` block, just a single dashboard
     definition — what `depictio/projects/init/*` and `depictio/projects/test/*`
     ship): use `depictio-cli dashboard import` per YAML with `--overwrite`.
     Pass `--skip-dashboard-import` to `run` to avoid double-importing.

   Detect by reading the first dashboard YAML and checking whether the
   top-level keys include `main_dashboard` / `tabs`.

5. **Run the data + project sync** (unless `--dashboards-only`):

   ```bash
   source depictio/cli/.venv/bin/activate
   depictio-cli run \
     --CLI-config-path "<cli-config>" \
     --template "<template-id>" \
     --data-root "<data-root>" \
     [--skip-dashboard-import]    # ONLY for single-dashboard format
     [--project-name "<name>"] \
     [--var KEY=VALUE]... \
     [--overwrite] \
     [--update-config]
   ```

   - All in one Bash invocation (the venv activation does not persist across
     calls).
   - `--overwrite` and `--update-config` are passed through directly when
     the user provides them. Don't add them silently. **For multi-tab
     templates, `--overwrite` is what makes the dashboard import update
     existing tabs instead of erroring** — pass it any time the user
     re-runs.
   - If `run` exits non-zero, **stop and surface the error**.
   - When `run` succeeds, capture the project ID from its output (look for
     `View at:` lines or the project document via `api_get_project_from_name`).

6. **(Single-dashboard format only)** Import dashboards explicitly with
   `--overwrite`:

   For every resolved dashboard YAML:

   ```bash
   depictio-cli dashboard import "<dashboard-yaml>" \
     --config "<cli-config>" \
     --overwrite \
     [--project "<project-id>"]
   ```

   - Pass `--project <id>` only if the YAML doesn't carry `project_tag`.
   - Imports run sequentially. If any fails, report which file and **stop**.
   - Skip this whole step for multi-tab template format — `run` step 5
     already handled it.

6. **Verify and report**:
   - Print: template ID, data root, CLI config used, API URL (from the CLI
     config's `api_base_url`), `run` outcome (skipped / success / failed),
     and per-dashboard import results (filename → dashboard ID + title).
   - End with a one-liner like
     `View at: <api_base_url>/dashboard/<dashboard_id>` for each imported
     dashboard so the user can click straight through.

## Stop conditions (ask, don't guess)

- `<template-id>` arg missing or no matching `template.yaml` found
- `--data-root` arg missing, doesn't exist, or isn't a directory
- Template's `dashboards:` list resolves to a file that's missing on disk
- `depictio/cli/.venv` missing (tell user to run `/cli-venv`)
- Resolved CLI config file doesn't exist
- `depictio-cli run` exits non-zero (unless `--dashboards-only`)
- Any `depictio-cli dashboard import` exits non-zero

## Worktree handling

The CLI reads its API URL from `api_base_url` inside the YAML config — there
is no `DEPICTIO_API_BASE_URL` env-var override. Every worktree allocates its
own port via `.env.instance` (e.g. `FASTAPI_PORT=8100` here, where the main
checkout would be 8058), so running `/import-template` with the global
`~/.depictio/CLI.yaml` silently uploads to the wrong instance.

This skill auto-routes around that. When `--cli-config` is **not** passed:

1. Look for `.env.instance` at the repo root (the worktree's top-level
   directory — same level as `docker-compose.dev.yaml`). If absent → we're
   in the main checkout, just use `~/.depictio/CLI.yaml` and continue.
2. Parse the relevant worktree env vars:
   - `INSTANCE_ID` (for the per-worktree config filename)
   - `FASTAPI_PORT` (for `api_base_url`)
   - `DEPICTIO_MINIO_EXTERNAL_PORT` (for `s3_storage.external_port`)
   - `MONGO_PORT` (for the worktree's MongoDB, where we fetch the token)
3. Read the user's default config at `~/.depictio/CLI.yaml`. If all three
   override targets already match the worktree (`api_base_url` port,
   `s3_storage.external_port`, AND the user token is the worktree's admin
   token), skip rewrite and use the default config. Otherwise:
4. Auto-generate `~/.depictio/CLI.<INSTANCE_ID>.yaml` using the Python
   snippet in "Implementing the worktree config in Python" below. This
   clones the default config and overrides:
   - `api_base_url` → `http://localhost:<FASTAPI_PORT>`
   - `s3_storage.external_port` → `<DEPICTIO_MINIO_EXTERNAL_PORT>`
   - `user.token` (full block) → fetched from
     `mongodb://localhost:<MONGO_PORT>/depictioDB` (admin user's
     `default_token`)
   - `user.id`, `user.email` → the worktree admin's user record
5. Print one line summarising the rewrite (path + api_base_url + s3 port +
   user id) so the user can sanity-check before the network calls fly.
6. Use that file as the `--CLI-config-path` for `run` (and `--config` for
   any standalone `dashboard import` calls).

**Token freshness**: re-fetch the token from MongoDB every time the config
is regenerated (i.e. when port mismatch is detected). Don't trust a cached
token — the worktree might have been re-seeded since the last invocation.

If `~/.depictio/CLI.yaml` doesn't exist (no default config to clone from),
**stop and ask** — we use it as the structural template (s3 keys, user
schema). Tell the user to either:

- run `depictio config` (or the equivalent setup flow) to create
  `~/.depictio/CLI.yaml` first, OR
- pass `--cli-config <path>` explicitly to point at an existing config.

If `.env.instance` exists but is missing `FASTAPI_PORT`,
`DEPICTIO_MINIO_EXTERNAL_PORT`, or `MONGO_PORT`, **stop and ask** — we don't
guess.

If `mongosh` is not on PATH, **stop and tell the user to install it**
(`brew install mongosh` on macOS). It's the only practical way to extract
the worktree's admin token without standing up a full Beanie/Pydantic
import.

A naive port-only override is **not enough** for a worktree. Each worktree
runs its own MongoDB + MinIO with its own auth token, so three things have
to be overridden in the cloned config:

1. `api_base_url` → `http://localhost:<FASTAPI_PORT>`
2. `s3_storage.external_port` → the worktree's `DEPICTIO_MINIO_EXTERNAL_PORT`
3. `user.token` (and `user.id`, `user.email`) → fetched from the worktree's
   MongoDB at `localhost:<MONGO_PORT>` for the admin user's `default_token`

Skipping (2) makes recipe Delta-table writes fail with
`Could not connect to the endpoint URL "http://localhost:9000/..."`.
Skipping (3) makes the very first `api_login` call fail with `Token expired
or not found.` (the default token authenticates against the main checkout's
MongoDB, not the worktree's).

### Implementing the worktree config in Python (preferred)

```python
import json, subprocess, yaml, os
from pathlib import Path

env = {}
for line in Path('.env.instance').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v

instance_id  = env['INSTANCE_ID']
api_port     = env['FASTAPI_PORT']
minio_port   = env['DEPICTIO_MINIO_EXTERNAL_PORT']
mongo_port   = env['MONGO_PORT']

# Pull the worktree admin token from its MongoDB
out = subprocess.check_output([
    'mongosh', '--quiet', f'mongodb://localhost:{mongo_port}/depictioDB',
    '--eval',
    'const a=db.users.findOne({is_admin:true}); '
    'const t=db.tokens.findOne({user_id:a._id,name:"default_token"}); '
    'print(JSON.stringify({'
      'user_id:a._id.toString(), email:a.email,'
      'access_token:t.access_token, refresh_token:t.refresh_token,'
      'token_type:t.token_type, token_lifetime:t.token_lifetime,'
      'expire_datetime:t.expire_datetime.toISOString(),'
      'refresh_expire_datetime:t.refresh_expire_datetime?t.refresh_expire_datetime.toISOString():null,'
      'name:t.name,'
      # toISOString gives ISO-8601 — Pydantic accepts it. Don't use .toString().
      'created_at:t.created_at?t.created_at.toISOString():null'
    '}));'
]).decode().strip().splitlines()[-1]
tok = json.loads(out)

cfg = yaml.safe_load(open(os.path.expanduser('~/.depictio/CLI.yaml')))
cfg['api_base_url'] = f'http://localhost:{api_port}'
cfg['s3_storage']['external_port'] = int(minio_port)
cfg['user']['id'] = tok['user_id']
cfg['user']['email'] = tok['email']
def _iso_to_space(s): return s.replace('T', ' ').split('.')[0] if s else None
cfg['user']['token'] = {
    'access_token': tok['access_token'],
    'refresh_token': tok['refresh_token'],
    'token_type': tok['token_type'],
    'token_lifetime': tok['token_lifetime'],
    'expire_datetime': _iso_to_space(tok['expire_datetime']),
    'refresh_expire_datetime': _iso_to_space(tok['refresh_expire_datetime']),
    'name': tok['name'],
    'created_at': _iso_to_space(tok['created_at']),
    'description': None, 'flexible_metadata': None, 'hash': None,
    'id': None, 'logged_in': True, 'user_id': tok['user_id'],
}
dest = os.path.expanduser(f'~/.depictio/CLI.{instance_id}.yaml')
yaml.safe_dump(cfg, open(dest, 'w'), default_flow_style=False, sort_keys=True)
print(f'WROTE: {dest}')
```

Run via the worktree's main venv:
`./.venv/bin/python -c "<paste-above>"` (or save to a tmp file and run).

**Gotcha**: `mongosh` Date.toString() returns a free-form string like
`Wed May 13 2026 11:27:54 GMT+0200` which Pydantic rejects. Always use
`.toISOString()` in the mongosh `--eval` payload and then strip the trailing
`Z` / milliseconds when writing to the YAML (the depictio CLI config schema
uses naive `YYYY-MM-DD HH:MM:SS` strings).

### When to delete the auto-generated config

Never automatically. Stale worktree configs in `~/.depictio/` are harmless
(the next run just overwrites if the port changes), and keeping them lets
you re-target an old worktree without re-running setup. If you want a
cleanup, do it manually:
`rm ~/.depictio/CLI.<old-instance-id>.yaml`.

## When to use vs neighbours

- **`/import-template`** (this one): template projects with `template.yaml` +
  `--template <id> --data-root <path>` (viralrecon, ampliseq, any nf-core
  pipeline shipped under `depictio/projects/nf-core/`).
- **`/import-project`**: static-config projects with a literal `project.yaml`
  (iris, penguins, anything in `depictio/projects/init/` or `test/`).
- **`/reseed <name>`**: bundled reference dataset (iris, penguins, ampliseq,
  advanced_viz_showcase) that's registered in
  `db_init_reference_datasets.py::STATIC_IDS` — does an in-place full
  re-init (cascade-delete + recreate) inside the API container, no CLI hop.
  Faster and more thorough than `/import-template`, but only works for the
  registered reference projects.

## Notes

- The CLI venv is per-worktree by design — running this skill in a worktree
  uses *that* worktree's CLI build, not the main checkout's. Matters when
  you've edited CLI source on a feature branch.
- `depictio-cli run` already imports the template's default dashboards as
  step 8 of its pipeline. This skill still runs an explicit `dashboard
  import --overwrite` afterwards because:
  1. It's the idempotent path for re-iterating on dashboard YAML edits.
  2. The explicit import surfaces clearer per-file error messages than the
     bundled step inside `run`.
  3. `--overwrite` upgrades existing dashboards instead of erroring on
     duplicate-title.
- Viralrecon-specific tip: the bundled test data lives at
  `~/Data/viralrecon/viralrecon-testdata/run_1` (downloaded via
  `depictio/projects/nf-core/viralrecon/3.0.0/download_test_data.sh`). After
  uploading, hard-refresh the browser (`Cmd+Shift+R`) — the React viewer
  caches by dashboard ID.
