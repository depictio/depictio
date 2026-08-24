# Ingest tuning (CLI environment flags)

The CLI ships four opt-in performance flags. All default to **off**, so ingest
behaviour is unchanged unless you set them — each trades memory, CPU or ingest
wall-time for something, and none of those trades should be made unasked.

They live in the `DEPICTIO_INGEST_` namespace, which belongs to the CLI. The
API's own configuration uses per-model prefixes (`DEPICTIO_MULTIQC_`,
`DEPICTIO_S3_`, …) declared in `depictio/api/v1/configs/settings_models.py`; CLI
flags deliberately stay out of those, because an env var that matches a settings
field name would silently drive an unrelated API setting. A test
(`depictio/tests/cli/utils/test_cli_env_flag_namespace.py`) enforces the split.

| Variable | Values | Default | Trades |
|---|---|---|---|
| `DEPICTIO_INGEST_STREAMING_WRITE` | `1` / `true` / `yes` / `on` | off | unstable polars API ⇄ bounded memory |
| `DEPICTIO_INGEST_DC_WORKERS` | integer | `1` (sequential) | CPU + memory ⇄ ingest wall-time |
| `DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS` | integer | `1` (serial) | peak RSS ⇄ MultiQC ingest wall-time |
| `DEPICTIO_INGEST_MULTIQC_PRERENDER` | `1` / `true` / `yes` | off | ingest time + S3 storage ⇄ first dashboard open |

---

## `DEPICTIO_INGEST_STREAMING_WRITE`

Streams the Delta write (`LazyFrame.sink_delta`) instead of materialising the
whole frame in memory first, so a large collection is written in chunks.

Off by default because `sink_delta` is marked unstable in polars 1.41.x. Also
settable per-run with `depictio run --streaming`.

## `DEPICTIO_INGEST_DC_WORKERS`

Number of data collections to ingest concurrently. `1` (the default) is
sequential. The value is clamped to the number of collections and to an internal
cap, so an over-large value degrades to the cap rather than spawning a thread per
collection. A non-integer value logs a warning and falls back to sequential.

## `DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS`

Number of MultiQC reports to parse concurrently. `multiqc.parse_logs` dominates
MultiQC ingestion and is independent per file, so this is the main lever — but
MultiQC keeps module-global state, so workers are **processes**, not threads.

Each worker holds a fully parsed report in memory, so on a large report set this
multiplies peak RSS. That is the reason it is opt-in rather than defaulted on.

## `DEPICTIO_INGEST_MULTIQC_PRERENDER`

Builds the collection's aggregated Plotly figures during ingest — reusing the
parse already paid for metadata extraction — and uploads them gzipped to
`s3://{bucket}/{dc_id}/prerender/{sha}.json.gz`. The API's render endpoint probes
that prefix before enqueueing a build; on a hit it warms Redis and the on-disk
store and serves the figure directly.

Only runs on a **fresh ingest**, where the reports the run uploaded are exactly
the collection's full report set. On an append the local files cannot reproduce
the full aggregation, so it skips and lets the existing Celery prerender build
against the complete set. A prerender failure is logged and never fails ingest.

Enabling it costs ingest wall-time (two figures — light and dark — per plot per
dataset) and S3 storage. Measured on the ampliseq scale scenario (50 reports,
34 figures, ~11.7 MB gzipped for two collections), serving a figure from S3 with
cold Redis and a cold disk store took **40–60 ms**, against a 30–75 s cold
`parse_logs` + `get_plot` build. The first request after an API process starts
additionally pays a one-time ~3.8 s fsspec S3 filesystem initialisation.

These are single-run numbers from one dev stack (one uvicorn worker, MinIO on the
same host); treat them as an order of magnitude, not a benchmark.

Invalidating a collection's caches (append / replace / clear) also deletes its S3
prerender prefix, so figures keyed over a pre-mutation report set do not linger.

### Collections that never opt in

The render endpoint keeps a short-lived per-collection marker recording whether
the prefix holds any objects at all, so a collection with no prerendered figures
costs one Redis lookup rather than an S3 round-trip per panel. The negative
marker has a deliberately short TTL: a CLI ingest can upload a prerender at any
time and the API gets no notification, so this bounds how long a
just-opted-in collection keeps being skipped.
