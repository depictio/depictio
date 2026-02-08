describe('Unauthenticated Mode - API Endpoint Protection', () => {

  beforeEach(function() {
    // Skip if not in unauthenticated mode
    if (!Cypress.env('UNAUTHENTICATED_MODE')) {
      this.skip()
    }
  })

  it('should reject dashboard creation API calls from anonymous users', () => {
    // Get the anonymous user token
    cy.visit('/dashboards')
    cy.wait(2000)

    // Get token from local storage
    cy.window().then((win) => {
      const localStorage = win.localStorage
      const userInfo = localStorage.getItem('userInfo')

      if (userInfo) {
        const parsedInfo = JSON.parse(userInfo)
        const token = parsedInfo.access_token

        // Try to create a dashboard via API
        cy.request({
          method: 'POST',
          url: 'http://localhost:8058/depictio/api/v1/dashboards/save/507f1f77bcf86cd799439011',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: {
            id: '507f1f77bcf86cd799439011',
            title: 'Test Dashboard',
            dashboard_id: '507f1f77bcf86cd799439011',
            project_id: '507f1f77bcf86cd799439012',
            permissions: {
              owners: [],
              viewers: []
            }
          },
          failOnStatusCode: false
        }).then((response) => {
          // Should get 401 (Unauthorized) or 403 (Forbidden)
          expect(response.status).to.be.oneOf([401, 403])

          // Should contain appropriate error message
          if (response.status === 403) {
            expect(response.body.detail).to.contain('Anonymous users cannot create')
          }
        })
      }
    })
  })

  it('should allow anonymous users to view public dashboards via API', () => {
    cy.visit('/dashboards')
    cy.wait(2000)

    // Get token from local storage
    cy.window().then((win) => {
      const localStorage = win.localStorage
      const userInfo = localStorage.getItem('userInfo')

      if (userInfo) {
        const parsedInfo = JSON.parse(userInfo)
        const token = parsedInfo.access_token

        // Try to list dashboards (should work for anonymous users)
        cy.request({
          method: 'GET',
          url: 'http://localhost:8058/depictio/api/v1/dashboards/list',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          failOnStatusCode: false
        }).then((response) => {
          // Should succeed (200) for anonymous users to view public dashboards
          expect(response.status).to.equal(200)

          // Should return array of dashboards
          expect(response.body).to.be.an('array')
        })
      }
    })
  })
})
