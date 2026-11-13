# Changed since your last visit

> Engineering reference for issue #1397. A returning reader sees what moved
> since they last looked: new data, edited components, new comments. On
> compatible figures they also see which points or bars changed.

Off by default. Turn it on with
`DEPICTIO_DASHBOARD_VERSIONS_CHANGES_SINCE_ENABLED=true`. It then shows up as
`features.changes_since` in `/utils/server-info`. Every route answers 404 while
it is off.

## The reader mark

A *reader mark* (`reader_marks` collection, unique on
`(user_id, scope_kind, scope_id)`) is a snapshot of what one reader
acknowledged, for one dashboard family (`scope_kind="dashboard"`, keyed by the
main tab id) or one project. It holds:

- the dashboard version they saw: id, seq and content hash;
- per data collection, the Delta commit, depictio's aggregation counter and the
  row count; for MultiQC, the report set (keyed by the content-addressed S3
  location, with a signature of samples and size), the samples and the run tags;
- the newest comment and ingestion seen;
- for a project, the run tags each workflow had.

It is a snapshot, not a timestamp, for two reasons:

- An ingestion records no dashboard version.
- Several of the clocks involved are local (`datetime.now`):
  - `Aggregation.aggregation_time`;
  - `MultiQCReport.processed_at`;
  - ingestion runs.

Comparing ids and commit numbers from one source holds where comparing clocks
does not.

A mark is per-reader state, never content: writing one records no dashboard
version and needs only viewer permission. It does end the coalescing window of
the version it points at (`version_store.close_window`): an author's next
autosave then opens a new version instead of folding into the one the reader
saw, which would otherwise hide the edit from them. Deleting a dashboard or a project
deletes its marks.

### Who holds it

| Reader | Where the mark lives |
|---|---|
| Signed in | Server (`reader_marks`) |
| Anonymous, temporary or public-mode guest | Browser `localStorage`, key `depictio.changesSince.v1:<family id>`. The server returns `current_baseline` with every change set and the browser sends it back. |

### When it moves

- **First visit**: the baseline is the current state, so a first visit shows
  nothing.
- **Visit**: the viewer records a visit 10 s after the page opens.
- **Mark modes** (a reader preference, set in the What's new panel or in
  /profile):
  - `sticky` (the server default, `..._CHANGES_SINCE_MARK_MODE`): the baseline
    stays until *Mark as seen*;
  - `previous_visit`: every recorded visit moves it.
- **Mark as seen** with no keys moves the baseline. With component keys it
  dismisses those components only. A dismissal holds while the component's
  definition fingerprint and its collection's data token are unchanged.
- **Never moved by**:
  - the editor;
  - a `?version=` preview;
  - the read-only views `?since=<iso>` and `?before_run=<ingestion run id>`.

### Where the reader sees it

- **Dashboard**: a *What's new* key in the header's top bar, beside settings,
  theme and the bell, with the change count on its corner. It opens the list
  of changes.
- **Project page**: the same button among the page's header actions.
- **Lists**: the dashboard's and the project's lists and the bell share one
  look (`changes/feed.tsx`). Each change is a row: an icon for its kind, a
  title, one line of facts and a dimmed *by … · when* line. Names are words in
  that line, not chips.
- **New items**: a quiet dot marks them in Runs and in Activity, the same dot
  as an updated tile.

## What counts as a change

`POST /changes/dashboard/{id}` returns three sections:

- **Data**: per collection read by the family, it lists:
  - new Delta commits (+rows, new run tags);
  - MultiQC reports added, refreshed or removed, with new samples and new run
    tags;
  - failed ingestions.
- **Dashboard**: components added, edited or removed, and tabs added or
  removed. It compares the baseline version's tabs with the live documents,
  keyed `(tab_id, index)`. Placement keys are ignored, so a moved tile is not
  "edited". Each change is attributed to the version that made it (author,
  time, version id).
- **Comments**: new threads and replies.

The reader's own edits never count: versions they authored and comments they
wrote are excluded. Ingestions count whoever ran them. An ingestion runs on its
own, often from a pipeline holding the reader's token, so starting one is not
seeing what it did to the figures. On a single-user instance every ingestion
is the reader's.

If retention has pruned the baseline version, the diff starts from the newest
surviving version at or before it and says `approximate: true`.

`changed_component_keys` (`<tab_id>:<index>`) drives the "updated" dot. It
covers the components whose definition changed and those reading a collection
whose data changed.

## Figure before/after

`POST /changes/component_diff/{dashboard_id}/{component_id}` compares one
component's data at the baseline with now. It reads the Delta commit pinned at
the baseline and the live one, never the live data twice. The same filters
apply to both reads.

| Shape | Figures | Matched on |
|---|---|---|
| `points` | scatter, line, strip, 3D | a key column: the selection or hover column, then an id-like column, never an axis. Without one, (x, y) value pairs. |
| `groups` | bar, area, funnel (sum), histogram, ecdf (count), box, violin (median) | x and colour, the same reduction the chart draws |
| `samples` | MultiQC | the baseline report set against the live one |
| `rows` | advanced viz | the kind's id role (`feature_id_col`, `sample_id_col`, ...) |

Code-mode figures answer `supported: false`: arbitrary code gives no mapping
from a row to a mark.

In the viewer, the dot's menu offers two views:

- **Compare with last visit**: an overlay on the card. Rings mark new points,
  ghosts show where removed or moved points were, and outlines show a bar's
  previous value.
- **Before | Now**: a read-only side-by-side modal. *Before* renders through
  the preview contract: `definition_version` is the baseline version, and the
  data is pinned (`data_versions`, `report_sets`, or `delta_version` for
  advanced viz).

The viewer never writes and never changes the page's own pins.

MultiQC time travel by report set is what makes the MultiQC *Before* possible:

- `DataCollectionStamp.report_ids` records the set at save time;
- `report_sets` in a render request restricts it.

## Projects

- `POST /changes/project/{id}` returns the same kind of change set for a
  project page: new runs, refreshed collections, failed ingestions and changed
  dashboards.
- The Runs tab marks new runs and shows what each run produced:
  - ingestions, Delta commits and MultiQC reports;
  - *Compare* (`?before_run=`): the dashboard with what that run changed
    marked, each component's *Before | Now* drawing the data just before it;
  - *Layout before <run>* (`?version=`): the definition only. An ingestion
    records no dashboard version, so the preview's data is whatever that
    version's stamps pin, and its banner names the rest as latest.
- `GET /changes/project/{id}/timeline` feeds the Activity tab's History view:
  ingestions, dashboard versions and comments, newest first, paged by
  `before`. An ingestion opens its steps; the list refreshes every 3 s while
  one is running.
- Activity replaces the Ingestion report and Timeline tabs. Its other view is
  the latest ingestion's report. With the feature off, History is the
  ingestion run list it always was. `?tab=ingestion`, `?tab=timeline`,
  `#ingestion` and `#ingestion-history` still open it.

Runs are told apart because ingestion now records which run wrote what:

- `IngestionRun.run_tags`;
- `MultiQCReport.run_tag` and `ingestion_run_id`;
- `trigger="ui"` for Add data.

## Notifications

When an ingestion finishes (success or partial), the server publishes
`ingestion_finished` on the `project:<id>` event channel. Any reader who can
view the project may subscribe.

The sidebar bell does two things:

- it polls `GET /changes/inbox` every 60 s: the reader's marked dashboards and
  projects that have changes;
- it raises a toast on the live event.

Every item links to the dashboard, with its updates marked, or to the
project's Runs tab on that run. The bell needs a server-held mark, so it is
hidden for anonymous readers.

## Routes

All routes are under `/depictio/api/v1/changes/`. They are per-reader state,
so `test_publish_lock_routes.py` lists the whole module as exempt from the
publish lock.

| Route | Purpose |
|---|---|
| `POST /dashboard/{id}` | Change set (body: `baseline`, `dismissed` for anonymous readers; `since` or `before_run` for read-only views) |
| `PUT /dashboard/{id}/visit` | Record a visit |
| `PUT /dashboard/{id}/seen` | Mark all, or some components, as seen |
| `POST /project/{id}`, `PUT .../visit`, `PUT .../seen` | Same for a project |
| `GET /project/{id}/timeline` | Project timeline |
| `GET`, `PUT /prefs` | Mark mode |
| `GET /inbox` | Bell |
| `POST /component_diff/{dashboard_id}/{component_id}` | Figure before/after |

## Known limits

- **In-place MultiQC overwrite.** It keeps its S3 key, so its *Before* shows
  today's report. The diff still flags it as refreshed, through the signature.
- **Local-clock timestamps.** Ingestion runs, aggregations and MultiQC reports
  still use the local clock. The diff never compares them with a server clock.
  The project timeline orders them as received.
- **Sample truncation.** A mark tracks at most 5000 samples per collection;
  past that, new samples are counted but not listed.
