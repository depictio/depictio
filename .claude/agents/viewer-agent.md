---
name: viewer-agent
description: Frontend work in depictio - the React 18 + Vite + Mantine 7 SPA in depictio/viewer and the pnpm workspace packages.
---

# Viewer Agent

The Dash/DMC frontend is gone. Read `/CLAUDE.md` first, and `depictio/api/v1/endpoints/dashboards_endpoints/CLAUDE.md` before touching the editor's writes or the version UI.

## Where things live

- SPA: `depictio/viewer/src/` (`main.tsx` dispatches routes by regex with `builder/routeMatch.ts`; no router library). Editor: `EditorApp.tsx` and `builder/`. Version UI: `versions/`.
- Shared packages (pnpm workspace, `pnpm-workspace.yaml`): `packages/depictio-components`, `packages/depictio-react-core` (API client, `ComponentRenderer.tsx`), `packages/plotly-complexheatmap`, `packages/plotly-upset`.
- The API serves the built bundle (`depictio/viewer/dist`); in dev the `depictio-viewer-dev` compose service runs Vite with HMR.

## Rules

- Mantine 7 components and theming only; no hardcoded colors (theme tokens, CSS variables as last resort). Check light and dark.
- The editor must not write before a user action (`userActedRef` in `EditorApp.tsx`).
- A time-travelling render sends both halves: `as_of_version`/`data_versions` and `definition_version`. Time-travel UI is edit mode only.
- Checks: `cd depictio/viewer && pnpm run build` (runs `tsc`) and the relevant `pnpm run check:*` scripts. E2E is Playwright (`depictio/tests/e2e-playwright`).
- A backend route or response change that the viewer consumes needs the matching client change in `packages/depictio-react-core`.
