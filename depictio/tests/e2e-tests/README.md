# E2E Tests - Local Testing Guide

## Prerequisites

1. **Services Running**: Ensure Depictio services are running locally
   ```bash
   # Start with pixi (recommended)
   pixi run start-infra  # MongoDB, Redis, MinIO
   pixi run api          # Backend API on :8058
   pixi run dash         # Frontend on :5080

   # OR with Docker Compose
   docker compose -f docker-compose.dev.yaml up -d
   ```

2. **Install Dependencies**:
   ```bash
   cd depictio/tests/e2e-tests
   npm install
   ```

## Running Tests

### Interactive Mode (Cypress UI)
```bash
npm run test:ui
```
Opens Cypress Test Runner for interactive debugging.

### Headless Mode (CI-style)
```bash
npm test                    # Run all tests
npm run test:headed         # Run with browser visible
```

### Test by Auth Mode

**Standard Auth Mode** (login required):
```bash
npm run test:auth
```

**Public Mode** (anonymous browsing):
```bash
# Enable PUBLIC_MODE in docker-compose/.env first:
# DEPICTIO_AUTH_PUBLIC_MODE=true
npm run test:public
```

**Demo Mode** (public + guided tour):
```bash
# Enable DEMO_MODE in docker-compose/.env:
# DEPICTIO_AUTH_PUBLIC_MODE=true
# DEPICTIO_AUTH_DEMO_MODE=true
npm run test:demo
```

**Single-User Mode** (no login, admin by default):
```bash
# Enable SINGLE_USER_MODE in docker-compose/.env:
# DEPICTIO_AUTH_SINGLE_USER_MODE=true
npm run test:single-user
```

### Test by Feature

```bash
npm run test:dashboards    # Dashboard management tests
npm run test:ui-themes     # Theme switching tests
```

## Configuration

### Environment Variables

Set in `docker-compose/.env`:
```bash
DEPICTIO_AUTH_SINGLE_USER_MODE=false
DEPICTIO_AUTH_PUBLIC_MODE=false
DEPICTIO_AUTH_DEMO_MODE=false
DEPICTIO_DEV_MODE=true
```

### Cypress Config

See `cypress.config.js` for:
- Base URL: `http://localhost:5080`
- Viewport: 1920x1080
- Timeouts and retry logic

## Test Structure

```
cypress/e2e/
├── auth/                    # Standard auth mode tests (login, registration)
├── auth-modes/             # Auth mode-specific tests
│   ├── demo-mode.cy.js     # Demo mode badge & tour tests
│   └── single-user-mode.cy.js  # Single-user badge & admin tests
├── dashboards_management/  # Dashboard CRUD tests
├── unauthenticated/        # Public mode tests (anonymous access)
├── ui/                     # Theme switching, dark mode
└── pages/                  # Static pages (about, etc.)
```

## Troubleshooting

### Tests Not Finding Elements
- Check if services are running (`curl http://localhost:5080`)
- Verify correct auth mode is enabled in `.env`
- Check Cypress console for element selectors

### Tests Timeout
- Increase timeouts in `cypress.config.js`
- Check backend logs for slow API responses
- Ensure MongoDB/Redis are running

### Badge Tests Failing
- Verify auth mode is correctly configured
- Check sidebar is visible (`mantine-AppShell-navbar`)
- Look for `mantine-Badge-label` with correct text

## CI Integration

Tests run automatically in GitHub Actions:
- `e2e-tests` - Standard auth mode
- `e2e-tests-unauthenticated` - Public mode
- `e2e-tests-demo-mode` - Demo mode
- `e2e-tests-single-user-mode` - Single-user mode

See `.github/workflows/depictio-ci.yaml` for CI configuration.
