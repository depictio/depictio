# Handoff — the ingestion path materialises the whole data collection in RAM

Branch: `claude/depictio-benchmark-datasets-8h9e7d` (pushed, tree clean at `30af57127`)

## Task

Make `POST /depictio/api/v1/deltatables/upsert` ingest a ~1 GB / ~14M-row data
collection without allocating gigabytes. Today it OOM-kills the backend worker.

## Evidence (measured, not inferred)

Reproduced on a local stack with the backend capped at 8G
(`docker-compose.bench.yaml`). The kernel OOM killer fired four times, always in
the backend cgroup (`memory.max = 8589934592`), always the same magnitude:

```
Memory cgroup out of memory: Killed process (python)
  total-vm:18238880kB  anon-rss:8278020kB  file-rss:123520kB
```

Read it back with:

```bash
colima ssh -- sudo dmesg | grep -E "Memory cgroup out of memory|oom_memcg="
```

The client symptom is `Server disconnected without sending a response` from
`depictio-cli` on the second DC, or — if the request is in flight when the
worker dies — the caller hangs in `sock_recv` until its own timeout, because the
half-open connection is never reset.

## Where the memory goes

Per single upsert of one DC (schema: 4 String, 4 Int64, 4 Float64):

| step | location | allocation |
|---|---|---|
| `pl.read_delta(...)` — eager | `api/v1/endpoints/deltatables_endpoints/routes.py:111` | whole table, ~1.3 GB |
| `aggregated_df.to_pandas()` | `api/v1/endpoints/deltatables_endpoints/utils.py:119` | full copy; String cols become Python `str` objects, ~4-5 GB |
| `df.hash_rows(seed=0).to_numpy().tobytes()` | `routes.py:116-117` | extra pass, ~0.2 GB |

`.to_pandas()` is the dominant term and the cheapest to remove:
`precompute_columns_specs` only needs, per column, a dtype and some
min/max/unique/nunique — all expressible as lazy polars aggregations, with no
frame materialised at all.

**The trap:** that function emits *pandas* dtype names, normalised to strings
like `"object"` for text columns, and those exact names are consumed downstream
by the spec validator, the `agg_functions` lookup and the frontend type maps.
A polars rewrite must keep emitting the same normalised names. See the comment
at `utils.py:151-156` — that normalisation already has history.

`hash_rows` also needs a decision: it exists to produce `aggregation_hash`. A
streaming/chunked hash, or hashing over a lazy scan, avoids holding the frame.

## Already done (do not redo)

`_build_event_payload` in `api/v1/endpoints/events_endpoints/routes.py` was a
*second* offender — four more full materialisations (two `.collect()`s plus a
Python set and two Python lists of ids) on the same request, for a websocket
journal message, executed even with zero subscribers. Fixed in `6558e29c5`:
lazy `select(pl.len())` for counts, Arrow anti-join for the new-id diff.
Semantics verified equivalent (duplicates included) against the old
implementation on a two-version delta table. That fix let both DCs' upserts
return 200, but did **not** remove the 8.27 GB peak — the table above is why.

## Constraints

- No tests exist for `precompute_columns_specs` or `_build_event_payload`. Add
  them; the column-spec output shape is the contract that must not drift.
- `pre-commit run --all-files` is mandatory. `ty check depictio/models/
  depictio/api/` currently reports ~30 pre-existing diagnostics (mostly
  `models/components/advanced_viz/catalog.py`) — do not let that number grow.
- Don't run docker commands other than `docker logs`. The stack is already up;
  the backend hot-reloads on source edits (`StatReload`).

## How to verify

1. Baseline the kill count: `colima ssh -- sudo dmesg | grep -c "Memory cgroup out of memory"`.
2. Sample the cgroup during ingest:
   ```bash
   colima ssh -- sh -c 'C=<container-id>; while :; do \
     echo "$(date +%H:%M:%S) $(( $(cat /sys/fs/cgroup/docker/$C/memory.current)/1024/1024 ))MB"; sleep 5; done'
   ```
   Pre-fix this reached ~6.7 GB before collapsing on the kill. Target: flat.
3. Then run the tier that has never completed:
   ```bash
   P=../../depictio/depictio-venv-dash-v3/bin
   $P/python -m benchmark.cli run \
     --cli-config ~/.depictio/CLI.claude-depictio-benchmark-datasets-8h9e7d-100.yaml \
     --server-mode celery_on --sizes 1gb --dcs 2 --components 5 --connect joins,links \
     --visu figure,table,advanced_viz --repeats 2 --dashboard-load \
     --depictio-bin $P/depictio
   ```
   Purge the celery queue first (redis on `localhost:6100`, key `celery` plus
   `unacked`/`unacked_index`) — orphaned tasks from a killed run poison the next
   one's latencies. Data is already generated at `benchmark/output/data/1gb_dc2`
   (2.2 GB); do not pass `--force-datagen`.

## Open question the benchmark should answer next

`max_dataframe_size_mb` defaults to 100 (`api/v1/configs/settings_models.py:503`,
enforced at `api/cache.py:112`), so above roughly 3M rows nothing is ever cached
and every render repays the cold Delta read. At 10mb the warm speedup measured
x15, at 100mb only x3 — consistent with the cap starting to bite. The 1gb tier
is where that should collapse to x1. Confirm or refute it.
