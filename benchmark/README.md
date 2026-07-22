# Depictio performance benchmark harness

Generate synthetic datasets + matching project/dashboard configs across a
matrix, run them against a live Depictio stack (ingest → render every
component), and report the collected timings.

Nothing large is committed: datasets and results live under
`benchmark/output/` (gitignored) and are **generated live before a run**.

## What it measures

The matrix combines the dimensions from the original request:

| Dimension | Flag | Values |
| --- | --- | --- |
| Components per tab | `--components` | `1,5,10,25,50` |
| Connected data collections | `--dcs` | `1,2,5` |
| Size per DC | `--sizes` | `10mb,100mb,1gb,5gb,10gb` |
| Visualization type | `--visu` | `figure,table,advanced_viz` |
| Connect mode | `--connect` | `independent,joins,links` |
| Celery offload | `--server-mode` | run twice (see below) |

The canonical metric per render is **HTTP wall-clock + the `X-Celery-Path`
header** (`inline` vs `offloaded`). Offloaded renders can be enriched with the
durable `duration_ms` from the Mongo `task_events` ledger (`GET
/monitoring/tasks`, admin token); the `load_ms`/`build_ms` split is in the
API/worker logs.

## Prerequisites

- A running Depictio stack (API + worker + Redis + Mongo + S3), e.g.
  `docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up`.
- A depictio CLI config with a valid token (`~/.depictio/CLI.yaml`).
- Python deps from the project env (Polars, NumPy, httpx, Typer; matplotlib is
  optional — plots are skipped if absent).

## Usage

```bash
# 1. (optional) pre-stage large datasets + configs without a server
python -m benchmark.cli generate --sizes 100mb,1gb --dcs 2 --connect joins

# 2. run the matrix — CELERY OFF half
#    (boot the stack with DEPICTIO_CELERY_OFFLOAD_RENDERING=false and a high
#     DEPICTIO_CELERY_OFFLOAD_SIZE_THRESHOLD_BYTES so figures/tables render inline)
python -m benchmark.cli run \
  --cli-config ~/.depictio/CLI.yaml \
  --server-mode celery_off \
  --sizes 10mb,100mb --components 5,25 --dcs 2 --connect joins,links --visu figure,table

# 3. restart the stack with DEPICTIO_CELERY_OFFLOAD_RENDERING=true, then:
python -m benchmark.cli run \
  --cli-config ~/.depictio/CLI.yaml \
  --server-mode celery_on \
  --sizes 10mb,100mb --components 5,25 --dcs 2 --connect joins,links --visu figure,table

# 4. build results.csv + REPORT.md + plots
python -m benchmark.cli report

# 5. build blog_metrics.json + BLOG_SNIPPET.md (absolute numbers, no baseline)
python -m benchmark.cli blog-metrics
```

**Use `--components 25` at 1 GB.** The report withholds a verdict below 20
successful renders per size (a p95 over a handful of points is the max of a tiny
sample, not a tail), so a 5-component run at 1 GB reports `n=1, insufficient`.

`all` chains run + report for one server config.

## Why Celery on/off needs two runs

`should_offload_render` reads the process-global `settings.celery`, fixed at API
startup — it cannot be flipped mid-process. So the harness runs the whole matrix
once per server config and stamps each row with (a) the `--server-mode` label
you pass and (b) the authoritative per-render `X-Celery-Path` header. Compare the
two halves in the report.

**Note:** `advanced_viz` volcano/ma render through `POST /advanced_viz/data`; the
heavy advanced-viz kinds (embedding/heatmap/upset/…) always use the Celery job
pattern regardless of the offload flags, so they only participate meaningfully in
the "celery on" half.

## Layout

| File | Role |
| --- | --- |
| `matrix.py` | dimensions + expansion into cells |
| `datagen.py` | Polars chunked/sharded data generation (10 MB … 10 GB, no OOM) |
| `configgen.py` | emit `project.yaml` (DCs + joins/links, static IDs) + `dashboard.yaml` |
| `runner.py` | ingest via CLI, discover components, POST renders, collect metrics |
| `metrics.py` | result schema, percentiles, monitoring-ledger enrichment |
| `report.py` | aggregate → `results.csv` + `REPORT.md` + PNG plots |
| `blog_metrics.py` | → `blog_metrics.json` + `BLOG_SNIPPET.md` for write-ups |
| `cli.py` | Typer entrypoint (`generate`/`run`/`report`/`blog-metrics`/`all`) |

## What each component type costs

Every component on the generated dashboard is timed, including the two that were
previously skipped:

| type | endpoint | note |
| --- | --- | --- |
| figure | `render_figure` | reducing visus (box/histogram/density/bar) are answered by a Polars aggregation — `X-Rows-Loaded: 0` |
| table | `render_table` | one AG Grid block |
| advanced_viz | `advanced_viz/data` | dominated by payload transport, not compute |
| card | `bulk_compute_cards` | timed **filtered and unfiltered** — unfiltered is served from precomputed specs, filtered is the path that has to touch the data |
| interactive | `deltatables/unique_values` | MultiSelect option list (the per-mount cost). RangeSliders read precomputed specs and never touch Delta, so they aren't timed |

## Reading the numbers

`X-Rows-Loaded` / `X-Aggregated` are what make a latency figure interpretable —
they say whether a render was fast because the work was small or because the work
was avoided. Keep the cache regimes apart when quoting anything: `dc_first_touch`
marks the render that paid the cold Delta read, `concurrent` marks renders fired
together by a dashboard load. Averaging cold with warm describes neither.

## What else could we measure? (roadmap)

Beyond render latency the harness is positioned to add:

- Ingestion / Delta-write throughput per size (via the `IngestionRun` ledger).
- Delta read cold vs warm (`load_ms`; Redis frame-cache hit ratio + speedup).
- Peak RSS during ingest and render — the real risk at 5–10 GB / OOM ceiling.
- Storage footprint: Delta/parquet vs raw CSV (compression ratio).
- The **offload crossover** DC size where offloaded beats inline — directly
  calibrates `offload_size_threshold_bytes`.
- Cross-filter latency as #interactive × #linked DCs grows.
- Dashboard cold-load (all components at once) → worker-pool contention / queue
  wait (`/celery/stats`); concurrency/saturation (N simultaneous viewers).
- Tail latencies (P95/P99); screenshot/thumbnail generation time.
