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
    // Log in using the reusable function
    cy.loginAsTestUser('testUser')

    // Check if the login was successful
    cy.url().should('include', '/dashboards')

    // Go to profile page
    cy.visit('/profile')

    // Click on the edit password button
    cy.contains('button', 'Edit Password').click()

    // Wait for edit password modal to appear
    cy.get('#edit-password-modal-body').should('be.visible')

    // Fill in current password field
    // From the HTML, the correct id is "old-password" and placeholder is "Old Password"
    cy.get('#old-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(testUser.password, { delay: 50 })
      .should('have.value', testUser.password)

    // Fill in new password field
    // From the HTML, the correct id is "new-password" and placeholder is "New Password"
    cy.get('#new-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(new_password, { delay: 50 })
      .should('have.value', new_password)

    // Fill in confirm new password field
    // From the HTML, the correct id is "confirm-new-password" and placeholder is "Confirm Password"
    cy.get('#confirm-new-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(new_password, { delay: 50 })
      .should('have.value', new_password)

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
        
        // Clear and re-enter the passwords more carefully
        cy.get('#old-password').clear().type(testUser.password, { delay: 100 })
        cy.get('#new-password').clear().type(new_password, { delay: 100 })
        cy.get('#confirm-new-password').clear().type(new_password, { delay: 100 })
        
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
    cy.contains('button', 'Edit Password').click()
    cy.get('#edit-password-modal-body').should('be.visible')
    cy.get('#old-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(new_password, { delay: 50 })
      .should('have.value', new_password)
    cy.get('#new-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(testUser.password, { delay: 50 })
      .should('have.value', testUser.password)
    cy.get('#confirm-new-password')
      .should('be.visible')
      .focus()
      .clear()
      .type(testUser.password, { delay: 50 })
      .should('have.value', testUser.password)
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
