# Dashboard versioning and saves

Loaded when working under `dashboards_endpoints/`. The viewer side (`EditorApp.tsx`, `src/versions/`) follows the same rules.

## Dashboard Versioning
- Every save snapshots the whole tab family into `dashboard_versions` (`dashboards_endpoints/versioning.py`)
- **`/save` is not the only route that captures.** `POST /edit`, `PATCH /tab`,
  `DELETE /tab`, `/tabs/reorder`, `PATCH /appearance` and a child-tab `DELETE /delete`
  all change content, so each seeds a baseline *before* its write and captures *after*
  it. A tab delete anchors on the parent (the deleted tab can no longer resolve its own
  family) and is `explicit`, so it never coalesces into a neighbouring autosave. Every
  import records the state it replaces, then an `import` version. `/upload_logo` is not
  captured: the bytes live in `branding_assets`, which no snapshot holds. Adding a new
  content-mutating route without both calls silently makes that change unrecoverable
- Autosaves coalesce within an anchored window; an unchanged save writes nothing, **whatever its kind**.
  One exception: a Save click (`seal=True`) on content an autosave already holds turns that
  autosave `explicit` and closes its window, or the click would leave no trace. A dashboard's
  creation is `explicit` too, so the creator's first edits cannot fold into and erase it
- Version timestamps are naive UTC (`utc_now_naive`), like every other API timestamp: a local
  clock is invisible in Docker but hours off under `depictio local up`
- The editor must not write before a user action. react-grid-layout reports a normalised
  layout on mount (compacted, `box-` ids bared) and TipTap's `setEditable` emits an update;
  saving either recorded a version on every open of an imported or restored dashboard.
  `userActedRef` in `EditorApp.tsx` gates layout reports, `applyServerDashboard` resets it
- The first save on a family seeds a baseline first (`ensure_baseline_quietly`), so the
  pre-edit state is restorable; capture otherwise only ever records states already left
- `tab_count`/`component_count` are **stored**, not derived: the list endpoint projects
  `tabs` away, so a timeline row has nothing left to count
- Snapshots are content-only: `permissions`/`is_public`/`project_id` always come from the live doc
- `TabSnapshot` is `extra="forbid"` and must cover every content field of `DashboardData`.
  A new dashboard field goes into `TabSnapshot` or one of the `SNAPSHOT_*_FIELDS` sets in
  `versioning.py`; the field-coverage test fails otherwise. Fields added after record
  schema 1 are hashed only when they differ from their default, so existing families keep
  their hashes. Restore writes only the keys a stored tab holds, and logo URLs always come
  from the live document
- Snapshots stringify ObjectIds to hash deterministically; restore calls `_rehydrate_ids`
  to undo that, or components come back with string `dc_id`s that match no lookup
- Retention is `version_store.prune_family()`, not a TTL index (a TTL cannot exempt pins)
- UI: entry point is the editor's Settings modal (History and Data version sections), not
  the header. `/dashboard/{id}?version={vid}` renders a snapshot read-only in the viewer
- Preview **merges** the snapshot onto the live document server-side (`_overlay_version`
  in `routes.py`, 404 for a version of another family): a `TabSnapshot` has no
  `project_id`/`permissions` by design, so rendering it alone breaks data resolution.
  `src/versions/preview.ts` only adds `as_of_version` and `definition_version` to render
  requests. Guarded by `pnpm run check:preview` (no JS test runner in this tree).
  Cross-tab sections and floating maps come from
  `GET /cross_tab_components/{id}?version_id=` (same family check, 404)
- Version history covers **layout, components and data**. `DataCollectionStamp` is read
  back: `as_of_version` expands a version's stamps into per-collection pins, and
  `data_versions: {dc_id: N}` (a non-bool int >= 0, or null for live) overrides one. A
  stale version id is a **400** with the fixed detail `"Version <id> no longer exists."`
  (the editor matches it), never a silent fall back to current data
- A time-travelling render needs **both halves** in the request body: `as_of_version` /
  `data_versions` for the data, and `definition_version` for the definition. Sending
  only the pins renders a past version's data through today's chart config and labels it
  as the past. Both halves were missing once, and neither failure raised
- `definition_version` names a stored version; the **server** reads the component from
  it (`_component_from_version` in `routes.py`, tab by the rendered dashboard id, then
  component by index) and replaces the live definition wholesale, except `index`, `wf_id`,
  `dc_id` and `dc_config`, which stay live. 409 when that version read another
  collection; a component deleted since renders from the version only if its collection
  is still in the project. Renders take **no definition from the request body**: the old
  `component_overrides` let any viewer hand the server a figure in code mode, and is now
  a 400
- Anything else a pinned view reads must honour the pins too: filter option lists come
  from `POST /filter_options/{id}`, and `POST /data_version_status/{id}` says per
  collection whether it is `pinned`, `live` (with a reason, e.g. `not_in_version` for a
  collection added since) or `not_versioned`. A render never carries that list
- Cache keys are salted with the pin, so a historical read is its own entry rather than
  colliding with the live one. A pinned read never comes from the `USE_LOCAL_FILES`
  mirror, which only holds the newest commit
- Component ids come from a UUID5 of the YAML tag, **not** regenerated on import. A child
  tab's ids are scoped by its title (`DashboardDataLite.tag_scope`), so two tabs sharing
  a tag never share an id; tags must be unique within a tab. Three places must agree
  (`index_from_tag`, `to_full`, `_tag_derived_indices`); `_regenerate_component_indices`
  runs on import and will silently undo it. Export writes an id its tag does not derive,
  so a round trip keeps it. `restore_component` takes `tab_id` with the index. Without
  stable ids no component-level history can match anything
- Time-travel UI is **edit mode only** (timeline, dataset picker, component history):
  all of it writes or re-points data. The viewer keeps only the `?version=` preview.
  `check_served_bundle.py` asserts that split in the *served bundle*, in both directions
- Deleting a main tab drops its ledger + seq counter; a child tab's versions belong to
  the family and must survive. Deleting a project drops its families' ledgers
- `depictio/projects/init/iris_versioned/` is the fixture for exercising any of this:
  4 data versions at 50/100/100/150 rows and 4 dashboard versions. Batch 2 vs 3 have the
  **same row count** and differ only in values, which is what makes a read that silently
  serves current data visible rather than merely plausible. Build it with
  `rebuild_demo.py`; not auto-seeded, see its README
- Batch N must be ingested *before* dashboard version N is saved. Ingest everything first
  and all four versions stamp the newest commit: labels, counts and stamps all look
  right, and "restore v1's data" quietly shows the complete survey. `rebuild_demo.py`
  asserts the stamps ascend
