describe('Unsuccessful Registration - Password Mismatch', () => {

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

    it('tests unsuccessful registration with password mismatch', () => {
      // Generate a unique test email to avoid conflicts with existing users
      const test_email = `test_user_${Date.now()}@example.com`
      const password1 = "SecurePassword123!"
      const password2 = "SecurePassword124!"

      // Use the reusable function with mismatched passwords
      cy.registerUser(test_email, password1, password2)

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
