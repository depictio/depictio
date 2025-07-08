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
