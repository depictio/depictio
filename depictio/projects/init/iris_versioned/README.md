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

```bash
cd depictio/projects/init/iris_versioned

# 1. Register the project (once).
depictio config create-project --project-config-path project.yaml

# 2. Stage and ingest each batch in turn. Each run writes a new Delta commit,
#    so this produces three data versions.
./stage_batch.sh 1 && depictio run --project-name "Iris Versioned Demo"
./stage_batch.sh 2 && depictio run --project-name "Iris Versioned Demo"
./stage_batch.sh 3 && depictio run --project-name "Iris Versioned Demo"

# 3. Import the first dashboard.
depictio dashboard import dashboards/v1_survey.yaml
```

The default `overwrite` write mode is deliberate here, rather than
`replace-runs`. Only one run is ever staged, so `replace-runs` would decline to
partition at all ("only one run in this data collection") — and its purpose is
to leave *other* runs' files untouched, which in this layout would keep the
previous batch's rows alive alongside the new one. Delta writes a new commit
either way, so the history is identical.

Check the Delta history on the project page, or:

```bash
depictio data versions iris_versioned_table --project-config-path project.yaml
```

You should see three commits. `--json` includes the write mode and run tags
depictio stamps into each one.

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

## What this demonstrates, and what it does not

**Works today.** Dashboard version history: the timeline, naming, pinning,
restore, and read-only preview of a past layout. Restoring v1 while the data is
at batch 3 shows the old layout against current data.

**Recorded but not yet used.** Each dashboard version stamps the Delta version
of every data collection it referenced (`DataCollectionStamp.delta_version`).
Nothing reads it back, so a preview always renders **current** data — the banner
says so rather than implying otherwise.

Wiring that up is blocked on one thing:
`deltatables_utils._generate_cache_keys` salts its cache key with
`aggregation_version` only. A historical read served through
`load_deltatable_lite` would be cached under the *live* key and then handed to
callers who asked for current data. The key has to carry the Delta version
before any as-of read can be exposed. `deltatables_endpoints/routes.py` carries
the same warning at its `version` parameter.

This project is the fixture that makes that work testable: batch 2 and batch 3
differ only in values, so a time-travel read that silently returns current data
is immediately visible instead of plausible.
