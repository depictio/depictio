describe('Registration Success', () => {
  console.log('Running registration success test');

  beforeEach(() => {
    // Skip if in unauthenticated mode (registration might be disabled)
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('registers a new user using reusable function', () => {
    // Generate a unique email for testing
    const timestamp = Date.now();
    const testEmail = `test_${timestamp}@example.com`;
    const testPassword = 'test_password_123';
    
    // Use the reusable registration function
    cy.registerUser(testEmail, testPassword);
    
    // Verify registration success message or behavior
    // Check for success feedback in the modal content
    cy.get('#modal-content').then(($modal) => {
      expect($modal.text()).to.satisfy((text) => {
        return text.includes('Registration successful') || text.includes('Please login');
      });
    });
  })

  it('registers user with different confirm password (should fail)', () => {
    const timestamp = Date.now();
    const testEmail = `test_fail_${timestamp}@example.com`;
    const testPassword = 'test_password_123';
    const wrongConfirmPassword = 'different_password';
    
    // This should fail because passwords don't match
    cy.registerUser(testEmail, testPassword, wrongConfirmPassword);
    
    // Verify error message in modal content
    cy.get('#modal-content')
      .should('contain', 'Passwords do not match');
  })

  it('tries to register with existing email (should fail)', () => {
    // Try to register with the test user email that already exists
    cy.fixture('test-credentials.json').then((credentials) => {
      const existingEmail = credentials.testUser.email;
      const testPassword = 'some_password';
      
      cy.registerUser(existingEmail, testPassword);
      
      // Verify error message for existing email
      cy.get('#modal-content')
        .should('contain', 'Email already registered');
    });
  })
})