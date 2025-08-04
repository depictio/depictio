describe('Login Success', () => {
  let testUser;
  console.log('Running login success test');

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('debug login', () => {
    cy.visit('/')
  })
});
