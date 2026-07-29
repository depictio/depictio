# Iris Versioned — a demo you can actually version

The bundled `iris` project is a single static CSV. That makes it a poor
demonstration of version history: there is only ever one state to look at, so
the version drawer shows a list of identical entries and the data-provenance
stamps have nothing to distinguish.

This project exists to give both dimensions something real to show:

- **four dataset versions** — four ingestion batches at 50 / 100 / 100 / 150
  rows, producing four Delta commits whose content genuinely differs;
- **four dashboard versions** — four layouts that *replace and remove*
  components rather than only adding, so restoring one is a visible change and
  the component-history modal has something real to show.

Not seeded automatically. It is a demo fixture, and adding a fourth project to
everyone's first run is a cost paid by people who did not ask for it. Set it up
with the steps below.

## The data

Four batches under `batches/`, each a directory the `sequencing-runs` scanner
picks up as its own `depictio_run_id`:

| batch | rows | varieties | mean Setosa petal | what changed |
|---|---|---|---|---|
| `batch_01_setosa_only` | 50 | Setosa | 1.46 | the first collection |
| `batch_02_versicolor_added` | 100 | + Versicolor | 1.46 | the survey grows |
| `batch_03_setosa_recalibrated` | 100 | same two | **2.07** | Setosa re-measured after a calibration fix |
| `batch_04_virginica_added` | 150 | + Virginica | 2.07 | the complete survey |

Batch 3 is the one that matters. It has the **same row count and the same
varieties** as batch 2 — only the values differ. Every other step moves the row
count, which makes time travel obvious at a glance; a demo built only from
those steps would pass while being wrong in the one way that counts. Batch 3 is
where "which version of the data is this chart built on?" stops being
rhetorical, because nothing on screen answers it.

The correction lands on **Setosa**, which is present from batch 1, so it
changes a value the earlier versions already had rather than one that arrived
with the batch. Time travel that only ever adds rows is the easy half.

Regenerate deterministically (fixed seed, byte-identical output):

```bash
python depictio/projects/init/iris_versioned/generate_batches.py
```

## Setting it up

There is no flag to ingest a single batch: `depictio run` scans everything the
project's `locations` point at. So the batches live in `batches/` and
`stage_batch.sh` swaps one at a time into `data/`. Each batch file is already
the complete state of the survey at that point, so exactly one is staged at a
time — side by side, the scanner would read the same flowers four times over.

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
#    so this produces four data versions.
#
#    --overwrite is required from the second run onward: the S3 destination
#    already exists, and the CLI refuses to replace it silently.
./stage_batch.sh 1
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync

./stage_batch.sh 2
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync --overwrite

./stage_batch.sh 3
depictio run --CLI-config-path $CFG --project-config-path $PROJ/project.yaml --skip-sync --overwrite

./stage_batch.sh 4
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

Four commits, at 50 / 100 / 100 / 150 rows:

```
 version   operation   write_mode   rows_after   runs
 3         WRITE       overwrite    150          1
 2         WRITE       overwrite    100          1
 1         WRITE       overwrite    100          1
 0         WRITE       overwrite    50           1
```

Versions 1 and 2 are the pair worth remembering: identical row counts, and the
only difference is Setosa's re-measured petal lengths (mean 1.46 → 2.07).

## The dashboard versions

Import `v1_survey.yaml`, then **edit it into v2, v3 and v4 in the editor**
rather than importing all four. Four imports create four unrelated dashboards;
editing one creates one dashboard with four versions in its history, which is
the thing being demonstrated.

| version | components | what changed |
|---|---|---|
| v1 Survey | 5 | baseline: counts, variety filter, petal **histogram** |
| v2 Extended | 8 | histogram → **box plot**; "Mean Petal Length" card **retyped** to "Varieties Surveyed"; adds scatter + range filter |
| v3 Recalibrated | 8 | scatter **removed**, replaced by a per-variety mean bar; adds a mean-petal card |
| v4 Complete | 9 | range filter **removed**; bar → scatter again; adds a longest-petal card and a run table |

Deliberately **not** a chain of supersets. A version diff that only appends is
the easy half: it never exercises removal, never changes what an existing
component means, and lets a component-history modal look right while only
pinning data. Here the same component id is a histogram in v1 and a box plot
afterwards, and the card at `petal-mean` asks a different question in v1 (mean
petal length, in cm) than in v2 onward (how many varieties). Open that card's
history and the two are plainly different measurements — which is only true
because the modal pins each version's *definition*, not just its data.

To build the history: import v1, then open the editor and edit it into each
later version in turn (the YAML files are the reference for what each holds).
Use **Settings → Version history → Bookmark this state → Name it** at each step,
so the timeline reads `v1 Survey` / `v2 Extended` / `v3 Recalibrated` /
`v4 Complete` rather than four anonymous autosaves.

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
