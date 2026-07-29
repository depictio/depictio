# Component export showcase

Everything on `feat/component-export`, exercised end to end: the export API, one
representative component of every type in both formats, a notebook tour, and a
separate locally-hosted site that embeds the results cross-origin.

The feature itself is documented in [`docs/design/component-export.md`](../../docs/design/component-export.md).
This directory is the demonstration, not the implementation.

## What the branch adds

```
GET /depictio/api/v1/export/dashboards/{id}/components            manifest
GET /depictio/api/v1/export/dashboards/{id}/components/{cid}      the component
```

`?format=json` returns a Plotly spec, `?format=html` returns one self-contained
file. The manifest reports which of the two each component supports, and why not
when it does not.

## Setup

Two things must be true on the instance:

```bash
# 1. the embed bundle exists (format=html injects a payload into it)
cd depictio/viewer && pnpm run build:embed

# 2. the routes are enabled, and this site's origin may frame them
#    docker-compose.override.yaml, depictio-backend environment:
#      DEPICTIO_FASTAPI_EMBED_ENABLED=true
#      DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS=http://localhost:8899,http://127.0.0.1:8899
docker compose -f docker-compose.dev.yaml -f docker-compose.override.yaml up -d depictio-backend
```

Both default to off. Serving embeds necessarily relaxes framing protections on
that path, so it is opt-in per deployment.

## Run it

```bash
cd dev/component-export-showcase

python export_all.py --clean      # export one component per type, both formats
python serve_site.py              # external site on http://localhost:8899
python shoot_site.py              # screenshots, if you want them

uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python jupyter plotly pandas
python build_notebook.py
.venv/bin/jupyter lab component_export_tour.ipynb
```

`export_all.py` reads the port and token out of the worktree's `.env.instance`
and the backend container, so nothing is hardcoded to one machine.

## What was measured

24 distinct component types across 38 seeded dashboards:

| | count |
|---|---|
| exported as HTML | 23 / 24 |
| exported as JSON | 8 / 24 |
| declined JSON, by design | 15 |
| failed | 1 (`phylogenetic`, data gap — see below) |

The JSON number is not a shortfall. `html` injects a payload into a prebuilt
React bundle that runs the viewer's real `ComponentRenderer`, so tables, cards,
text and the client-built advanced-viz kinds all render with no Python
equivalent. `json` can only serve what Python builds, so it covers `figure`,
`map`, `multiqc`, the Celery-backed advanced-viz kinds (`complex_heatmap`,
`upset_plot`, `sankey`) and the three ported to Python (`volcano`, `ma`, `qq`).
Everything else answers 501 with a reason and a working `html_url`.

`advanced_viz:phylogenetic` fails on **both** formats here with
`Data collection has no materialised Delta table yet.` That is this instance's
seed data, not the export path: the `bacterial_tree` data collection was never
ingested, so the live dashboard cannot render it either.

## The external site

`serve_site.py` runs on `:8899` while Depictio is on `:8102`. Different origin,
different server, no shared code — which is the point. Each card offers three
delivery modes, and each one proves something distinct:

| mode | route | proves |
|---|---|---|
| live frame | `<iframe>` → Depictio | cross-origin framing works: CSP `frame-ancestors` names this origin and no `X-Frame-Options` is sent |
| saved file | `<iframe>` → this server's copy | the download is genuinely standalone; Depictio is not in the loop |
| plotly spec | `fetch` → our own plotly.js | the JSON is a real figure the caller owns, restyled here to show it |

To confirm the headers yourself:

```bash
curl -sD - -o /dev/null -H "Origin: http://localhost:8899" \
  "http://localhost:8102/depictio/api/v1/export/dashboards/DASH/components/CID?format=html" \
  | grep -iE "content-security-policy|x-frame-options"
```

`frame-ancestors` should list `http://localhost:8899`, and there should be no
`X-Frame-Options` line at all — that header has no "allow these origins" form,
so the export path has to skip it.

## Files

| path | role |
|---|---|
| `showcase_lib.py` | instance discovery + a thin API client, shared by everything here |
| `export_all.py` | the sweep; writes `exports/` and `exports/index.json` |
| `serve_site.py` | the external site, and `/site-data.json` built from the export index |
| `site/` | the site itself (no build step, no framework) |
| `build_notebook.py` | generates `component_export_tour.ipynb` |
| `shoot_site.py` | headless-Chrome screenshots into `screenshots/` |

The notebook is generated rather than committed with outputs, because a
committed `.ipynb` is JSON with embedded base64 and cannot be reviewed in a diff.
Edit `build_notebook.py`, regenerate, then execute.

`exports/` and `notebook_exports/` are gitignored: 24 components × ~7 MB is
150 MB of build output, reproducible in 20 seconds from `export_all.py`.
