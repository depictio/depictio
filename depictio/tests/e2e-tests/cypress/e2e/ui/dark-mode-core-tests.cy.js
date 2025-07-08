describe('Dark Mode Core Functionality', () => {
  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }

    // Clear localStorage to start with clean state
    cy.clearLocalStorage()

    // Login and navigate to dashboard
    cy.loginAsTestUser('testUser')
    cy.wait(3000)
    cy.visit('/dashboards')
    cy.wait(2000)
  })

  it('should display and interact with theme switch', () => {
    // Verify theme switch exists
    cy.get('#theme-switch').should('exist')
    cy.get('label[for="theme-switch"]').should('be.visible')

    // Take screenshot of theme switch
    cy.screenshot('theme-switch-visible')
  })

  it('should toggle between light and dark modes', () => {
    // Check current theme state
    cy.get('body').then(($body) => {
      const isDarkMode = $body.hasClass('theme-dark')
      cy.log(`Current theme: ${isDarkMode ? 'dark' : 'light'}`)

      // Toggle theme
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify theme changed
      if (isDarkMode) {
        cy.get('body').should('have.class', 'theme-light')
        cy.get('#theme-switch').should('not.be.checked')
      } else {
        cy.get('body').should('have.class', 'theme-dark')
        cy.get('#theme-switch').should('be.checked')
      }

      // Take screenshot
      cy.screenshot('theme-toggled')

      // Toggle back
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify original state restored
      if (isDarkMode) {
        cy.get('body').should('have.class', 'theme-dark')
        cy.get('#theme-switch').should('be.checked')
      } else {
        cy.get('body').should('have.class', 'theme-light')
        cy.get('#theme-switch').should('not.be.checked')
      }
    })
  })

  it('should persist theme after page reload', () => {
    // Get initial theme state
    cy.get('body').then(($body) => {
      const initialTheme = $body.hasClass('theme-dark') ? 'dark' : 'light'

      // Toggle to opposite theme
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify theme changed
      const expectedNewTheme = initialTheme === 'dark' ? 'light' : 'dark'
      cy.get('body').should('have.class', `theme-${expectedNewTheme}`)

      // Reload the page
      cy.reload()
      cy.wait(2000)

      // Verify new theme persists
      cy.get('body').should('have.class', `theme-${expectedNewTheme}`)

      if (expectedNewTheme === 'dark') {
        cy.get('#theme-switch').should('be.checked')
      } else {
        cy.get('#theme-switch').should('not.be.checked')
      }

      // Take screenshot of persisted theme
      cy.screenshot('theme-persisted-after-reload')
    })
  })

  it('should update logo based on theme', () => {
    // Get current theme and verify correct logo
    cy.get('body').then(($body) => {
      const isDarkMode = $body.hasClass('theme-dark')
      const expectedLogo = isDarkMode ? 'logo_white.svg' : 'logo_black.svg'

      // Verify current logo matches theme
      cy.get('#navbar-logo-content')
        .should('have.attr', 'src')
        .and('include', expectedLogo)

      // Switch theme
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify logo changed
      const newExpectedLogo = isDarkMode ? 'logo_black.svg' : 'logo_white.svg'
      cy.get('#navbar-logo-content')
        .should('have.attr', 'src')
        .and('include', newExpectedLogo)
    })
  })

})
