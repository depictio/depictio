describe('Unsuccessful Registration - Password Mismatch', () => {

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

    it('tests unsuccessful registration with password mismatch', () => {
      // Navigate to the auth page
      cy.visit('/auth')

      // Check if we're on the auth page
      cy.url().should('include', '/auth')

      // Check if the auth modal is present
      cy.get('#auth-modal').should('be.visible')

      // Click on the Switch to Register button
      cy.contains('button', 'Register').click()

      // Generate a unique test email to avoid conflicts with existing users
      const test_email = `test_user_${Date.now()}@example.com`
      const password1 = "SecurePassword123!"
      const password2 = "SecurePassword124!"

      // Use the email and mismatched passwords
      cy.get('input[type="text"][placeholder="Enter your email"]')
        .filter(':visible')
        .type(test_email)

      cy.get('input[type="password"][placeholder="Enter your password"]')
        .filter(':visible')
        .type(password1)

      cy.get('input[type="password"][placeholder="Confirm your password"]')
        .filter(':visible')
        .type(password2)

      // Wait for the register button to be enabled
      // cy.get('#register-button').should('not.be.disabled')

      // Click the register button
      cy.contains('button', 'Register').click()

      // Verify error message about passwords not matching (case-insensitive)
      cy.get('#user-feedback-message-register')
        .invoke('text')
        .then((text) => {
          const lowerText = text.toLowerCase();
          expect(lowerText).to.include('passwords do not match');
        });

      // Take a screenshot
      cy.screenshot('registration_password_mismatch_error')
    })
  })
