describe('Single-User Mode - UI and Database Verification', () => {

  // Only run these tests in single-user mode
  before(() => {
    if (!Cypress.env('SINGLE_USER_MODE')) {
      cy.log('Skipping single-user mode tests - not in single-user mode')
      return
    }
  })

  beforeEach(function() {
    // Skip if not in single-user mode
    if (!Cypress.env('SINGLE_USER_MODE')) {
      this.skip()
    }
  })

  it('should display Single User Mode badge in sidebar', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should show Single User Mode badge in sidebar
    cy.get('body').should('contain', 'Single User Mode')

    // Verify badge has correct styling (violet color)
    cy.contains('.mantine-Badge-label', 'Single User Mode')
      .closest('.mantine-Badge-root')
      .should('exist')
      .and('have.attr', 'data-variant', 'light')

    cy.screenshot('single_user_mode_badge_visible')
  })

  it('should show Single User Mode badge icon (account)', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Verify the account icon SVG is present in the Single User Mode badge
    cy.contains('.mantine-Badge-label', 'Single User Mode')
      .closest('.mantine-Badge-root')
      .find('.mantine-Badge-section svg')
      .should('exist')
      .and('have.attr', 'width', '16')
      .and('have.attr', 'height', '16')

    // Verify it has the correct path (account icon pattern)
    cy.contains('.mantine-Badge-label', 'Single User Mode')
      .closest('.mantine-Badge-root')
      .find('svg path')
      .should('have.attr', 'fill', 'currentColor')

    cy.screenshot('single_user_mode_badge_icon')
  })

  it('should allow immediate access without login', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should be able to access dashboards directly without login
    cy.url().should('include', '/dashboards')
    cy.url().should('not.include', '/auth')

    // Should not see login prompt or auth modal
    cy.get('body').should('not.contain', 'Sign In')
    cy.get('body').should('not.contain', 'Login as a temporary user')

    cy.screenshot('single_user_mode_no_login_required')
  })

  it('should have admin privileges immediately', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should be able to create dashboards (admin privilege)
    cy.get('[data-testid="new-dashboard-button"]', { timeout: 5000 })
      .should('be.visible')
      .and('not.be.disabled')

    cy.screenshot('single_user_mode_admin_access')
  })

  it('should hide user management UI', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Single-user mode should hide user management features
    // No "Change Password" or multi-user account settings
    cy.get('body').should('not.contain', 'Change Password')

    // Should show simplified profile for single user
    cy.url().should('include', '/profile')

    cy.screenshot('single_user_mode_simplified_profile')
  })

  it('should verify database initialization with admin user', () => {
    // Visit backend health endpoint to trigger DB initialization
    cy.request('/depictio/api/v1/health').then((response) => {
      expect(response.status).to.eq(200)
    })

    // Visit dashboards to ensure DB is accessible
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should load without errors (DB initialized correctly)
    cy.get('body').should('not.contain', 'Database Error')
    cy.get('body').should('not.contain', 'Connection Error')

    // Sidebar should be visible (indicates successful DB connection)
    cy.get('[class*="mantine-AppShell-navbar"]').should('be.visible')

    cy.screenshot('single_user_mode_db_initialized')
  })

  it('should show Single User Mode badge as clickable link to profile', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Badge should be clickable and link to profile
    cy.contains('Single User Mode')
      .parent()
      .should('have.attr', 'href', '/profile')

    // Click badge to navigate to profile
    cy.contains('Single User Mode').click()
    cy.wait(1000)

    cy.url().should('include', '/profile')

    cy.screenshot('single_user_mode_badge_navigation')
  })

  it('should not show demo tour or public mode features', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Should not show Demo Mode badge
    cy.get('body').should('not.contain', 'Demo Mode')

    // Should not show Public Mode badge
    cy.get('body').should('not.contain', 'Public Mode')

    // Should not show tour popovers
    cy.get('[data-tour-step]').should('not.exist')

    cy.screenshot('single_user_mode_no_demo_features')
  })
})
