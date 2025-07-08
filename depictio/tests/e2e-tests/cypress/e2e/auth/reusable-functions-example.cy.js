describe('Reusable Auth Functions - Usage Examples', () => {
  console.log('Demonstrating reusable auth functions');

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

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
    const timestamp = Date.now();
    const newEmail = `newuser_${timestamp}@example.com`;
    const password = 'test123';

    // Register new user
    cy.registerUser(newEmail, password);

    // Then login with the same credentials
    cy.loginUser(newEmail, password);
  })

  it('Example 5: Test registration validation', () => {
    const timestamp = Date.now();
    const email = `validation_test_${timestamp}@example.com`;

    // Test password mismatch
    cy.registerUser(email, 'password1', 'password2');
    cy.get('#modal-content').should('contain', 'Passwords do not match');
  })

  it('Example 6: Login as admin user', () => {
    // Login as admin using fixture credentials
    cy.loginAsTestUser('adminUser');

    // Now perform admin actions
    // cy.visit('/admin');
    // cy.get('[data-testid="admin-panel"]').should('exist');
  })
});
