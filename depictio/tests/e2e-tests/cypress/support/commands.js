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

  // Fill in email input with improved reliability for CI
  cy.get('#modal-content')
    .find('input[id="login-email"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .wait(100) // Small wait after clear
    .type(email, { delay: 100, force: true })
    .should('have.value', email)
    .then(($input) => {
      // Verify the email was typed correctly, retry if truncated
      if ($input.val() !== email) {
        cy.wrap($input).clear().wait(200).type(email, { delay: 150, force: true })
      }
    });

  // Fill in password input with improved reliability
  cy.get('#modal-content')
    .find('input[id="login-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .wait(100) // Small wait after clear
    .type(password, { delay: 100, force: true })
    .should('have.value', password);

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

  // Fill in email input - wait for register form to be visible with improved CI reliability
  cy.get('#modal-content')
    .find('input[id="register-email"]')
    .should('be.visible')
    .should('be.enabled')
    .should('not.have.css', 'display', 'none')
    .focus()
    .clear()
    .wait(100) // Small wait after clear
    .type(email, { delay: 150, force: true })
    .should('have.value', email)
    .then(($input) => {
      // Verify the email was typed correctly, retry if truncated
      if ($input.val() !== email) {
        cy.wrap($input).clear().wait(200).type(email, { delay: 200, force: true })
      }
    });

  // Fill in password input with improved reliability
  cy.get('#modal-content')
    .find('input[id="register-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .wait(100) // Small wait after clear
    .type(password, { delay: 100, force: true })
    .should('have.value', password);

  // Fill in confirm password input with improved reliability
  cy.get('#modal-content')
    .find('input[id="register-confirm-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .wait(100) // Small wait after clear
    .type(confirmPwd, { delay: 100, force: true })
    .should('have.value', confirmPwd);

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
 * Quick token-based login using test credentials
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

    // Call the main loginWithToken command
    cy.loginWithToken(user.email, user.password);
  });
});
