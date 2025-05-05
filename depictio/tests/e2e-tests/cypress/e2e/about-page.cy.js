describe('About Page Test', () => {
    let testUser;
    
    before(() => {
      cy.fixture('test-credentials.json').then((credentials) => {
        testUser = credentials.testUser;
      });
    });
    
    it('tests the About page for errors', () => {
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
      
      // Go to about page
      cy.visit('/about')
      
      // Check if dash debug error is visible
      cy.get('.dash-debug-error-count').should('not.be.visible')
      
      // Take a screenshot of the success
      cy.screenshot('about_page_success')
    })
  })