describe('Login Success', () => {
  let testUser;

  before(() => {
    cy.fixture('test-credentials.json').then((credentials) => {
      testUser = credentials.testUser;
    });
  });

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
