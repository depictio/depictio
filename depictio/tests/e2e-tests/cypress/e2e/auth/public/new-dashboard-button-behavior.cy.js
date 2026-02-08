describe('Unauthenticated Mode - New Dashboard Button Behavior', () => {

  beforeEach(function() {
    // Skip if not in unauthenticated mode
    if (!Cypress.env('PUBLIC_MODE')) {
      this.skip()
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

  it.skip('should enable New Dashboard button after enabling Interactive Mode', () => {
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
    cy.wait(5000) // Wait longer for upgrade to complete

    // Go back to dashboards with retries
    cy.visit('/dashboards')
    cy.wait(3000)

    // Sometimes need to reload to get updated button state
    cy.reload()
    cy.wait(3000)

    // Now the button should be enabled and show "New Dashboard" (with retry logic)
    cy.get('body').then($body => {
      if ($body.find('button:contains("+ New Dashboard")').length === 0) {
        // If not found, reload and try again
        cy.reload()
        cy.wait(3000)
      }
    })

    cy.contains('button', '+ New Dashboard').should('be.visible').should('not.be.disabled')

    // Should not have the "Login to Create Dashboards" version anymore
    cy.get('button').should('not.contain.text', 'Login to Create Dashboards')

    cy.screenshot('dashboard_button_enabled_after_interactive')
  })

  it.skip('should open dashboard creation modal after enabling Interactive Mode', () => {
    // Enable Interactive Mode first
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(5000) // Wait longer for upgrade to complete

    // Go to dashboards and try to create a dashboard
    cy.visit('/dashboards')
    cy.wait(3000)

    // Sometimes need to reload to get updated button state
    cy.reload()
    cy.wait(3000)

    // Click the enabled New Dashboard button (with retry logic)
    cy.get('body').then($body => {
      if ($body.find('button:contains("+ New Dashboard")').length === 0) {
        // If not found, reload and try again
        cy.reload()
        cy.wait(3000)
      }
    })

    cy.contains('button', '+ New Dashboard').click()

    // Wait for modal to load
    cy.wait(1000)

    // Dashboard creation modal should open - check for form elements instead of modal container
    cy.get('input[placeholder="Enter dashboard title"]').should('be.visible')

    // Should have project selector
    cy.get('#dashboard-projects').should('be.visible')

    cy.screenshot('dashboard_creation_modal_opened')
  })

  it('should redirect to auth when anonymous user clicks Login to Create Dashboards', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Get current URL for comparison
    cy.url().then((dashboardsUrl) => {
      // Click the Login to Create Dashboards button
      cy.contains('button', 'Login to Create Dashboards').click()

      // Should redirect to auth page with sign-in options
      cy.url().should('include', '/auth')
      cy.url().should('not.equal', dashboardsUrl)

      // Wait for auth modal to appear
      cy.get('[role="dialog"][aria-modal="true"]', { timeout: 10000 }).should('be.visible')

      // Verify auth modal shows public mode sign-in options
      cy.get('body').should('contain', 'Welcome to Depictio')
    })

    cy.screenshot('anonymous_redirected_to_auth')
  })
})
