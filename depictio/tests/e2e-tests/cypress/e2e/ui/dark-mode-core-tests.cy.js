describe('Dark Mode Core Functionality', () => {
  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }

    // Clear localStorage to start with clean state
    cy.clearLocalStorage()

    // Fast token-based login and navigate to dashboard
    cy.loginWithTokenAsTestUser('testUser')
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
    // Check current theme state via MantineProvider's data-mantine-color-scheme
    cy.get('[data-mantine-color-scheme]').then(($element) => {
      const currentScheme = $element.attr('data-mantine-color-scheme')
      const isDarkMode = currentScheme === 'dark'
      cy.log(`Current theme: ${currentScheme}`)

      // Toggle theme
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify theme changed via MantineProvider attribute
      if (isDarkMode) {
        cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', 'light')
        cy.get('#theme-switch').should('not.be.checked')
      } else {
        cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', 'dark')
        cy.get('#theme-switch').should('be.checked')
      }

      // Take screenshot
      cy.screenshot('theme-toggled')

      // Toggle back
      cy.get('label[for="theme-switch"]').click()
      cy.wait(1000)

      // Verify original state restored
      if (isDarkMode) {
        cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', 'dark')
        cy.get('#theme-switch').should('be.checked')
      } else {
        cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', 'light')
        cy.get('#theme-switch').should('not.be.checked')
      }
    })
  })

  // it('should persist theme after page reload', () => {
  //   // Get initial theme state from MantineProvider
  //   cy.get('[data-mantine-color-scheme]').then(($element) => {
  //     const initialTheme = $element.attr('data-mantine-color-scheme') || 'light'

  //     // Toggle to opposite theme
  //     cy.get('label[for="theme-switch"]').click()
  //     cy.wait(1000)

  //     // Verify theme changed
  //     const expectedNewTheme = initialTheme === 'dark' ? 'light' : 'dark'
  //     cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', expectedNewTheme)

  //     // Reload the page
  //     cy.reload()
  //     cy.wait(2000)

  //     // Verify new theme persists
  //     cy.get('[data-mantine-color-scheme]').should('have.attr', 'data-mantine-color-scheme', expectedNewTheme)

  //     if (expectedNewTheme === 'dark') {
  //       cy.get('#theme-switch').should('be.checked')
  //     } else {
  //       cy.get('#theme-switch').should('not.be.checked')
  //     }

  //     // Take screenshot of persisted theme
  //     cy.screenshot('theme-persisted-after-reload')
  //   })
  // })

  it('should update logo based on theme', () => {
    // Get current theme from MantineProvider and verify correct logo
    cy.get('[data-mantine-color-scheme]').then(($element) => {
      const currentScheme = $element.attr('data-mantine-color-scheme') || 'light'
      const isDarkMode = currentScheme === 'dark'
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
