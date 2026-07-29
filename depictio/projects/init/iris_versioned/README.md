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

One command, run wherever the paths in `project.yaml` resolve. They are
container paths (`/app/depictio/...`), so in a docker deployment that means
inside the backend container:

```bash
docker compose exec depictio-backend \
    python /app/depictio/projects/init/iris_versioned/rebuild_demo.py
```

That tears down any previous copy of the demo and rebuilds all three moving
parts, then asserts the result matches what this README describes and fails
loudly if it does not. `--verify` checks an existing setup without touching it.

### Why a script rather than a list of commands

This README used to say: run `depictio run` four times, then import v1 and edit
it into v2/v3/v4 in the editor. That is a fine way to *demonstrate* the feature
and a poor way to *build* the fixture. It cannot be repeated, cannot be
verified, and a stray autosave in the middle leaves anonymous versions
interleaved with the named ones.

Worse, hand-setup makes it easy to get the ordering wrong in a way nothing
catches. The batches must be ingested **interleaved** with the dashboard saves:

```
batch 1 -> save "v1 Survey"   -> stamps delta 0   (50 rows)
batch 2 -> save "v2 Extended" -> stamps delta 1   (100 rows)
batch 3 -> save "v3 Recalib." -> stamps delta 2   (100 recalibrated)
batch 4 -> save "v4 Complete" -> stamps delta 3   (150 rows)
```

A dashboard version stamps the Delta commit of each collection it referenced
**at the moment it was saved**. Ingest everything first and then save the four
dashboards, and all four versions stamp commit 3 — the labels are right, the
component counts are right, the stamps exist and say `delta`, and "restore v1's
data" quietly shows the complete survey. The script asserts the stamps are
strictly ascending, which is the one check that separates a working demo from
one that merely looks like it.

### What the script does

1. Deletes the existing project (cascading to its Delta table) and dashboards.
   The version ledger is keyed on the dashboard family and survives an
   overwrite, so reusing an id would append to old history.
2. `depictio config sync` to register the project.
3. For each batch: `stage_batch.sh N`, then `depictio run`, then write the
   matching dashboard YAML, then `POST /dashboards/save` and
   `POST /{id}/versions` to name the state. Those last two are exactly what the
   editor calls, so the ledger, the stamps and the coalescing all behave as
   they would for a user with a mouse.
4. Verifies: row progression, that Setosa's mean moved across the flat step,
   the four labels in order, component counts `[5, 8, 8, 9]`, and ascending
   Delta stamps.

`stage_batch.sh` exists because there is no flag to ingest a single batch --
`depictio run` scans everything the project's `locations` point at. Each batch
file is the complete state of the survey at that point, so exactly one is
staged at a time; side by side, the scanner would read the same flowers four
times over.

The default `overwrite` write mode is deliberate, rather than `replace-runs`.
Only one run is ever staged, so `replace-runs` would decline to partition at
all ("only one run in this data collection") -- and its purpose is to leave
*other* runs' files untouched, which here would keep the previous batch's rows
alive alongside the new one. Delta writes a new commit either way, so the
history is identical.

### Doing it by hand

Still useful if you want to *watch* the versions accumulate. Run the CLI steps
from the script one at a time, and after each `depictio run` open the editor,
apply the next YAML's changes, and use **Settings -> Version history -> Bookmark
this state -> Name it**. Keep the interleaving: ingest batch N before saving
version N, or every version will stamp the newest commit.

Note that `dashboard import` writes the document directly and does **not**
record a version -- the ledger is fed by `POST /dashboards/save`, which is what
the editor calls. So the timeline is empty until the first edit, and that first
save seeds a `Before first tracked change` baseline holding the as-imported
state. That baseline is what makes the imported layout restorable at all.

### Checking the data

On the project page, or:

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
only difference is Setosa's re-measured petal lengths (mean 1.46 -> 2.07).

## The dashboard versions

One dashboard, four versions in its history:

| version | components | stamps | what changed |
|---|---|---|---|
| v1 Survey | 5 | delta 0 | baseline: counts, variety filter, petal **histogram** |
| v2 Extended | 8 | delta 1 | histogram -> **box plot**; "Mean Petal Length" card **retyped** to "Varieties Surveyed"; adds scatter + range filter |
| v3 Recalibrated | 8 | delta 2 | scatter **removed**, replaced by a per-variety mean bar; adds a mean-petal card |
| v4 Complete | 9 | delta 3 | range filter **removed**; bar -> scatter again; adds a longest-petal card and a run table |

Deliberately **not** a chain of supersets. A version diff that only appends is
the easy half: it never exercises removal, never changes what an existing
component means, and lets a component-history modal look right while only
pinning data. Here the same component id is a histogram in v1 and a box plot
afterwards, and the card at `petal-mean` asks a different question in v1 (mean
petal length, in cm) than in v2 onward (how many varieties). Open that card's
history and the two are plainly different measurements -- which is only true
because the modal pins each version's *definition*, not just its data.

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
instance, then drives the real HTTP API:

* a save writes a version whose stamps record a real Delta commit;
* the card reads 50 / 100 / 100 / 150 across the four commits;
* `as_of_version` on the **stored** `v1 Survey` returns 50 rows, not today's
  150 — checking only the newest version would pass whether the stamps are
  honoured or ignored, since "as of now" and "now" are the same read;
* mean petal length differs between the two 100-row commits;
* a live read afterwards is still current (no cache poisoning);
* the boundaries hold: a `dc_id` override is ignored, a stale `as_of_version`
  is a 400, a malformed override degrades to a 200.

Override the defaults with `DEPICTIO_API`, `DEPICTIO_CLI_CONFIG` and
`DASHBOARD_TITLE`.

### Still not covered

Collections that are not Delta-backed. A MultiQC collection is plain parquet
with no commit log, so it cannot be travelled to; the API refuses rather than
quietly serving current data, and the UI reports which collections are showing
live data instead of implying everything travelled.
