describe('Public Mode - Temporary User Profile', () => {

  // Only run these tests in public mode
  before(() => {
    if (!Cypress.env('PUBLIC_MODE')) {
      cy.log('Skipping public mode tests - not in public mode')
      return
    }
  })

  beforeEach(function() {
    // Skip if not in public mode
    if (!Cypress.env('PUBLIC_MODE')) {
      this.skip()
    }
  })

  it('should show temporary user in profile section', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should be able to access profile page
    cy.url().should('include', '/profile')

    // Should show temporary user email (temp_user_*@depictio.temp pattern)
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').invoke('text').should('match', /temp_user_.*@depictio\.temp/)
      })
    })

    // Should not show regular user profile features
    cy.get('body').should('not.contain', 'Change Password')
    cy.get('body').should('not.contain', 'Account Settings')

    cy.screenshot('temporary_user_profile_page')
  })

  it.skip('should display Login as a temporary user button', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should have the upgrade to temporary user button
    cy.get('#upgrade-to-temporary-button').should('be.visible')
    cy.get('#upgrade-to-temporary-button').should('contain', 'Login as a temporary user')

    cy.screenshot('enable_interactive_mode_button_visible')
  })

  // it('should show anonymous user limitations', () => {
  //   cy.visit('/profile')
  //   cy.wait(2000)

  //   // cy.get('body').should('contain', 'Anonymous')

  //   // Should explain what
  //   cy.get('body').should('contain', 'Interactive Mode')

  //   cy.screenshot('anonymous_user_limitations')
  // })

  it('should not have profile editing capabilities for temporary user', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should not have typical profile editing features
    cy.get('body').should('not.contain', 'Edit Profile')
    cy.get('body').should('not.contain', 'Update Email')
    cy.get('body').should('not.contain', 'Save Changes')

    // Form inputs for editing should not be present or should be disabled
    cy.get('input[type="email"]').should('not.exist')
    cy.get('input[type="text"]').should('not.exist')

    cy.screenshot('no_profile_editing_temporary_user')
  })

  it('should show temporary user email from depictio.temp domain', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should show temporary user email with @depictio.temp domain
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').invoke('text').should('match', /temp_user_.*@depictio\.temp/)
      })
    })

    // Should not show regular test user emails
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('not.contain', '@example.com')
        cy.get('.mantine-Text-root').should('not.contain', 'test_user')
        cy.get('.mantine-Text-root').should('not.contain', 'admin@example.com')
      })
    })

    cy.screenshot('temporary_user_email_indicator')
  })
})
