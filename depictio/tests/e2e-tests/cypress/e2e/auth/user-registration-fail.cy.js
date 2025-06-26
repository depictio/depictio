describe('Unsuccessful Registration - Already Registered', () => {
    let testUser;

    before(() => {
      // Skip this test suite if in unauthenticated mode
      if (Cypress.env('UNAUTHENTICATED_MODE')) {
        cy.log('Skipping registration fail test - running in unauthenticated mode')
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

    it('tests unsuccessful registration with already registered email', () => {
      // Navigate to the auth page
      cy.visit('/auth')

      // Check if we're on the auth page
      cy.url().should('include', '/auth')

      // Check if the auth modal is present
      cy.get('#auth-modal').should('be.visible')

      // Click on the Switch to Register button
      cy.contains('button', 'Register').click()

      // Use a known registered email (from initial_users.yaml)
      cy.get('input[type="text"][placeholder="Enter your email"]')
        .filter(':visible')
        .type(testUser.email)

      cy.get('input[type="password"][placeholder="Enter your password"]')
        .filter(':visible')
        .type("SecurePassword123!")

      cy.get('input[type="password"][placeholder="Confirm your password"]')
        .filter(':visible')
        .type("SecurePassword123!")

    //   // Wait for the register button to be enabled
    //   cy.get('#register-button').should('not.be.disabled')

      // Click the register button
      cy.contains('button', 'Register').click()

      // Wait for the error message
      cy.get('#user-feedback-message-register').should('be.visible')

      // Verify error message about existing user
      cy.get('#user-feedback-message-register')
        .first()
        .should('contain.text', 'already registered')

      // Take a screenshot
      cy.screenshot('registration_duplicate_error')
    })
  })
