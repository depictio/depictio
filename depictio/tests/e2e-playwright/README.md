# Depictio Playwright e2e tests (parallel, work-in-progress)

A Playwright e2e suite that runs **alongside** the existing Cypress suite at
`../e2e-tests/`. The Cypress suite is untouched and remains the canonical
e2e runner. This package only adds a parallel implementation so we can
evaluate Playwright and gradually migrate specs.

## What's in here today

| Spec | Ported from | Status |
|---|---|---|
| `tests/auth/auth-ui-login.spec.ts` | `cypress/e2e/auth/standard/auth-ui-login.cy.js` | ✅ |
| `tests/auth/logout.spec.ts` | `cypress/e2e/auth/standard/logout.cy.js` | ✅ |
| `tests/dashboards/create-dashboard.spec.ts` | `cypress/e2e/dashboards/create-dashboard.cy.js` | ✅ |

The remaining ~18 Cypress specs are not yet ported. The fixtures + patterns
established here cover the bulk of what they need; porting is mostly
mechanical from this point.

## Prerequisites

- Node 20+ and npm 10+
- The depictio stack running (backend + frontend) — same contract as the
  Cypress suite. By default Playwright targets `http://localhost:5080`
  (Dash). To target the React frontend instead set `PLAYWRIGHT_BASE_URL`.

Bring up the stack the same way you do for Cypress:

```bash
docker compose -f docker-compose.dev.yaml --env-file docker-compose/.env up -d
```

## Install

```bash
cd depictio/tests/e2e-playwright
npm install
npm run install-browsers      # downloads Chromium (+ deps on Linux)
```

## Running locally

### Headless (CLI, like `cypress run`)

```bash
npm test                           # all specs
npm run test:auth                  # just tests/auth/**
npm run test:dashboards            # just tests/dashboards/**
npx playwright test tests/auth/auth-ui-login.spec.ts   # single file
npx playwright test -g "invalid credentials"           # by test name
```

After a run, open the HTML report:

```bash
npm run show-report     # opens playwright-report/index.html in your browser
```

### Headed (watch the browser)

```bash
npm run test:headed
```

### **UI mode — the interactive runner (this is the Cypress-equivalent visual UI)**

```bash
npm run test:ui
```

What you get:

- **Tree of all specs/tests** on the left — click to run one.
- **Watch mode** toggle — re-runs on file save.
- **Timeline** of every action with DOM snapshots — click any step to
  time-travel back to that exact state.
- **Locator picker** — hover the rendered page to get a suggested locator
  (then paste it into the spec).
- **Network log, console log, source view** side-by-side with the page.
- **Pick locator** + **Record** buttons to extend specs interactively.

This is the closest analogue to `cypress open`, and most teams find it more
capable.

### Debug mode (Playwright Inspector)

```bash
npm run test:debug
# or:
PWDEBUG=1 npx playwright test tests/auth/auth-ui-login.spec.ts
```

Pauses on every action, lets you step, edit locators on the fly.

### Codegen — record a spec by clicking

```bash
npm run codegen
# or against a different URL:
npx playwright codegen http://localhost:5080
```

Opens a browser; everything you do is transcribed into runnable Playwright
code in a side panel. Useful for bootstrapping a new test.

### Trace viewer (post-mortem of any failed CI run)

Failed tests upload a `trace.zip` (configured in `playwright.config.ts`).
Open one locally:

```bash
npx playwright show-trace test-results/<spec>/trace.zip
```

The viewer shows DOM snapshots, screenshots, network, console — for every
action. There is no Cypress equivalent.

## Configuration

`playwright.config.ts`:

- `baseURL` — defaults to `http://localhost:5080`. Override with
  `PLAYWRIGHT_BASE_URL=http://localhost:5173 npm test` to target the React
  frontend.
- `PLAYWRIGHT_API_URL` — backend URL used by the programmatic login fixture.
  Defaults to `http://localhost:8058`.
- `UNAUTHENTICATED_MODE` / `PUBLIC_MODE` — set to `"true"` to skip specs
  that require interactive auth (same semantics as the Cypress env vars).
- Tracing: `retain-on-failure` (lightweight in CI). Set `trace: 'on'` for
  always-on local capture.
- Browsers: Chromium only by default; uncomment Firefox/WebKit in
  `playwright.config.ts` for cross-browser runs.

## Fixtures

`fixtures/auth.ts` provides:

- `apiLogin(request, email, password)` — POST to `/auth/login`, returns
  tokens. Equivalent to Cypress `cy.loginWithToken`.
- `uiLogin(page, email, password)` — fills the auth modal. Equivalent to
  `cy.loginUser`.
- `loginAsTestUser(page, request, userType)` — apiLogin + seed tokens into
  localStorage so the next `page.goto()` is already authenticated. The
  fastest path; use it unless you're specifically testing the login UI.
- `test` — extended Playwright `test` with `loginAsAdmin` and `loginAsUser`
  fixtures injected directly into the test signature.

`fixtures/test-credentials.json` is a copy of the Cypress fixture; same
seeded users from `depictio/api/v1/configs/initial_users.yaml`.

## Cypress → Playwright cheat sheet

| Cypress | Playwright |
|---|---|
| `cy.visit(url)` | `await page.goto(url)` |
| `cy.get(sel)` | `page.locator(sel)` |
| `cy.contains(text)` | `page.getByText(text)` |
| `cy.get(sel).should('be.visible')` | `await expect(page.locator(sel)).toBeVisible()` |
| `cy.get(sel).type(val)` | `await page.locator(sel).fill(val)` |
| `cy.get(sel).click()` | `await page.locator(sel).click()` |
| `cy.fixture('x.json')` | `import x from './x.json'` |
| `cy.intercept(...)` | `await page.route(...)` |
| `cy.wait(2000)` | Don't — locators auto-wait. If you must: `await page.waitForTimeout(2000)` |
| `cy.url().should('include', '/x')` | `await expect(page).toHaveURL(/\/x/)` |
| Cypress runner UI | `npx playwright test --ui` |

## Why coexist with Cypress

- The Cypress suite is the production safety net. Don't break it.
- This package lets you run **either** suite against the same docker stack
  and compare results, flake rate, runtime, DX.
- When a Playwright spec proves itself, you can delete its Cypress twin in
  a follow-up PR. No big-bang migration.

## Known limitations of the current scaffold

- Only Chromium is installed by default (config has Firefox/WebKit
  commented out — uncomment to enable).
- No CI workflow is wired up yet. To add one, mirror the existing
  `e2e-tests` job in `.github/workflows/depictio-ci.yaml`, swapping the
  Cypress invocation for `npx playwright test` (and `npm install
  --prefix depictio/tests/e2e-playwright` + `npx playwright install
  --with-deps chromium`).
- The token-seeding fixture targets the Dash app's `local-store` shape.
  When pointed at the React frontend (`depictio/react-frontend/`) it will
  also need to populate `depictio-auth` (Zustand persist key) — easy
  extension, not done yet.
