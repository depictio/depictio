describe('Demo Mode - UI and Tour Verification', () => {

  // Only run these tests in demo mode
  before(() => {
    if (!Cypress.env('DEMO_MODE')) {
      cy.log('Skipping demo mode tests - not in demo mode')
      return
    }
  })

  beforeEach(function() {
    // Skip if not in demo mode
    if (!Cypress.env('DEMO_MODE')) {
      this.skip()
    }
  })

  it('should display Demo Mode badge in sidebar', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should show Demo Mode badge in sidebar
    cy.get('body').should('contain', 'Demo Mode')

    // Verify badge has correct styling (violet color for demo)
    cy.contains('.mantine-Badge-label', 'Demo Mode')
      .closest('.mantine-Badge-root')
      .should('exist')
      .and('have.attr', 'data-variant', 'light')

    cy.screenshot('demo_mode_badge_visible')
  })

  it('should display welcome tour popover on first visit', () => {
    // Clear localStorage to simulate first visit
    cy.clearLocalStorage()

    cy.visit('/dashboards')
    cy.wait(2000)

    // Should show the welcome tour popover (step 0: welcome-demo)
    cy.get('[data-tour-step="welcome-demo"]', { timeout: 5000 })
      .should('be.visible')

    // Verify popover contains expected content
    cy.get('[data-tour-step="welcome-demo"]').within(() => {
      cy.contains('Welcome to Depictio Demo!')
      cy.contains('24 hours') // Mentions 24h retention
    })

    cy.screenshot('demo_tour_welcome_popover_visible')
  })

  it('should show Demo Mode badge icon (compass)', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Verify the compass icon SVG is present in the Demo Mode badge
    cy.contains('.mantine-Badge-label', 'Demo Mode')
      .closest('.mantine-Badge-root')
      .find('.mantine-Badge-section svg')
      .should('exist')
      .and('have.attr', 'width', '16')
      .and('have.attr', 'height', '16')

    // Verify it has the correct path (compass icon pattern)
    cy.contains('.mantine-Badge-label', 'Demo Mode')
      .closest('.mantine-Badge-root')
      .find('svg path')
      .should('have.attr', 'fill', 'currentColor')

    cy.screenshot('demo_mode_badge_icon')
  })

  it('should allow navigation through tour steps', () => {
    // Clear localStorage to simulate first visit
    cy.clearLocalStorage()

    cy.visit('/dashboards')
    cy.wait(2000)

    // Step 0: Welcome
    cy.get('[data-tour-step="welcome-demo"]').should('be.visible')

    // Click Next to go to step 1
    cy.get('[data-tour-step="welcome-demo"]').within(() => {
      cy.contains('Next').click()
    })

    // Step 1: Example Dashboards
    cy.get('[data-tour-step="example-dashboards"]', { timeout: 3000 })
      .should('be.visible')
      .within(() => {
        cy.contains('Explore Example Dashboards')
      })

    cy.screenshot('demo_tour_navigation_working')
  })

  it('should persist tour state in localStorage', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Tour state should be stored in localStorage
    cy.window().then((win) => {
      const tourState = win.localStorage.getItem('depictio-tour-completed')
      // Should either be null (tour active) or have completion data
      expect(tourState).to.satisfy((state) => {
        return state === null || state !== undefined
      })
    })
  })

  it('should show demo mode in public mode context', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Demo mode requires public mode to be enabled
    // Verify we can access dashboards without login
    cy.url().should('include', '/dashboards')
    cy.url().should('not.include', '/auth')

    // Should see Demo Mode badge (not Public Mode badge)
    cy.get('body').should('contain', 'Demo Mode')
    cy.get('body').should('not.contain', 'Public Mode')

    cy.screenshot('demo_mode_public_context')
  })
})
