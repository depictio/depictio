# Depictio React Frontend (parallel, work-in-progress)

A React rewrite of the Depictio frontend, running **alongside** the existing
Dash app. The Dash app at `depictio/dash/` is untouched and remains the
production frontend. This package only adds a parallel implementation.

## Status — first slice

- [x] Project scaffold (Vite + React 18 + TypeScript)
- [x] Mantine 7 theme + provider (matches DMC 2.0 styling family)
- [x] React Router routing (`/auth`, `/dashboards`)
- [x] API client with JWT bearer auth (axios + Zustand persisted store)
- [x] Login page (`/auth`) — mirrors Dash element IDs for Cypress continuity
- [x] Dashboards list page (`/dashboards`) — read-only card grid
- [ ] Dashboard viewer (`/dashboard/{id}`)
- [ ] Dashboard editor (`/dashboard/{id}/edit`)
- [ ] Registration flow
- [ ] Theme persistence across sessions (currently uses Mantine `auto`)
- [ ] Cypress test run against this app

## Why Mantine 7?

DMC 2.0 in the Dash app wraps Mantine v7 internally, so the rendered DOM
class names (`.mantine-Card-root`, etc.) are largely the same shape. The
existing Cypress selectors targeting Mantine classes should keep working,
which de-risks the eventual cutover.

## Element IDs preserved from Dash

The login page deliberately reuses the same DOM IDs as the Dash modal so
existing Cypress specs in
`depictio/tests/e2e-tests/cypress/e2e/auth/standard/` can be pointed here
without selector edits:

- `#auth-modal`, `#modal-content`, `#auth-background`
- `#login-email`, `#login-password`, `#login-button`
- `#open-register-form`, `#user-feedback-message-login`
- `#app-shell`, `#page-content`
- `#theme-switch`, `#logout-button`, `#user-info-placeholder`

## Running locally

Prerequisites: Node 20+, npm 10+. The FastAPI backend should be reachable
(default: `http://localhost:8058`).

```bash
cd depictio/react-frontend
cp .env.example .env       # optional; defaults to localhost:8058
npm install
npm run dev                 # http://localhost:5173
```

The Vite dev server proxies `/depictio/api/*` → `$VITE_API_TARGET`, so the
browser never sees a cross-origin request.

To use it against the existing dockerised stack:

```bash
# From repo root, in one shell:
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up

# In another shell:
cd depictio/react-frontend && npm run dev
```

Then open http://localhost:5173 and log in with any seeded user
(see `depictio/api/v1/configs/initial_users.yaml`).

## Running in Docker (optional)

A `Dockerfile` is provided for the dev server. It is **not** wired into
`docker-compose.dev.yaml` yet — by design, to keep the Dash stack the
default. To run it manually:

```bash
docker build -t depictio-react-frontend depictio/react-frontend
docker run --rm -p 5173:5173 \
  -e VITE_API_TARGET=http://host.docker.internal:8058 \
  depictio-react-frontend
```

## Project layout

```
depictio/react-frontend/
├── src/
│   ├── api/         # FastAPI client (auth, dashboards, types)
│   ├── components/  # AppShell, ThemeToggle, ProtectedRoute
│   ├── pages/       # AuthPage, DashboardsPage
│   ├── store/       # Zustand auth store (persisted to localStorage)
│   ├── App.tsx      # Router
│   ├── main.tsx     # Entry, providers
│   └── theme.ts     # Mantine theme
├── Dockerfile       # Dev image (Vite HMR server)
├── vite.config.ts   # Proxy /depictio/api/* to backend
└── package.json
```

## Scripts

- `npm run dev` — Vite dev server with HMR on :5173
- `npm run build` — TypeScript check + production bundle to `dist/`
- `npm run preview` — Serve the production bundle on :5174
- `npm run lint` — `tsc --noEmit` (TS-only check, no ESLint yet)

## Next steps

1. Add registration form (`#register-*` IDs from Dash).
2. Add a copy of `cypress/e2e/auth/standard/auth-ui-login.cy.js` pointed
   at `http://localhost:5173` to verify selector parity.
3. Add dashboard viewer page (read-only, react-grid-layout + Plotly).
4. Decide on a long-term selector contract: switch to `data-testid` once
   parity tests pass, or keep mirroring IDs forever.
