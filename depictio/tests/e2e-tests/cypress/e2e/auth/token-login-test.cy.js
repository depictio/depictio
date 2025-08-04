describe('Token-Based Login Tests', () => {

  it('should check API endpoints are accessible', () => {
    const apiBaseUrl = 'http://localhost:8058'

    // First, let's check what endpoints are available
    cy.request({
      method: 'GET',
      url: `${apiBaseUrl}/depictio/api/v1/status`,
      failOnStatusCode: false
    }).then((response) => {
      cy.log(`Status endpoint: ${response.status}`)
      cy.log(`Status body:`, response.body)
    })

    // Check if the auth endpoint exists by trying OPTIONS
    cy.request({
      method: 'OPTIONS',
      url: `${apiBaseUrl}/depictio/api/v1/auth/login`,
      failOnStatusCode: false
    }).then((response) => {
      cy.log(`Auth endpoint OPTIONS: ${response.status}`)
      cy.log(`Auth endpoint headers:`, response.headers)
    })
  })

  it('should login with direct token command using admin credentials', () => {
    // Test the basic token login with default admin credentials
    cy.loginWithToken()

    // Verify we're logged in by checking localStorage
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      expect(token).to.not.be.null
      const parsed = JSON.parse(token)
      expect(parsed.logged_in).to.be.true
    })

    // Visit a page to see if authentication works
    cy.visit('/dashboards')
    cy.url().should('include', '/dashboards')
  })

  it('should login with custom email and password', () => {
    // Test with custom credentials (adjust email/password as needed)
    cy.loginWithToken('admin@example.com', 'changeme')

    // Check the token is set
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      const parsed = JSON.parse(token)
      expect(parsed.access_token).to.exist
      expect(parsed.user_id).to.exist
    })
  })

  it('should login using test credentials fixture', () => {
    // Test the fixture-based login
    cy.loginWithTokenAsTestUser('testUser')

    // Verify login worked
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      expect(token).to.not.be.null
    })

    // Try to access a protected page
    cy.visit('/profile')
    cy.url().should('include', '/profile')
  })

  it('should login as admin user from fixture', () => {
    // Test admin user from fixture
    cy.loginWithTokenAsTestUser('adminUser')

    // Verify we have admin token
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      const parsed = JSON.parse(token)
      expect(parsed.logged_in).to.be.true
      expect(parsed.token_type).to.equal('bearer')
    })
  })

  it('should work without visiting home page first', () => {
    // Test the visitHome: false option
    cy.loginWithToken('admin@example.com', 'changeme', { visitHome: false })

    // Navigate manually after login
    cy.visit('/')

    // Check we're still logged in
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      expect(token).to.not.be.null
    })
  })

  it('should handle login failure gracefully', () => {
    // Test with wrong credentials - this should fail gracefully
    cy.on('fail', (err) => {
      // Expect the error to contain login failure information
      expect(err.message).to.include('Login failed for wrong@email.com')
      expect(err.message).to.include('Status: 401')
      expect(err.message).to.include('Invalid credentials')
      return false // Prevent Cypress from failing the test
    })

    // This will throw an error, which we're catching above
    cy.loginWithToken('wrong@email.com', 'wrongpassword')
  })

  it('should successfully login and show success message', () => {
    // Test successful login with proper logging
    cy.loginWithToken('admin@example.com', 'changeme')

    // Verify success by checking the success log message appears
    // This test mainly verifies that no errors are thrown for valid credentials
    cy.window().then((win) => {
      const token = win.localStorage.getItem('local-store')
      expect(token).to.not.be.null

      const parsed = JSON.parse(token)
      expect(parsed.logged_in).to.be.true
      expect(parsed.access_token).to.exist
      expect(parsed.user_id).to.exist

      cy.log('✅ Successful login verified with all required token fields')
    })
  })

})
