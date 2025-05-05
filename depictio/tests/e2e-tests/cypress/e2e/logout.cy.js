describe('Logout Test', () => {
    let testUser;
    
    before(() => {
      cy.fixture('test-credentials.json').then((credentials) => {
        testUser = credentials.testUser;
      });
    });
    
    it('logs out of the application', () => {
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
      
      // Click on the logout button
      cy.contains('button', 'Logout').click()
      
      // Wait for the auth modal to reappear
      cy.get('#auth-modal').should('be.visible')
      
      // Verify we're back on the auth page
      cy.url().should('include', '/auth')
    })
  })