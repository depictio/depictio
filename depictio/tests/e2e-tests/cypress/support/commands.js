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

  // Fill in email input
  cy.get('#modal-content')
    .find('input[id="login-email"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .type(email, { delay: 50 })
    .should('have.value', email);

  // Fill in password input
  cy.get('#modal-content')
    .find('input[id="login-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .type(password, { delay: 50 })
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

  // Fill in email input - wait for register form to be visible
  cy.get('#modal-content')
    .find('input[id="register-email"]')
    .should('be.visible')
    .should('be.enabled')
    .should('not.have.css', 'display', 'none')
    .focus()
    .clear()
    .type(email, { delay: 100 })
    .should('have.value', email);

  // Fill in password input
  cy.get('#modal-content')
    .find('input[id="register-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .type(password, { delay: 50 })
    .should('have.value', password);

  // Fill in confirm password input
  cy.get('#modal-content')
    .find('input[id="register-confirm-password"]')
    .should('be.visible')
    .should('be.enabled')
    .focus()
    .clear()
    .type(confirmPwd, { delay: 50 })
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
