# Dashboard session annotations — implementation plan

## Context

Spec: `docs/superpowers/specs/2026-11-09-dashboard-session-annotations-design.md` (validated).
From a dashboard viewer, a reader labels samples in an AG Grid side panel. Each label of the
"Compare by" column becomes a selection group in the existing Analysis panel, which filters,
colours and splits the charts. The data does not change. Owners and editors can also write for
real through `TableEditor` and `merge_file`. A file dropped on the dashboard never leaves the browser.

Branch: `feat/dashboard-annotations-m8v0sa`, already stacked on `feat/project-data-and-table-editing`
(`fc1f6ce`) with only the spec commit on top. One PR, in English, based on
`feat/project-data-and-table-editing`.

Format follows writing-plans (not installed here): small test-first tasks, one commit each,
`pre-commit run --all-files` after every code change (shellcheck failures on unrelated scripts
are pre-existing and are reported, not fixed). Only the tests that cover each change are run.

## Resolved "To confirm" points (verified in code)

| Point | Finding | Decision |
| --- | --- | --- |
| `MAX_GROUPS` | 24 (`services/figure/groups.py:80`). `sanitize_group_defs` **truncates silently**, counts manual groups too, and cuts names to `MAX_NAME_LENGTH = 80` | Active column allowed only if `distinct labels + other groups ≤ 24`. Label cap **80**, not 200 (two labels sharing an 80-char prefix would collide and one group would vanish) |
| CSV parser | `papaparse` 5.7.0 already locked, used by `packages/tool-studio/src/catalog/parseFixture.ts` | Add `papaparse` + `@types/papaparse` (same ranges) to `packages/depictio-react-core`. Reuse the `sniffDelimiter` rule |
| Re-render after a write | `triggerRefresh()` / `refreshTick` in `depictio/viewer/src/App.tsx:538,1119` already drive every renderer. `commit_table_frame` bumps `aggregation_version`, so the caches are salted | Call `triggerRefresh()` after an apply |
| Pinned Delta version | `POST /data_version_status/{id}` already returns `delta_version` per collection (`fetchDataVersionStatus`, `api.ts:1390`) | No server change. Status other than `pinned` with an int → fail closed |
| Preview row limit (new) | Server clamps `limit` to 1000 (`celery_tasks.py:929`) | Raise the clamp to 10,000 (user's choice) |

Other facts used:
- Single-user mode resolves data calls to the shared anonymous user (`get_user_or_anonymous`).
  Account storage therefore accepts the anonymous user **only** in single-user mode.
- No user-keyed cascade exists anywhere: one is added for annotations.
- `/auth/me/optional` gives `user.is_temporary` and `is_single_user_mode`. Client rule: account
  storage iff `isSingleUserMode || (user && !user.is_temporary)`; otherwise browser storage.
- `useSelectionGroups` has no bulk setter; one is added.

## Tasks

### 0. Spec update (docs only)
Edit the spec: papaparse instead of a hand-written parser, 10,000 clamp raised server-side,
label cap 80 and the 24-group budget including manual groups, single-user storage under the
anonymous user, user-deletion cascade. Commit `docs: settle open points of the annotations design`.

### 1. Preview limit 10,000 (backend)
- Test first: extend the existing preview test (locate with `grep -rn "preview" depictio/tests/api/v1 -l`)
  asserting `limit=10000` returns 10,000 rows and `limit=20000` is clamped to 10,000.
- `depictio/api/v1/celery_tasks.py:929`: `min(..., 10_000)` through a named constant
  `MAX_PREVIEW_ROWS`. Check the GET route at `deltatables_endpoints/routes.py:1724` adds no extra clamp.

### 2. Model `DashboardAnnotations` (backend, `ty`-gated dir)
- New `depictio/models/models/dashboard_annotations.py`, modelled on `dashboard_filter_state.py`:
  - `AnnotationColumn(id, name, values: dict[str, str])`, `DashboardAnnotationsPayload(version: Literal[1], dc_id, key_column, columns, active_column_id)`, all `extra="forbid"`.
  - Caps: 20 columns, 10,000 keys per column, 80 chars per label, 1 MB of serialised JSON
    (same validator pattern as `MAX_FILTERS_JSON_BYTES`). Unique column ids; `active_column_id`
    must name a column.
  - `DashboardAnnotationsBeanie` with collection `dashboard_annotations`, unique
    `IndexModel([("user_id",1),("dashboard_id",1)])`.
- Tests `depictio/tests/models/test_dashboard_annotations.py`: caps, extra keys, bad active id.
- `uv run --extra dev ty check depictio/models/` must stay at zero.

### 3. Routes `annotation_routes.py`
- `depictio/api/v1/endpoints/dashboards_endpoints/annotation_routes.py`: `GET`, `PUT`,
  `DELETE /{dashboard_id}`, mounted at `prefix="/dashboards/annotations"` in `endpoints/routers.py`
  (no collision: checked against the `/{id}/yaml|json|versions` patterns).
- `_authorize` copied from `filter_state_routes.py` (404 / 403 via `check_project_permission(..., "viewer")`),
  run on every call. The id is normalised to the family main tab (`parent_dashboard_id` or itself).
- Refusal 403: `is_temporary`, or `is_anonymous` outside `settings.auth.is_single_user_mode`.
- Own document only: queries always filter on `user_id == current_user.id`.
- Register the Beanie model in `services/lifespan.py`, add the sync handle in `db.py`.
- Tests `depictio/tests/api/v1/endpoints/dashboards_endpoints/test_annotation_routes.py`, with the
  mongomock-Beanie + `_FakeDashboards` pattern of `test_filter_state_routes.py`: round trip, other
  user's doc invisible, 404/403, temporary 403, anonymous 403, anonymous OK in single-user mode
  (monkeypatch the setting), child-tab id maps to the main tab, payload caps → 422.
- `tests/api/v1/test_publish_lock_routes.py`: add `"dashboards_endpoints.annotation_routes": "per-viewer session annotations"` to `EXEMPT_MODULES`.

### 4. Cascades
- `dashboards_endpoints/annotation_cascade.py`: `delete_annotations_for_dashboards(ids)`,
  `delete_annotations_for_project(project_id)`, `delete_annotations_for_user(user_id)`, best-effort like
  `filter_state_cascade.py`.
- Call sites: next to each filter-state cascade (`delete_dashboard` routes.py:1459, `delete_tab`
  routes.py:1674, `_cascade_delete_project` projects routes.py:228); user side in `delete_user`
  (`user_endpoints/routes.py:1486`), `delete_user_from_db` (`user_endpoints/utils.py:146`) and
  `_cleanup_expired_temporary_users` (`user_endpoints/core_functions.py:198`).
- Tests `test_annotation_cascade.py` (mongomock), plus one assertion per call site that the cascade runs.

### 5. Pure logic in `packages/depictio-react-core` (vitest, node env)
- `package.json`: add `papaparse` / `@types/papaparse`; `pnpm install` updates `pnpm-lock.yaml`.
- `src/annotations.ts`: `DashboardAnnotations` type, `readAnnotations`/`writeAnnotations`
  (`depictio.annotations.<id>`, try/catch, returns `{ok:false}` when storage is unavailable),
  `validateAnnotations`.
- `src/annotationGroups.ts`: `deriveAnnotationGroups(annotations, existingGroups, palette)` returns
  the new group list. It replaces only the groups carrying `annotationColumnId`, keeps colour and
  `filterActive` by label, skips empty labels, and avoids collisions with manual group names and
  the server's "Other" label. Add `annotationColumnBudget(column, otherGroups)` → `{ok, reason}` for the 24 cap.
- `src/annotationInput.ts`: `parseDroppedTable(name, text)` (papaparse, sniffed delimiter, 5 MB check
  by the caller on `File.size`), `matchOnKey(fileRows, keyColumn, tableKeys)` mirroring
  `_as_key` of `table_merge.py:85` (blank/NaN → none, bool → "true"/"false", integer float →
  int text, else trimmed text; duplicate file keys refused), `parsePastedBlock(text)` (TSV, CRLF,
  quoted cells).
- `selectionGroups.ts`: optional `annotationColumnId` on `SelectionGroup`, preserved by
  `readSelectionGroups`. `hooks/useSelectionGroups.ts`: add `replaceAnnotationGroups(groups)`.
- Tests: `annotationGroups.test.ts`, `annotationInput.test.ts`, `annotations.test.ts`
  (`pnpm --filter depictio-react-core test`).

### 6. Client API (react-core `api.ts`)
`fetchDashboardAnnotations`, `putDashboardAnnotations`, `deleteDashboardAnnotations`, typed like the
filter-state client. A `useDashboardAnnotations(scopeId, storageMode)` hook loads the annotations
and saves them with a debounce (~800 ms). A failed account save keeps the state and exposes
`saveError`. Browser mode uses `annotations.ts`.

### 7. Viewer panel (`depictio/viewer/src/components/annotations/`)
- `AnnotateHeaderControl.tsx`: header button next to Analysis (`App.tsx:1540`). It opens a right
  `Drawer` with the same non-blocking props as `GroupingHeaderControl`, width `min(760px, 92vw)`,
  with a new event in `PANEL_TOGGLE_EVENTS` so the grid reflows and the charts stay visible.
  Annotate and Analysis are mutually exclusive on screen. The Annotate panel shows the group
  summary and an "Open Analysis" link.
- `AnnotationPanel.tsx`: table and key pickers (default = first referenced table with a column
  unique per row), AG Grid Community (same imports and theme classes as `TableEditor.tsx`).
  Read-only context columns (only those with one value per key), editable annotation columns,
  "+ Add annotation", "Compare by" select (disabled with the budget reason), drop zone, and a
  custom `paste` handler.
- Reading rows: `fetchDataCollectionPreview(dcId, 10000, [], version)`. `total_rows > 10000` →
  refusal message. When a `?version=` preview is active: `fetchDataVersionStatus` gives the version;
  without a `pinned` int there is a message and no grid. Keys absent from the table are kept and counted.
- Derived groups are pushed with `groupsApi.replaceAnnotationGroups` when the active column or its
  labels change.
- Temporary or anonymous accounts: browser storage, and the account-only controls are disabled with the reason. A note
  appears when localStorage is unavailable.
- Tabs **Edit table** (shown when `fetchTableEditStatus(dcId).can_edit`): mounts
  `TableEditor` (`onSaved` → `triggerRefresh` + reload the grid). **Save to table**: builds the
  CSV `key,label` in memory, `mergeTableFile(..., {mode:'add_columns', key, baseVersion, dryRun:true})`,
  shows the report (`reason`, `matched_rows`, `new_columns`), then applies with
  `report.delta_version`. A `stale_version` error offers a reload. On success the column is
  removed from the session and `triggerRefresh()` runs. Both are disabled with the reason on a pinned view.
- `data-testid`s on the button, panel, grid, drop zone, Compare by select and save button.

### 8. Playwright `depictio/tests/e2e-playwright/tests/dashboards/annotations.spec.ts`
Scenarios: annotate → compare by → the charts narrow and colour; a reload keeps the annotations; a dropped
CSV with a sentinel string never appears in any request body (`page.on('request')`); a temporary
account sees the disabled controls; an owner saves to table and the column exists; a `?version=`
view reads the pinned version.

## Verification

- Run per task: `uv run --extra dev pytest -xvs <test files of the task>`,
  `pnpm --filter depictio-react-core test`, `uv run --extra dev ty check depictio/models/`,
  viewer `tsc` / build, `pre-commit run --all-files`.
- **Not verifiable here:** the Playwright suite and the live check on `depictio local up` need a
  running stack (Mongo, S3, backend, viewer). Docker is forbidden and it is not sure that
  `depictio local up` / pixi works in this container. I will try `depictio local up` once; if
  it fails, the spec is written but not run, and the PR says so. CI runs it.
- Push to `feat/dashboard-annotations-m8v0sa`, open the PR (English, base
  `feat/project-data-and-table-editing`), and watch it.
