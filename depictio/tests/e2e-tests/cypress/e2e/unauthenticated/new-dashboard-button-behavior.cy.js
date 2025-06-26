describe('Unauthenticated Mode - New Dashboard Button Behavior', () => {

  beforeEach(() => {
    // Skip if not in unauthenticated mode
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }

    // Clear any existing state
    cy.clearLocalStorage()
  })

  it('should show enabled Login to Create Dashboards button for anonymous users', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Check header button is enabled and has blue styling
    cy.contains('button', 'Login to Create Dashboards').should('be.visible').should('not.be.disabled')

    cy.screenshot('dashboard_button_enabled_anonymous')
  })

  it('should enable New Dashboard button after enabling Interactive Mode', () => {
    // Start as anonymous user
    cy.visit('/dashboards')
    cy.wait(2000)

    // Verify button is initially "Login to Create Dashboards"
    cy.contains('button', 'Login to Create Dashboards').should('be.visible').should('not.be.disabled')

    // Enable Interactive Mode
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Go back to dashboards
    cy.visit('/dashboards')
    cy.wait(2000)

    // Now the button should be enabled and show "New Dashboard"
    cy.get('button').contains('+ New Dashboard').should('be.visible').should('not.be.disabled')

    // Should not have the disabled version anymore
    cy.get('button').should('not.contain.text', 'Login to Create Dashboards')

    cy.screenshot('dashboard_button_enabled_after_interactive')
  })

  it('should open dashboard creation modal after enabling Interactive Mode', () => {
    // Enable Interactive Mode first
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Go to dashboards and try to create a dashboard
    cy.visit('/dashboards')
    cy.wait(2000)

    // Click the enabled New Dashboard button
    cy.get('button').contains('+ New Dashboard').click()

    // Dashboard creation modal should open
    cy.get('#dashboard-modal').should('be.visible')

    // Should have title input
    cy.get('#dashboard-title-input').should('be.visible')

    // Should have project selector
    cy.get('#dashboard-projects').should('be.visible')

    cy.screenshot('dashboard_creation_modal_opened')
  })

  it('should redirect to profile when anonymous user clicks Login to Create Dashboards', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Get current URL for comparison
    cy.url().then((dashboardsUrl) => {
      // Click the Login to Create Dashboards button
      cy.contains('button', 'Login to Create Dashboards').click()

      // Should redirect to profile page
      cy.url().should('include', '/profile')
      cy.url().should('not.equal', dashboardsUrl)

      // Wait for profile page to load
      cy.get('#page-content', { timeout: 10000 }).should('be.visible')

      // Verify we're on the profile page
      cy.get('body').should('contain', 'User Profile')
      cy.get('body').should('contain', 'Login as a temporary user')
    })

    cy.screenshot('anonymous_redirected_to_profile')
  })
})
