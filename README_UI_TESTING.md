# UI Testing with MongoDB

This document explains how to run UI tests for the Depictio application using a separate test database.

## Overview

The UI tests use Playwright to interact with the Dash application. The tests are designed to run against a real MongoDB instance, but with a separate test database to avoid affecting production data.

## Running Tests

There are two ways to run the tests:

### 1. Docker Mode (Default)

This mode starts the Docker containers with the test environment variables, then runs the tests against the containerized application.

```bash
./run_ui_tests.sh
```

### 2. Local Mode

This mode runs the tests against a locally running MongoDB instance (must be running on port 27018).

```bash
./run_ui_tests.sh --local
```

## How It Works

1. The tests use a separate database named `depictioDB_test` for testing.
2. Before each test, the database is cleaned to ensure a fresh state.
3. Test data is loaded from `depictio/api/v1/configs/initial_users.yaml`.
4. The tests run against this isolated database, so they don't affect production data.

## Implementation Details

### Database Connection

The application detects whether it's running in a Docker container or locally:

- In Docker: Uses `mongodb://mongo:27018/`
- Locally: Uses `mongodb://localhost:27018/`

### Test Database Cleanup

Before each test, the `clean_test_database()` function is called to drop all collections in the test database, ensuring a clean state.

### Environment Variables

Two environment variables control the test behavior:

- `DEPICTIO_TEST_MODE`: When set to `true`, enables test mode
- `DEPICTIO_MONGODB_DB_NAME`: Specifies the test database name (defaults to `depictioDB_test`)

## Inspecting the Test Database

Since the tests use a real MongoDB database, you can inspect it using standard MongoDB tools:

```bash
# Connect to the test database
mongo localhost:27018/depictioDB_test

# List collections
show collections

# Query users
db.users.find()
```

This allows you to debug tests by examining the database state during or after test execution.
