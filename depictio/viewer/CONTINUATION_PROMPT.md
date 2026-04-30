# Continuation prompt — React viewer MVP

Paste the section below into a fresh Claude Code session (in plan mode) when you're ready to keep building.

---

## Prompt to paste

```
I'm continuing work on the Depictio React viewer MVP that lives at
/Users/tweber/Gits/workspaces/depictio-workspace/depictio-worktrees/viralrecon-template-dashboard
on branch `feat/react-viewer-mvp`.

ENTER PLAN MODE. Build understanding before proposing changes.

## Mandatory reading (before proposing anything)

1. `depictio/viewer/HANDOFF.md` — what was shipped, runbook to bring it up
2. `/Users/tweber/Library/CloudStorage/GoogleDrive-thomas.weber@embl.de/My Drive/Obsidian/Vaults/depictio-notes/02-Project/Development/Active Development/React Viewer + Shared Component Library.md`
   — full architecture reference (Mermaid diagrams, file map, performance numbers, maintenance POV)
3. `/Users/tweber/Library/CloudStorage/GoogleDrive-thomas.weber@embl.de/My Drive/Obsidian/Vaults/depictio-notes/02-Project/Development/Active Development/Flask Multi-App Architecture for Depictio.md`
   — the Phase 1 split that this Phase 2 work builds on
4. `git log --oneline -5 feat/react-viewer-mvp` — see the two MVP commits
5. `git diff main...feat/react-viewer-mvp --stat` — full surface of the MVP

## What's shipped

- Shared package `packages/depictio-components/` with DepictioCard, DepictioMultiSelect, DepictioRangeSlider (TSX + hand-written Python wrappers + webpack UMD bundle)
- React viewer SPA at `depictio/viewer/` (Vite + React + Mantine 7), mounted by FastAPI at `/dashboard-beta/{id}` on port 8122
- Backend routes: `bulk_compute_cards`, `render_figure` (Plotly), `render_table` (AG Grid), `unique_values`, plus auth fix (`oauth2_scheme_optional`)
- Working dashboards: Iris, Penguins, viralrecon Coverage & Depth (`69ea13b37da6e01317a4bab4`), partial on ampliseq community

## What's next (Phase 2 backlog)

Pick one or check what the user wants:

A. **Dash editor consumes the shared React wrappers.** Currently `build_card`,
   `_build_select_component` (MultiSelect branch), etc. still emit DMC trees.
   Wrappers (`from depictio_components import DepictioCard, ...`) work and
   serialize correctly — proven in the MVP smoke tests. The wiring needs
   Output rewiring on existing pattern-matched callbacks
   (`render_card_value_background` targets `card-value.children`, etc.).
   Riskiest part: the inner pattern-matched IDs (`card-value`,
   `card-comparison`, `card-secondary-metrics`, `interactive-component-value`)
   need to either stay as Dash sub-components inside DepictioCard OR be
   rewired to set DepictioCard.value prop directly.
   Estimated 2–3 days.

B. **Other Interactive sub-types** (Slider single-value, DatePicker, Checkbox,
   Switch, SegmentedControl). Pattern is established by RangeSlider — see
   `packages/depictio-components/src/lib/components/DepictioRangeSlider.tsx`,
   then `depictio/viewer/src/components/ComponentRenderer.tsx`'s
   `RangeSliderRenderer` for the data-fetch pattern. ~0.5 day each.

C. **MultiQC component port.** Most complex remaining type.
   Existing Dash logic at `depictio/dash/modules/multiqc_component/`.
   Likely needs: new shared DepictioMultiQC component (Plotly +
   sample-aware controls), backend route similar to `render_figure`.
   ~3–5 days.

D. **Map (Leaflet) port.** `react-leaflet` + a backend route mirroring the
   Dash map_component logic. ~2 days.

E. **Image component port.** Simpler than the others.
   `depictio/dash/modules/image_component/` is the reference. ~1 day.

F. **JBrowse component port.** Iframe wrapping; should be quick. ~1 day.

G. **Auto-generated Python wrappers.** Replace the hand-written
   `depictio_components/Depictio<X>.py` files with output from
   `react-docgen-typescript` parsing the TSX `Props` interfaces.
   Schema: produce a `_PROP_NAMES` list and `__init__` mirroring
   the props. Hand-written wrappers stay valid as fallback.
   ~0.5 day, low priority.

H. **AG Grid server-side row model.** Currently `TableRenderer` fetches
   first 200 rows. For large tables, switch to AG Grid's infinite-row /
   server-side row model. Backend `render_table` already supports
   `start` + `limit`; frontend just needs `getRows` callback.
   ~0.5 day.

I. **Dashboard editor for the React viewer** — currently editor stays in
   Dash. If/when you want a React-native editor, a much bigger project.
   Out of scope for incremental work.

## Workflow rules to follow

- **Add deps inline as you write code; install/build once at the end.**
  Don't stop mid-flow to run `npm install` or `uv sync`. (See
  `~/.claude/projects/-Users-tweber-.../memory/feedback_batch_dev_then_install.md`
  if you're an agent — this is a documented user preference.)
- **Code in Docker, build on host.** `depictio/viewer/dist/` and
  `packages/depictio-components/depictio_components/*.min.js` are
  volume-mounted into the backend container. Build on host (`npm run
  build`), hard-refresh browser. Backend Python auto-reloads in dev.
- **Don't run docker build/up — only `docker logs`/`docker restart`.**
  If a Dockerfile change is needed, ask the user to run it.
- **Per-tier validation.** The user values measurement: every layout
  change or backend route → check via Chrome MCP
  (`mcp__claude-in-chrome__javascript_tool` against tab on
  `http://0.0.0.0:8122/dashboard-beta/<id>`). Don't guess.
- **No silent fallback / try-except eating errors.** Surface errors via
  the existing `ErrorBoundary` (depictio/viewer/src/components/ErrorBoundary.tsx)
  or HTTPException with detail. The user has been clear on this.

## Hard constraints (don't violate)

- DB schema (MongoDB `dashboards`, `stored_metadata`) untouched
- YAML ingestion path untouched
- Pydantic models in `depictio/models/components/lite.py` untouched
- Dash viewer at `/dashboard/{id}` keeps working — nothing destructive
- Visual parity with Dash for ported components (use Mantine 7 + Iconify,
  reuse `--app-bg-color` etc. CSS vars, mirror DMC structure)
- For shared components: Mantine + Iconify + React stay in
  `peerDependencies` of `packages/depictio-components/package.json` so
  Vite's `dedupe` collapses to one copy in the viewer. Don't move them
  back to `dependencies`.

## Repo navigation cheatsheet

```
depictio/api/v1/endpoints/dashboards_endpoints/routes.py
  ├── bulk_compute_cards          (line ~1456)
  ├── render_figure_endpoint      (line ~1640)
  └── render_table_endpoint       (line ~1820)

depictio/api/v1/endpoints/deltatables_endpoints/routes.py
  └── get_unique_values           (line ~385)

depictio/api/v1/endpoints/user_endpoints/routes.py
  ├── oauth2_scheme               (strict)
  ├── oauth2_scheme_optional      (the auth fix)
  └── get_user_or_anonymous       (line ~83)

packages/depictio-components/src/lib/components/
  ├── DepictioCard.tsx
  ├── DepictioMultiSelect.tsx
  └── DepictioRangeSlider.tsx

depictio/viewer/src/
  ├── App.tsx                     (layout, tabs, filter state)
  ├── api.ts                      (fetch wrappers + auth)
  └── components/
      ├── ComponentRenderer.tsx   (dispatch + per-type renderers)
      ├── FigureRenderer.tsx      (Plotly)
      ├── TableRenderer.tsx       (AG Grid)
      └── ErrorBoundary.tsx
```

## How to run/test

```bash
# Backend container has FastAPI auto-reload; Python edits picked up live
# Frontend (Dash) container: docker restart <name> if Python changed there

# After a TSX or component-package change:
cd packages/depictio-components && npm run build:js
cd ../../depictio/viewer && npm run build
# Hard-refresh http://0.0.0.0:8122/dashboard-beta/<id>

# Iris (works end-to-end): /dashboard-beta/6824cb3b89d2b72169309737
# Penguins:                /dashboard-beta/6824cb3b89d2b72169309738
# Viralrecon Coverage:     /dashboard-beta/69ea13b37da6e01317a4bab4
# Diff Abundance (corrupt DC, show "—"): /dashboard-beta/646b0f3c1e4a2d7f8e5b8cb4
```

## Git state

- Branch: `feat/react-viewer-mvp`
- HEAD: should be at the second commit ("React viewer MVP + shared component library")
- HEAD~1: "Perf fixes: SVG re-encode, MultiQC samples strip + N+1 cache, route guard"
- HEAD~2: "Bump Dash 3.2 → 4.1 for pattern-matching callback perf fix"
- HEAD~3: viralrecon work (a0605806) — already on PR #740 from
  `claude/viralrecon-template-dashboard-DN8J6`

If `feat/react-viewer-mvp` hasn't been pushed yet (network was flaky),
the first task is `git push -u origin feat/react-viewer-mvp` and then
`gh pr create --base main` with a structured body that mirrors the
viralrecon PR style (Summary / What changed / Test plan / Out of scope).

## What I want from you (the agent)

1. Confirm the repo + branch state in your first turn
2. Read the mandatory references (especially the Obsidian note —
   it's the canonical architecture doc)
3. Ask which Phase 2 item to pick (or default to whatever the user
   indicates)
4. Plan the work with file paths, then exit plan mode and implement

Don't propose architectural rewrites or new infrastructure unless the
existing pattern (TSX + Python wrapper + ComponentRenderer dispatch
+ optional FastAPI route) is genuinely insufficient for the task at
hand.
```

---

## How to use this

1. Open a new Claude Code session in this worktree
2. Paste the prompt above (the part inside the triple-backticks)
3. The session enters plan mode, reads the Obsidian + HANDOFF docs, then asks which Phase 2 item to take on
4. Pick one and let it cook
