# Dashboard session annotations: design

## Résumé (FR)

Depuis un dashboard aux données figées, un panneau latéral ouvre une grille où l'on ajoute des
annotations par échantillon (par exemple `réponse` = *répondeur* / *non-répondeur*). Chaque valeur
devient un groupe du panneau Analysis existant, qui sait déjà filtrer, colorer et scinder les
graphiques. La vraie table ne change pas. Les annotations restent dans le navigateur pour un compte
temporaire, et sur le compte pour une vraie connexion. Un fichier déposé sur le dashboard est lu
dans le navigateur et n'est jamais envoyé au serveur. Les owners et editors peuvent aussi écrire
réellement : onglet « Edit table » et bouton « Save to table ».

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

## User experience

1. An **Annotate** button in the dashboard header opens a wide panel on the right. It does not
   block the page, so the charts stay visible and react.
2. The panel picks a table and a key column. Defaults: the first table the dashboard's components
   reference that has a column unique per row; that column as key. Both can be changed.
3. The grid has one row per key value, the table's columns as read-only context, and one column
   per annotation. The grid is AG Grid, as in the table editor.
4. **+ Add annotation** names a column. It is filled by typing, by pasting from a spreadsheet, or
   by dropping a CSV or TSV.
5. **Compare by** selects the annotation that drives the comparison; only one at a time, because a
   sample must not sit in two groups. Each distinct label becomes a group in the Analysis panel,
   where the existing controls filter, colour or split.
6. Owners and editors of a table a user added also get an **Edit table** tab (the table editor,
   real writes) and **Save to table** (the annotation becomes a real column).

| | Annotations stored | Typing and paste | Drop on the dashboard |
| --- | --- | --- | --- |
| Temporary or anonymous account | browser | yes | yes, browser only |
| Signed-in account | account (file annotations: browser, until kept) | yes | yes, browser only |

"Signed-in" means any non-temporary, non-anonymous account (OIDC, password) and single-user mode.

Controls a temporary account cannot use are disabled, not hidden, with the reason shown.

## Data model

```ts
interface DashboardAnnotations {
  version: 1;
  dcId: string;
  keyColumn: string;
  columns: { id: string; name: string; values: Record<string, string> }[];
  activeColumnId: string | null;
}
```

The annotations are the source of truth. Groups are derived from them and are never edited back
into them.

### Deriving groups

- `SelectionGroup` gains an optional `annotationColumnId`.
- Changing a label or the active column replaces only the groups carrying an
  `annotationColumnId`. Groups made by lasso or table selection are left alone.
- For the active column, one group per distinct non-empty label:
  `{name: label, dcId, columnName: keyColumn, values: keys}`. A label keeps its colour and
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

## Real writes

- The **Edit table** tab mounts `TableEditor`, shown when `fetchTableEditStatus` answers `can_edit`.
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
- Sharing annotations with other users.
- Carrying a temporary account's annotations over when it signs in.
- The dashboard editor (`EditorApp`); the viewer only.
- Excel and Parquet in the browser.

## Delivery

One PR, stacked on the table editing work it reuses.

## Settled during implementation

- `MAX_GROUPS` is 24 and counts every group; the label cap is the group name cap, 80.
- No CSV parser in the viewer; `papaparse` is reused from the workspace lock.
- A live view re-renders through `triggerRefresh`.
- `POST /data_version_status/{id}` already returns `delta_version`; no server change.
- Annotate and Analysis are not shown at once: both are right-hand panels. Annotate shows the
  derived groups and opens Analysis.
