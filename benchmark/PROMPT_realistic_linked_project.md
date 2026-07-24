# Prompt — realistic 3-DC linked benchmark project

Paste this into a fresh session on branch `claude/depictio-benchmark-datasets-8h9e7d`
(or a worktree off it). It is self-contained.

---

## Objective

Build a **realistic three-data-collection project** for the benchmark harness, so
that cross-DC filtering (`links`) can be measured on a topology that actually
occurs in practice — and produce **wall-clock compute + render figures for a
stated CPU/RAM budget on a MacBook Pro**.

The deliverable is not "a faster number". It is a measurement someone can trust:
a named hardware profile, a named dataset shape, and per-phase timings that say
where the time went.

## Why — what is wrong with the current dataset

`benchmark/datagen.py` generates `n_dcs` collections that are **symmetric**: same
row count, same schema, same `individual_id` set, different measurements
(`seed = run * 1_000 + dc_i`). For `joins` that is fine. For `links` it is a
worst case that does not represent normal usage:

- both DCs hold ~14M rows at the `1gb` tier;
- the join key `individual_id` is **unique per row**, so its cardinality equals
  the row count.

Translating a filter on `species` (3 distinct values) into `individual_id`
therefore yields ~1/3 of the table. Measured on the running stack:

```
Column translation: 2 species values -> 9 398 400 individual_id values
Column translation: 1 species values -> 4 698 815 individual_id values
```

Those millions of values were materialised as a Python list, serialised to JSON
and sent over a loopback HTTP call. Real link topologies look nothing like this:
a metadata DC has one row per sample and the join key has tens to thousands of
distinct values, not millions.

**So: the numbers this dataset produces for `links` describe a pathological case.
They must not be published as "the cost of cross-filtering".**

## What to build

### Three data collections

| DC | grain | rows (default tier) | role |
| --- | --- | --- | --- |
| `metadata` | one row per sample | ~500 | sample attributes: `sample_id`, `condition`, `batch`, `timepoint`, `tissue`, `sex`, `age` |
| `metrics` | one row per (sample, tool) | ~500 × 20 = 10 000 | QC metrics: `sample_id`, `tool`, `metric`, `value`, plus a few wide numeric columns |
| `features` | one row per (sample, feature) | ~500 × 25 000 = 12.5M | the heavy one: `sample_id`, `feature_id`, `expression`, `effect_size`, `neg_log10_p`, `mean_expression` |

The essential property, and the whole point of the exercise: **`sample_id` has
~500 distinct values**, not millions. Row counts scale with the size tier;
`sample_id` cardinality scales far more slowly (make it configurable, and let the
per-sample fan-out absorb most of the growth).

Keep the columns advanced-viz needs (`effect_size`, `neg_log10_p`,
`mean_expression`) on `features` so volcano/MA components still bind.

### Links — all three connected

    metadata ──sample_id──> metrics
    metadata ──sample_id──> features
    metrics  ──sample_id──> features

This gives, in one project:

- **star**: filter `metadata.condition`, two targets narrow;
- **chain**: `metadata -> metrics -> features` (multi-hop propagation landed in
  `filter_links._link_paths` / `_walk_link_path`; this is the dataset that
  exercises it end to end);
- **two routes to one target**: `metadata -> features` directly and
  `metadata -> metrics -> features`, which must not produce contradictory
  filters.

### Dashboard

One tab, mixing component types so every render path is covered:

- interactive filters on `metadata` (`condition` MultiSelect, `batch`
  MultiSelect, `age` RangeSlider);
- cards over `metrics`;
- figures over `features` (scatter, box, histogram — the aggregation-pushdown
  paths in `services/figure/aggregate.py`);
- a table over `features`;
- volcano + MA over `features`.

## What to measure

Use the existing `--filter-rounds` phase (`benchmark/runner.py::_filter_round`).
It already fires every component through a pool the width of the viewer's
`fetchQueue` limit and records `time_to_first_ms` / `time_to_last_ms`, with a new
filter value per round so the filtered-frame cache cannot answer.

Report, per phase:

1. **Ingest** — wall, rows/s, peak RSS (`IngestResult`, already collected).
2. **Cold dashboard open** — `--dashboard-load`, unfiltered.
3. **Filter round** — the number a user waits for. Break it down by which DC the
   filter originates on, because that is what changes the cost:
   - filter on `metadata` → 1 hop to `metrics`, 1 hop to `features`, plus the
     2-hop chain;
   - filter on `features` → no propagation.
4. **Link resolution size** — log and record how many values each translation
   produces. On this topology it should be ~500, not millions. **If it is
   millions, the dataset is wrong, not the code.**

Keep the regimes apart exactly as `blog_metrics.py` already does: cold
(`dc_first_touch`) vs warm, sequential vs concurrent. Do not average them.

## Resource profile — this is part of the result

`docker-compose.bench.yaml` parameterises the limits:

```bash
BENCH_API_CPUS=4 BENCH_API_WORKERS=4 \
BENCH_CELERY_CPUS=4 BENCH_CELERY_WORKERS=4 \
BENCH_MONGO_CPUS=2 \
docker compose -p ${COMPOSE_PROJECT_NAME} --env-file .env.instance \
  -f docker-compose.dev.yaml -f docker-compose.override.yaml \
  -f docker-compose.bench.yaml --profile dev up -d
```

Every reported number must state:

- the host (MacBook Pro model, chip, total RAM);
- the Colima VM's vCPU and RAM;
- the per-service CPU/memory limits used.

Run at least two profiles so the numbers mean something as a curve rather than a
point — e.g. `2 CPU` (mirrors the EMBL cluster) and `4 CPU`. A single unlabelled
figure is not a result.

## Reuse — do not rebuild these

| what | where |
| --- | --- |
| chunked/sharded data generation, size calibration | `benchmark/datagen.py` (`_make_batch`, `rows_for_bytes`, `SHARD_TARGET_BYTES`) |
| project + dashboard YAML emission with static IDs | `benchmark/configgen.py` (`write_configs`, `build_project`, `build_dashboard`) |
| matrix expansion | `benchmark/matrix.py` (`Cell`, `ConnectMode`) |
| ingest → import → render loop, project reset | `benchmark/runner.py` (`run_matrix`, `_reset_project`, `_render_component`) |
| filter-round timing | `benchmark/runner.py::_filter_round`, `benchmark/metrics.py::FilterRoundResult` |
| report + blog export | `benchmark/report.py`, `benchmark/blog_metrics.py` |

`_reset_project` deletes the project before each cell — keep that. Without it,
`depictio run --overwrite` overwrites the *config* but upserts runs, so a re-run
silently doubles the dataset (this already caused a 300s upsert timeout and a
wedged backend).

## Constraints

- Python via `depictio-venv-dash-v3/bin/python`; CLI via `python -m depictio.cli`.
- `ruff format` + `ruff check`, then `pre-commit run --all-files`. No
  `# type: ignore`.
- Do not run docker commands other than `docker logs` — print the compose command
  for the user to run.
- Datasets and results stay under `benchmark/output*/` (gitignored). At the
  `features` scale here, generation is tens of GB of CSV: check free disk first
  and make the tier configurable.
- Percentiles over fewer than 20 renders are not quotable — `report.py` and
  `blog_metrics.py` already guard this (`_MIN_RENDERS`).

## Definition of done

- [ ] `--connect links` on the new project generates the 3-DC topology with
      `sample_id` cardinality in the hundreds.
- [ ] All three link routes resolve, including the 2-hop chain, verified by a
      test and by log lines showing the hop count.
- [ ] A filter round on `metadata` completes with per-translation value counts in
      the hundreds.
- [ ] `REPORT.md` and `blog_metrics.json` carry the filter-latency block, stamped
      with the hardware profile.
- [ ] Numbers exist for at least two CPU profiles.
- [ ] Post-implementation review: `code-simplifier` then `code-reviewer` on the
      diff.

## One caveat to carry

The current symmetric dataset is still worth keeping as an explicit **worst-case**
cell (unique join key, both sides large). It found real bugs — an eager
full-table read in link resolution, a timeout silently degrading into unfiltered
data, and an empty resolution rendering every row. Label it as the adversarial
case; do not let it be the default that describes normal usage.
