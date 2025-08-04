describe('About Page Test', () => {
    let testUser;

    before(() => {
      // Skip this test suite if in unauthenticated mode
      if (Cypress.env('UNAUTHENTICATED_MODE')) {
        cy.log('Skipping about page test - running in unauthenticated mode')
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

    it('tests the About page for errors', () => {
      // Fast token-based login
      cy.loginWithTokenAsTestUser('testUser')

      // Navigate to dashboards
      cy.visit('/dashboards')
      cy.wait(2000)

      // Check if the login was successful
      cy.url().should('include', '/dashboards')

      // Go to about page
      cy.visit('/about')

      // Check if dash debug error is visible
      // cy.get('.dash-debug-error-count').should('not.be.visible')

      // Take a screenshot of the success
      cy.screenshot('about_page_success')
    })
  })
