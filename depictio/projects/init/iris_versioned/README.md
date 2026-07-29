# Iris Versioned — a demo you can actually version

The bundled `iris` project is a single static CSV. That makes it a poor
demonstration of version history: there is only ever one state to look at, so
the version drawer shows a list of identical entries and the data-provenance
stamps have nothing to distinguish.

This project exists to give both dimensions something real to show:

- **three dataset versions** — three ingestion batches whose content genuinely
  differs, producing three Delta versions;
- **three dashboard versions** — three layouts, each a superset of the last, so
  the version timeline shows the component count moving and a restore is a
  visible change rather than a no-op.

Not seeded automatically. It is a demo fixture, and adding a fourth project to
everyone's first run is a cost paid by people who did not ask for it. Set it up
with the steps below.

## The data

Three batches under `data/`, each a directory the `sequencing-runs` scanner
picks up as its own `depictio_run_id`:

| batch | rows | varieties | what changed |
|---|---|---|---|
| `batch_01_initial_survey` | 100 | Setosa, Versicolor | the original survey |
| `batch_02_virginica_added` | 150 | + Virginica | a third variety arrives |
| `batch_03_virginica_recalibrated` | 150 | same three | Virginica petals re-measured, ~0.6 cm shorter |

Batch 3 is the one that matters. It has the **same row count and the same
varieties** as batch 2 — only the values differ. That is exactly the situation
where "which version of the data is this chart built on?" stops being
rhetorical, because nothing on screen answers it.

Regenerate deterministically (fixed seed, byte-identical output):

```bash
python depictio/projects/init/iris_versioned/generate_batches.py
```

## Setting it up

There is no flag to ingest a single batch: `depictio run` scans everything the
project's `locations` point at. So the batches live in `batches/` and
`stage_batch.sh` swaps one at a time into `data/`. Each batch file is already
the complete state of the survey at that point, so exactly one is staged at a
time — side by side, the scanner would read the same flowers three times over.

Run the CLI wherever the paths in `project.yaml` resolve. They are container
paths (`/app/depictio/...`), so in a docker deployment that means inside the
backend container:

```bash
cd depictio/projects/init/iris_versioned
CFG=/app/depictio/.depictio/admin_config.yaml
PROJ=/app/depictio/projects/init/iris_versioned

# 1. Register the project (once).
depictio config sync --CLI-config-path $CFG --project-config-path $PROJ/project.yaml

# 2. Stage and ingest each batch in turn. Each run writes a new Delta commit,
#    so this produces three data versions.
#
#    --overwrite is required from the second run onward: the S3 destination
#    already exists, and the CLI refuses to replace it silently.
./stage_batch.sh 1
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync

./stage_batch.sh 2
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync --overwrite

./stage_batch.sh 3
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync --overwrite

# 3. Import the first dashboard. Note: `--config`, not `--CLI-config-path`.
depictio dashboard import $PROJ/dashboards/v1_survey.yaml --config $CFG
```

`--skip-sync` after the first `config sync`, because `run` re-syncs by default
and refuses when the project already exists.

The default `overwrite` write mode is deliberate here, rather than
`replace-runs`. Only one run is ever staged, so `replace-runs` would decline to
partition at all ("only one run in this data collection") — and its purpose is
to leave *other* runs' files untouched, which in this layout would keep the
previous batch's rows alive alongside the new one. Delta writes a new commit
either way, so the history is identical.

Check the Delta history on the project page, or:

```bash
depictio data versions iris_versioned_table \
    --CLI-config-path $CFG --project-config-path $PROJ/project.yaml
```

Three commits, at 100 / 150 / 150 rows:

```
 version   operation   write_mode   rows_after   runs
 2         WRITE       overwrite    150          1
 1         WRITE       overwrite    150          1
 0         WRITE       overwrite    100          1
```

## The dashboard versions

Import `v1_survey.yaml`, then **edit it into v2 and v3 in the editor** rather
than importing all three. Three imports create three unrelated dashboards;
editing one creates one dashboard with three versions in its history, which is
the thing being demonstrated.

| version | components | adds |
|---|---|---|
| v1 Survey | 5 | baseline: counts, variety filter, petal box plot |
| v2 Extended | 8 | median petal card, petal range filter, sepal/petal scatter |
| v3 Recalibrated | 11 | Virginica-only median, batch filter, per-batch table |

Each is a strict superset of the previous, so restoring v1 from v3 visibly
removes six components — a restore you can confirm at a glance instead of
squinting at a diff.

To build the history: import v1, then open the editor and add the components
listed for v2 (the YAML files are the reference for what each contains). Use
**Settings → Version history → Bookmark this state → Name it** at each step, so
the timeline reads `v1 Survey` / `v2 Extended` / `v3 Recalibrated` rather than
three anonymous autosaves.

Note that `dashboard import` writes the document directly and does **not**
record a version — the ledger is fed by `POST /dashboards/save`, which is what
the editor calls. So the timeline is empty until the first edit, and that first
save seeds a `Before first tracked change` baseline holding the as-imported
state. That baseline is what makes the imported layout restorable at all.

## What this demonstrates

**Dashboard version history.** The timeline, naming, pinning, restore, and
read-only preview of a past layout.

**Dataset time travel.** Every dashboard version stamps the Delta version of
each data collection it referenced, and those stamps are now read back:

* *Use this data* on a timeline row draws the dashboard from the commits that
  version recorded (`as_of_version`).
* The dataset picker pins a single collection to any commit
  (`data_versions: {dc_id: N}`), for "current layout, last month's data".
* The component-history modal shows one component across versions, pinning
  both its stored config and its data.

This project is the fixture that makes it testable. Batch 2 and batch 3 have
the **same row count** and differ only in values, so a read that silently
returns current data is immediately visible rather than merely plausible — a
row-count check alone would pass while being wrong.

### Verifying it

With the demo ingested and a CLI config to hand:

```bash
uv run python depictio/projects/init/iris_versioned/check_time_travel.py
```

It discovers the dashboard, its collection and a card from the running
instance, then drives the real HTTP API: stamps record `delta_version=2`, the
card reads 100/150/150 rows across the three commits, mean petal length differs
between the two 150-row commits, a live read afterwards is still current (no
cache poisoning), and the boundaries hold (a `dc_id` override is ignored, a
stale `as_of_version` is a 400, a malformed override degrades to a 200).

Override the defaults with `DEPICTIO_API`, `DEPICTIO_CLI_CONFIG` and
`DASHBOARD_TITLE`.

### Still not covered

Collections that are not Delta-backed. A MultiQC collection is plain parquet
with no commit log, so it cannot be travelled to; the API refuses rather than
quietly serving current data, and the UI reports which collections are showing
live data instead of implying everything travelled.
