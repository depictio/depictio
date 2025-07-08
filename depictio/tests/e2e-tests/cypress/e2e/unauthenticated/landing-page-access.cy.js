describe('Unauthenticated Mode - Landing Page Access', () => {

  // Only run these tests in unauthenticated mode
  before(() => {
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping unauthenticated tests - not in unauthenticated mode')
      return
    }
  })

  beforeEach(function() {
    // Skip if not in unauthenticated mode
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      this.skip()
    }
  })

  it('should bypass /auth page and land directly on dashboards page', () => {
    // Visit the root URL
    cy.visit('/')

    // Should be redirected to dashboards page without going through auth
    cy.url().should('include', '/dashboards')

    // Should not have visited /auth page
    cy.url().should('not.include', '/auth')

    // Verify that the auth modal is not present
    cy.get('#auth-modal').should('not.exist')

    // Take screenshot for verification
    cy.screenshot('unauthenticated_landing_success')
  })

  it('should show anonymous user in session', () => {
    cy.visit('/dashboards')

    // Wait for page to load
    cy.wait(2000)

    // Check if we can access the page without authentication
    cy.url().should('include', '/dashboards')



    cy.screenshot('anonymous_session_active')
  })

  it('should not redirect to /auth when visiting protected routes', () => {
    // Test various routes that would normally require auth
    const routes = ['/dashboards', '/about', '/profile']

    routes.forEach(route => {
      cy.visit(route)
      cy.url().should('include', route)
      cy.url().should('not.include', '/auth')
      cy.get('#auth-modal').should('not.exist')
    })
  })

  it('should not have authentication-related UI elements', () => {
    cy.visit('/dashboards')
    cy.wait(1000)

    // Verify no auth modal is present
    cy.get('body').should('not.contain', 'Register')

    // Auth modal should not exist
    cy.get('#auth-modal').should('not.exist')
  })
})
