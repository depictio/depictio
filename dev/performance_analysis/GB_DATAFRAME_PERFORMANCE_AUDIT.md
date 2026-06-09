# Depictio Performance Audit — Processing Gb / 10–100M-row DataFrames

> Audit of the blockers to processing 10–100M-row (multi-Gb) data collections, across
> API/data-loading, caching, Celery, and the React rendering layer. Each item has concrete
> file:line anchors, a fix direction, and a rough effort estimate (S/M/L).
> Infra constraints: Redis & Celery already exist; prefer no *new* infra dependencies;
> scaling CPU/RAM is acceptable.

## Architecture reality check (CLAUDE.md is stale on this)

- The frontend is now **React** (`packages/depictio-react-core/`), served by FastAPI.
  **Dash has been removed** (`depictio/dash/app.py` no longer exists). Figures are built
  server-side in Python (Plotly), serialized to JSON, and rendered by React
  (`FigureRenderer.tsx`, `TableRenderer.tsx`). The `depictio/dash/CLAUDE.md` guidance no
  longer reflects the runtime.
- Stack confirmed: FastAPI + Beanie/Mongo, Polars + Delta Lake + S3/MinIO, Celery (Redis
  broker DB1 / result DB2), Redis cache (DB0, pickle-serialized), React/AG-Grid frontend.

## What's already good (do NOT touch)

- **Table rendering**: AG-Grid `infinite` row model, server-side pagination capped at 500
  rows/req, lazy mount via IntersectionObserver — correct for Gb-scale tables
  (`TableRenderer.tsx`, `DashboardGrid.tsx`).
- **Large-DF load path (>1GB)**: `_load_large_dataframe` pushes filters down to the Delta
  scan before `.collect()` (`deltatables_utils.py:894-939`).
- **Advanced-viz compute** (embedding/heatmap/etc.): clean dispatch→poll async pattern via
  Celery with Mongo-backed dedup (`advanced_viz_endpoints/routes.py`, `celery_dispatch.py`).
- **MultiQC cold-start**: returns HTTP 202 + async build on first miss
  (`dashboards_endpoints/routes.py:2916-2963`).

---

## Prioritized Blockers & Fix Roadmap

Severity = impact at 10–100M rows. All paths verified against source.

### P0 — Critical (cheap, high-impact)

1. **Dashboard figure rendering is synchronous by default.**
   `settings_models.py:523` → `offload_rendering=False`. So `/dashboards/render_figure/*`
   builds Polars+Plotly **on the API worker thread**. An 8-figure dashboard on multi-Gb data
   pins API workers for tens of seconds; a few concurrent users make the API unresponsive.
   **Fix:** default `offload_rendering=True` (already plumbed through
   `dashboards_endpoints/routes.py:1895` + `celery_dispatch.offload_or_run`). Effort: **S**.

2. **No downsampling / WebGL before Plotly — full DataFrame becomes trace JSON.**
   `figure_builder.py:93-96` does `df.to_pandas()` on the *entire* filtered frame and passes
   it whole to Plotly Express; no row gate, no `sample()`, no `render_mode='webgl'`. 1M
   scatter points ≈ 50–100MB JSON → browser stalls on parse. This is *the* rendering blocker.
   **Fix:** add a pre-Plotly gate in `create_figure_from_data` — if `df.height >` threshold,
   downsample (Polars `.sample()` or bin/aggregate), and set `render_mode='webgl'` for
   scatter types above a point count. Keep raw frame only for genuinely aggregate plots.
   Effort: **M**.

2b. **Eliminate `df.to_pandas()` entirely — go Polars end-to-end in the figure path.**
   `figure_builder.py:94` converts the *whole* frame to pandas up front, a second full copy
   in RAM on every figure. Confirmed: code uses modern `plotly.express` (`figure_builder.py:11`)
   and `narwhals 1.39.1` is in the lockfile (Plotly ≥5.20) — **px accepts Polars natively via
   narwhals**, so `plot_func(polars_df, …)` (line 270) works unconverted. **Fix:**
   - Remove the blanket `to_pandas()`; pass the Polars frame straight to `px.*`.
   - Port the two pandas idioms: NaN mask (227-231) → `df.filter(pl.col(size_col).is_not_null())`;
     `_col_annotations_json .iloc[0]` (170) → `df[col][0]`.
   - **Heatmap path:** `ComplexHeatmap.from_dataframe` already accepts Polars at the boundary
     (`packages/plotly-complexheatmap/.../heatmap.py:188` → `_to_pandas` at 1035 converts
     internally), so the caller now passes Polars unchanged. A *deep* internal Polars rewrite of
     the `ComplexHeatmap` class (it uses pandas indexing throughout) is a larger, separate effort
     — deferred.
   - **Deferred:** remove the dead `plotly-express==0.4.1` legacy pin from `pyproject.toml`
     (unused — code imports from `plotly` proper). Needs care: there is no direct `plotly` dep,
     so Plotly is pulled transitively; removal requires adding an explicit `plotly` pin +
     regenerating `uv.lock` + checking the dep graph.
   Pairs with #2 to roughly halve figure-path memory. **Status: DONE** (main px path is now
   pandas-free; pin removal + deep heatmap port deferred).

3. **Celery worker concurrency is only 2 (and the `worker_pool` setting is dead config).**
   The worker is launched by `docker-images/run_celery_worker.sh` with `--concurrency`
   (default 2 via `DEPICTIO_CELERY_WORKERS`) and **no `--pool`**, while
   `celery_app.conf.update(...)` is commented out (`celery_app.py:19-25`). So the
   `worker_pool="threads"` / `worker_concurrency=2` fields in `settings_models.py:495-496`
   are **never applied** — the worker actually runs Celery's default **`prefork`** pool. That
   is the right pool for CPU-bound Plotly/scipy work (separate processes, no shared GIL), but
   2 slots throttle throughput and each prefork process holds its own copy of `multiqc.report`
   + cached DFs. **Fix:** raise the worker concurrency (e.g. 4–8, watch RAM since each process
   holds its own DF copies); align the dead settings defaults with reality (`prefork`) to
   avoid confusion. Effort: **S** (config), validate via load.

4. **Establish a benchmark baseline.**
   Reuse the `dev/performance_analysis/` harness and `dev/memory_profiling/app.py`.
   Build a small repeatable bench: a synthetic 50M-row Delta DC, then time/profile
   `load_deltatable_lite` → filter → figure build → JSON size, and table pagination. Capture
   p50/p95 latency, peak RSS, and payload bytes per endpoint. Gates every other fix. Effort: **M**.

### P0/P1 — MultiQC subsystem (worst pain in practice; root cause is NOT dataframe size)

When combining many plots with many ingested reports, the bottleneck is the **MultiQC
library's non-thread-safe global singleton** (`multiqc.report`), not Polars/Delta.

- **M1.** A process-wide lock serializes MultiQC rendering *within each worker process* —
  `create_multiqc_plot` holds `_multiqc_lock` across parse *and* `get_plot`
  (`services/multiqc/figures.py:424`, 260) because `multiqc.report` is global. The worker runs
  `prefork` (see #3), so builds parallelize across processes — but with concurrency 2 only 2
  MultiQC figures build at once, and any inline build in the API process (see #9) serializes
  there. Lever: raise concurrency (#3) + keep builds off the API process (#9).
- **M2.** The entire parsed report is cloudpickle-(de)serialized on every render
  (`figures.py:250`, written at 296). The object holds *all* parsed reports, grows with report
  count, and is re-deserialized for each figure under the lock.
- **M3.** Prewarm fan-out is O(module × plot × dataset × {light,dark}), each a separate
  `create_multiqc_plot` with its own full report restore (`celery_app.py:837-888`) — hence the
  45-min task timeout. The **2× light/dark** multiplier rebuilds the whole figure per theme.
- **M4.** general_stats path is pandas-heavy (`general_stats_payload.py`).

**Where the cost actually is (the "leverage"):** Steady-state *serving* is already cheap — once
figures are prewarmed, the endpoint returns pre-built JSON from Redis/disk
(`multiqc_prerender_store`) without touching `multiqc.report`. The pain ("many plots × many
reports") is in the **build/prewarm/cold path**, where the same expensive work repeats N times.

- **M2 fix — deserialize the report once, not per combo (biggest, cheapest win).** The *report*
  cache key (`figures.py:189`, `_generate_cache_key`) is keyed on `s3_locations` only → the same
  key for every plot in a DC. So each combo re-does `cache.get` + `cloudpickle.loads()` on the
  entire report even though it's already resident in `multiqc.report`.
  *Worked example:* 150 reports → ~120 MB serialized report; one restore ≈ ~2 s
  (cloudpickle.loads ~1.5 s + Redis GET ~0.5 s); 40 plots × 2 themes = 80 combos →
  **80 × ~2 s ≈ 160 s of pure redundant restore per prewarm**. Cold interactive loads hit it too
  (6 components = 6 × 2 s, serialized under the lock).
  **Fix:** add a process-global "resident report key" marker; in `_get_or_parse_multiqc_logs`
  (`figures.py:258-268`) return immediately when the report for this `cache_key` is already
  loaded — skip `cache.get` + `cloudpickle.loads`. Self-invalidates under `_multiqc_lock`; clear
  the marker on `multiqc.reset()` / `_force_reparse`. **After: ~160 s → ~2 s per prewarm.**
  Effort: **S**.
- **Theme 2× — build once, restyle for dark** (`celery_app.py:847`). Halves the build phase. Effort: **S/M**.
- **M1 — process isolation via `prefork`** (each worker its own `multiqc.report`; ties to #3) so
  N DCs build in parallel. Effort: **M/L**.
- **M4 — port the general_stats pandas pipeline to Polars** where cheap. Effort: **M**.

### P1 — High

5. **Cache uses pickle for Polars DataFrames** (`cache.py:76,95`). Slow/memory-heavy; with the
   100MB cap (`settings_models.py:465`) big frames silently aren't cached. **Fix:** Arrow IPC
   (`df.write_ipc`/`pl.read_ipc`); for big frames store to disk/S3 and keep a reference in Redis.
   Effort: **M**.
6. **`.collect()` materializes the full filtered result into worker RAM** (`deltatables_utils.py:934`
   + small path). The ≤1GB "small" path (`1148-1162`) is worse: loads the entire table, caches,
   then filters **in memory** — no pushdown. **Fix:** apply the `_load_large_dataframe` scan-level
   filter+projection to the small path; only `.collect()` what's needed. Effort: **M**.
7. **No column projection in hot render paths.** `select_columns` exists
   (`deltatables_utils.py:1144`) but render/card/analytics endpoints don't pass it. **Fix:** thread
   needed columns from component metadata into `select_columns`. Effort: **M**.
8. **Card aggregation runs synchronously in the request path** (`dashboards_endpoints/routes.py`
   `bulk_compute_cards` ~1690); dedup cache is request-scoped only. **Fix:** offload to Celery
   and/or cache aggregation *results* keyed by `(wf_id, dc_id, filter_fingerprint)`. Effort: **M**.

### P2 — Medium / hardening

9. **MultiQC sync fallback can still block on true cold disk+Redis miss**
   (`dashboards_endpoints/routes.py:~3021` → `create_multiqc_plot`, 30–75s). **Fix:** always 202 +
   async build, never inline. Effort: **S**.
10. **Advanced-viz hard timeouts too low** — UMAP/clustering on 100k×50k can exceed 600s/900s
    (`celery_tasks.py:~400`). **Fix:** size-aware `soft_time_limit` or a dedicated long queue. Effort: **S**.
11. **Per-process in-memory DF cache** (`_dataframe_memory_cache`, `deltatables_utils.py:1182`)
    multiplies RAM across workers, no per-item cap. **Fix:** per-item size cap; lean on Redis/Arrow.
    Effort: **S/M**.
12. **Repeated `collect_schema()` on remote S3 LazyFrames** per load (`deltatables_utils.py:903`).
    **Fix:** cache column list in component/DC metadata. Effort: **S**.
13. **Response compression** — add gzip/brotli middleware for figure/table JSON; pairs with #2. Effort: **S**.
14. **Unbounded local S3 file cache** (`settings_models.py:564-583`), no TTL/eviction. **Fix:** max
    size + LRU eviction. Effort: **S**.

---

## Recommended sequencing

- **Phase 0:** #4 benchmark harness → numbers first (include a many-reports × many-plots MultiQC DC).
- **Phase 1 (quick wins):** #1, #3, #2b, #9, #13 — mostly config/guard/branch changes.
- **Phase 2 (MultiQC):** M2/M3 (parse-once + batched prewarm + theme collapse), then M1 (prefork).
- **Phase 3 (core data path):** #2 figure downsampling/WebGL, #6 lazy collect, #7 projection.
- **Phase 4 (caching & cards):** #5 Arrow serialization, #8 card offload + result caching, M4.
- **Phase 5 (hardening):** #10, #11, #12, #14, and CLAUDE.md update (Dash→React).

## Critical files (anchors)

- `depictio/api/v1/configs/settings_models.py` — offload, worker pool/concurrency, cache caps, timeouts.
- `depictio/api/v1/services/figure/figure_builder.py` — figure build / to_pandas / downsampling gate.
- `depictio/api/v1/deltatables_utils.py` — load_deltatable_lite, small vs large path, in-memory cache.
- `depictio/api/cache.py` — Redis serialization (pickle → Arrow).
- `depictio/api/v1/endpoints/dashboards_endpoints/routes.py` — render_figure, bulk_compute_cards, render_table, multiqc fallback.
- `depictio/api/v1/celery_tasks.py` / `celery_dispatch.py` — task defs, offload helper, timeouts.
- `packages/depictio-react-core/src/components/FigureRenderer.tsx` — client figure consumption (payload size).
- **MultiQC**: `depictio/api/v1/services/multiqc/figures.py`, `general_stats_payload.py`,
  `multiqc_prerender_store.py`, `depictio/api/celery_app.py` (prewarm fan-out ~739-904).

## Verification (per fix)

- Run the #4 benchmark harness before/after each change; compare p50/p95 latency, peak RSS, and
  per-endpoint payload bytes on the synthetic 50M-row DC.
- Figure path (#2): Chrome DevTools Network tab — confirm figure JSON drops from tens of MB to
  <1MB after downsampling; visually confirm plot fidelity.
- Offload (#1/#3): confirm API worker stays responsive under concurrent dashboard loads while
  Celery does the work; check `docker logs` for the worker.
- Memory (#6/#11): watch worker RSS under N concurrent large-DC requests; confirm no OOM.
- Regression: `pytest depictio/tests/ -xvs -n auto`; `ruff format/check`; `ty check`;
  `pre-commit run --all-files`. E2E Cypress for dashboard render correctness.
