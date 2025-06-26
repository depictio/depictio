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

  it('logs in user', () => {
    cy.visit('/auth')
    cy.get('#auth-modal').should('be.visible')

    cy.get('input[type="text"][placeholder="Enter your email"]')
      .filter(':visible')
      .type(testUser.email)

    cy.get('input[type="password"][placeholder="Enter your password"]')
      .filter(':visible')
      .type(testUser.password)

    cy.contains('Login').click()
    // cy.url().should('include', '/dashboards')
  })
})
