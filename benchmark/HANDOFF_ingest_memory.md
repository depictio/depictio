# The ingestion path no longer materialises the data collection — resolved

Branch: `claude/depictio-benchmark-datasets-8h9e7d`

`POST /depictio/api/v1/deltatables/upsert` used to allocate 8.27 GB on a ~14M-row
data collection and get OOM-killed inside the backend cgroup (`memory.max = 8 GB`).
It now ingests the same collection without materialising anything, and the `1gb`
benchmark tier — which had never completed — runs end to end.

## What the memory was going into

| step | location | allocation |
|---|---|---|
| `pl.read_delta(...)` — eager | `deltatables_endpoints/routes.py` | whole table, ~1.3 GB |
| `aggregated_df.to_pandas()` | `deltatables_endpoints/utils.py` | full copy, strings became Python `str`, ~4-5 GB |
| `df.hash_rows(seed=0).to_numpy().tobytes()` | `routes.py` | extra pass, ~0.2 GB |

## What replaced it

`precompute_columns_specs` is lazy polars and takes a `LazyFrame`; `routes.py`
hands it a `pl.scan_delta`. The aggregations run in one pass per **cost class**,
because what dominates depends on the column, not the row count. Measured on this
tier (14.1M rows, 12 columns, polars 1.42 streaming engine):

| class | scales with | measured |
|---|---|---|
| cheap (count, min/max, mean, var, skew…) | nothing | 0.37 GB for all 12 columns |
| order statistics (median, quantile) | the column | 1.30 GB for 8 numeric columns |
| cardinality (nunique, mode) | the distinct values | 2.20 GB for 1 near-unique string column |

Run together those buffers coexist (5.4 GB); run as separate passes the cost is
the maximum, not the sum. A column above 1M distinct values — detected with a
`approx_n_unique` HyperLogLog that is never recorded — gets a pass of its own:
three near-unique string columns cost 6.71 GB sharing a pass against 2.94 GB one
at a time, for the same wall time.

`aggregation_hash` is now derived from the Delta log (table version + active
files) instead of hashing every row. It was never a comparable value — the caller
salts it with `datetime.now()` — and it only ever serves as a change marker.

Same data, same harness, specs step alone:

| | time | peak RSS |
|---|---|---|
| old (`read_parquet` + `to_pandas` + pandas aggregations) | 23.8 s | 6.29 GB |
| new (lazy, phased) | 3.1 s | 3.16 GB |

## Value parity

The specs are the contract — the `DeltaTableColumn` validator, the `agg_functions`
lookup and the frontend type maps all read those names. Divergences found by
running both implementations and fixed, not assumed:

- `quantile`: polars defaults to `nearest` interpolation, pandas to `linear`.
- `skew` / `kurt`: polars defaults to the biased estimator, pandas to the
  bias-corrected one — and pandas returns NaN below 3 / 4 observations where
  polars still returns a number.
- NaN: pandas treats it as missing, polars as a value (`fill_nan(None)`).
- `nunique` / `mode`: polars counts null as a distinct value, pandas drops it.
- `mode`: pandas returned the tied modes sorted and the caller took the first —
  i.e. the smallest.

`to_pandas()` also silently widened two dtypes: an integer column holding nulls
came back as `float64`, a boolean column holding nulls as `object`. A column
already recorded in the previous aggregation keeps its recorded type, so saved
dashboard components don't desync; a column never seen before gets the true
polars type. `routes.py` reads the previous aggregation to supply that.

Tests live in `depictio/tests/api/v1/test_precompute_columns_specs.py` (32),
including a parity test against the previous pandas implementation kept verbatim
in the module, and a guard that makes `to_pandas` raise so the materialisation
cannot come back unnoticed.

## The 1gb run

```bash
P=../../depictio/depictio-venv-dash-v3/bin
$P/python -m benchmark.cli run \
  --cli-config ~/.depictio/CLI.claude-depictio-benchmark-datasets-8h9e7d-100.yaml \
  --server-mode celery_on --sizes 1gb --dcs 2 --components 5 --connect joins,links \
  --visu figure,table,advanced_viz --repeats 2 --dashboard-load \
  --depictio-bin $P/depictio
```

50 measurements, all `ok`, no errors, **zero OOM kills**
(`colima ssh -- sudo dmesg | grep -c "Memory cgroup out of memory"` → 0). Backend
cgroup over the run: 0.50 GB idle → 2.90-3.34 GB during ingest → 5.18 GB transient
during the render phase → 2.93 GB at rest. No `precompute_columns_specs` warning
was logged, so the per-expression degradation path never fired.

Both data collections were verified in Mongo afterwards: 14 columns each,
`count = 14,097,113`, modes / nunique / medians all present, and one collection at
`aggregation_version = 2` exercising the re-ingest path.

## The cache question — refuted

`max_dataframe_size_mb` defaults to 100 (`api/v1/configs/settings_models.py`,
enforced in `api/cache.py`), and the expectation was that above ~3M rows nothing
would be cached, collapsing the warm speedup to x1 at this tier. It does not
happen, because renders no longer load the collection: the largest payload in the
whole run was 100,000 rows / 4.8 MB (advanced_viz), figures load 40,000 rows /
0.9 MB, tables one 100-row block. What reaches the cache is the bounded render
payload, far below the cap, so warm figure loads still come back at ~0 ms.

The cap would only bite on a render that asks for the whole collection — i.e. the
explicit load-all escape hatch. That is the case left to measure.

## What is now the largest term

Ingestion is no longer the ceiling: the 5.18 GB peak in this run came from the
**render** phase, not the upsert. That is where the next look belongs.
