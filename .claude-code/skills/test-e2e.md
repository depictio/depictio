# Test E2E

Run end-to-end (E2E) tests using Cypress to test the full application workflow.

## Usage

When the user wants to run E2E browser tests, set up the environment and execute Cypress tests.

## Prerequisites

- Node.js installed (v20.16.0 recommended)
- Cypress setup in `depictio/tests/e2e-tests/`
- Application running (API + Dash)

## E2E Test Execution

### Full Test Suite

```bash
cd depictio/tests/e2e-tests && /Users/tweber/.nvm/versions/node/v20.16.0/bin/npx cypress run \
  --config screenshotsFolder=cypress/screenshots,\
videosFolder=cypress/videos,\
trashAssetsBeforeRuns=false,\
video=true,\
screenshotOnRunFailure=true
```

### Interactive Mode (Cypress UI)

```bash
cd depictio/tests/e2e-tests && npx cypress open
```
- Opens Cypress Test Runner
- Select browser and tests to run
- Watch tests execute in real-time
- Useful for debugging

### Specific Test File

```bash
cd depictio/tests/e2e-tests && npx cypress run --spec "cypress/e2e/test_file.cy.js"
```

### Specific Browser

```bash
cd depictio/tests/e2e-tests && npx cypress run --browser chrome
# or: --browser firefox, --browser edge
```

## Process

1. **Check prerequisites**:
   - Verify Node.js installed: `node --version`
   - Check Cypress installed: `cd depictio/tests/e2e-tests && npx cypress --version`
   - Ensure application is running

2. **Start application if needed**:
   - API: `pixi run api` or via Docker
   - Dash: `pixi run dash` or via Docker
   - Check services: http://localhost:8058 (API), http://localhost:5080 (Dash)

3. **Run E2E tests**:
   - Full suite or specific tests based on user request
   - Capture screenshots and videos

4. **Review results**:
   - Show test summary (passed/failed)
   - Display screenshots for failures
   - Point to video recordings if needed

5. **Debug failures**:
   - Open Cypress UI for interactive debugging
   - Review screenshots in `cypress/screenshots/`
   - Review videos in `cypress/videos/`

## Test Configuration

Cypress configuration options:

- **screenshotsFolder**: Where to save screenshots (`cypress/screenshots/`)
- **videosFolder**: Where to save videos (`cypress/videos/`)
- **trashAssetsBeforeRuns**: Keep previous test artifacts (false)
- **video**: Record video of tests (true)
- **screenshotOnRunFailure**: Capture screenshot on failure (true)

## Common Test Scenarios

E2E tests typically cover:

1. **Authentication**:
   - User login/logout
   - Session management
   - Permission checks

2. **Dashboard Creation**:
   - Create new dashboard
   - Add components (cards, figures, tables)
   - Save dashboard

3. **Data Upload**:
   - Upload data files
   - Create data collections
   - Verify data processing

4. **Visualization**:
   - Render charts and tables
   - Interactive filtering
   - Component interactions

5. **Workflows**:
   - Complete user workflows
   - Multi-step processes
   - Integration between components

## Output Artifacts

After test run:

- **Screenshots**: `depictio/tests/e2e-tests/cypress/screenshots/`
  - Captured on test failure
  - Named by test and timestamp

- **Videos**: `depictio/tests/e2e-tests/cypress/videos/`
  - Full test execution recording
  - One video per spec file

- **Console output**: Test results, timing, errors

## Environment Setup

### Install Cypress (if not installed)

```bash
cd depictio/tests/e2e-tests
npm install cypress --save-dev
```

### Verify Installation

```bash
cd depictio/tests/e2e-tests
npx cypress verify
```

### Update Cypress

```bash
cd depictio/tests/e2e-tests
npm install cypress@latest
```

## Debugging E2E Tests

### Interactive Debugging

1. Open Cypress UI:
   ```bash
   cd depictio/tests/e2e-tests && npx cypress open
   ```

2. Select test file to debug

3. Use browser DevTools during test execution

4. Add `cy.pause()` in test code to pause execution

### Review Failures

1. Check screenshots in `cypress/screenshots/`
2. Watch video in `cypress/videos/`
3. Review console output for errors
4. Check application logs (API, Dash)

### Common Issues

**Application not running**:
- Start API and Dash services
- Verify ports: 8058 (API), 5080 (Dash)
- Check health endpoints

**Cypress not found**:
- Install: `cd depictio/tests/e2e-tests && npm install`
- Verify: `npx cypress --version`

**Tests timing out**:
- Increase timeout in test: `cy.visit('/', { timeout: 10000 })`
- Check application performance
- Verify network connectivity

**Element not found**:
- Check if DOM structure changed
- Update selectors in test
- Add wait conditions: `cy.get('.element').should('be.visible')`

## CI/CD Integration

E2E tests in CI pipeline:

```bash
# Start services in background
docker compose up -d

# Wait for services to be ready
./scripts/wait-for-services.sh

# Run E2E tests
cd depictio/tests/e2e-tests && npx cypress run

# Stop services
docker compose down
```

## Performance Tips

- Run specific tests during development (faster feedback)
- Use interactive mode for debugging (visual feedback)
- Keep test data small (faster execution)
- Clean up test data between runs
- Use `--headed false` for faster headless execution

## Integration with Other Skills

- Run `/run-tests` (unit tests) before E2E tests
- Run `/check-quality` before E2E tests
- Use `/create-pr` only after all tests pass (unit + E2E)
- Debug with `/debug-dash` if E2E tests fail

## Quick Command Reference

```bash
# Run all E2E tests
cd depictio/tests/e2e-tests && npx cypress run

# Open Cypress UI
cd depictio/tests/e2e-tests && npx cypress open

# Run specific test
cd depictio/tests/e2e-tests && npx cypress run --spec "cypress/e2e/login.cy.js"

# Run in specific browser
cd depictio/tests/e2e-tests && npx cypress run --browser chrome

# Run headless (no browser UI)
cd depictio/tests/e2e-tests && npx cypress run --headless
```
