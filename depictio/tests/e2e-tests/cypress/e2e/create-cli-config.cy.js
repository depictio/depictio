describe('Create CLI Config Test', () => {
    let testUser;
    
    before(() => {
      cy.fixture('test-credentials.json').then((credentials) => {
        testUser = credentials.testUser;
      });
    });
    
    it('creates a new CLI configuration', () => {
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
      
      // Click on CLI-Agents button
      cy.contains('button', 'CLI Agents').click()
      
      // Wait for the page to load
      cy.url().should('include', '/cli_configs')
      
      // Click on Add New Configuration button
      cy.contains('button', 'Add New Configuration').click()
      
      // Fill in CLI config fields
      cy.get('[placeholder="Enter a name for your CLI configuration"]')
        .type('Test_CLI')
      
      // Save the configuration
      cy.contains('button', 'Save').click()
      
      // Check if present in the list
      cy.get('#config-created-success').should('be.visible')
      
      // Retrieve content of agent-config-md
      cy.get('#agent-config-md')
        .first()
        .invoke('text')
        .then((text) => {
          cy.log(`Agent Config MD Content: ${text}`)
          expect(text).to.contain('base_url')
        })
    })
  })