# Project Permissions E2E Tests

This directory contains end-to-end tests for the project permissions management system.

## Test Files

### project-permissions.cy.js
Main test suite covering core functionality:
- Admin user permissions management
- Project owner permissions
- Non-owner user restrictions
- Permission validation rules
- Grid interactions and checkbox behavior

### project-permissions-edge-cases.cy.js
Edge cases and advanced scenarios:
- Modal interactions and confirmations
- Grid pagination and sorting
- Rapid action handling
- Multi-user selection
- Session persistence
- Error recovery

## Running the Tests

To run these tests locally:

```bash
# Run all project management tests
npx cypress run --spec "cypress/e2e/projects_management/*.cy.js"

# Run in interactive mode
npx cypress open
# Then select the test files from the UI

# Run specific test file
npx cypress run --spec "cypress/e2e/projects_management/project-permissions.cy.js"
```

## Test Requirements

These tests require:
- A running Depictio instance
- Test users configured in `cypress/fixtures/test-credentials.json`
- At least one project (e.g., "Iris Dataset Project Data Analysis" with ID: 646b0f3c1e4a2d7f8e5b8c9a)
- The project should be accessible at URL: `/project/646b0f3c1e4a2d7f8e5b8c9a`

## Test Coverage

The tests cover:
1. **Permission Roles**: Owner, Editor, Viewer
2. **User Management**: Adding, modifying, and removing users
3. **Access Control**: Ensuring only admins/owners can modify permissions
4. **UI Interactions**: Dropdown filtering, checkbox states, button enabling/disabling
5. **Project Visibility**: Public/private toggle functionality
6. **Edge Cases**: Last owner protection, duplicate user prevention, error handling

## Notes

- Tests skip automatically in `UNAUTHENTICATED_MODE`
- Each test cleans up after itself to ensure test isolation
- Wait times are included to handle async operations and API calls
- The backend callback has been fixed to prevent the "flash of disabled state" during page loading
- 10-second timeouts are used for permission state checks to handle async operations
