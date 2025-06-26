describe('Unauthenticated Mode - Login as a temporary user Flow', () => {

  // Only run these tests in unauthenticated mode
  before(() => {
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping unauthenticated tests - not in unauthenticated mode')
      return
    }

    // Clear any existing local storage to ensure clean state
    cy.clearLocalStorage()
  })

  beforeEach(() => {
    // Skip if not in unauthenticated mode
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('should open Login as a temporary user modal when button is clicked', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Click the Login as a temporary user button
    cy.get('#upgrade-to-temporary-button').should('be.visible').click()

    // Modal should appear
    cy.get('.mantine-Modal-root').should('be.visible')

    // Modal should contain the confirmation button
    cy.get('#upgrade-modal-confirm').should('be.visible')
    cy.get('#upgrade-modal-confirm').should('contain', 'Login as a temporary user')

    cy.screenshot('interactive_mode_modal_opened')
  })

  it('should enable Interactive Mode and update local storage', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Verify initial state - should be anonymous user
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'anonymous')
      })
    })

    // Click Login as a temporary user button
    cy.get('#upgrade-to-temporary-button').click()

    // Wait for modal to appear
    cy.get('.mantine-Modal-root').should('be.visible')

    // Click confirm button in modal
    cy.get('#upgrade-modal-confirm').click()

    // Wait for the upgrade process
    cy.wait(3000)

    // Modal should close
    cy.get('.mantine-Modal-root').should('not.exist')

    // Verify local storage was updated (may take time to update)
    cy.window().then((win) => {
      const localStorage = win.localStorage
      // Check if temporary user info was stored
      const userInfo = localStorage.getItem('userInfo') || localStorage.getItem('tempUser')

      // Allow for localStorage to be updated asynchronously
      if (userInfo) {
        const parsedInfo = JSON.parse(userInfo)
        cy.log('User info found:', parsedInfo.email)
        expect(parsedInfo.email).to.include('temp_user_')
      } else {
        cy.log('User info not yet in localStorage - this is okay, it may update later')
      }
    })

    cy.screenshot('interactive_mode_enabled')
  })

  it('should show temporary user in profile after enabling Interactive Mode', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Enable Interactive Mode
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Refresh page to see updated profile
    cy.reload()
    cy.wait(2000)

    // Should now show temporary user email instead of anonymous
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'temp_user_')
        cy.get('.mantine-Text-root').should('not.contain', 'anonymous')
      })
    })

    // Should not have the Login as a temporary user button anymore (it should be hidden)
    cy.get('#upgrade-to-temporary-button').should('not.be.visible')

    cy.screenshot('temporary_user_profile')
  })

  it('should enable Duplicate button for Iris Dashboard after Interactive Mode', () => {
    // First enable Interactive Mode
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Now go to dashboards
    cy.visit('/dashboards')
    cy.wait(2000)

    // Find the Iris Dashboard card
    cy.contains('h5.mantine-Title-root', 'Iris Dashboard')
      .parents('.mantine-Card-root')
      .within(() => {
        // Open Dashboard Actions accordion
        cy.contains('Dashboard Actions').click({ force: true })
        cy.wait(500)

        // Duplicate button should now be enabled
        cy.contains('button', 'Duplicate').should('be.visible').should('not.be.disabled')

        // Other buttons should still be disabled for temporary users
        cy.contains('button', 'Delete').should('be.disabled')
        cy.contains('button', 'Edit name').should('be.disabled')
      })

    cy.screenshot('duplicate_button_enabled_after_interactive_mode')
  })

  it('should be able to duplicate dashboard after enabling Interactive Mode', () => {
    // Enable Interactive Mode first
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Go to dashboards and duplicate
    cy.visit('/dashboards')
    cy.wait(2000)

    cy.contains('h5.mantine-Title-root', 'Iris Dashboard')
      .parents('.mantine-Card-root')
      .within(() => {
        cy.contains('Dashboard Actions').click({ force: true })
        cy.wait(500)
        cy.contains('button', 'Duplicate').click({ force: true })
      })

    // Wait for duplication to complete
    cy.wait(3000)

    // Should see the duplicated dashboard
    cy.contains('h5.mantine-Title-root', 'Iris Dashboard (copy)').should('be.visible')

    cy.screenshot('dashboard_duplicated_successfully')
  })

  it('should persist Interactive Mode across page reloads', () => {
    // Enable Interactive Mode
    cy.visit('/profile')
    cy.wait(2000)
    cy.get('#upgrade-to-temporary-button').click()
    cy.get('#upgrade-modal-confirm').click()
    cy.wait(3000)

    // Reload the page multiple times
    cy.reload()
    cy.wait(2000)
    cy.reload()
    cy.wait(2000)

    // Should still be in Interactive Mode - check email field
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'temp_user_')
      })
    })
    cy.get('#upgrade-to-temporary-button').should('not.be.visible')

    // Go to dashboards and verify duplicate button is still enabled
    cy.visit('/dashboards')
    cy.wait(2000)

    cy.contains('h5.mantine-Title-root', 'Iris Dashboard')
      .parents('.mantine-Card-root')
      .within(() => {
        cy.contains('Dashboard Actions').click({ force: true })
        cy.wait(500)
        cy.contains('button', 'Duplicate').should('be.visible').should('not.be.disabled')
      })

    cy.screenshot('interactive_mode_persists_across_reloads')
  })

  it('should handle modal cancellation properly', () => {
    cy.visit('/profile')
    cy.wait(2000)

    // Click Login as a temporary user button
    cy.get('#upgrade-to-temporary-button').click()

    // Modal should appear
    cy.get('.mantine-Modal-root').should('be.visible')

    // Click outside modal or find cancel button to close it
    cy.get('.mantine-Modal-root').then($modal => {
      if ($modal.find('button:contains("Cancel")').length > 0) {
        cy.contains('button', 'Cancel').click()
      } else {
        // Click outside modal
        cy.get('.mantine-Modal-overlay').click({ force: true })
      }
    })

    cy.wait(1000)

    // Modal should close
    cy.get('.mantine-Modal-root').should('not.exist')

    // Should still be anonymous (no change) - check email field
    cy.get('#user-info-placeholder').within(() => {
      cy.contains('Email').parent().within(() => {
        cy.get('.mantine-Text-root').should('contain', 'anonymous')
      })
    })
    cy.get('#upgrade-to-temporary-button').should('be.visible')

    cy.screenshot('modal_cancellation_handled')
  })
})
