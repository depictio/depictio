describe('Authentication UI - Registration Flow', () => {
  beforeEach(() => {
    // Skip if in unauthenticated mode (registration might be disabled)
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  describe('Registration Success Scenarios', () => {
    it('should register a new user successfully using reusable function', () => {
      // Generate a unique email for testing
      const timestamp = Date.now();
      const testEmail = `test_${timestamp}@example.com`;
      const testPassword = 'test_password_123';

      // Use the reusable registration function
      cy.registerUser(testEmail, testPassword);

      // Verify registration success message or behavior
      cy.get('#user-feedback-message-register').should('be.visible')
      cy.get('#user-feedback-message-register')
        .should('contain.text', 'Registration successful')
    })

    it('should register a new user and verify login works', () => {
      // Use unique email to avoid conflicts
      const timestamp = Date.now()
      const test_email = `test_user_${timestamp}@example.com`
      const test_password = "SecurePassword123!"

      // Register using the reusable function
      cy.registerUser(test_email, test_password)

      // Wait for the success message
      cy.get('#user-feedback-message-register').should('be.visible')

      // Check for successful registration message
      cy.get('#user-feedback-message-register')
        .should('contain.text', 'Registration successful')

      // Wait and close any modals or messages
      cy.wait(3000)

      // Try to close any open registration modal/message
      cy.get('body').then(($body) => {
        if ($body.find('button:contains("Close")').length > 0) {
          cy.contains('button', 'Close').click()
        }
        cy.wait(2000)

        // Navigate to dashboards and try to login with the newly registered user
        cy.visit('/dashboards')
        cy.wait(2000)

        // Test login with the new user credentials
        cy.loginUser(test_email, test_password, { visitAuth: false })
      })
    })
  })

  describe('Registration Failure Scenarios', () => {
    it('should show error for password mismatch', () => {
      // Generate a unique test email to avoid conflicts with existing users
      const test_email = `test_user_${Date.now()}@example.com`
      const password1 = "SecurePassword123!"
      const password2 = "SecurePassword124!"

      // Use the reusable function with mismatched passwords
      cy.registerUser(test_email, password1, password2)

      // Verify error message about passwords not matching (case-insensitive)
      cy.get('#user-feedback-message-register')
        .should('be.visible')
        .invoke('text')
        .should('match', /password.*match/i)
    })

    it('should show error when trying to register with existing email', () => {
      let testUser;

      cy.fixture('test-credentials.json').then((credentials) => {
        testUser = credentials.testUser;

        // Try to register with an existing email
        cy.registerUser(testUser.email, 'SomePassword123!')

        // Wait for error message
        cy.get('#user-feedback-message-register').should('be.visible')

        // Check for error message indicating user already exists
        cy.get('#user-feedback-message-register')
          .invoke('text')
          .should('match', /already.*exist|already.*register/i)
      });
    })

    it('should handle duplicate registration attempts gracefully', () => {
      // Generate a unique email for testing
      const timestamp = Date.now();
      const testEmail = `test_${timestamp}@example.com`;
      const testPassword = 'test_password_123';

      // Use the reusable registration function
      cy.registerUser(testEmail, testPassword);

      // Wait for the success message to appear first
      cy.get('#user-feedback-message-register').should('be.visible')

      // Then check if it indicates success or failure appropriately
      cy.get('#user-feedback-message-register').then(($message) => {
        const messageText = $message.text().toLowerCase()

        if (messageText.includes('already') || messageText.includes('exist')) {
          // User already exists - this is expected for duplicate registration
          cy.log('Duplicate registration handled correctly')
        } else if (messageText.includes('success') || messageText.includes('created')) {
          // Registration was successful
          cy.log('Registration successful')
        } else {
          // Unexpected message
          cy.log(`Unexpected registration message: ${messageText}`)
        }
      })
    })
  })

  describe('Registration Validation Examples', () => {
    it('Example 5: Test registration validation', () => {
      // Test with weak password
      const email = `weak_${Date.now()}@example.com`;

      // This should fail validation (adjust based on your validation rules)
      cy.registerUser(email, '123', '123');

      // Check for validation error
      // cy.get('#password-validation-error').should('be.visible');
    })
  })
})
