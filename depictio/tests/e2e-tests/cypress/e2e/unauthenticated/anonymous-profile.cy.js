describe('Unauthenticated Mode - Anonymous Profile', () => {

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

  it('should show anonymous user in profile section', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should be able to access profile page
    cy.url().should('include', '/profile')

    // Should show anonymous user email in the Email field
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'anonymous')
      })
    })

    // Should not show regular user profile features
    cy.get('body').should('not.contain', 'Change Password')
    cy.get('body').should('not.contain', 'Account Settings')

    cy.screenshot('anonymous_profile_page')
  })

  it('should display Login as a temporary user button', () => {
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

  it('should not have profile editing capabilities for anonymous user', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should not have typical profile editing features
    cy.get('body').should('not.contain', 'Edit Profile')
    cy.get('body').should('not.contain', 'Update Email')
    cy.get('body').should('not.contain', 'Save Changes')

    // Form inputs for editing should not be present or should be disabled
    cy.get('input[type="email"]').should('not.exist')
    cy.get('input[type="text"]').should('not.exist')

    cy.screenshot('no_profile_editing_anonymous')
  })

  it('should show current session type as anonymous', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Should show anonymous email in the user info
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'anonymous')
      })
    })

    // Should not show test user emails
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('not.contain', '@example.com')
        cy.get('.mantine-Text-root').should('not.contain', 'test_user')
        cy.get('.mantine-Text-root').should('not.contain', 'admin@example.com')
      })
    })

    cy.screenshot('anonymous_session_indicator')
  })
})
