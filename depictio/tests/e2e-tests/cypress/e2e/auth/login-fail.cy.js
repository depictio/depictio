describe('Login fail', () => {

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('should show error message for invalid credentials', () => {
    // Use invalid credentials
    const invalidEmail = 'invalid_user@example.com'
    const invalidPassword = 'wrong_password'

    // Try to login with invalid credentials using reusable function
    cy.loginUser(invalidEmail, invalidPassword)

    // Wait for error message to appear
    cy.get('#user-feedback-message-login').should('be.visible')

    // Verify error message content
    cy.get('#user-feedback-message-login')
      .first()
      .should('contain', 'User not found. Please register first.')

    // Verify we're still on the auth page (not redirected)
    cy.url().should('include', '/auth')

    // Verify the modal is still open
    cy.get('[role="dialog"][aria-modal="true"]').should('be.visible')

    cy.log('Successfully verified unsuccessful login scenario')
  })
})
