# Penguins Versioned: two datasets, their join, five dashboard versions

A demo project for version history where more than one thing moves. It is built
from the bundled `penguins` observations, re-cut by **field season** (2007, 2008,
2009) so the data has an order of arrival, and it holds:

- **two datasets on two schedules**: `physical_features` (measurements) and
  `demographic_data` (census), each a Delta table with its own commit history.
  At two of the five steps only one of them is ingested, so the per-dataset
  pins of a dashboard version genuinely diverge;
- **their persisted join**, `penguins_complete` (one row per bird with both
  records), a third Delta table that `depictio ingest` rebuilds after every
  batch. It moves with **either** input: with the measurements at step 3, with
  the census at step 5;
- **one dashboard family** (a main tab plus up to two child tabs) saved as five
  named versions, one right after each batch.

`iris_versioned` shows one dataset and one tab. This fixture is the next step:
it is what you open to see "this chart moved because its dataset moved, and
that one did not because its dataset did not", and "this chart on the join
moved although its definition did not, because one of the join's inputs did".

**Not seeded automatically.** Nothing in `db_init`, `.db_seeds` or `STATIC_IDS`
refers to it. Build it with `rebuild_demo.py` (below).

## The story

| step | batch | `physical_features` | `demographic_data` | `penguins_complete` (join) | dashboard version |
|---|---|---|---|---|---|
| 1 | `batch_01_season_2007` | delta 0: 109 rows | delta 0: 109 rows | delta 0: 109 rows | **v1 First season** |
| 2 | `batch_02_season_2008` | delta 1: 223 rows | delta 1: 223 rows | delta 1: 223 rows | **v2 Second season** |
| 3 | `batch_03_scale_recalibrated` | delta 2: 223 rows, 2007 masses corrected | not ingested, stays delta 1 | delta 2: 223 rows, new masses, same sexes | **v3 Scale recalibrated** (pinned) |
| 4 | `batch_04_season_2009` | delta 3: 342 rows | delta 2: 342 rows | delta 3: 342 rows | **v4 Three seasons** |
| 5 | `batch_05_sex_completed` | not ingested, stays delta 3 | delta 3: 342 rows, 9 sexes filled | delta 4: 342 rows, same masses, new sexes | **v5 Sex records completed** |

Steps 3 and 5 are the ones that matter. Each moves **one** dataset with **the
same row count** as before, while the other dataset stands still. A read that
silently serves current data, or pins one collection and not the other, is
visible there and nowhere else: row counts alone cannot tell delta 1 from delta
2 of `physical_features`, or delta 2 from delta 3 of `demographic_data`.

**The join at steps 3 and 5.** Those steps ingest one collection
(`--data-collection-tag`), but the CLI runs every persisted join after
processing, whatever the tag names, so the join is rebuilt from both tables as
they now stand. One input moved, so its rows changed and it gets a new commit:
delta 2 carries the recalibrated masses and the census it already had, delta 4
the completed sexes and the masses it already had. Same row count both times,
which is what makes the join's own pins as visible as the tables'. It is never
a no-op duplicate: `persist_joined_table` compares the rows it is about to
write with the table's (ignoring `join_timestamp` and row order) and writes
nothing when they are the same and the server already records that commit.
`depictio data join --overwrite` on the finished demo shows it: "Joined rows
unchanged, Delta table left at version 4".

So the stamps each dashboard version records are:

| version | `physical_features` | `demographic_data` | `penguins_complete` (join) |
|---|---|---|---|
| v1 First season | 0 | 0 | not read |
| v2 Second season | 1 | 1 | 1 |
| v3 Scale recalibrated | **2** | **1** (held) | **2** (moved with the measurements) |
| v4 Three seasons | 3 | 2 | 3 |
| v5 Sex records completed | **3** (held) | **3** | **4** (moved with the census) |

v1 holds no component on the join, so it does not stamp it. From v2 on the
join's stamp ascends at every version, because every step moves one of its
inputs.

## The data

`generate_batches.py` reads `../penguins/data/run_*/` (the palmerpenguins
observations shipped with the plain `penguins` project), merges the two files
per bird and writes five batches under `batches/`. Each batch directory is the
**complete** state of the survey at that step, one run per season:

```
batches/batch_04_season_2009/
  season_2007/  physical_features.csv  demographic_data.csv
  season_2008/  ...
  season_2009/  ...
```

| file | columns |
|---|---|
| `physical_features.csv` | individual_id, species, island, year, bill_length_mm, bill_depth_mm, flipper_length_mm, body_mass_g |
| `demographic_data.csv` | individual_id, species, island, year, sex |

`species`, `island` and `year` are in both files on purpose. A dashboard
filter reaches another collection through a column of the same name, so these
three are what let one Species, Island or Season filter narrow both datasets
and the join (see "Design notes" for why there is no link).

The join, `penguins_complete`, is an inner join on `individual_id` (plus
`depictio_run_id`, the season, added automatically since both tables have it).
It keeps the measurement columns, adds `sex`, and stamps a `join_timestamp`.

**Two corrections are synthetic** and do not exist in the real dataset:

- **Batch 3** multiplies every 2007 body mass by 1.05 and adds a seeded jitter
  of up to 20 g either way, as if the 2007 scale had been found to read low.
  `demographic_data.csv` is byte-identical to batch 2.
- **Batch 5** gives the 9 birds with no recorded sex one, imputed from body mass
  (heavier than their species' median of sexed birds: male, else female).
  `physical_features.csv` is byte-identical to batch 4.

Everything else is the real data. Regenerate with (fixed seed, byte-identical
output):

```bash
python depictio/projects/init/penguins_versioned/generate_batches.py
```

`data/` is the staging directory the project's `locations` point at.
`stage_batch.py N` copies one batch into it, replacing what was there; it is
gitignored except for a `.gitkeep`.

## The dashboard versions

Generated by `regenerate_dashboards.py`, because what makes them useful is a
property of the set. `--check` asserts it.

| version | tabs | components | what changed |
|---|---|---|---|
| v1 First season | 1 | 6 | Overview: two cards, a Species `Select`, a bare box of mass by species, a flipper/mass scatter |
| v2 Second season | 2 | 15 | box now by **season**, coloured by species; Select becomes **MultiSelect**; a Season **RangeSlider**; Sex recorded and Species mix cards; a row on the **join** (Body mass by sex, and a mean-mass card with a sex donut); new tab **Islands & Seasons** |
| v3 Scale recalibrated | 2 | 16 | only `physical_features` components change: box becomes **violin**, scatter gains a **trendline**, mean mass card gains a **trend** layout, a mass histogram is added. The join row is unchanged |
| v4 Three seasons | 2 | 19 | renamed to "Palmer Penguins: Three Field Seasons", **brand theme**, regrouped into **sections** (the Cohort filters are persistent, so they reach the Islands tab; the join row gets a **Joined** section), scatter **axes change** to bill length vs depth, a body-mass filter, a measurements table, a mass-by-island box on the tab |
| v5 Sex records completed | 3 | 22 | only `demographic_data` components change (Sex recorded card, Sex by species chart); new tab **Census records** with a sex filter and the census table. The Joined section is unchanged |

The layout mirrors the data. In v3 every component reading `demographic_data`
is exactly as it was in v2, and in v5 every component reading
`physical_features` is exactly as it was in v4. Their component history across
that step shows the same definition on the same data, which is the right answer
and the control for the components that did change. Components that follow the
whole story: **Body mass by ...** (`fig-mass`: bare box, box by season, violin,
notched box), the mass card (`card-mass`: mean, median, mean with trend, median
with box plot), the flipper scatter (`fig-morph`), Birds measured, Sex recorded,
and Sex by species.

The two components on the join (`fig-mass-by-sex`, `card-joined`) are the third
case: the **same definition on different data**. They are left exactly as they
were across v2 to v3 and across v4 to v5 (`--check` asserts it), and at both
steps the join moved, with the measurements and then with the census. Their
history there shows the join following whichever input moved, and nothing else.

Tab titles never change between versions: an import matches a child tab by its
title, so a renamed tab would be imported as a new one beside the old one.

## Building it

### On a host running `depictio local up`

From the repository root, with `DEPICTIO_LOCAL_HOME` exported if the local
server does not use the default home:

```bash
.venv/bin/python depictio/projects/init/penguins_versioned/rebuild_demo.py --server local
.venv/bin/python depictio/projects/init/penguins_versioned/rebuild_demo.py --server local --verify
```

The rebuild prints the editor URL at the end
(`http://127.0.0.1:<port>/dashboard-edit/<id>`). The dashboard id changes on
every rebuild: the import endpoint always mints a new id, so the script finds
the dashboard by its `source_key` instead.

`project.yaml` keeps the container path in `locations`, like every other init
project. On a host the script writes a temporary copy with the `--data-root`
path in its place and ingests from that; the committed file is never touched.

| flag | default | |
|---|---|---|
| `--server` | `$DEPICTIO_CLI_CONFIG_PATH`, else `local` | `local` or a CLI config file |
| `--data-root` | `data/` next to the script | staging directory the batches are copied into |
| `--upto N` | 5 | build batches 1..N only (they only make sense in order) |
| `--verify` | | check the current state and change nothing |
| `--teardown-only` | | delete the demo and exit |
| `-v` | | stream the CLI output |

### Docker compose

Inside the backend container, where `/app/...` resolves (pass the CLI config
your deployment uses):

```bash
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env \
    exec depictio-backend \
    python /app/depictio/projects/init/penguins_versioned/rebuild_demo.py \
    --server /app/depictio/.depictio/cli_local.yaml
```

### What the script does

1. Deletes the project if it exists. That cascades to its Delta tables (the
   join's included, and their S3 objects), runs, files, dashboards and version
   ledgers, so the fixed ids start from an empty history.
2. For each step: `stage_batch.py N`, then `depictio ingest` (with
   `--update-config` from step 2 on, and `--data-collection-tag` at steps 3 and
   5; every ingest ends by rebuilding the join), then imports
   `dashboards/vN_*.yaml` under a fixed `source_key`, then
   names the version with `POST /dashboards/{id}/versions` (and pins v3). An
   import is itself a captured change, so naming labels that state rather than
   writing a second version: the timeline holds exactly five entries.
3. Runs `--verify`.

The interleaving is not optional. A dashboard version stamps the Delta version
each collection is at **when it is captured**. Ingest all five batches first
and every version stamps the newest commits: labels, counts and stamps all look
right, and "this version's data" quietly shows the complete survey.

Steps 3 and 5 pass `--data-collection-tag`. A plain re-ingest rewrites every
collection with a new commit even when its rows did not change, so the held pin
would become a new, identical commit and "only one dataset moved" would be
false in the one place it is recorded.

## What to try in the UI

All of it is in **edit mode** (`/dashboard-edit/<id>`), from the **Settings**
modal:

- **History**: five named versions, v3 pinned. Preview opens the version
  read-only in the viewer (`/dashboard/<id>?version=<version_id>`), drawn on
  the data that version stamped.
- **Data version**, one collection at a time: pin `physical_features` to
  delta 1 and then delta 2. The Body mass charts change (the 2007 groups move
  up) while Birds measured stays at 223 and every `demographic_data` card stays
  put. Then pin `demographic_data` to delta 2 and delta 3: Sex recorded goes
  from 333 to 342 while every body-mass chart stays put.
- **Data version**, as of a dashboard version: pick v2, *Use this data*, then
  v3. Same birds, same census, different body mass, because v3 stamped a new
  `physical_features` commit and the same `demographic_data` one. The join row
  moves with the body mass: v3 stamped a new join commit too.
- **Data version** on the join: pin `joined_penguins_complete` to delta 1 and
  then delta 2. *Body mass by sex* shifts up (the 2007 masses) while its sex
  split stays put; then delta 3 and delta 4: the birds with no sex leave that
  group for female or male while the masses stay put.
- **Component history** (component menu): open it on *Body mass by ...* to see
  a bare box become a seasonal box, a violin, then a notched grouped box, each
  on its own version's data. Open it on *Sex recorded* across v2 and v3: the
  same card on the same data, the control. Open it on *Body mass by sex* (the
  join): one definition from v2 to v3 and from v4 to v5, and the chart still
  moves at both steps, because its data did.
- **Restore** v1 and then v5 from History: the family goes from three tabs to
  one and back (restore deletes the tabs a version does not hold and recreates
  the ones it does). Restoring writes new versions, so rerun `rebuild_demo.py`
  for a clean five-entry timeline afterwards.

## Verifying

`--verify` checks, against the running server:

- Delta commits: `physical_features` holds 109 / 223 / 223 / 342 rows,
  `demographic_data` 109 / 223 / 342 / 342, and the join 109 / 223 / 223 / 342
  / 342 (each registered with its Delta version: a join without one would show
  no commits here at all).
- Five named versions in order, with their tab and component counts, v3
  pinned, and **each collection's exact stamped delta version and row count**
  (the table above), so a batch ingested out of order fails loudly. v1 must not
  stamp the join, and the join's stamps must ascend from v2 on.
- Pinned reads (`bulk_compute_cards` with `data_versions`) of every commit of
  each dataset and of the join: bird count, mean body mass and sex count,
  compared with the values computed from the batch files themselves (for the
  join, by joining them the way the CLI does).
- `as_of_version` on each stored version: v2 to v3 moves body mass only, v4 to
  v5 moves the sex count only, for the tables and for the join alike. A stale
  version id is a 400.
- The same flat step through `render_table` and `render_figure`: 223 rows at
  delta 1 and delta 2 of `physical_features`, different total body mass, and
  the same through the join's figure.

```
  Dashboard versions (each collection's stamped Delta version and rows)
    version                          tabs comps   physical_features    demographic_data     penguins_complete (join)
    v1 First season                     1     6   delta 0  109 rows    delta 0  109 rows    -
    v2 Second season                    2    15   delta 1  223 rows    delta 1  223 rows    delta 1  223 rows
    v3 Scale recalibrated [pinned]      2    16   delta 2  223 rows    delta 1  223 rows    delta 2  223 rows
    v4 Three seasons                    2    19   delta 3  342 rows    delta 2  342 rows    delta 3  342 rows
    v5 Sex records completed            3    22   delta 3  342 rows    delta 3  342 rows    delta 4  342 rows
    -> penguins_complete stamps ascend ([1, 2, 3, 4]): it moved with either input

  as_of_version: penguins_complete (the join), read back through each version's stamp
    v1 First season            does not read the join
    v2 Second season           delta 1  birds  223  mean mass  4197.20 g  sex recorded  216
    v3 Scale recalibrated      delta 2  birds  223  mean mass  4297.35 g  sex recorded  216
    v4 Three seasons           delta 3  birds  342  mean mass  4267.06 g  sex recorded  333
    v5 Sex records completed   delta 4  birds  342  mean mass  4267.06 g  sex recorded  342
    -> v2 -> v3: the join's body mass moved with physical_features, its sexes held
    -> v4 -> v5: the join's sexes moved with demographic_data, its body mass held
```

## Design notes

- **The join records its provenance.** `persist_joined_table`
  (`depictio/cli/cli/utils/joins.py`) registers each commit with the Delta
  version it wrote, the commit timestamp and the row count, exactly as a table
  ingest does (`commit_provenance` in `deltatables.py`), and stamps depictio's
  commit metadata into the Delta log. Without it the join's aggregation record
  had no `delta_version`, every dashboard version stamped it `none`
  (`no_delta_version_recorded`), and a dashboard on the join time-travelled its
  layout over today's data. `--verify` would now fail on that at the first
  check: the join would show no Delta commits.
- **The join moves with either input, and only then.** It is rebuilt at every
  ingest; a rebuild whose rows (ignoring `join_timestamp` and row order) equal
  the stored table's writes nothing, as long as the server already records that
  commit. In this story every step moves one input, so the join has five
  commits; the no-op path is what keeps a later ingest of an unrelated
  collection, or a bare `depictio data join --overwrite`, from adding a sixth.
- **No link** between the two datasets. Link resolution
  (`depictio/api/v1/filter_links.py`) reads the source collection live, so in a
  pinned view a filter would be resolved against current data. Shared column
  names do the same job without that gap; the cost is that the Census records
  tab's Sex filter narrows `demographic_data` only.
- **Fixed ids** for the project, workflow, collections and the join's
  collection (`...a005`, the join's `id` in `project.yaml`), all with the prefix
  `56284517418915ace150`, used nowhere else in the repository. Dashboards cannot
  have one: the import endpoint mints a new dashboard id.
- One module, `penguins_story.py`, holds the ids, the steps and the expected
  counts; every script reads from it.
