describe('Basic Theme Switch Test', () => {
  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('should find and interact with theme switch after login', () => {
    // Login using the reusable function
    cy.loginAsTestUser('testUser')

    // Wait for login to complete
    cy.wait(3000)

    // Force navigation to dashboards if not already there
    cy.visit('/dashboards')
    cy.wait(2000)

    // Try to find theme switch in sidebar
    cy.get('body').then(($body) => {
      if ($body.find('#theme-switch').length > 0) {
        cy.log('Theme switch found!')

        // Verify theme switch is present
        cy.get('#theme-switch').should('exist')

        // Try to click the visible switch component (Mantine Switch uses label)
        cy.get('label[for="theme-switch"]').click()
        cy.wait(1000)

        // Click it back
        cy.get('label[for="theme-switch"]').click()
        cy.wait(1000)

        cy.log('Theme switch interaction successful')
      } else {
        cy.log('Theme switch not found - might not be available on this page')

        // Try visiting dashboard explicitly
        cy.visit('/dashboards')
        cy.wait(2000)

        // Look for theme switch again
        cy.get('#theme-switch').should('exist')
      }
    })
  })
})
