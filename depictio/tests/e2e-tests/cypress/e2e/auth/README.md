# Authentication Tests - Reorganized Structure

This directory contains authentication-related E2E tests organized into a cleaner, more maintainable structure.

## 📁 **New Structure (3 files)**

### 🔐 **auth-ui-login.cy.js**
**Purpose**: Tests the `/auth` page login UI functionality
- ✅ Login success scenarios
- ❌ Login failure scenarios
- 📖 Login usage examples and patterns
- 🧪 Reusable function demonstrations

### 📝 **auth-ui-registration.cy.js**
**Purpose**: Tests the `/auth` page registration UI functionality
- ✅ Registration success scenarios
- ❌ Registration failure scenarios (password mismatch, duplicate email)
- 🛡️ Registration validation testing
- 🔄 Registration flow verification

### ⚙️ **auth-account-management.cy.js**
**Purpose**: Tests account management and token-based authentication
- 🔑 Password management (edit/change password)
- 🚪 Session management (logout functionality)
- 🎫 Token management (CLI config creation)
- 🚀 Token-based authentication API tests

## 📦 **Current File Mapping**

| **New File** | **Consolidates These Old Files** |
|--------------|-----------------------------------|
| `auth-ui-login.cy.js` | `login-success.cy.js`, `login-fail.cy.js`, `reusable-functions-example.cy.js` (login examples) |
| `auth-ui-registration.cy.js` | `registration-success.cy.js`, `user-registration-success.cy.js`, `user-registration-fail.cy.js`, `user-registration-password-mismatch.cy.js` |
| `auth-account-management.cy.js` | `edit-password.cy.js`, `logout.cy.js`, `create-cli-config.cy.js`, `token-login-test.cy.js` |

## 🗂️ **Files Kept Unchanged**

These files remain in their current location as they serve specific purposes:

- ✅ `token-login-test.cy.js` - **Moved into account management**
- ✅ `edit-password.cy.js` - **Moved into account management**
- ✅ `logout.cy.js` - **Moved into account management**
- ✅ `create-cli-config.cy.js` - **Moved into account management**

## 📁 **Backup Location**

Original files have been moved to: `old-files-backup/`
- **Files renamed**: `.cy.js` → `.backup.js` to prevent Cypress from running them
- This preserves the original test implementations
- Easy to reference if needed
- **Safe from accidental execution**: Cypress only runs `*.cy.js` files
- Can be removed after verification of new structure

## 🎯 **Benefits of Reorganization**

1. **🧹 Cleaner Structure**: 3 focused files instead of 12 scattered files
2. **📋 Logical Grouping**: Related tests are grouped together
3. **🔍 Easier Navigation**: Clear naming shows what each file tests
4. **🚀 Better Maintenance**: Easier to update and extend tests
5. **📖 Self-Documenting**: File names clearly indicate their purpose
6. **🧪 Comprehensive Coverage**: All original test scenarios preserved

## 🚀 **Usage**

```bash
# Run all auth tests (only runs .cy.js files - backup files are safe)
npx cypress run --spec "cypress/e2e/auth/*.cy.js"

# Run specific test categories
npx cypress run --spec "cypress/e2e/auth/auth-ui-login.cy.js"
npx cypress run --spec "cypress/e2e/auth/auth-ui-registration.cy.js"
npx cypress run --spec "cypress/e2e/auth/auth-account-management.cy.js"

# Verify backup files are not executed
find cypress/e2e -name "*.backup.js" | wc -l  # Shows 8 backup files
find cypress/e2e -name "*.cy.js" | grep backup  # Shows nothing (safe!)
```

## ⚡ **Performance Impact**

The reorganization maintains the same test coverage while:
- ✅ Reducing file clutter (12 → 3 files)
- ✅ Improving test discovery and organization
- ✅ Making it easier to run related tests together
- ✅ Simplifying maintenance and updates
