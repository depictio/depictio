describe('User Registration Test', () => {

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

    it('tests user registration functionality', () => {
      // Use unique email to avoid conflicts
      const timestamp = Date.now()
      const test_email = `test_user_${timestamp}@example.com`
      const test_password = "SecurePassword123!"

      // Register using the reusable function
      cy.registerUser(test_email, test_password)

      // Wait for the success message
      cy.get('#user-feedback-message-register').should('be.visible')

      // Verify success message content
      cy.get('#user-feedback-message-register')
        .first()
        .should('contain.text', 'Registration successful! Please login.')

      // Click Back to Login button
      cy.contains('button', 'Back to Login').click()

      // Take a screenshot of the success message
      cy.screenshot('registration_success')

      // Verify we're still on the auth page since we need to log in
      cy.url().should('include', '/auth')

      // Log in with the new credentials using reusable function
      cy.loginUser(test_email, test_password, { visitAuth: false })

      // Check if the login was successful
      cy.url().should('include', '/dashboards')

      // Note: You might want to add API call to delete the test user
      // cy.request('DELETE', `/api/v1/users/${test_email}`)
    })
  })
