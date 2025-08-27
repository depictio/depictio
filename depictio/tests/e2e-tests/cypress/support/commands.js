// ***********************************************
// This example commands.js shows you how to
// create various custom commands and overwrite
// existing commands.
//
// For more comprehensive examples of custom
// commands please read more here:
// https://on.cypress.io/custom-commands
// ***********************************************
//
//
// -- This is a parent command --
// Cypress.Commands.add('login', (email, password) => { ... })
//
//
// -- This is a child command --
// Cypress.Commands.add('drag', { prevSubject: 'element'}, (subject, options) => { ... })
//
//
// -- This is a dual command --
// Cypress.Commands.add('dismiss', { prevSubject: 'optional'}, (subject, options) => { ... })
//
//
// -- This will overwrite an existing command --
// Cypress.Commands.overwrite('visit', (originalFn, url, options) => { ... })

// Add any general custom commands here

/**
 * Reusable login function that opens the auth modal and logs in a user
 * @param {string} email - User email
 * @param {string} password - User password
 * @param {object} options - Optional configuration
 * @param {boolean} options.visitAuth - Whether to visit /auth page first (default: true)
 * @param {number} options.timeout - Timeout for operations (default: 10000)
 */
Cypress.Commands.add('loginUser', (email, password, options = {}) => {
  const { visitAuth = true, timeout = 10000 } = options;

  if (visitAuth) {
    cy.visit('/auth');
    cy.wait(2000); // Wait for page to load
  }

  // Check for modal visibility
  cy.get('[role="dialog"][aria-modal="true"]', { timeout }).should('be.visible');
  cy.get('#modal-content', { timeout }).should('be.visible');

  // Use robust typing for email and password
  cy.typeRobust('#modal-content input[id="login-email"]', email)
  cy.typePassword('#modal-content input[id="login-password"]', password)

  // Click login button
  cy.get('#modal-content')
    .find('button[id="login-button"]')
    .should('be.visible')
    .should('not.be.disabled')
    .click();

  // Wait for login processing
  cy.wait(1000);
});

/**
 * Reusable registration function that opens the auth modal and registers a new user
 * @param {string} email - User email
 * @param {string} password - User password
 * @param {string} confirmPassword - Password confirmation (optional, defaults to password)
 * @param {object} options - Optional configuration
 * @param {boolean} options.visitAuth - Whether to visit /auth page first (default: true)
 * @param {number} options.timeout - Timeout for operations (default: 10000)
 */
Cypress.Commands.add('registerUser', (email, password, confirmPassword = null, options = {}) => {
  const { visitAuth = true, timeout = 10000 } = options;
  const confirmPwd = confirmPassword || password;

  if (visitAuth) {
    cy.visit('/auth');
    cy.wait(2000); // Wait for page to load
  }

  // Check for modal visibility
  cy.get('[role="dialog"][aria-modal="true"]', { timeout }).should('be.visible');
  cy.get('#modal-content', { timeout }).should('be.visible');

  // Click register button to switch to registration form
  cy.get('#modal-content')
    .contains('Register')
    .should('be.visible')
    .click();

  // Wait for form to switch
  cy.wait(500);

  // Use robust typing for registration fields
  cy.typeRobust('#modal-content input[id="register-email"]', email, { delay: 150 })
  cy.typePassword('#modal-content input[id="register-password"]', password)
  cy.typePassword('#modal-content input[id="register-confirm-password"]', confirmPwd)

  // Click register button
  cy.get('#modal-content')
    .find('button[id="register-button"]')
    .should('be.visible')
    .should('not.be.disabled')
    .click();

  // Wait for registration processing
  cy.wait(1000);
});

/**
 * Quick login using test credentials from fixture
 * @param {string} userType - Type of user to login as ('testUser' or 'adminUser')
 */
Cypress.Commands.add('loginAsTestUser', (userType = 'testUser') => {
  cy.fixture('test-credentials.json').then((credentials) => {
    const user = credentials[userType];
    cy.loginUser(user.email, user.password);
  });
});

/**
 * Wait for sidebar and other UI elements to be fully rendered
 * This helps prevent visibility issues in CI environments
 * @param {number} timeout - Timeout for waiting (default: 15000)
 */
Cypress.Commands.add('waitForUIElements', (timeout = 15000) => {
  // Wait for the main application layout to be ready
  cy.get('body', { timeout }).should('be.visible');

  // Wait for any potential loading spinners to disappear
  cy.get('body').should('not.contain', 'Loading...');

  // Wait for any sidebar elements (adjust selectors based on your app)
  // This is a general approach - you may need to customize selectors
  cy.get('[data-cy="sidebar"], .sidebar, #sidebar', { timeout: 5000 }).should('exist').then(($sidebar) => {
    if ($sidebar.length > 0) {
      // If sidebar exists, ensure it's visible
      cy.wrap($sidebar).should('be.visible').and('not.have.css', 'display', 'none');
    }
  });

  // Additional wait to ensure all CSS transitions and animations complete
  cy.wait(1000);
});

/**
 * Enhanced wait for dashboard elements specifically
 * @param {number} timeout - Timeout for waiting (default: 20000)
 */
Cypress.Commands.add('waitForDashboard', (timeout = 20000) => {
  // First wait for basic UI elements
  cy.waitForUIElements(timeout);

  // Wait for dashboard-specific elements
  cy.get('body', { timeout }).should('not.contain', 'Redirecting...');

  // Wait for any dashboard containers or main content areas
  cy.get('[data-cy="dashboard"], .dashboard-container, #dashboard-content', { timeout: 10000 }).should('exist').then(($dashboard) => {
    if ($dashboard.length > 0) {
      cy.wrap($dashboard).should('be.visible');
    }
  });

  // Ensure page is fully loaded by checking for common elements
  cy.get('nav, .nav, .navbar, [role="navigation"]', { timeout: 5000 }).should('exist').then(($nav) => {
    if ($nav.length > 0) {
      cy.wrap($nav).should('be.visible');
    }
  });

  // Final wait for any remaining async operations
  cy.wait(2000);
});

/**
 * Direct token-based login that bypasses the auth form by directly setting localStorage
 * This is faster for tests than going through the full UI login flow
 * @param {string} email - User email to authenticate as
 * @param {string} password - User password
 * @param {object} options - Optional configuration
 * @param {boolean} options.visitHome - Whether to visit home page first (default: true)
 * @param {string} options.apiBaseUrl - Base URL for API calls (default: localhost:8058)
 * @param {string} options.frontendBaseUrl - Base URL for frontend visits (default: uses Cypress baseUrl)
 */
Cypress.Commands.add('loginWithToken', (email = 'admin@example.com', password = 'changeme', options = {}) => {
  const {
    visitHome = true,
    apiBaseUrl = 'http://localhost:8058',  // API server
    frontendBaseUrl = Cypress.config('baseUrl')  // Frontend server
  } = options;

  cy.log('🚀 Starting token-based login process');
  cy.log(`📧 Email: ${email}`);
  cy.log(`🔒 Password: ${'*'.repeat(password.length)}`);
  cy.log(`🌐 API Base URL: ${apiBaseUrl}`);
  cy.log(`🌐 Frontend Base URL: ${frontendBaseUrl}`);
  cy.log(`🏠 Visit Home: ${visitHome}`);

  // Step 1: Login via API to get a fresh token
  const loginUrl = `${apiBaseUrl}/depictio/api/v1/auth/login`;
  cy.log(`📞 Calling login API: ${loginUrl}`);

  cy.request({
    method: 'POST',
    url: loginUrl,
    form: true, // Important: OAuth2PasswordRequestForm expects form data
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: {
      username: email, // OAuth2PasswordRequestForm uses 'username' field for email
      password: password,
      grant_type: 'password' // OAuth2 often requires this
    },
    failOnStatusCode: false
  }).then((loginResponse) => {
    cy.log(`📨 Login API Response Status: ${loginResponse.status}`);
    cy.log(`📨 Response Headers:`, loginResponse.headers);
    cy.log(`📨 Full Response Body:`, loginResponse.body);

    if (loginResponse.status !== 200) {
      cy.log(`❌ Login failed with status ${loginResponse.status}`);
      cy.log(`❌ Error details:`, loginResponse.body);
      cy.log(`❌ Response text:`, loginResponse.body);

      // Try to extract more detailed error info
      let errorMessage = 'Unknown error';
      if (loginResponse.body) {
        if (typeof loginResponse.body === 'string') {
          errorMessage = loginResponse.body;
        } else if (loginResponse.body.detail) {
          errorMessage = loginResponse.body.detail;
        } else if (loginResponse.body.message) {
          errorMessage = loginResponse.body.message;
        } else {
          errorMessage = JSON.stringify(loginResponse.body);
        }
      }

      throw new Error(`Login failed for ${email} (Status: ${loginResponse.status}): ${errorMessage}`);
    }

    cy.log('✅ Login API call successful');
    const tokenBeanie = loginResponse.body;

    // Debug: Log the received token structure
    cy.log('📋 Received TokenBeanie structure:');
    cy.log(`   - ID: ${tokenBeanie.id || tokenBeanie._id}`);
    cy.log(`   - User ID: ${tokenBeanie.user_id}`);
    cy.log(`   - Token Type: ${tokenBeanie.token_type}`);
    cy.log(`   - Token Lifetime: ${tokenBeanie.token_lifetime}`);
    cy.log(`   - Token Name: ${tokenBeanie.name}`);
    cy.log(`   - Expire DateTime: ${tokenBeanie.expire_datetime}`);
    cy.log(`   - Refresh Expire DateTime: ${tokenBeanie.refresh_expire_datetime}`);
    cy.log(`   - Created At: ${tokenBeanie.created_at}`);
    cy.log(`   - Access Token: ${tokenBeanie.access_token?.substring(0, 20)}...`);
    cy.log(`   - Refresh Token: ${tokenBeanie.refresh_token?.substring(0, 20)}...`);

    // Step 2: Prepare token data for localStorage (matching screenshot_dash_fixed format)
    cy.log('🔧 Preparing token data for localStorage');
    const tokenData = {
      _id: tokenBeanie.id || tokenBeanie._id,
      user_id: tokenBeanie.user_id,
      access_token: tokenBeanie.access_token,
      refresh_token: tokenBeanie.refresh_token,
      token_type: tokenBeanie.token_type || 'bearer',
      token_lifetime: tokenBeanie.token_lifetime || 'short-lived',
      expire_datetime: tokenBeanie.expire_datetime,
      refresh_expire_datetime: tokenBeanie.refresh_expire_datetime,
      name: tokenBeanie.name,
      created_at: tokenBeanie.created_at,
      logged_in: true
    };

    cy.log('💾 Final token data structure for localStorage:');
    cy.log(`   - _id: ${tokenData._id}`);
    cy.log(`   - user_id: ${tokenData.user_id}`);
    cy.log(`   - token_type: ${tokenData.token_type}`);
    cy.log(`   - token_lifetime: ${tokenData.token_lifetime}`);
    cy.log(`   - logged_in: ${tokenData.logged_in}`);
    cy.log(`   - expire_datetime: ${tokenData.expire_datetime}`);
    cy.log(`   - refresh_expire_datetime: ${tokenData.refresh_expire_datetime}`);

    const tokenDataJson = JSON.stringify(tokenData);
    cy.log(`📏 Token JSON size: ${tokenDataJson.length} characters`);

    // Step 3: Visit home page and set the token in localStorage
    if (visitHome) {
      cy.log('🏠 Visiting home page before setting token');
      cy.visit(frontendBaseUrl);
    } else {
      cy.log('⏭️ Skipping home page visit');
    }

    cy.window().then((win) => {
      cy.log('💾 Setting token in localStorage with key "local-store"');
      win.localStorage.setItem('local-store', tokenDataJson);
      cy.log('✅ Token stored in localStorage');

      // Debug: Check localStorage immediately after setting
      const immediateCheck = win.localStorage.getItem('local-store');
      cy.log(`🔍 Immediate localStorage check: ${immediateCheck ? 'Token found' : 'Token NOT found'}`);
    });

    // Step 4: Verify token was set correctly
    cy.window().then((win) => {
      cy.log('🔍 Verifying token was stored correctly...');
      const storedToken = win.localStorage.getItem('local-store');

      if (!storedToken) {
        cy.log('❌ No token found in localStorage!');
        throw new Error('Token was not stored in localStorage');
      }

      cy.log('✅ Token found in localStorage');
      const parsed = JSON.parse(storedToken);

      cy.log('🧪 Verifying token structure...');
      cy.log(`   - Parsed logged_in: ${parsed.logged_in}`);
      cy.log(`   - Parsed access_token matches: ${parsed.access_token === tokenBeanie.access_token}`);
      cy.log(`   - Parsed user_id: ${parsed.user_id}`);
      cy.log(`   - Parsed _id: ${parsed._id}`);

      expect(storedToken).to.not.be.null;
      expect(parsed.logged_in).to.be.true;
      expect(parsed.access_token).to.equal(tokenBeanie.access_token);

      cy.log('✅ All token verifications passed');
    });

    cy.log(`🎉 Successfully logged in and set token for user: ${email}`);
    cy.log('🏁 Token-based login process completed');
  });
});

/**
 * Ensures test user exists by attempting to create it if login fails
 * @param {string} email - User email
 * @param {string} password - User password
 * @param {boolean} isAdmin - Whether user should be admin
 */
Cypress.Commands.add('ensureUserExists', (email, password, isAdmin = false) => {
  const apiBaseUrl = 'http://localhost:8058';

  cy.log(`🔍 Ensuring user exists: ${email}`);

  // First try to login to check if user exists
  return cy.request({
    method: 'POST',
    url: `${apiBaseUrl}/depictio/api/v1/auth/login`,
    form: true,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: { username: email, password: password, grant_type: 'password' },
    failOnStatusCode: false
  }).then((response) => {
    if (response.status === 200) {
      cy.log(`✅ User ${email} already exists and credentials are valid`);
      return cy.wrap({ exists: true, user: { email, password, isAdmin } });
    } else {
      cy.log(`⚠️ User ${email} login failed (${response.status}). Attempting to create user...`);

      // Try to create the user via admin API (if available)
      // First login as admin to get admin token
      return cy.request({
        method: 'POST',
        url: `${apiBaseUrl}/depictio/api/v1/auth/login`,
        form: true,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: { username: 'admin@example.com', password: 'changeme', grant_type: 'password' },
        failOnStatusCode: false
      }).then((adminResponse) => {
        if (adminResponse.status === 200) {
          cy.log(`✅ Admin login successful. Creating user ${email}...`);

          // Create the user using admin token
          return cy.request({
            method: 'POST',
            url: `${apiBaseUrl}/depictio/api/v1/users/create`,
            headers: {
              'Authorization': `Bearer ${adminResponse.body.access_token}`,
              'Content-Type': 'application/json'
            },
            body: {
              email: email,
              password: password,
              is_admin: isAdmin
            },
            failOnStatusCode: false
          }).then((createResponse) => {
            if (createResponse.status === 200 || createResponse.status === 201) {
              cy.log(`✅ User ${email} created successfully`);
              return cy.wrap({ exists: true, user: { email, password, isAdmin } });
            } else {
              cy.log(`⚠️ Failed to create user ${email}. Using admin fallback.`);
              return cy.wrap({
                exists: false,
                fallback: { email: 'admin@example.com', password: 'changeme', isAdmin: true }
              });
            }
          });
        } else {
          cy.log(`❌ Admin login also failed. Using hardcoded admin fallback.`);
          return cy.wrap({
            exists: false,
            fallback: { email: 'admin@example.com', password: 'changeme', isAdmin: true }
          });
        }
      });
    }
  });
});

/**
 * Quick token-based login using test credentials with user existence check
 * @param {string} userType - Type of user to login as ('testUser' or 'adminUser')
 */
Cypress.Commands.add('loginWithTokenAsTestUser', (userType = 'testUser') => {
  cy.log(`🎭 Loading test credentials for user type: ${userType}`);

  cy.fixture('test-credentials.json').then((credentials) => {
    cy.log('📁 Test credentials loaded successfully');
    cy.log(`🔍 Available user types: ${Object.keys(credentials).join(', ')}`);

    const user = credentials[userType];

    if (!user) {
      cy.log(`❌ User type '${userType}' not found in test credentials`);
      throw new Error(`User type '${userType}' not found in test credentials`);
    }

    cy.log(`✅ Found credentials for ${userType}:`);
    cy.log(`   - Email: ${user.email}`);
    cy.log(`   - Password: ${'*'.repeat(user.password?.length || 0)}`);

    // Ensure user exists before attempting login
    cy.ensureUserExists(user.email, user.password, user.is_admin).then((result) => {
      if (result.exists) {
        cy.log(`🚀 Logging in with verified user: ${user.email}`);
        cy.loginWithToken(user.email, user.password);
      } else if (result.fallback) {
        cy.log(`🔄 Using fallback user: ${result.fallback.email}`);
        cy.loginWithToken(result.fallback.email, result.fallback.password);
      } else {
        throw new Error(`Unable to ensure user ${user.email} exists and no fallback available`);
      }
    });
  });
});

/**
 * Robust text input with retry logic and validation
 * Handles timing issues with text inputs in React components
 * @param {string} selector - CSS selector for the input element
 * @param {string} text - Text to input
 * @param {object} options - Configuration options
 * @param {number} options.delay - Delay between keystrokes (default: 100)
 * @param {number} options.clearDelay - Delay after clearing (default: 200)
 * @param {number} options.retryDelay - Delay before retry (default: 300)
 * @param {number} options.maxRetries - Maximum retry attempts (default: 2)
 * @param {boolean} options.force - Force typing even if element not in viewport (default: true)
 * @param {boolean} options.validateValue - Validate the final value matches input (default: true)
 * @param {number} options.timeout - Timeout for element selection (default: 10000)
 */
Cypress.Commands.add('typeRobust', (selector, text, options = {}) => {
  const {
    delay = 100,
    clearDelay = 200,
    retryDelay = 300,
    maxRetries = 2,
    force = true,
    validateValue = true,
    timeout = 10000
  } = options;

  cy.log(`📝 Robust typing: "${text}" into ${selector}`);

  // Helper function to perform the typing operation
  const performTyping = (attempt = 1) => {
    cy.log(`🎯 Typing attempt ${attempt}/${maxRetries + 1}`);

    return cy.get(selector, { timeout })
      .should('be.visible')
      .should('be.enabled')
      .focus()
      .clear()
      .wait(clearDelay)
      .type(text, { delay, force })
      .wait(clearDelay)
      .then(($el) => {
        if (validateValue && $el.val() !== text) {
          if (attempt <= maxRetries) {
            cy.log(`⚠️ Input mismatch (expected: "${text}", got: "${$el.val()}"). Retrying...`);
            cy.wait(retryDelay);
            return performTyping(attempt + 1);
          } else {
            cy.log(`❌ Input failed after ${maxRetries + 1} attempts. Expected: "${text}", Got: "${$el.val()}"`);
            throw new Error(`Text input failed after ${maxRetries + 1} attempts. Expected: "${text}", Got: "${$el.val()}"`);
          }
        }

        cy.log(`✅ Successfully typed "${text}" into ${selector}`);
        return cy.wrap($el);
      });
  };

  return performTyping();
});

/**
 * Simplified robust typing for password fields
 * Pre-configured for common password input scenarios
 * @param {string} selector - CSS selector for the password input
 * @param {string} password - Password to input
 * @param {object} options - Additional options (merged with password defaults)
 */
Cypress.Commands.add('typePassword', (selector, password, options = {}) => {
  const passwordDefaults = {
    delay: 100,
    clearDelay: 200,
    retryDelay: 300,
    maxRetries: 2,
    force: true,
    validateValue: true
  };

  const finalOptions = { ...passwordDefaults, ...options };
  cy.log(`🔒 Robust password typing into ${selector}`);
  return cy.typeRobust(selector, password, finalOptions);
});

/**
 * Robust logout functionality that waits for elements and handles timing issues
 * This addresses the common race condition where logout button may not be loaded yet
 * @param {object} options - Configuration options
 * @param {number} options.timeout - Timeout for finding elements (default: 15000)
 * @param {boolean} options.visitProfile - Whether to visit profile page first (default: true)
 * @param {boolean} options.verifyLogout - Whether to verify logout completed (default: true)
 */
Cypress.Commands.add('logoutRobust', (options = {}) => {
  const { timeout = 15000, visitProfile = true, verifyLogout = true } = options;

  cy.log('🚪 Starting robust logout process');

  if (visitProfile) {
    cy.log('👤 Visiting profile page');
    cy.visit('/profile');
    cy.wait(2000);
  }

  cy.log('⏳ Waiting for profile page elements to load...');

  // Wait for user info placeholder to be populated (indicates page loaded)
  cy.get('[id="user-info-placeholder"]', { timeout })
    .should('exist')
    .and('not.be.empty');

  // Wait specifically for logout button using correct selector
  cy.log('🔍 Looking for logout button...');
  cy.get('button[id="logout-button"]', { timeout })
    .should('exist')
    .and('be.visible')
    .and('not.be.disabled')
    .and('contain.text', 'Logout');

  cy.log('👆 Clicking logout button');
  cy.get('button[id="logout-button"]')
    .click({ force: true });

  cy.wait(2000); // Give logout time to process

  if (verifyLogout) {
    cy.log('✅ Verifying logout completed...');

    // Check that we're redirected away from protected pages
    cy.url().should('not.include', '/dashboards');

    // Verify localStorage state
    cy.window().then((win) => {
      const localStore = win.localStorage.getItem('local-store');
      if (localStore) {
        const parsed = JSON.parse(localStore);
        expect(parsed.logged_in).to.be.false;
        cy.log('✅ LocalStorage updated - user logged out');
      } else {
        cy.log('✅ LocalStorage cleared - user logged out');
      }
    });

    // Additional verification: try to access protected route
    cy.visit('/dashboards');
    cy.wait(1000);
    cy.url().should('not.include', '/dashboards');
  }

  cy.log('🎉 Logout process completed successfully');
});

/**
 * Clean up test dashboards via API to prevent test pollution
 * Uses the same token mechanism as loginWithTokenAsTestUser
 * @param {string} userType - Type of user for authentication (default: 'adminUser')
 * @param {string} titlePattern - Pattern to match dashboard titles (default: 'Simple Test Dashboard')
 */
Cypress.Commands.add('cleanupTestDashboards', (userType = 'adminUser', titlePattern = 'Simple Test Dashboard') => {
  cy.log(`🧹 Starting cleanup of test dashboards matching: "${titlePattern}"`);

  // Login to get token (same approach as loginWithTokenAsTestUser)
  cy.fixture('test-credentials.json').then((credentials) => {
    const user = credentials[userType];

    if (!user) {
      cy.log(`❌ User type '${userType}' not found in credentials. Skipping cleanup.`);
      return;
    }

    cy.log(`🔑 Authenticating as ${user.email} for cleanup`);

    // Get token via API login
    cy.request({
      method: 'POST',
      url: 'http://localhost:8058/depictio/api/v1/auth/login',
      form: true,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: {
        username: user.email,
        password: user.password,
        grant_type: 'password'
      },
      failOnStatusCode: false
    }).then((loginResponse) => {
      if (loginResponse.status !== 200) {
        cy.log(`⚠️ Authentication failed for cleanup. Status: ${loginResponse.status}`);
        cy.log(`⚠️ Skipping dashboard cleanup due to auth failure`);
        return;
      }

      const token = loginResponse.body.access_token;
      cy.log(`✅ Authentication successful for cleanup`);

      // Get all dashboards
      cy.request({
        method: 'GET',
        url: 'http://localhost:8058/depictio/api/v1/dashboards/list_all',
        headers: { 'Authorization': `Bearer ${token}` },
        failOnStatusCode: false
      }).then((dashboardsResponse) => {
        if (dashboardsResponse.status !== 200) {
          cy.log(`⚠️ Failed to fetch dashboards for cleanup. Status: ${dashboardsResponse.status}`);
          return;
        }

        // Filter dashboards matching the pattern
        const testDashboards = dashboardsResponse.body.filter(dashboard =>
          dashboard.title && dashboard.title.includes(titlePattern)
        );

        cy.log(`🔍 Found ${testDashboards.length} dashboards matching pattern "${titlePattern}"`);

        if (testDashboards.length === 0) {
          cy.log(`✅ No test dashboards found to clean up`);
          return;
        }

        // Delete each matching dashboard
        testDashboards.forEach((dashboard, index) => {
          cy.log(`🗑️ Deleting dashboard ${index + 1}/${testDashboards.length}: "${dashboard.title}"`);

          cy.request({
            method: 'DELETE',
            url: `http://localhost:8058/depictio/api/v1/dashboards/delete/${dashboard.dashboard_id}`,
            headers: { 'Authorization': `Bearer ${token}` },
            failOnStatusCode: false // Don't fail cleanup if individual delete fails
          }).then((deleteResponse) => {
            if (deleteResponse.status === 200) {
              cy.log(`✅ Successfully deleted: "${dashboard.title}"`);
            } else {
              cy.log(`⚠️ Failed to delete "${dashboard.title}" (Status: ${deleteResponse.status})`);
            }
          });
        });

        cy.log(`🧹 Cleanup completed for ${testDashboards.length} test dashboards`);
      });
    });
  });
});
