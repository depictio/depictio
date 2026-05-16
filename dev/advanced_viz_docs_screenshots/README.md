# Advanced-viz docs screenshot pipeline

Two helper scripts used to (re)generate the per-viz screenshots that live in
`depictio-docs/docs/images/guides/advanced-visualizations/`. The screenshots
back the `<viz>_light.webp#only-light` + `<viz>_dark.webp#only-dark` pairs in
the docs page so the mkdocs-material theme switch flips them automatically.

Two-step workflow because the showcase dashboards each carry several
sibling components (cards, tables, filters) that we strip to a lone viz
filling the right-panel grid — that's what makes the captures tight enough
to embed in the docs.

## 1. `strip_dashboards_to_single_viz.py`

Edits the JSON dashboard seeds under
`depictio/projects/init/advanced_viz_showcase/.db_seeds/` in place:

- Keeps the single `advanced_viz` component, drops everything else
- Resizes its grid tile to fill the panel (w=12, h=8)
- Empties the left-panel filters and add-component button
- Skips `dashboard_overview.json` (curated 4-viz tab — leave intact)

Idempotent. Re-run after upserting the original showcase seeds back into Mongo.

## 2. `capture_react_screenshots.py`

Drives the new `GET /depictio/api/v1/utils/screenshot-react-dual/{id}` endpoint
(see `depictio/api/v1/services/screenshot_service.py::generate_react_dual_theme_screenshots`)
for each of the 18 unique `viz_kind`s. Per dashboard:

1. POSTs the auth header and triggers the endpoint with `open_settings=true`
   so the Mantine viz-settings popover shows in the shot.
2. The endpoint runs Playwright headless inside the API container and writes
   `react_<viz>_<dashboard_id>_<theme>.png` to the bind-mounted
   `depictio/dash/static/screenshots/` folder.
3. This script then converts the PNG → WebP (`cwebp -q 82 -m 6`) on the way
   into `…/docs/images/guides/advanced-visualizations/<viz>_<theme>.webp`.

WebP rather than PNG keeps the docs repo footprint at ~1.6 MB across the 36
files (≈60% smaller than PNG at visually identical quality).

### Auth

Reads the admin token from `/tmp/admin_token.txt`. Mint a fresh one with:

```bash
curl -s -X POST "http://localhost:${FASTAPI_PORT}/depictio/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=changeme" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])" \
  > /tmp/admin_token.txt
```

### Run

```bash
python3 dev/advanced_viz_docs_screenshots/capture_react_screenshots.py --open-settings
# subset:
python3 dev/advanced_viz_docs_screenshots/capture_react_screenshots.py --only volcano ma
```

≈25 s per dashboard × 18 = ~7 min for the full batch.

## Tuning

- Quality knob: `cwebp -q 82` — drop to 75 for tighter files, push to 90 for
  near-lossless. Below 70 the Plotly grid lines start to blur visibly.
- Viewport: hard-coded at 1920×1080 in the service. Drop to 1280×800 if you
  want to roughly halve the files again at the cost of less retina-crispness
  on hi-DPI displays.
