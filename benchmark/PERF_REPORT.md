# Depictio — performance report

Single run, current build. 719 of 720 renders succeeded (one transport blip:
`RemoteProtocolError` on a table).

## Setup

| | |
|---|---|
| Dataset | **17,232,000 rows** across 3 linked collections |
| | features 17,221,500 · metrics 10,000 · metadata 500 |
| Size | 0.997 GB raw / 1.492 GB Delta |
| Host | Apple M1 Max, 10 CPU, 32 GB — Colima VM 8 vCPU / 20 GB |
| API container | **4 CPU, 1 uvicorn worker, dev mode (`--reload`)** |
| Celery | 4 CPU / 4 workers |

The single dev worker matters: a production deploy runs several. These numbers are
pessimistic in that respect.

### Where each render actually ran

Not uniform, and it changes how the per-component table reads. Taken from the
`X-Celery-Path` header on every render, not from the run's label.

| component | path | renders |
|---|---|---|
| figure | **offloaded to Celery** | 197 of 198 (1 inline) |
| table, advanced viz, card, interactive | **inline on the API process** | 521 |

Figures offloaded because `offload_size_threshold_bytes` defaults to 50 MB and the source
collection is 1.49 GB — adaptive, not forced (`offload_rendering` is `false`). The other
endpoints have no Celery path at all.

Figures ran in 4 separate Celery worker processes. The rest ran in the API process's
own thread pool — `render_table`, `bulk_compute_cards` and `/advanced_viz/data` are
declared `def`, not `async def`, so FastAPI already moves them off the event loop. They
do run in parallel (Polars releases the GIL), but they share the API container's 4 CPUs
with the event loop itself, while the Celery workers get their own 4.

Only figures offload because `build_figure_preview` is the only Celery task the dashboard
render path can dispatch to. `render_figure_endpoint` is `async def` and would otherwise
block the event loop for the whole build; the other three already had a thread pool and
never needed the escape hatch.

`DEPICTIO_CELERY_ENABLED=false` in `docker-compose/.env` is unrelated — it is a Dash-era
flag for dashboard view-mode background callbacks, read only by
`docker-images/run_celery_worker.sh` and the Helm configmaps. No Python reads it, and it
does not gate this offload path.

## Opening a dashboard

Every component fetched at once, the way the page does it.

| components (timed) | cache | first component | first chart | all components |
|---|---|---|---|---|
| 4 (9) | cold | 96 ms | 628 ms | 3.7 s |
| 4 (9) | warm | 65 ms | 522 ms | 2.2 s |
| 8 (13) | warm | 88 ms | 129 ms | 1.7 s |
| 16 (21) | warm | 141 ms | 141 ms | 3.3 s |
| 32 (37) | warm | 214 ms | 214 ms | 14.3 s |

*first chart* = first figure or advanced viz on screen. From 8 components up, the first
thing to land **is** a chart. *cold* = first ever open, every server cache empty.

## Changing a filter

Across 3 linked collections. No round is a cache hit — each applies a value no earlier
round used.

| components | starts responding | fully caught up | worst round |
|---|---|---|---|
| 4 | 618 ms | **1.1 s** | 2.4 s |
| 8 | 529 ms | **1.8 s** | 3.3 s |
| 16 | 567 ms | **3.3 s** | 4.1 s |
| 32 | 843 ms | **8.1 s** | 10.3 s |

## Latency per component

All 718 successful renders, every phase.

| component | p50 | p95 |
|---|---|---|
| interactive | 74 ms | 181 ms |
| card | 124 ms | 789 ms |
| figure · scatter | 486 ms | 3.8 s |
| figure · histogram | 775 ms | 3.3 s |
| table | 780 ms | 2.0 s |
| advanced viz · volcano | 931 ms | 5.5 s |
| advanced viz · MA | 1.1 s | 5.4 s |
| figure · box | 1.2 s | 7.9 s |

p50 = median, the typical case. p95 = 95th percentile, the tail.

## Efficiency

| | |
|---|---|
| Figure renders materialising **zero rows** | **125 of 197** (box, histogram) |
| Largest frame held in memory, any render | **1.5 MB** |
| API process peak RSS | 3.2 GB (whole-run high-water mark) |
| Cross-collection filter translation | **69 ms** median, 152–193 values out |

Rows pulled into memory, median per render:

| component | rows |
|---|---|
| box, histogram | **0** — computed as an aggregation over the Delta scan, exact |
| table | 100 |
| scatter | 40,000 |
| volcano, MA | 5,741,054 (max 17,221,500) |

## Caveats

- The 32-component **warm** full load (14.3 s) is slower than its cold (7.9 s). Unexplained,
  one sample each — do not build a scaling claim on the 32 column.
- Only the 4-component cold row is a true first visit; 8/16/32 share one ingested project,
  so their caches were already warm. Those rows are excluded here.
- "Cold" = server caches empty. Delta files may still be in the OS/MinIO page cache, so it
  is a lower bound on a genuinely cold machine.
- No before/after claim: the pre-fix baseline was measured on a differently loaded machine.

---

# What we improved

- **Charts no longer disappear on dense dashboards.** Past ~5 plots the browser was running
  out of graphics contexts and silently blanking the oldest ones. Depictio now budgets them
  and falls back to a lighter renderer instead of showing nothing.
- **Box plots and histograms never load the data.** They are computed as a single
  calculation over the stored file. The result is exact — the rows just never leave storage.
- **Big tables no longer slow down as you page through them.** Deep pages used to load
  everything up to that point.
- **Sorting is turned off above a size where it would stall**, and the column header says so
  instead of silently returning unsorted rows.
- **Advanced visualisations now sample the whole dataset** instead of reading the first rows
  and calling it a sample. They also report the true row count — one chart was saying
  "100,000 rows" for a 17-million-row table.
- **The benchmark measures what a user feels**: when the first chart appears, not just when
  the last component finishes — and separates a first visit from a revisit.
