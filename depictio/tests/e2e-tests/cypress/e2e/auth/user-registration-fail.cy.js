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
      // Use a known registered email (from initial_users.yaml) with reusable function
      cy.registerUser(testUser.email, "SecurePassword123!")

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
