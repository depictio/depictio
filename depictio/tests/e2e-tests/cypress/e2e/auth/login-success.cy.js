describe('Login Success', () => {
  let testUser;
  console.log('Running login success test');

  before(() => {
    // Skip this test suite if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping login test - running in unauthenticated mode')
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

  it('logs in user using reusable function', () => {
    // Use the new reusable login function
    cy.loginUser(testUser.email, testUser.password)
    
    // Optional: verify successful login by checking URL or page content
    // cy.url().should('include', '/dashboards')
  })
  
  it('logs in user using quick test user function', () => {
    // Even simpler - use the test user function
    cy.loginAsTestUser('testUser')
    
    // Optional: verify successful login
    // cy.url().should('include', '/dashboards')
  })
})
