# Dashboard session annotations: design

## Résumé (FR)

Depuis un dashboard aux données figées, le bouton « Metadata » du dock ouvre une grille sur les
tables de métadonnées du projet (samplesheet, metadata sheet), où l'on ajoute des
annotations par échantillon (par exemple `réponse` = *répondeur* / *non-répondeur*). Chaque valeur
devient un groupe du panneau Analysis existant, qui sait déjà filtrer, colorer et scinder les
graphiques. La vraie table ne change pas. Les annotations restent dans le navigateur pour un compte
temporaire, et sur le compte pour une vraie connexion. Un fichier déposé sur le dashboard est lu
dans le navigateur et n'est jamais envoyé au serveur. Les owners et editors peuvent aussi écrire
réellement : édition des cellules et bouton « Save to table ». Seule une table de métadonnées
liée aux données par un Link (pas un Join), de 10 000 lignes au plus, peut être annotée.
Une colonne de labels peut être **partagée sur le dashboard** : tous ses lecteurs la voient en
lecture seule et peuvent la copier dans leurs propres labels ; seuls un editor du projet ou le
propriétaire du dashboard (une copie, par exemple) la modifient. Pour une table de pipeline,
**Export** télécharge la table avec les colonnes de labels, à remettre dans la feuille de
métadonnées du pipeline. Le panneau Analysis reste une vue temporaire : couleurs, groupes et
comparaisons dans les cartes ne sont jamais enregistrés avec le dashboard.

## Goal

A reader of a dashboard whose data is frozen wants to add conditions or annotations for the
duration of their work and compare the resulting groups, without changing the dataset. Owners and
editors can also make the change real.

Success: from a dashboard, a reader labels samples in a grid and, without leaving the page, sees
every linked chart filter, colour or split by those labels. A file they drop there never reaches
the server.

## What exists and is reused

- **Selection groups** (`packages/depictio-react-core/src/selectionGroups.ts`, UI in
  `components/interactive/SelectionGroupsPanel.tsx`, opened by
  `depictio/viewer/src/components/GroupingHeaderControl.tsx`). A group is a named colour plus
  `{dcId, columnName, values}`. Groups persist in localStorage per dashboard, project into ordinary
  `MultiSelect` filters at the fetch boundary (`groupsToFilters`), and drive server-side colouring
  and small multiples (`groupsRenderPayload`, `sanitize_group_defs` in
  `depictio/api/v1/services/figure/groups.py`). Cross-collection reach goes through DC links.
  Per-tile reach is reported by `groupReach.ts`.
- **Table editor** (`depictio/viewer/src/projects/detail/TableEditor.tsx`) and
  `POST /datacollections/{id}/merge_file` (`table_merge.py`).
- **Per-viewer server state** (`dashboards_endpoints/filter_state_routes.py`,
  `filter_state_cascade.py`), the model for account storage. That module is already exempt from
  the publish lock as "per-viewer filter state".

No change is needed in the render pipeline, the cache keys or the Delta tables for session use.

## Scope: which tables

Revised after review: labels on any table were confusing, and a table built by a CLI join
cannot follow labels keyed on one of its inputs. Only a **metadata table linked to the data**
can be labelled. The rule lives in one function, `classify_tables` in
`dashboards_endpoints/annotation_tables.py`. A table is eligible when all of these hold:

1. it is a table;
2. it is the `source_dc_id` of at least one enabled link; its key columns are the distinct
   `source_column`s of those links (labels reach the charts through those links);
3. it is not derived: no `config.join` or `config.transform`, `source` absent or `native`,
   and not named as a join's `result_dc_id` or `id`;
4. it is not a join input: its tag (or `workflow.tag` when the join reference is scoped) is in
   no `project.joins[].left_dc` / `right_dc`;
5. its `metatype` is absent or "metadata", case-insensitive. A pipeline samplesheet often
   declares none (ampliseq); "Aggregate" tables are results, not metadata;
6. it has at most `MAX_EDITABLE_ROWS` (10,000) rows, the size the grid loads whole.

A project can have several eligible tables: nf-core pipelines such as ampliseq have a
mandatory `samplesheet` and an optional `metadata` sheet, both link sources. Each label
column belongs to one table.

`GET /dashboards/annotations/{dashboard_id}/tables` lists every table of the project with
`eligible`, a stable `code` (`not_linked`, `derived_table`, `join_input`, `not_metadata`,
`no_data`, `table_too_large`) and a `reason` to show. It is open to every reader, temporary
and anonymous ones included, since they label in the browser. A `PUT` naming an ineligible
table, or a key column none of its links uses, is a 422; it checks structure only and reads no
table.

## Levels

- **N0 (this PR):** labels become selection groups, which filter, colour and split the
  dashboard's existing charts.
- **N2 (this PR):** owners and editors write labels or cell edits into the table
  (**Save to table**), where the table's own rules allow it.
- **N1 (follow-up issue):** temporary comparison figures built from labels, from a closed list
  of types with validated parameters; no free definition and no code mode.

## User experience

Revised after review: tabs inside Analysis (Groups / Labels) were hard to read, and a panel
that edits a table is not the place for groups. The two are separate again.

1. A **Metadata** button in the dock, shown only when the project has an eligible table. It
   opens a docked, non-modal drawer (760 px) built like Analysis. Metadata and Analysis share
   the right edge, so opening one closes the other. Escape does not close it: in a grid cell it
   cancels the edit. The button's badge counts label columns.
2. **Analysis** is groups only. A group derived from labels shows a tag icon; it cannot be
   renamed or deleted there ("Rename the label in Metadata.").
3. The panel's header row: the table (a segmented control when there are several, else its
   name), the key column (a select when its links use several, else "by {key}"), an info icon
   listing the project's other tables and why they cannot be labelled, and **Import**. A file
   can also be dropped on the panel.
4. One grid: the key, the label columns of that table, a **+** column that adds one, then the
   table's columns. Each label column's header holds a menu with every action on it: compare in
   the charts (one at a time; a dot marks it; the 24-group budget disables it with the reason),
   rename, keep on my account (for a label column from a file), save to table, delete.
5. Owners and editors of a table a user added edit its cells in place. Changed cells turn
   yellow and a bar under the grid offers Discard or **Save to table**, which writes them in one
   version and re-renders the dashboard. Everyone else sees those columns read-only.
6. Text appears only when it says something: browser storage, labels compared from a file, an
   error, a refusal.

| | Labels stored | Typing and paste | Import |
| --- | --- | --- | --- |
| Temporary or anonymous account | browser | yes | as labels, browser only |
| Signed-in account | account (file labels: browser, until kept) | yes | as labels, or into the table for owners and editors |

"Signed-in" means any non-temporary, non-anonymous account (OIDC, password) and single-user mode.

## Data model

```ts
interface DashboardAnnotations {
  version: 2;
  columns: {
    id: string;
    name: string;        // unique across tables
    dcId: string;        // the metadata table
    keyColumn: string;   // one of its links' source columns
    values: Record<string, string>;
  }[];
  activeColumnId: string | null;
}
```

Version 1 (one table per dashboard) was never merged; a stored version 1 document reads as
absent and the next save replaces it. Caps count columns across all tables.

The annotations are the source of truth. Groups are derived from them and are never edited back
into them.

### Deriving groups

- `SelectionGroup` gains an optional `annotationColumnId`.
- Changing a label or the active column replaces only the groups carrying an
  `annotationColumnId`. Groups made by lasso or table selection are left alone.
- For the active column, one group per distinct non-empty label:
  `{name: label, dcId, columnName: keyColumn, values: keys}`, taken from that column. A label keeps its colour and
  `filterActive` across recomputation.
- The server keeps at most `MAX_GROUPS` (24) groups in all, lasso and table groups included, and
  drops the rest without saying so (`sanitize_group_defs`). A column cannot be the active column
  when its distinct labels plus the other groups exceed 24; the control says why.

The derivation is a pure function in `packages/depictio-react-core/src/annotationGroups.ts`.

## Storage

Keyed on the dashboard family's main tab, since annotations belong to the whole dashboard.

- **Browser:** localStorage key `depictio.annotations.<dashboardId>`, wrapped in try/catch like
  `readSelectionGroups`.
- **Account:** new module `dashboards_endpoints/annotation_routes.py`, modelled on
  `filter_state_routes.py`, on a new collection `dashboard_annotations` with a unique index on
  `(user_id, dashboard_id)`.
  - `GET`, `PUT`, `DELETE /dashboards/annotations/{dashboard_id}`.
  - Only the caller's own document. Requires read access to the dashboard, re-checked on every
    call. 403 for a temporary or anonymous account outside single-user mode. Single-user mode
    resolves every call to the shared anonymous user, which is then accepted.
  - The id is normalised to the family main tab, so a child tab's id reaches the same document.
  - Pydantic model with `extra="forbid"`. Caps: 1 MB of serialised payload (a model
    validator, as for filter state: the API has no body-size middleware), 20 columns, 10,000 keys
    per column, 80 characters per label. 80 is the server's group `MAX_NAME_LENGTH`: a longer
    label would be cut, and two labels sharing their first 80 characters would collapse into one
    group.
  - Deletion follows the cascades of `filter_state_cascade.py` (dashboard, project), plus user
    deletion and the temporary user cleanup. No user-keyed cascade existed before, so
    `delete_annotations_for_user` is added and called from both.
  - Classified `EXEMPT` in `test_publish_lock_routes.py` through the module-level per-viewer rule.
- Saving is debounced. A failed account save keeps the panel's state and shows a warning; it is
  never silently dropped.

## Reading the grid

- Rows come from `fetchDataCollectionPreview`, limit 10,000. The preview task clamped `limit` to
  1,000; the clamp is raised to 10,000 (callers default to 100, so none of them reads more). A table with more rows is refused
  with a message asking for a smaller table, because a truncated list of samples would look
  complete.
- A table with several rows per key shows the first row per key, and only the context columns
  that hold one value per key.
- **Pinned views:** when the dashboard renders a past version (`?version=`), the grid must read
  the same Delta version, passing `version`. If the pin for that collection cannot be resolved,
  the panel says so and does not open the grid. It never shows current rows as if they were the
  past. Pins are read through the existing `POST /data_version_status/{id}` and `dataVersionBody`.

## Input in the browser

- A dropped CSV or TSV is parsed in the browser with `papaparse` (already locked for
  `packages/tool-studio`; declared in `depictio-react-core`), with a 5 MB limit. The delimiter
  follows the extension, else the header line, as in `tool-studio`'s `parseFixture.ts`. No request carries the file.
  Excel and Parquet are out of scope.
- A file is dropped on the grid or picked with **Annotate from file**. Like the table editor's
  file merge, it opens a preview with three modes before anything changes: **Add columns** (new
  columns become annotations), **Fill missing** (labels go into same-named annotations where a
  row has none; differing labels are counted and kept) and **Replace** (the file becomes the
  whole set). The drop overlay is the editor's.
- **What a dropped file yields stays in the browser**, for every account. Its annotations are
  marked `local` and kept under the browser key even when the account stores annotations; the
  account copy never holds them, and a file merged into an account annotation makes it local.
  A cloud icon on one sends it to the account, the reader's explicit choice. While a local
  annotation drives Compare by, its labels and keys go with each chart request (colouring and
  splitting are server-side), and the panel says so; nothing is stored there.
- A dropped file is matched on the key column by the same rule as `table_merge.py`: text
  comparison, integer floats as integers, file values unique. Each other column of the file
  becomes an annotation. Unmatched rows are reported and left out.
- **Paste needs its own handler:** clipboard paste is an AG Grid Enterprise feature and the viewer
  uses Community. The panel handles the `paste` event and writes tab-separated values from the
  focused cell downward.

## Sharing on the dashboard

Labels are personal by default. A column can be **shared on the dashboard**: it is stored in the
main tab's `shared_labels` (same shape and caps as a reader's own column), and every reader of
the dashboard sees it, read-only.

| | Own labels | Share / edit shared | Copy shared to mine | Export | Save to table |
| --- | --- | --- | --- | --- | --- |
| Anonymous / temporary | browser | no | yes (browser) | yes | no |
| Viewer | account | no | yes | yes | no |
| Owner of the dashboard, no project role (a copy) | account | yes | yes | yes | no |
| Editor / owner of the project | account | yes | yes | yes | table a user added only |

- **Write path:** `PUT /dashboards/annotations/{id}/shared` replaces the family's shared
  columns. It needs `check_dashboard_mutation_permission(main_tab, user, "editor")` and an
  unlocked dashboard (409 when published; a copy of a published dashboard can share). Anonymous
  users outside single-user mode get 403. Tables are checked like a reader's own labels.
- **Read path:** `GET /dashboards/annotations/{id}/tables` returns `shared` and `can_share`.
  With `version_id` it returns that version's shared labels, read-only (404 for another
  family's version).
- **Read-only for readers (option A):** a reader compares by a shared column, or copies it into
  their own labels ("<name> (copy)") to change it. The choice of column to compare by stays
  personal, so `activeColumnId` may name a shared column (and is kept on the account even when
  the reader has no column of their own).
- **Versioning:** the route seeds a baseline and captures a version. Sharing, unsharing or
  deleting a column is an `explicit` version, so the state before it is restorable; an edit of a
  shared column's labels folds into the autosave window. `/save` never writes `shared_labels`,
  so the editor cannot overwrite labels shared meanwhile. `TabSnapshot.shared_labels` is recorded
  on the main tab only and hashed only when non-empty.
- **Migration:** bundles copy the raw documents, so shared labels travel with the dashboard.
- **No companion table.** A table Depictio writes beside a pipeline's would drift from it, and
  the pipeline's own statistics (ANCOM-BC, adonis) would never see its columns.
- **Export** downloads the selected table's rows with the chosen label columns, as a TSV built in
  the browser (no request carries it). Columns Depictio adds at ingest (`depictio_*`,
  `aggregation_time`) are left out. A table whose data lives elsewhere (a pipeline run, a URL,
  an ingest of unknown origin) refuses Save to table and points to Export: the columns go into
  the source sheet, and a re-run brings them in with the pipeline's statistics.
- **Analysis is temporary.** Its panel says so at the top: colors, groups and card comparisons
  stay in this browser and are never saved with the dashboard. "Compare in the charts" says the
  same.
- **Limitation:** the YAML (Lite) export does not carry shared labels; they hold collection ids,
  while Lite refers to collections by tag.

## Real writes

- Cell edits in the Metadata grid, enabled when `fetchTableEditStatus` answers `can_edit`. A
  pipeline table answers `pipeline_table`, so on nf-core projects only N0 is offered, and the
  menu says why.
- **Save to table** builds a CSV of `key,label` in the browser and calls `mergeTableFile` with
  `mode: add_columns`: dry run, a confirmation showing the report, then apply. Server rules are
  unchanged (owners and editors, a table a user added, not published). A name that already exists
  surfaces the report's `reason`. On success the annotation is removed from the session.
- Both are disabled on a pinned view, with the reason: a write would not appear there.
- After a real write on a live view the dashboard's components re-render through the existing
  refresh path (`triggerRefresh` in `App.tsx`; the write bumps `aggregation_version`, which salts
  the caches).

## Error handling

| Case | Behaviour |
| --- | --- |
| Key absent from the charts and no DC link | Groups are created; Analysis already reports that they reach nothing |
| Dashboard access lost | Account read answers 403; the panel shows no annotations |
| localStorage unavailable | Panel works for the session and says it will not be kept |
| Table replaced so some keys vanish | Annotations for missing keys are kept and counted, not shown as rows |
| Stale version on Save to table | The existing 409 handling offers a reload |

## Testing

- **pytest:** `test_annotation_routes.py` covers own document only, read access re-check, temporary
  and anonymous refusal, single-user mode, caps, `extra="forbid"` and cascades.
- **vitest** (`packages/depictio-react-core`): group derivation, including preserving colours and
  leaving manual groups untouched; key matching for dropped files; paste parsing.
- **Playwright:** annotate, compare by, charts narrow and colour; reload keeps the annotations; a
  dropped CSV sends no request containing the file; a temporary account sees the disabled controls;
  owner saves to table and the column exists.
- **Live** on `depictio local up`, using a dashboard with linked tables and a pinned `?version=`.

## Out of scope

- Multi-column keys.
- Shared labels in the YAML (Lite) export.
- Carrying a temporary account's annotations over when it signs in.
- The dashboard editor (`EditorApp`); the viewer only.
- Excel and Parquet in the browser.
- Tables produced by a join, or used as an input of one, and tables without a link.
- Temporary comparison figures (N1), tracked in a follow-up issue.

## Delivery

One PR, stacked on the table editing work it reuses.

## Settled during implementation

- `MAX_GROUPS` is 24 and counts every group; the label cap is the group name cap, 80.
- No CSV parser in the viewer; `papaparse` is reused from the workspace lock.
- A live view re-renders through `triggerRefresh`.
- `POST /data_version_status/{id}` already returns `delta_version`; no server change.
- Metadata and Analysis are not shown at once: both are right-hand panels. Opening one closes
  the other, and the second opens after the first has closed (280 ms), so the grid reflows once
  per swing.
- A dropped file is matched only against the selected table's label columns; a file column named
  like another table's labels is skipped and reported.
