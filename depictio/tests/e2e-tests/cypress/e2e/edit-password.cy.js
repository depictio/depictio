describe('Edit Password Test', () => {
    let testUser;
    
    before(() => {
      cy.fixture('test-credentials.json').then((credentials) => {
        testUser = credentials.testUser;
      });
    });
    
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
      
      // Fill in new password fields
      const new_password = "NewSecurePassword123!"
      const confirm_new_password = "NewSecurePassword123!"
      
      // Fill in current password field
      cy.get('[role="textbox"][name="Old password"]')
        .type(testUser.password)
      
      // Fill in new password field
      cy.get('[role="textbox"][name="New password"]')
        .type(new_password)
      
      // Fill in confirm new password field
      cy.get('[role="textbox"][name="Confirm Password"]')
        .type(confirm_new_password)
      
      // Wait for the save button to be enabled
      cy.get('#save-password').should('not.be.disabled')
      
      // Click the save button
      cy.contains('button', 'Save').click()
      
      // Wait for the success message
      cy.get('#message-password').should('be.visible')
      
      // Verify success message
      cy.get('#message-password')
        .first()
        .should('contain.text', 'password updated successfully')
      
      // Close the modal using the Escape key
      cy.get('body').type('{esc}')
      
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
    })
  })