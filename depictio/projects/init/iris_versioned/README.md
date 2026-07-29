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
   the four labels in order, component counts `[5, 8, 7, 9]`, ascending Delta
   stamps, that component ids persist across all four versions, and that no
   surviving component is unchanged between consecutive versions.

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

One dashboard, four versions in its history. Generated by
`regenerate_dashboards.py` rather than hand-written, because what makes them
useful is a property of the *set*: every component that survives a step has to
differ in something visible, or opening its history shows two identical renders
and the feature looks broken.

| version | components | stamps | what changed |
|---|---|---|---|
| v1 Survey | 5 | delta 0 | one variety: a histogram, a count, a mean |
| v2 Extended | 8 | delta 1 | histogram → **box**; count → **nunique**; average → **median**; Select → **MultiSelect**; adds a scatter, a range filter, a sepal card |
| v3 Recalibrated | 7 | delta 2 | box → **bar**; scatter → **line**; nunique → **range**; median → **std_dev**; MultiSelect → **SegmentedControl**; RangeSlider → **Slider**; removes the sepal card |
| v4 Complete | 9 | delta 3 | bar → **box**; line → **scatter**; range → **count**; std_dev → **max**; sepal card returns as **min**; adds a table and a variety count; removes the petal filter |

Each step changes 8–10 components. Read down one component's column and it is
four different questions in the same slot:

```
headline        count(variety) -> nunique(variety) -> range(petal) -> count(variety)
petal-stat      average        -> median           -> std_dev      -> max
main-chart      histogram      -> box              -> bar          -> box
variety-filter  Select         -> MultiSelect      -> SegmentedControl -> MultiSelect
sepal-stat      —              -> average          -> (removed)    -> min
```

Deliberately **not** a chain of supersets. A diff that only appends is the easy
half: it never exercises removal, never changes what an existing component
means, and lets a component-history modal look right while only pinning data.
Here the same component id is a histogram in v1 and a box plot after; the
headline card asks a different question in every version; and `sepal-stat` is
removed in v3 and returns in v4, so restoring across that gap has to delete a
component in one direction and add one in the other.

`rebuild_demo.py` fails if any surviving component is unchanged across a step.
It compares what each component *draws* rather than its title, because a filter
that switches from a dropdown to a segmented control keeps its name while
looking completely different.

## Where the version UI lives

**Edit mode only** (`/dashboard-edit/{id}`):

* **Settings → Version history** — the timeline: name, pin, preview, restore.
* **Dataset version** picker in that drawer — draw the current layout from an
  older commit.
* **Per-component menu → History** — one component across versions, with its
  own dataset travel, a side-by-side compare against current, and
  "restore this component" on its own.

Everything there either writes or re-points the dashboard at data it was not
saved with, which is why none of it appears in the viewer.

**The viewer** (`/dashboard/{id}`) renders `?version=` previews — read-only,
banner-marked, and pinned to the data that version recorded. That is how the
editor's Preview opens a past version.

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
  both its stored config and its data — with per-pane dataset selection, so
  holding the data constant isolates what a config change did, and
  "restore this component" to put one back without reverting the rest.

This project is the fixture that makes it testable. Batch 2 and batch 3 have
the **same row count** and differ only in values, so a read that silently
returns current data is immediately visible rather than merely plausible — a
row-count check alone would pass while being wrong.

### Verifying it

Five API checks and three front-end ones, each aimed at a failure that a
compile and a green test suite both miss. Run them with the demo ingested and a
CLI config to hand.

```bash
cd depictio/projects/init/iris_versioned
uv run python check_time_travel.py       # pins reach the data
uv run python check_render_paths.py      # ...on figures and tables too
uv run python check_component_history.py # the modal shows what it claims
uv run python check_component_restore.py # one component, nothing else
uv run python check_served_bundle.py     # the browser has the current code
```

Plus the front-end state checks, which execute the real functions rather than
reading them:

```bash
cd depictio/viewer
npm run check:dataversions      # a pin reaches the request body
npm run check:componenthistory  # version vs data axes stay independent
npm run check:renderkey         # a replaced definition refetches
```

Highlights of what they pin down, all of which were real bugs at some point:

* `as_of_version` on the **stored** `v1 Survey` returns 50 rows, not today's
  150. Checking only the newest version passes whether the stamps are honoured
  or ignored, since "as of now" and "now" are the same read.
* Mean petal length differs between the two 100-row commits, so a read that
  silently serves current data is visible rather than merely plausible.
* A figure's rendered trace type follows the version — `histogram` in v1,
  `box` in v2, `bar` in v3 — which is only true because the render endpoint
  honours the version's stored definition rather than today's.
* Same data on both compare panes with different configs gives different
  answers, which is what per-pane dataset selection is for.
* The served bundle contains the time-travel wiring. Twice a feature here was
  correct in source, correct in the API, and broken on screen because Vite
  cached a transform from a moment when an import failed to resolve. If that
  check fails, restart the viewer container rather than reading the source.

Override the defaults with `DEPICTIO_API`, `DEPICTIO_CLI_CONFIG` and
`DASHBOARD_TITLE`.

### Still not covered

Collections that are not Delta-backed. A MultiQC collection is plain parquet
with no commit log, so it cannot be travelled to; the API refuses rather than
quietly serving current data, and the UI reports which collections are showing
live data instead of implying everything travelled.
