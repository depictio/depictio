# Cypress → Playwright migration status

Target frontend: **React** (`depictio/react-frontend/`), Vite dev server on
`http://localhost:5173`. The legacy Dash app and the Cypress suite are left
untouched as the safety net.

This first slice covers **`/auth` checks + dashboards management only**, per
review scope. Everything else is intentionally deferred.

## Ported (this slice)

| Playwright spec | Source Cypress spec | Notes |
|---|---|---|
| `tests/auth/auth-ui-login.spec.ts` | `auth/standard/auth-ui-login.cy.js` | login success/failure + programmatic fixtures |
| `tests/auth/auth-ui-registration.spec.ts` | `auth/standard/auth-ui-registration.cy.js` | success, password mismatch, duplicate email |
| `tests/auth/logout.spec.ts` | `auth/standard/logout.cy.js` | via `/profile` → logout → `/auth` |
| `tests/dashboards/create-dashboard.spec.ts` | `dashboards/create-dashboard.cy.js` | create + delete (React direct Delete button) |
| `tests/dashboards/create-dashboard-extended.spec.ts` | `dashboards/create-dashboard-extended.cy.js` | create + reload-persists + delete |
| `tests/dashboards/create-multiple-dashboards.spec.ts` | `dashboards/create-multiple-dashboards.cy.js` | revived (original was fully commented out) |

## React features added to support this slice

- Registration form in `AuthPage.tsx` (login/register toggle, mirrored Dash IDs).
- Dashboard create modal + per-card Delete in `DashboardsPage.tsx`.
- `/profile` route + `ProfilePage.tsx` (hosts the header logout button).
- API client: `register()`, `listProjects()`, `createDashboard()`, `deleteDashboard()`.

## Fixture changes

- `seedTokenInStorage` now writes the React Zustand `depictio-auth` shape by
  default; set `PLAYWRIGHT_TARGET=dash` to write the Dash `local-store` shape.
- New helpers: `uiRegister`, `uiLogout`.
- `fixtures/projects.ts` — shared seeded Iris project id/label.

## Deferred (NOT in this slice)

- `auth/standard/`: account-management, edit-password, create-cli-config, token-login-test
- `projects/project-permissions.cy.js` (needs React projects + AG Grid permissions UI)
- `ui/` theme + dark-mode logo specs
- `pages/about-page.cy.js`
- All `auth/public/`, `auth/demo/`, `auth/single-user/` (mode-gated; React mode routing not built)

## Verification status

- ✅ React app: `tsc --noEmit` clean, `npm run build` succeeds.
- ✅ Playwright: `tsc --noEmit` clean, `npx playwright test --list` resolves all 13 tests.
- ⏳ **Full e2e green run not executed here** — requires the backend stack
  (Mongo/MinIO/FastAPI) which isn't run in this environment. Run locally:

```bash
# 1. Backend stack
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up -d

# 2. React frontend
cd depictio/react-frontend && npm install && npm run dev   # :5173

# 3. Playwright (new shell)
cd depictio/tests/e2e-playwright
npm install && npm run install-browsers
npm test                 # or: npm run test:ui  for the interactive runner
```
