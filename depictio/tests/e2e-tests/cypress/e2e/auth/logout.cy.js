describe('Logout Test', () => {
    let testUser;

    before(() => {
      // Skip this test suite if in unauthenticated mode
      if (Cypress.env('UNAUTHENTICATED_MODE')) {
        cy.log('Skipping logout test - running in unauthenticated mode')
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

    it('logs out of the application', () => {
      // Fast token-based login for test setup
      cy.loginWithTokenAsTestUser('testUser')

      // Navigate to dashboards
      cy.visit('/dashboards')
      cy.wait(2000)

      // Check if the login was successful
      cy.url().should('include', '/dashboards')

      // Go to profile page
      cy.visit('/profile')

      // Click on the logout button
      cy.contains('button', 'Logout').click()

      // Wait for the auth modal to reappear
      cy.get('[role="dialog"][aria-modal="true"]').should('be.visible')

      // Verify we're back on the auth page
      cy.url().should('include', '/auth')
    })
  })
