describe('Example.com - Parallel Test 2', () => {
  it('visits example.com', () => {
    cy.visit('https://example.com')
    cy.contains('Example Domain')
    cy.get('h1').should('contain', 'Example Domain')
  })
})
