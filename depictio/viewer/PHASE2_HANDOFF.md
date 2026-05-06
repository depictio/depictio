# Phase 2 handoff — React viewer component ports

Branch `feat/react-viewer-mvp`, two new commits on top of the original MVP.

## What landed (commits, in order)

| HEAD | Commit | Scope |
|---|---|---|
| `c80357d3` | Batch 1 | Slider (single), DatePicker (range), Checkbox/Switch, SegmentedControl, Image grid, AG Grid SSRM |
| `a6828fb8` | Batch 2 | Map (Plotly Express, **not** Leaflet), JBrowse (iframe), MultiQC (regular plots; general-stats placeholder) |

Plus reorg: every interactive sub-type now lives under `depictio/viewer/src/components/interactive/` (mirrors the Dash side's `modules/interactive_component/`); MultiQC helpers under `components/multiqc/`.

## Bring it live (after restarting Docker)

```bash
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up -d
```

The viewer dist (`depictio/viewer/dist/`) was rebuilt during this session; if your host volume mount picks it up directly, no extra step. If not:

```bash
cd depictio/viewer && npm run build
```

(Already passes — `tsc && vite build` succeeded with the new code.)

Backend Python is auto-reloaded by FastAPI in dev. New routes:
- `POST /depictio/api/v1/dashboards/render_map/{dashboard_id}/{component_id}`
- `POST /depictio/api/v1/dashboards/render_jbrowse/{dashboard_id}/{component_id}`
- `POST /depictio/api/v1/dashboards/render_multiqc/{dashboard_id}/{component_id}`
- `GET  /depictio/api/v1/dashboards/render_image_paths/{dashboard_id}/{component_id}?max=N`

## Smoke-test checklist (per component)

All URLs are at `http://0.0.0.0:8122/dashboard-beta/<id>` (the React viewer; the Dash viewer at `:5122/dashboard/<id>` should remain unchanged).

### Already shipped in MVP — regression checks
- **Iris** `6824cb3b89d2b72169309737` — cards, MultiSelect, RangeSlider all still render
- **Coverage & Depth** `69ea13b37da6e01317a4bab4`
- **Diff Abundance (corrupt DC)** `646b0f3c1e4a2d7f8e5b8cb4` — broken card values still show "—"

### New in Batch 1
- **Slider (single)** — find a dashboard with `interactive_component_type: "Slider"` (grep `.db_seeds/*.json` and `depictio/projects/*/dashboards/*.yaml`). If none exist, hand-edit a seed to swap a `RangeSlider` for `Slider` and reload. Drag the thumb; expect the live label, marks, and a debounced filter that recomputes cards.
- **DatePicker (range)** — find any dashboard with `DatePicker` or `DateRangePicker`. Pick a sub-range; expect cards to recompute. Picking the full original range emits `value: null` (filter inactive).
- **Checkbox / Switch** — no existing seed uses these; flip a `MultiSelect` seed to `Checkbox`/`Switch` to test, or skip until a real dashboard exists.
- **SegmentedControl** — same caveat. Test path: flip Iris's `MultiSelect` on `variety` to `SegmentedControl`.
- **Image grid** — `image_demo/dashboards/gallery.yaml` (project `image_demo`, dashboard ID `6997872a694d2122240775c6`). 4-column grid of 9 sample PNGs; click → modal with full-size + close.
- **AG Grid SSRM** — any dashboard with a Table (e.g. bab4). Scroll a large table; DevTools Network shows sequential POSTs to `/dashboards/render_table/...` with `start` advancing. Filter changes purge and reload from `start=0`.

### New in Batch 2
- **Map** — ampliseq community dashboard `646b0f3c1e4a2d7f8e5b8cb3` (component index `9d34a1e4-b699-4278-a3e8-cc08a92305b1`). Expect a `carto-positron` (or `carto-darkmatter` in dark mode) tile layer with sample points; scrollZoom + pan work; dark-mode toggle flips `map_style`.
- **JBrowse** — **no existing dashboard** has `component_type: "jbrowse"` in seeds or YAMLs. To test: add one to a YAML, regenerate the seed, reload. The renderer expects JBrowse 2 at `localhost:3000` and its session config server at `localhost:9010`. If those services are down, the renderer surfaces a clean 503 error (no white screen).
- **MultiQC (regular plots)** — ampliseq dashboards `dashboard_community.json` and `dashboard_multiqc.json` (in 2.14.0 and 2.16.0). Each MultiQC tile renders a Plotly figure with the MultiQC logo overlay. Loading spinner during fetch; red error chrome on failure. Theme follows light/dark.
- **MultiQC (general-stats)** — currently a placeholder Paper saying "General Stats not yet ported". This is the next port to ship.

### Console + network sanity check
- Open DevTools on each new dashboard, watch for:
  - No red console errors (warnings about Plotly bundle size are expected)
  - Network shows expected `/render_*` POSTs for figure-style components
  - `/render_image_paths` GET for image grid
  - No 401/403 (anonymous mode + admin works)

## Known gaps / next steps

| Item | Status | Effort |
|---|---|---|
| MultiQC sample-aware filtering (patch_multiqc_figures) | route accepts filters but doesn't apply them yet | ~0.5 day |
| MultiQC general-stats table (Tanstack Table + violins) | placeholder shipped; refactor of `general_stats.py:build_general_stats_content` needed to expose JSON shape | ~1-2 days |
| GeoJSON access tokens for non-public Map choropleths | route passes `access_token=None` | <1 hour once propagation pattern decided |
| Auto-generated Python wrappers (replace hand-written) | hand-written still used | low priority |
| Dash editor consumes shared wrappers | unchanged from MVP plan | 2-3 days, separate session |

## Verified static checks

- `npm run build` (viewer): ✅ green, 858 modules, 6.1 MB raw / 1.8 MB gzipped JS
- `ruff format` + `ruff check` on `routes.py`: ✅ clean
- `python3 -c "import ast; ast.parse(...)"` on `routes.py`: ✅ parses
- `ty check depictio/api/v1/endpoints/dashboards_endpoints/routes.py`: 3 pre-existing errors near line 3489 (project_resolved type), zero from new code

### Pre-commit `ty-check-models-api-dash-cli` was SKIPped on both commits

The hook fails on **191 pre-existing diagnostics** in unrelated files — biggest cluster is `depictio/models/yaml_serialization/validation.py:14` importing a non-existent `MVPDashboard`. This count is identical with or without the Batch 1+2 diffs. Suggest a follow-up issue: "Fix pre-existing ty diagnostics blocking pre-commit".

## Rollback (if needed)

The Dash viewer at `/dashboard/{id}` is untouched. To roll back the React viewer to the MVP, `git revert a6828fb8 c80357d3`. The shared package and the `/dashboard-beta/{id}` mount stay live; only the new component types fall back to "not yet ported" placeholders.
