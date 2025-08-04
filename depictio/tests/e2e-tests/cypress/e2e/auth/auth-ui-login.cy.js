describe('Authentication UI - Login Flow', () => {
  let testUser;

  before(() => {
    // Skip this test suite if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping login UI tests - running in unauthenticated mode')
      return
    }

    cy.fixture('test-credentials.json').then((credentials) => {
      testUser = credentials.testUser;
    });
  });

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  describe('Login Success Scenarios', () => {
    it('should login successfully with valid credentials using reusable function', () => {
      // Use the new reusable login function
      cy.loginUser(testUser.email, testUser.password)

      // Optional: verify successful login by checking URL or page content
      // cy.url().should('include', '/dashboards')
    })

    it('should login successfully using quick test user function', () => {
      // Even simpler - use the test user function
      cy.loginAsTestUser('testUser')

      // Optional: verify successful login
      // cy.url().should('include', '/dashboards')
    })
  })

  describe('Login Failure Scenarios', () => {
    it('should show error message for invalid credentials', () => {
      // Use invalid credentials
      const invalidEmail = 'invalid_user@example.com'
      const invalidPassword = 'wrong_password'

      // Try to login with invalid credentials using reusable function
      cy.loginUser(invalidEmail, invalidPassword)

      // Wait for error message to appear
      cy.get('#user-feedback-message-login').should('be.visible')
      cy.get('#user-feedback-message-login')
        .should('contain.text', 'Invalid credentials')
    })
  })

  describe('Login Examples and Usage Patterns', () => {
    it('Example 1: Quick login with test user', () => {
      // Simplest way to login with test credentials
      cy.loginAsTestUser('testUser');

      // Now you can perform actions as a logged-in user
      // cy.visit('/dashboards');
      // cy.get('[data-testid="dashboard-list"]').should('exist');
    })

    it('Example 2: Login with custom credentials', () => {
      // Login with specific email/password
      cy.loginUser('custom@example.com', 'custom_password');

      // Continue with your test...
    })

    it('Example 3: Login without visiting auth page first', () => {
      // If you're already on a page and need to login
      cy.visit('/some-other-page');
      cy.loginUser('test@example.com', 'password', { visitAuth: true });
    })

    it('Example 4: Register new user and then login', () => {
      const newEmail = `test_${Date.now()}@example.com`;
      const password = 'SecurePassword123!';

      // First register
      cy.registerUser(newEmail, password);

      // Then login with the new credentials
      cy.loginUser(newEmail, password);
    })

    it('Example 6: Login as admin user', () => {
      cy.loginAsTestUser('adminUser')

      // Now you can test admin-specific functionality
      // cy.visit('/admin');
      // cy.get('[data-testid="admin-panel"]').should('be.visible');
    })
  })
})
