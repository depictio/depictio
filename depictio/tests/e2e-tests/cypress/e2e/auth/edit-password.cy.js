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
    // Navigate to the auth page
    cy.visit('/auth')

    // Check if we're on the auth page
    cy.url().should('include', '/auth')

    // Check if the login form is present
    cy.get('#auth-modal').should('be.visible')

    // Log in with valid credentials
    cy.get('input[type="text"][placeholder="Enter your email"]')
      .filter(':visible')
      .type(testUser.email)

    cy.get('input[type="password"][placeholder="Enter your password"]')
      .filter(':visible')
      .type(testUser.password)

    cy.contains('button', 'Login').click()

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
      .type(testUser.password)

    // Fill in new password field
    // From the HTML, the correct id is "new-password" and placeholder is "New Password"
    cy.get('#new-password')
      .should('be.visible')
      .type(new_password)

    // Fill in confirm new password field
    // From the HTML, the correct id is "confirm-new-password" and placeholder is "Confirm Password"
    cy.get('#confirm-new-password')
      .should('be.visible')
      .type(new_password)

    // Wait for the save button to be enabled
    cy.get('#save-password').should('be.enabled')

    // Click the save button
    cy.get('#save-password').click()

    // Wait for the success message
    cy.get('#message-password')
      .should('be.visible')
      .should('not.have.css', 'display', 'none')

    // Verify success message text (case-insensitive)
    cy.get('#message-password')
      .invoke('text')
      .then((text) => {
        const lowerText = text.toLowerCase();
        expect(lowerText).to.include('password updated successfully');
      });

    // Close the modal by clicking the X button (or using ESC)
    cy.get('body').type('{esc}')
    // Alternatively, if ESC doesn't work:
    // cy.get('.mantine-Modal-close').click()

    // Log out
    cy.contains('button', 'Logout').click()

    // Wait for the auth modal to reappear
    cy.get('#auth-modal').should('be.visible')

    // Verify we're back on the auth page
    cy.url().should('include', '/auth')

    // Log in with the new credentials
    cy.get('input[type="text"][placeholder="Enter your email"]')
      .filter(':visible')
      .type(testUser.email)

    cy.get('input[type="password"][placeholder="Enter your password"]')
      .filter(':visible')
      .type(new_password)

    cy.contains('button', 'Login').click()

    // Check if the login was successful
    cy.url().should('include', '/dashboards')

    // Edit the password back to the original for cleanup
    cy.visit('/profile')
    cy.contains('button', 'Edit Password').click()
    cy.get('#old-password')
      .should('be.visible')
      .type(new_password)
    cy.get('#new-password')
      .should('be.visible')
      .type(testUser.password)
    cy.get('#confirm-new-password')
      .should('be.visible')
      .type(testUser.password)
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
