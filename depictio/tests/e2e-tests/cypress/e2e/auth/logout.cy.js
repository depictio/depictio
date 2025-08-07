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
      // Try test user first, fall back to admin user if needed
      cy.log('🎯 Starting logout test with user verification')

      // The enhanced loginWithTokenAsTestUser will handle user existence automatically
      cy.loginWithTokenAsTestUser('testUser')

      // Navigate to dashboards
      cy.visit('/dashboards')
      cy.wait(2000)

      // Check if the login was successful
      cy.url().should('include', '/dashboards')
      cy.log('✅ Successfully logged in and reached dashboards page')

      // Go to profile page
      cy.visit('/profile')
      cy.wait(1000)

      // Click on the logout button
      cy.contains('button', 'Logout').click()
      cy.log('🚪 Logout button clicked')

      // Wait for the auth modal to reappear
      cy.get('[role="dialog"][aria-modal="true"]').should('be.visible')
      cy.log('✅ Auth modal appeared after logout')

      // Verify we're back on the auth page
      cy.url().should('include', '/auth')
      cy.log('✅ Successfully redirected to auth page')
    })
  })
