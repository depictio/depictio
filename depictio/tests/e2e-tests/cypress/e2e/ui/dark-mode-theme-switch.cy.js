describe('Dark Mode Theme Switch Functionality', () => {
  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
    
    // Clear localStorage to start with clean state
    cy.clearLocalStorage()
    
    // Login first to access the dashboard
    cy.loginAsTestUser('testUser')
    
    // Wait for login to complete
    cy.wait(3000)
    
    // Force navigation to dashboards if not already there
    cy.visit('/dashboards')
    cy.wait(2000) // Wait for page load and sidebar to appear
  })

  it('should display theme switch in sidebar', () => {
    // Verify theme switch is visible in sidebar
    cy.get('#theme-switch')
      .should('be.visible')
      .should('have.attr', 'data-switch')

    // Verify auto button exists (might be hidden initially)
    cy.get('#auto-theme-button').should('exist')
    
    // Take screenshot of initial state
    cy.screenshot('theme-switch-initial-state')
  })

  it('should toggle between light and dark themes', () => {
    // Start in light mode (default)
    cy.get('body').should('have.class', 'theme-light')
    cy.get('#theme-switch').should('not.be.checked')

    // Click to switch to dark mode using the label
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500) // Wait for theme transition

    // Verify dark mode is applied
    cy.get('body').should('have.class', 'theme-dark')
    cy.get('#theme-switch').should('be.checked')

    // Verify localStorage is updated
    cy.window().then((win) => {
      expect(win.localStorage.getItem('depictio-theme')).to.equal('dark')
      expect(win.localStorage.getItem('depictio-theme-manual-override')).to.equal('true')
    })

    // Take screenshot of dark mode
    cy.screenshot('theme-switch-dark-mode')

    // Switch back to light mode
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Verify light mode is restored
    cy.get('body').should('have.class', 'theme-light')
    cy.get('#theme-switch').should('not.be.checked')
    
    // Take screenshot of light mode restored
    cy.screenshot('theme-switch-light-mode-restored')
  })

  it('should show auto button when manual override is active', () => {
    // Click theme switch to create manual override
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Auto button should become visible after manual override
    cy.get('#auto-theme-button').should('be.visible')
    
    // Take screenshot showing auto button
    cy.screenshot('theme-switch-auto-button-visible')
  })

  it('should reset to automatic theme detection', () => {
    // First create a manual override
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Verify manual override is set
    cy.window().then((win) => {
      expect(win.localStorage.getItem('depictio-theme-manual-override')).to.equal('true')
    })

    // Click auto button to reset
    cy.get('#auto-theme-button').should('be.visible').click()
    cy.wait(500)

    // Verify manual override is removed
    cy.window().then((win) => {
      expect(win.localStorage.getItem('depictio-theme-manual-override')).to.be.null
    })
    
    // Auto button should be hidden again
    cy.get('#auto-theme-button').should('not.be.visible')
  })

  it('should apply theme to page elements', () => {
    // Get initial background color in light mode
    cy.get('body').should('have.class', 'theme-light')
    
    // Switch to dark theme
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Verify dark theme class is applied
    cy.get('body').should('have.class', 'theme-dark')
    
    // Check that CSS variables are updated (verify dark styling is applied)
    cy.get('body').should('have.css', 'background-color').then((darkBg) => {
      // Switch back to light
      cy.get('#theme-switch').click()
      cy.wait(500)
      
      // Verify different background color in light mode
      cy.get('body').should('have.css', 'background-color').then((lightBg) => {
        expect(darkBg).to.not.equal(lightBg)
      })
    })
  })

  it('should persist theme choice across page refreshes', () => {
    // Switch to dark theme
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Verify dark theme is applied
    cy.get('body').should('have.class', 'theme-dark')
    cy.get('#theme-switch').should('be.checked')

    // Refresh page
    cy.reload()
    cy.wait(2000)

    // Verify dark theme persists after reload
    cy.get('body').should('have.class', 'theme-dark')
    cy.get('#theme-switch').should('be.checked')
    
    // Take screenshot of persisted dark mode
    cy.screenshot('theme-switch-persisted-dark-mode')
  })

  it('should update navbar logo based on theme', () => {
    // Check light theme logo
    cy.get('#navbar-logo-content')
      .should('be.visible')
      .should('have.attr', 'src')
      .and('include', 'logo_black.svg')

    // Switch to dark theme
    cy.get('label[for="theme-switch"]').click()
    cy.wait(500)

    // Check dark theme logo
    cy.get('#navbar-logo-content')
      .should('have.attr', 'src')
      .and('include', 'logo_white.svg')
      
    // Take screenshot showing logo change
    cy.screenshot('theme-switch-logo-change-dark')
  })

  it('should work correctly across different pages', () => {
    // Start on dashboards page
    cy.get('body').should('have.class', 'theme-light')
    
    // Switch to dark mode
    cy.get('#theme-switch').click()
    cy.wait(500)
    cy.get('body').should('have.class', 'theme-dark')

    // Navigate to profile page
    cy.visit('/profile')
    cy.wait(1000)

    // Verify dark theme persists on profile page
    cy.get('body').should('have.class', 'theme-dark')
    cy.get('#theme-switch').should('be.checked')

    // Navigate to projects page
    cy.visit('/projects')
    cy.wait(1000)

    // Verify dark theme persists on projects page
    cy.get('body').should('have.class', 'theme-dark')
    cy.get('#theme-switch').should('be.checked')
    
    // Take screenshot of dark mode on projects page
    cy.screenshot('theme-switch-projects-page-dark')
  })

  it('should maintain theme state during navigation', () => {
    // Set to dark mode
    cy.get('#theme-switch').click()
    cy.wait(500)
    
    // Navigate through multiple pages and verify theme consistency
    const pages = ['/profile', '/projects', '/dashboards']
    
    pages.forEach((page, index) => {
      cy.visit(page)
      cy.wait(1000)
      
      // Verify dark theme is maintained
      cy.get('body').should('have.class', 'theme-dark')
      cy.get('#theme-switch').should('be.checked')
      
      // Take screenshot for each page
      cy.screenshot(`theme-consistency-${page.replace('/', '')}-${index}`)
    })
  })

  it('should handle rapid theme switching', () => {
    // Rapidly toggle theme multiple times
    for (let i = 0; i < 5; i++) {
      cy.get('label[for="theme-switch"]').click()
      cy.wait(100) // Short wait between clicks
    }
    
    // Wait for final state to settle
    cy.wait(1000)
    
    // Verify the switch still works correctly
    cy.get('#theme-switch').should('exist')
    
    // Check final state consistency
    cy.get('#theme-switch').then(($switch) => {
      const isChecked = $switch.prop('checked')
      if (isChecked) {
        cy.get('body').should('have.class', 'theme-dark')
      } else {
        cy.get('body').should('have.class', 'theme-light')
      }
    })
  })
})