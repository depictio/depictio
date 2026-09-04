# xy spike (issue #945)

Evidence for the evaluation of [reflex-dev/xy](https://github.com/reflex-dev/xy)
(Rust compute + WebGL2 charting, alpha) as an additive renderer for Depictio's
large point plots. **Read the write-up first:**
[`docs/design/rfc-reflex-xy-evaluation.md`](../../docs/design/rfc-reflex-xy-evaluation.md).

Everything here is spike/demonstration code — nothing is wired into the app,
and nothing under `depictio/` or `packages/` changed.

## Layout

| Path | What |
|---|---|
| `CLIENT_NOTES.md` | Dissection of the xy 0.0.6 browser client (mount API, events, GL topology, density tier) — version-pinned observations |
| `phase1_payloads.py` / `phase1_browser.py` / `phase1b_browser.py` | Reflex-free mount + selection + GL-topology verification (→ `results/phase1*.json`) |
| `gen_data.py` | Synthetic Delta tables at 100k/1M/10M (canonical `benchmark/datagen.py` schema) + real-read-path check |
| `bench_python.py` | Server-side build/serialize matrix (→ `results/python_timings.csv`) |
| `gen_browser_assets.py` / `bench_browser.py` | Browser render + interaction matrix (→ `results/browser_timings.csv`) |
| `phase5_theming.py` | `.dark` + `--chart-*` runtime theming + native `to_png()` (→ `results/phase5_theming.json`, `theme_*.png`) |
| `poc/` | React 18 wrapper PoC (`XyChart.tsx`), esbuild-bundled, fed via `load_deltatable_lite` |
| `phase6_verify.py` | Drives the PoC: selection → InteractiveFilter emission, theme toggle (→ `results/phase6_poc.json`, `poc_*.png`) |
| `results/` | Committed evidence (CSVs, JSON findings, screenshots); `results/raw/` + `data/` are gitignored/regenerable |

## Reproduce

```bash
# from the repo root; uv + node on PATH; Playwright Chromium preinstalled
uv venv --python 3.12.9 venv && uv pip install --python venv/bin/python -e ".[dev]"
uv pip install --python venv/bin/python xy deltalake playwright
(cd dev/xy_spike/harness && npm i)                  # plotly.js-dist-min@2.35.3
venv/bin/python dev/xy_spike/gen_data.py
venv/bin/python dev/xy_spike/phase1_payloads.py
venv/bin/python dev/xy_spike/phase1_browser.py
venv/bin/python dev/xy_spike/phase1b_browser.py
venv/bin/python dev/xy_spike/bench_python.py
venv/bin/python dev/xy_spike/gen_browser_assets.py
venv/bin/python dev/xy_spike/bench_browser.py
venv/bin/python dev/xy_spike/phase5_theming.py
(cd dev/xy_spike/poc && npm i \
  && npx esbuild main.tsx --bundle --outfile=app.js --jsx=automatic --minify \
  && ../../../venv/bin/python gen_poc_assets.py)
venv/bin/python dev/xy_spike/phase6_verify.py
```

Scripts import depictio with the same env defaults the test suite uses
(`_env.py`, mirrors `depictio/tests/conftest.py`) and read local Delta tables
via `DEPICTIO_USE_LOCAL_FILES=true` — no Mongo/MinIO/API needed. On a machine
with Playwright's matching Chromium, drop the `executable_path` overrides.

## Honesty notes

- WebGL in the spike container is SwiftShader (software): compare plotly-vs-xy
  ratios, not absolute times. Hardware block: `results/hardware_profile.md`.
- Every result row records how many points were actually serialized/drawn —
  the shipped Plotly path draws a 10k/50k *sample*; xy draws all N.
- `results/dataset_loads.csv` full-load timings include a ~30 s Mongo
  server-selection timeout (no Mongo in the container); `bench_python.py`
  stubs that lookup instead and its `load_s` column is clean.
