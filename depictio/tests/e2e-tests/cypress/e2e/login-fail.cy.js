describe('Login fail', () => {
    it('should show error message for invalid credentials', () => {
      // Navigate to the auth page
      cy.visit('/auth')

      // Check if we're on the auth page
      cy.url().should('include', '/auth')

      // Check if the login form is present
      cy.get('#auth-modal').should('be.visible')

      // Use invalid credentials
      const invalidEmail = 'invalid_user@example.com'
      const invalidPassword = 'wrong_password'

      // Fill in invalid credentials
      cy.get('input[type="text"][placeholder="Enter your email"]')
        .filter(':visible')
        .type(invalidEmail)

      cy.get('input[type="password"][placeholder="Enter your password"]')
        .filter(':visible')
        .type(invalidPassword)

      cy.contains('Login').click()

      // Wait for error message to appear
      cy.get('#user-feedback-message-login').should('be.visible')

      // Verify error message content
      cy.get('#user-feedback-message-login')
        .first()
        .should('contain', 'User not found. Please register first.')

      // Verify we're still on the auth page (not redirected)
      cy.url().should('include', '/auth')

      // Verify the login form is still available
      cy.get('#auth-modal').should('be.visible')

      cy.log('Successfully verified unsuccessful login scenario')
    })
  })
