describe('User Registration Test', () => {
    it('tests user registration functionality', () => {
      // Navigate to the auth page
      cy.visit('/auth')

      // Check if we're on the auth page
      cy.url().should('include', '/auth')

      // Check if the auth modal is present
      cy.get('#auth-modal').should('be.visible')

      // Click on the Switch to Register button
      cy.contains('button', 'Register').click()

      const test_email = "test_user_playwright@example.com"
      const test_password = "SecurePassword123!"

      // Fill in registration details
      cy.get('input[type="text"][placeholder="Enter your email"]')
        .filter(':visible')
        .type(test_email)

      cy.get('input[type="password"][placeholder="Enter your password"]')
        .filter(':visible')
        .type(test_password)

      cy.get('input[type="password"][placeholder="Confirm your password"]')
        .filter(':visible')
        .type(test_password)

      // Click the register button
      cy.contains('button', 'Register').click()

      // Wait for the success message
      cy.get('#user-feedback-message-register').should('be.visible')

      // Verify success message content
      cy.get('#user-feedback-message-register')
        .first()
        .should('contain.text', 'Registration successful! Please login.')

      // Click Back to Login button
      cy.contains('button', 'Back to Login').click()

      // Take a screenshot of the success message
      cy.screenshot('registration_success')

      // Verify we're still on the auth page since we need to log in
      cy.url().should('include', '/auth')

      // Log in with the new credentials
      cy.get('input[type="text"][placeholder="Enter your email"]')
        .filter(':visible')
        .type(test_email)

      cy.get('input[type="password"][placeholder="Enter your password"]')
        .filter(':visible')
        .type(test_password)

      cy.contains('button', 'Login').click()

      // Check if the login was successful
      cy.url().should('include', '/dashboards')

      // Note: You might want to add API call to delete the test user
      // cy.request('DELETE', `/api/v1/users/${test_email}`)
    })
  })
