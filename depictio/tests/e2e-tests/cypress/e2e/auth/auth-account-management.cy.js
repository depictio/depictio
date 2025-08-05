describe('Authentication - Account Management', () => {
  let testUser;

  before(() => {
    // Skip this test suite if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping account management tests - running in unauthenticated mode')
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

  // describe('Password Management', () => {
  //   it('should edit user password successfully', () => {
  //     const new_password = 'NewPassword123!'; // New password for the test

  //     cy.log('Starting password change test for user:', testUser.email)

  //     // Fast token-based login for test setup
  //     cy.loginWithTokenAsTestUser('testUser')

  //     // Navigate to dashboards
  //     cy.visit('/dashboards')
  //     cy.wait(2000)

  //     // Go to profile page
  //     cy.visit('/profile')
  //     cy.wait(2000)

  //     // Look for "Edit Password" button directly (no accordion needed)
  //     cy.contains('Edit Password', { timeout: 10000 }).should('be.visible').click()
  //     cy.wait(1000)

  //     // The edit password form should now be visible
  //     // Fill out the password change form with better Mantine compatibility

  //     // Old Password - use multiple strategies for Mantine PasswordInput
  //     cy.get('input[placeholder="Old Password"]', { timeout: 10000 })
  //       .should('be.visible')
  //       .should('not.be.disabled')
  //       .focus()
  //       .clear()
  //       .type(testUser.password, {
  //         delay: 50,
  //         force: true,
  //         parseSpecialCharSequences: false
  //       })
  //       .should('have.value', testUser.password)

  //     // New Password
  //     cy.get('input[placeholder="New Password"]')
  //       .should('be.visible')
  //       .should('not.be.disabled')
  //       .focus()
  //       .clear()
  //       .type(new_password, {
  //         delay: 50,
  //         force: true,
  //         parseSpecialCharSequences: false
  //       })
  //       .should('have.value', new_password)

  //     // Confirm Password
  //     cy.get('input[placeholder="Confirm Password"]')
  //       .should('be.visible')
  //       .should('not.be.disabled')
  //       .focus()
  //       .clear()
  //       .type(new_password, {
  //         delay: 50,
  //         force: true,
  //         parseSpecialCharSequences: false
  //       })
  //       .should('have.value', new_password)

  //     // Submit the password change
  //     cy.contains('button', 'Save').click()

  //     cy.wait(2000)

  //     // Check for success message or confirmation
  //     cy.get('body').then(($body) => {
  //       // Look for success indicators
  //       if ($body.find('.notification').length > 0) {
  //         cy.get('.notification').should('contain.text', 'success')
  //       }

  //       cy.wait(1000)

  //       // Logout to test the new password
  //       cy.get('[data-testid="logout-button"], button:contains("Logout"), a:contains("Logout")')
  //         .first()
  //         .click({ force: true })

  //       cy.wait(2000)

  //       // Verify we're logged out (check URL or page content)
  //       cy.url().should('not.include', '/dashboards')

  //       // Wait a bit for logout to complete
  //       cy.wait(1000)

  //       // Test login with the new password
  //       // Navigate away from profile to reset state
  //       cy.visit('/profile')
  //       cy.wait(2000)

  //       // Try to login with the new password
  //       cy.loginUser(testUser.email, new_password, { visitAuth: false })
  //     })
  //   })
  // })

  describe('Session Management', () => {
    it('should logout successfully', () => {
      // Fast token-based login for test setup
      cy.loginWithTokenAsTestUser('testUser')

      // Navigate to dashboards
      cy.visit('/dashboards')
      cy.wait(2000)

      // Check if the login was successful
      cy.url().should('include', '/dashboards')

      // Go to profile page
      cy.visit('/profile')
      cy.wait(2000)

      // Find and click the logout button - try multiple possible selectors
      cy.get('body').then(($body) => {
        // Try different possible logout button selectors
        const logoutSelectors = [
          '[data-testid="logout-button"]',
          'button:contains("Logout")',
          'a:contains("Logout")',
          '[data-cy="logout"]',
          '.logout-button'
        ]

        let found = false
        for (const selector of logoutSelectors) {
          if ($body.find(selector).length > 0 && !found) {
            cy.get(selector).first().click({ force: true })
            found = true
            break
          }
        }

        if (!found) {
          // If no standard logout button found, look for any element containing "logout"
          cy.contains(/logout/i).first().click({ force: true })
        }
      })

      cy.wait(2000)

      // Verify logout succeeded - we should be redirected away from protected pages
      cy.url().should('not.include', '/dashboards')

      // Alternatively, verify we can't access protected content without re-authentication
      cy.visit('/dashboards')
      // Should be redirected to auth or see login prompt
      cy.url().should('not.include', '/dashboards')
    })
  })

  describe('Token Management', () => {
    it('should create a new CLI configuration token', () => {
      let configName; // Variable to store the dynamic config name

      // Fast token-based login
      cy.loginWithTokenAsTestUser('testUser')

      // Navigate to dashboard
      cy.wait(1000)

      // Check if we're redirected off auth page (more flexible)
      cy.url().should('not.include', '/auth')

      // If we're still on the auth page, wait and check again
      cy.get('body').then(($body) => {
        if ($body.find('[role="dialog"][aria-modal="true"]').length > 0) {
          // Still showing auth modal, wait longer
          cy.wait(2000)
        } else {
          // Navigate to dashboard to ensure we're logged in
          cy.visit('/dashboards')
          cy.wait(2000)
        }
      })

      // Navigate to profile page
      cy.visit('/profile')

      // Wait for the profile page to load
      cy.wait(2000)

      // Look for CLI configuration section or API tokens section
      cy.get('body').then(($body) => {
        // Try to find CLI or token management section
        if ($body.find('button:contains("Generate CLI Config")').length > 0) {
          cy.contains('button', 'Generate CLI Config').click()
        } else if ($body.find('a:contains("CLI")').length > 0) {
          cy.contains('a', 'CLI').click()
        } else {
          // Look for any token or API related buttons
          cy.contains(/token|api|cli/i).first().click()
        }
      })

      cy.wait(2000)

      // Generate a unique config name
      const timestamp = Date.now()
      configName = `test-cli-config-${timestamp}`

      // Look for configuration name input field
      cy.get('body').then(($body) => {
        if ($body.find('input[placeholder*="name"], input[placeholder*="Config"]').length > 0) {
          cy.get('input[placeholder*="name"], input[placeholder*="Config"]')
            .first()
            .clear()
            .type(configName)
        }
      })

      // Click create/generate button
      cy.get('body').then(($body) => {
        if ($body.find('button:contains("Create"), button:contains("Generate")').length > 0) {
          cy.contains('button', /Create|Generate/i).first().click()
        }
      })

      cy.wait(2000);

      // Verify config was created (look for success message or new config in list)
      cy.get('body').then(($body) => {
        if ($body.find('.notification, .alert, .message').length > 0) {
          cy.get('.notification, .alert, .message').should('contain.text', configName)
        }

        // Clean up - try to delete the created config
        cy.wait(2000);

        if ($body.find('button:contains("Delete"), .delete-button').length > 0) {
          cy.contains('button', 'Delete').click({ force: true })
          cy.wait(1000); // Wait for dialog to fully render

          // Confirm deletion if prompted
          if ($body.find('button:contains("Confirm"), button:contains("Yes")').length > 0) {
            cy.contains('button', /Confirm|Yes|Delete/i).click({ force: true })
          }
        }
      })
    })
  })

  describe('Token-Based Authentication Tests', () => {
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
      // Test with custom credentials
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
})
