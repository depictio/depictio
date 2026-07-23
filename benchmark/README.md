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
| Connect mode | `--connect` | `independent,joins,links,links-adversarial` |
| Celery offload | `--server-mode` | run twice (see below) |

### The two link topologies

Cross-filter cost is dominated by the **cardinality of the join key**, not by the
size of the collections, so the harness ships two link datasets and never mixes
them:

| `--connect` | dataset | join key | what it describes |
| --- | --- | --- | --- |
| `links` | `datagen_linked.py` — `metadata` / `metrics` / `features` | `sample_id`, ~`--samples` (default 500) distinct values | a realistic project |
| `links-adversarial` | `datagen.py` — N symmetric collections | `individual_id`, **unique per row** (millions) | a deliberate worst case |

`links` builds three collections at three grains — one row per sample, one per
(sample, tool), one per (sample, feature) — connected in a star *and* a chain:

```
metadata ──sample_id──> metrics ──sample_id──> features
    └──────────sample_id──────────────────────────┘
```

so one project exercises 1-hop propagation, the 2-hop chain
(`filter_links._link_paths` / `_walk_link_path`), and two competing routes to the
same target. Rows follow the size tier through the per-sample fan-out; the join
key does not — that is the property the whole dataset exists to hold, and it is
what keeps a filter translation in the hundreds of values.

`links-adversarial` is the previous default. Its join key is unique per row, so
filtering a 3-value column translates into millions of values, materialised as a
Python list and sent over HTTP. It found real bugs (an eager full-table read in
link resolution, a timeout degrading into unfiltered data, an empty resolution
rendering every row) and is kept for that — but **its cross-filter numbers must
never be published as "the cost of cross-filtering"**. The report flags any
translation returning more than 10 000 values as `⚠️ pathological` — past that,
the value list itself is the problem, whatever the machine.

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

To measure what a user waits for after moving a filter, add `--filter-rounds`
(with `--dashboard-load`, so the dashboard is warm first):

```bash
python -m benchmark.cli run \
  --cli-config ~/.depictio/CLI.yaml --server-mode celery_off \
  --sizes 1gb --dcs 2 --components 25 --connect joins,links \
  --visu figure,table,advanced_viz --repeats 2 \
  --dashboard-load --filter-rounds 3
```

On the linked topology this runs **one sweep of rounds per filter origin**: a
filter on `metadata.condition` (translated across 1 and 2 links before `features`
can be narrowed) and one on `features.feature_class` (applied natively, no
propagation). They are reported apart — they are different mechanisms, and their
mean describes neither. Each round also probes every link route directly against
`POST /links/{project}/resolve` and records how many values the translation
produced (`kind="link_resolution"`).

## Stating the hardware — this is part of the result

A latency without the machine and the container limits it was taken on cannot be
compared to anything, including a later run of the same harness. Pass
`--profile-label`; the harness records host / Colima VM / per-service CPU limits
into `hardware_profile.json`, stamps every row with the label, and puts the block
at the top of `REPORT.md` and in `blog_metrics.json`.

Boot the stack with the limits you intend to report, then label the run with
them:

```bash
BENCH_API_CPUS=4 BENCH_API_WORKERS=4 \
BENCH_CELERY_CPUS=4 BENCH_CELERY_WORKERS=4 \
BENCH_MONGO_CPUS=2 \
docker compose -p ${COMPOSE_PROJECT_NAME} --env-file .env.instance \
  -f docker-compose.dev.yaml -f docker-compose.override.yaml \
  -f docker-compose.bench.yaml --profile dev up -d

python -m benchmark.cli run --cli-config ~/.depictio/CLI.yaml \
  --server-mode celery_on --profile-label mbp-m1max-4cpu \
  --sizes 1gb --connect links --components 25 \
  --visu figure,table,advanced_viz --repeats 2 \
  --dashboard-load --filter-rounds 3
```

The limits are read from the same `BENCH_*` variables `docker-compose.bench.yaml`
uses, so export them for the benchmark process too (or pass the matching flags) —
otherwise the profile records the compose *defaults*, not what the stack is
actually running under.

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

## A/B'ing a server-side setting

The same two-run mechanism works for any setting fixed at process start. Boot,
run one half with a label, reboot with the setting flipped, run the other half
with `--reuse-ingest` so both halves measure the same ingested data:

```bash
# Half A — exact box quartiles (the current default)
BENCH_BOX_SAMPLE_ROWS_PER_GROUP=0 docker compose … up -d
python -m benchmark.cli run --cli-config ~/.depictio/CLI.yaml \
  --server-mode box_exact --sizes 1gb --components 25 --visu figure --repeats 2

# Half B — per-group sampled quartiles
BENCH_BOX_SAMPLE_ROWS_PER_GROUP=10000 docker compose … up -d
python -m benchmark.cli run --cli-config ~/.depictio/CLI.yaml \
  --server-mode box_sampled --sizes 1gb --components 25 --visu figure \
  --repeats 2 --reuse-ingest
```

`box_sample_rows_per_group` is off by default because the measured 3.7x win at
17 M rows was taken on warm local parquet: sampling trades a sort for an *extra
scan*, and on S3-backed Delta the read can cost more than the sort it removes.
This is the run that settles it. Compare `visu == "box"` latency across the two
`server_mode` halves, and check the quartiles agree — the whiskers come from the
exact pass either way, so only q1/median/q3 can move.

## Advanced viz: the payload picks the reduction

`POST /advanced_viz/data` chooses how to reduce a large frame from the `viz_kind`
in the request body, so the harness sends the same `viz_kind` / `roles` / `tail`
fields the React renderers do (`_advanced_viz_policy` in `runner.py`). Omitting
them would time the uniform-sample path that no renderer takes any more. Each
render records the policy the server actually applied (`sampling_policy`, from
`X-Sampling-Policy`), because a `tail` and a `hash` render of the same component
are not the same measurement: the tail keeps every significant row and pays a
predicate for it.

## Layout

| File | Role |
| --- | --- |
| `matrix.py` | dimensions + expansion into cells |
| `datagen.py` | symmetric Polars data generation (10 MB … 10 GB, no OOM) — also the adversarial links dataset |
| `datagen_linked.py` | the realistic 3-collection topology (bounded join-key cardinality) |
| `profile.py` | host / VM / container-limit profile stamped onto every row |
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

## The three render phases

They answer different questions and must not be averaged together:

| phase | flag | what it measures |
| --- | --- | --- |
| sequential | (default) | one component on an idle server — the cost of the render itself |
| dashboard load | `--dashboard-load` | every component at once, **unfiltered** — opening the page cold |
| filter round | `--filter-rounds N` | every component at once, **filtered**, on an already-warm dashboard — what a user waits for after moving a filter |

The filter round is the closest thing to the interactive experience, and it is
deliberately the strictest:

- It runs **last**, after every DC has been touched, so it times a filter change
  rather than a first Delta read.
- Each round applies a value **none of the previous rounds used**
  (`FilterPlan.values` in `configgen.py`; the runner caps the round count at the
  number of distinct values). Re-applying a value is answered by the filtered
  frame cache and would time the cache, not the filter.
- Requests go through a pool the width of the viewer's `fetchQueue` limit
  (`packages/depictio-react-core/src/fetchQueue.ts`). Firing all N at once would
  measure a client that doesn't exist and would hide the queueing.

It emits `kind="filter_round"` (aggregate: `time_to_first_ms` /
`time_to_last_ms`) plus one `kind="render"` row per component stamped
`filtered=True, concurrent=True`.

**This is a server-side number.** It ends when the last HTTP response lands, not
when the browser has painted: `JSON.parse` and the Plotly / AG Grid build happen
afterwards on a single main thread. The in-browser figure is larger, and the gap
between the two is the client-side cost.

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
- Dashboard cold-load (all components at once) → worker-pool contention / queue
  wait (`/celery/stats`); concurrency/saturation (N simultaneous viewers).
- Tail latencies (P95/P99); screenshot/thumbnail generation time.
