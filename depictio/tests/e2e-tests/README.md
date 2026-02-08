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
# Runs: cypress/e2e/auth/standard/**/*.cy.js
```

**Public Mode** (anonymous browsing):
```bash
# Enable PUBLIC_MODE in docker-compose/.env first:
# DEPICTIO_AUTH_PUBLIC_MODE=true
npm run test:public
# Runs: cypress/e2e/auth/public/**/*.cy.js
```

**Demo Mode** (public + guided tour):
```bash
# Enable DEMO_MODE in docker-compose/.env:
# DEPICTIO_AUTH_PUBLIC_MODE=true
# DEPICTIO_AUTH_DEMO_MODE=true
npm run test:demo
# Runs: cypress/e2e/auth/demo/**/*.cy.js
```

**Single-User Mode** (no login, admin by default):
```bash
# Enable SINGLE_USER_MODE in docker-compose/.env:
# DEPICTIO_AUTH_SINGLE_USER_MODE=true
npm run test:single-user
# Runs: cypress/e2e/auth/single-user/**/*.cy.js
```

### Test by Feature

```bash
npm run test:dashboards    # Dashboard CRUD tests (cypress/e2e/dashboards/**/*.cy.js)
npm run test:ui-themes     # Theme switching tests (cypress/e2e/ui/**/*.cy.js)
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
├── auth/                           # All authentication-related tests
│   ├── standard/                   # Standard auth mode (login required)
│   │   ├── login.cy.js            # Login functionality
│   │   ├── register.cy.js         # User registration
│   │   └── password.cy.js         # Password reset/change
│   ├── public/                     # Public mode (anonymous browsing)
│   │   ├── api_protection.cy.js   # API access restrictions
│   │   └── unauthenticated_access.cy.js  # Anonymous access
│   ├── demo/                       # Demo mode (public + tour)
│   │   └── demo-mode.cy.js        # Demo badge & tour popover
│   └── single-user/                # Single-user mode (no login)
│       └── single-user-mode.cy.js # Single-user badge & admin
├── dashboards/                     # Dashboard CRUD operations
├── projects/                       # Project management & permissions
├── ui/                            # UI components & theme switching
└── pages/                         # Static pages (about, etc.)
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
