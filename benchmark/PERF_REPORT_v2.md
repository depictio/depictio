# Depictio — performance report v2

Single run, current build. 1,434 of 1,482 renders succeeded. The 48 failures are
all figure offloads hitting the 30 s Celery ceiling; they are a result, not noise,
and are described under *Where the failures are*.

`PERF_REPORT.md` (v1) is kept as it stands. It describes a different dataset and a
different dashboard, see *Why the numbers moved*.

## Setup

| | |
|---|---|
| Dataset | **12,019,500 rows** across 3 linked collections |
| | features 12,011,000 · metrics 8,000 · metadata 500 |
| Size | 1.025 GB raw / 1.429 GB Delta |
| Host | Apple M1 Max, 10 CPU, 32 GB, Colima VM 8 vCPU / 20 GB |
| API container | **4 CPU, 1 uvicorn worker, dev mode (`--reload`)** |
| Celery | 4 CPU / 4 workers, `offload_timeout_seconds` 30.0 |

Same hardware profile as v1. The single dev worker matters: a production deploy
runs several, so these numbers are pessimistic in that respect.

Ingest was reused (`--reuse-ingest`) against the already-loaded project, so this
run reports no ingest timings. v1 did the same.

### Where each render actually ran

Taken from the `X-Celery-Path` header on every render, not from the run's label.

| component | path | renders |
|---|---|---|
| figure | **offloaded to Celery** | 225 |
| table, advanced viz, card, interactive | **inline on the API process** | 1,209 |

Unchanged from v1 in structure. Figures offload because `build_figure_preview` is
the only Celery task the dashboard render path can dispatch to;
`render_figure_endpoint` is `async def` and would otherwise block the event loop
for the whole build. `render_table`, `bulk_compute_cards` and
`/advanced_viz/data` are declared `def`, so FastAPI already moves them to a thread
pool. They run in parallel (Polars releases the GIL) but share the API
container's 4 CPUs with the event loop, while the Celery workers get their own 4.

## Opening a dashboard

Every component fetched at once, the way the page does it. *first chart* = first
figure or advanced viz on screen. *cold* = server caches empty (the Redis cache
was flushed before this run).

| components (fired) | cache | first component | first chart | all components | rendered |
|---|---|---|---|---|---|
| 4 (18) | cold | 155 ms | 1.2 s | 30.3 s | 16/18 |
| 4 (18) | warm | 133 ms | 218 ms | **816 ms** | 18/18 |
| 8 (22) | cold | 162 ms | 184 ms | 4.2 s | 21/22 |
| 8 (22) | warm | 140 ms | 1.5 s | 19.9 s | 22/22 |
| 16 (30) | cold | 135 ms | 190 ms | 3.3 s | 30/30 |
| 16 (30) | warm | 151 ms | 243 ms | 3.1 s | 30/30 |
| 30 (44) | cold | 224 ms | 4.3 s | 30.9 s | 40/44 |
| 30 (44) | warm | 270 ms | 270 ms | 6.2 s | 44/44 |

The two 30 s walls are **timeouts, not slow renders**: the last component never
arrived, and the row records the ceiling. Read those two rows as failures.

The page starts showing something in 133 to 270 ms regardless of size, and that
number barely moves between 4 and 30 components. What scales is the tail.

## Changing a filter

Across 3 linked collections. No round is a cache hit, each applies a value no
earlier round used. Fired through a pool of 4, matching the viewer's fetch queue.

| components | starts responding | fully caught up | worst round | complete rounds |
|---|---|---|---|---|
| 4 | 154 ms | **1.7 s** | 1.9 s | 9/9 |
| 8 | 93 ms | **2.0 s** | 3.0 s | 9/9 |
| 16 | 214 ms | **4.1 s** | 33.5 s | 7/9 |
| 30 | 186 ms | **6.3 s** | 92.9 s | 5/9 |

*fully caught up* is the median over rounds where every component landed. Rounds
that lost a figure to the timeout are excluded from that column and counted in
the last one, otherwise the median would silently describe a partial dashboard.

By the collection the filter starts on, over complete rounds:

| filter origin | rounds | median catch-up | worst |
|---|---|---|---|
| features | 11 | 2.0 s | 7.7 s |
| metrics | 9 | 2.3 s | 4.5 s |
| metadata | 10 | 2.4 s | 6.5 s |

All three origins now narrow the whole dashboard, and they cost about the same.
That is the point of the bidirectional link graph: a filter starting on the
12 M-row feature matrix is no more expensive than one starting on the 500-row
sample sheet, because both resolve to the same few hundred sample ids before any
data is touched.

Link translation itself: **25 ms** median, 152 to 193 values out, across 36
probes against `POST /links/{project}/resolve`.

## Latency per component

All 1,434 successful renders, every phase. p50 = median, p95 = 95th percentile.

| component | p50 | p95 |
|---|---|---|
| interactive | 11 ms | 132 ms |
| card | 119 ms | 1.3 s |
| table | 222 ms | 1.2 s |
| figure · histogram | 271 ms | 4.3 s |
| figure · bar | 310 ms | 7.4 s |
| figure · line | 696 ms | 3.4 s |
| figure · box | 709 ms | 7.0 s |
| figure · scatter | 1.1 s | 4.2 s |
| advanced viz · dot plot | 691 ms | 5.4 s |
| advanced viz · volcano | 822 ms | 2.6 s |
| advanced viz · MA | 876 ms | 2.8 s |
| advanced viz · stacked taxonomy | 905 ms | 4.1 s |
| advanced viz · DA barplot | 917 ms | 5.5 s |
| advanced viz · manhattan | 979 ms | 6.0 s |
| advanced viz · sankey | 1.0 s | 4.7 s |
| advanced viz · QQ | 1.1 s | 3.4 s |
| advanced viz · sunburst | 1.1 s | 3.5 s |
| advanced viz · lollipop | 1.2 s | 4.6 s |

## Efficiency

| | |
|---|---|
| Figure renders materialising **zero rows** | **114 of 225** (box, histogram, bar) |
| Largest frame held in memory, any render | **1.57 MB** (median 439 KB) |
| API process peak RSS | 3.47 GB (whole-run high-water mark) |
| Cross-collection filter translation | 25 ms median, 152 to 193 values out |

Rows pulled into memory, median per render:

| component | rows |
|---|---|
| box, histogram, bar | **0**, computed as an aggregation over the Delta scan, exact |
| table | 100 |
| scatter, line | 40,000 |
| every advanced viz kind | 6,005,500 (max 12,011,000) |

`bar` joins box and histogram on the zero-row path; in v1 only box and histogram
did. Every advanced viz kind reads the full matrix and samples from it, which is
what makes their p95 the widest on the page.

## Where the failures are

All 48 are figure renders: 46 timed out at the 30 s Celery ceiling, 2 lost their
worker to a SIGKILL. No table, card, advanced viz or interactive render failed.

| phase | 4 comp | 8 comp | 16 comp | 30 comp |
|---|---|---|---|---|
| dashboard open (cold) | 2 | 1 | 0 | 4 |
| sequential | 2 | 4 | 0 | 4 |
| filter round | 0 | 0 | 3 | 28 |

Two separate causes, and they should not be read as one number:

- **The first 4 are startup, not load.** Renders #0, #3, #18 and #21 are the run's
  first four figures, all timing out while the Celery worker re-established its
  broker connection after Redis was recreated just before the run. From render
  #36 onward offloads succeed in 71 to 433 ms. Discount these.
- **The other 44 are saturation**, 28 of them in the 30-component filter rounds.
  Four Celery workers serving up to 14 concurrent figure offloads over a
  12 M-row table do not clear the queue inside 30 s, so the slowest are cut off
  at the ceiling rather than finishing late.

The ceiling is a configured limit (`offload_timeout_seconds`, 30.0), not a crash.
Raising it converts these into slow renders rather than failures, which is a
product decision: a user staring at a spinner for 40 s is not obviously better
served than one shown an error.

## Why the numbers moved since v1

v1 reported 17,232,000 rows. Nothing was made smaller. The row got wider and the
byte target did not move.

The generator sizes the `features` collection to ~1 GB of CSV and derives
`features_per_sample = 1 GB / bytes_per_row / n_samples`. The features schema
gained four columns in `8728208bd` so the diverse dashboard could bind manhattan,
lollipop, dot plot and stacked taxonomy:

```
v1 (7 cols):  sample_id,feature_id,expression,effect_size,neg_log10_p,mean_expression,feature_class
v2 (11 cols): … ,feature_class,chr,position,frac_expressing,rank
```

Calibrated CSV width went 62.35 to 89.40 bytes/row (+43%), so the row count fell
by the same ratio: 34,443 to 24,022 features per sample.

`metrics` fell separately, 10,000 to 8,000 rows, when the flat five-tool pool
became two four-tool panels (`_TOOL_PANELS`). That was not a size decision. It is
what makes a `tool` filter select a strict subset of samples instead of all of
them, which the reverse links need in order to translate anything.

| | v1 | v2 |
|---|---|---|
| features/sample | 34,443 | 24,022 |
| features rows | 17,221,500 | 12,011,000 |
| metrics rows | 10,000 | 8,000 |
| metadata rows | 500 | 500 |
| **total** | **17,232,000** | **12,019,500** |
| features columns | 7 | 11 |
| raw CSV | 1.0 GB | 1.0 GB |
| Delta | 1.492 GB | 1.429 GB |

**Why v1 measured the old schema after the columns had landed.** The `.manifest`
idempotency gate compared only `size_bytes` and `n_samples`. The CSVs already on
disk satisfied both, so the widened generator never regenerated them: the v1 run
read seven-column data under eleven-column code. `SCHEMA_VERSION` (added in
`7617e48ca`) closed that hole. The marker now also records what the generator
*writes*, not just how much of it, so a generator change invalidates data on disk.

## Caveats

- **Do not read v1 to v2 as a code delta.** The hardware profile is identical,
  but both the dataset and the dashboard changed. v2's 30-component cell fires
  **44** components against v1's 32-component cell firing 37, because the left
  panel went from 4 filters to 12 and the cards became multi-metric
  (`box_plot_stats` quantiles and `top_n` group-bys against the filtered frame).
  v2's largest dashboard is heavier than v1's despite the smaller label.
- The 8-component **warm** full load (19.9 s) is slower than its cold (4.2 s),
  with all 22 components landing in both. Unexplained, one sample each. Do not
  build a scaling claim on that row.
- Only the 4-component cold row is a true first visit. 8/16/30 share one ingested
  project, so their caches were already populated.
- "Cold" means server caches empty. Delta files may still be in the OS or MinIO
  page cache, so it is a lower bound on a genuinely cold machine.
- v1 remains a valid measurement of the seven-column schema. Its byte-level and
  wall-clock figures are broadly comparable to v2. Its per-render row counts are
  not.

## Notes from the run

Redis had no `maxmemory` and no eviction policy, and grew until the 2 GB cgroup
OOM-killed it, three times, aborting three runs before this one. Because the same
Redis is the cache (db 0) and the Celery broker (db 1), each kill took figure
offload down with it. `redis_max_memory_mb` and `redis_db` are declared in
`settings_models.py` and read by nothing.

`docker-compose.bench.yaml` now sets `--maxmemory 1500mb --maxmemory-policy
volatile-lru`. `volatile-lru` rather than `allkeys-lru` because the policy is
server-wide and every cache write goes through `setex` (`api/cache.py:123`), so
cache entries carry a TTL and broker keys do not. Only the cache can be evicted.

The dead settings are a real bug outside the benchmark: any deployment relying on
`DEPICTIO_CACHE_REDIS_MAX_MEMORY_MB` has an uncapped Redis. Not fixed here.
