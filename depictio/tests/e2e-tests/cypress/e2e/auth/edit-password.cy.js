describe('Edit Password Test', () => {
  let testUser;
  const new_password = 'NewPassword123!'; // New password for the test

  before(() => {
    // Skip this test suite if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping edit password test - running in unauthenticated mode')
      return
    }

    cy.fixture('test-credentials.json').then((credentials) => {
      testUser = credentials.testUser;
    });
  });

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('edits the password of the user', () => {
    // Fast token-based login for test setup
    cy.loginWithTokenAsTestUser('testUser')

    // Navigate to dashboards
    cy.visit('/dashboards')
    cy.wait(2000)

    // Go to profile page
    cy.visit('/profile')
    cy.wait(2000)

    // Click on the edit password button
    cy.contains('button', 'Edit Password').click()

    // Wait for edit password modal to appear
    cy.get('#edit-password-modal-body').should('be.visible')

    // Fill in password fields using robust typing commands
    cy.typePassword('#old-password', testUser.password)
    cy.typePassword('#new-password', new_password)
    cy.typePassword('#confirm-new-password', new_password)

    // Wait a bit for form validation to complete
    cy.wait(1000)

    // Wait for the save button to be enabled
    cy.get('#save-password').should('be.enabled')

    // Click the save button
    cy.get('#save-password').click()

    // Wait for the response
    cy.wait(2000)

    // Check for any error messages first
    cy.get('body').then(($body) => {
      if ($body.find('#message-password:contains("passwords do not match")').length > 0) {
        cy.log('Password mismatch detected - retrying with fresh inputs')

        // Clear and re-enter the passwords using robust commands
        cy.typePassword('#old-password', testUser.password)
        cy.typePassword('#new-password', new_password)
        cy.typePassword('#confirm-new-password', new_password)

        cy.wait(1000)
        cy.get('#save-password').click()
        cy.wait(2000)
      }
    })

    // Wait for either success or error message
    cy.get('#message-password').should('be.visible')

    // Verify success message text (case-insensitive)
    cy.get('#message-password')
      .invoke('text')
      .then((text) => {
        const lowerText = text.toLowerCase();
        if (lowerText.includes('passwords do not match')) {
          cy.log('Passwords still not matching - might be a timing issue')
          throw new Error('Password validation failed: ' + text)
        }
        expect(lowerText).to.include('password updated successfully');
      });

    // Close the modal by clicking the X button (or using ESC)
    cy.get('body').type('{esc}')
    // Alternatively, if ESC doesn't work:
    // cy.get('.mantine-Modal-close').click()

    // Log out
    cy.contains('button', 'Logout').click()

    // Wait for the auth modal to reappear
    cy.get('[role="dialog"][aria-modal="true"]').should('be.visible')

    // Verify we're back on the auth page
    cy.url().should('include', '/auth')

    // Log in with the new credentials using reusable function
    cy.loginUser(testUser.email, new_password, { visitAuth: false })

    // Check if the login was successful
    cy.url().should('include', '/dashboards')

    // Edit the password back to the original for cleanup
    cy.visit('/profile')
    cy.wait(2000)
    cy.contains('button', 'Edit Password').click()
    cy.get('#edit-password-modal-body').should('be.visible')

    // Use robust typing commands for cleanup
    cy.typePassword('#old-password', new_password)  // Current password is now the new one
    cy.typePassword('#new-password', testUser.password)  // Restore to original
    cy.typePassword('#confirm-new-password', testUser.password)  // Confirm original
    cy.get('#save-password').should('be.enabled')
    cy.get('#save-password').click()
    cy.get('#message-password')
      .should('be.visible')
      .should('not.have.css', 'display', 'none')
    cy.get('#message-password')
      .invoke('text')
      .then((text) => {
        const lowerText = text.toLowerCase();
        expect(lowerText).to.include('password updated successfully');
      });
    cy.get('body').type('{esc}')
    cy.contains('button', 'Logout').click()
  })
})
