describe('Cypress Example - Parallel Test 1', () => {
  it('visits cypress example page', () => {
    cy.visit('https://example.cypress.io')
    cy.contains('Kitchen Sink')
    cy.get('h1').should('contain', 'Kitchen Sink')
  })
})
