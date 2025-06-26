// Custom commands for unauthenticated mode tests

// Command to check if we're in unauthenticated mode
Cypress.Commands.add('isUnauthenticatedMode', () => {
  return Cypress.env('UNAUTHENTICATED_MODE') === true
})

// Command to skip test if not in unauthenticated mode
Cypress.Commands.add('skipIfNotUnauthenticated', () => {
  if (!Cypress.env('UNAUTHENTICATED_MODE')) {
    cy.skip()
  }
})

// Command to skip test if in unauthenticated mode
Cypress.Commands.add('skipIfUnauthenticated', () => {
  if (Cypress.env('UNAUTHENTICATED_MODE')) {
    cy.skip()
  }
})

// Command to enable interactive mode
Cypress.Commands.add('enableInteractiveMode', () => {
  cy.visit('/profile')
  cy.wait(2000)
  cy.get('#upgrade-to-temporary-button').click()
  cy.get('#upgrade-modal-confirm').click()
  cy.wait(3000)
})

// Command to verify anonymous user state
Cypress.Commands.add('verifyAnonymousUser', () => {
  cy.visit('/profile')
  cy.wait(2000)

  // Check email field in user info
  cy.get('#user-info-placeholder').within(() => {
    cy.contains('Email').parent().within(() => {
      cy.get('.mantine-Text-root').should('contain', 'anonymous')
      cy.get('.mantine-Text-root').should('not.contain', 'temp_user_')
    })
  })

  cy.contains('button', 'Login as a temporary user').should('be.visible')
})

// Command to verify temporary user state
Cypress.Commands.add('verifyTemporaryUser', () => {
  cy.visit('/profile')
  cy.wait(2000)

  // Check email field in user info
  cy.get('#user-info-placeholder').within(() => {
    cy.contains('Email').parent().within(() => {
      cy.get('.mantine-Text-root').should('contain', 'temp_user_')
      cy.get('.mantine-Text-root').should('not.contain', 'anonymous')
    })
  })

  cy.get('#upgrade-to-temporary-button').should('not.exist')
})

// Command to check dashboard button states
Cypress.Commands.add('checkDashboardButtons', (dashboardTitle, expectedStates) => {
  cy.contains('h5.mantine-Title-root', dashboardTitle)
    .parents('.mantine-Card-root')
    .within(() => {
      // Open Dashboard Actions accordion first to reveal buttons
      cy.get('[data-accordion-control="true"]').contains('Dashboard Actions').click()
      cy.wait(500)

      // Check View button
      if (expectedStates.view !== undefined) {
        if (expectedStates.view) {
          cy.contains('button', 'View').should('be.visible').should('not.be.disabled')
        } else {
          cy.contains('button', 'View').should('be.disabled')
        }
      }

      // Check Duplicate button
      if (expectedStates.duplicate !== undefined) {
        if (expectedStates.duplicate) {
          cy.contains('button', 'Duplicate').should('be.visible').should('not.be.disabled')
        } else {
          cy.contains('button', 'Duplicate').should('be.disabled')
        }
      }

      // Check Delete button
      if (expectedStates.delete !== undefined) {
        if (expectedStates.delete) {
          cy.contains('button', 'Delete').should('be.visible').should('not.be.disabled')
        } else {
          cy.contains('button', 'Delete').should('be.disabled')
        }
      }

      // Check Edit name button
      if (expectedStates.editName !== undefined) {
        if (expectedStates.editName) {
          cy.contains('button', 'Edit name').should('be.visible').should('not.be.disabled')
        } else {
          cy.contains('button', 'Edit name').should('be.disabled')
        }
      }

      // Check Make private/public button
      if (expectedStates.makePrivate !== undefined) {
        if (expectedStates.makePrivate) {
          cy.contains('button', 'Make private').should('be.visible').should('not.be.disabled')
        } else {
          cy.contains('button', 'Make private').should('be.disabled')
        }
      }
    })
})

// Command to verify no auth page redirect
Cypress.Commands.add('verifyNoAuthRedirect', (path = '/') => {
  cy.visit(path)
  cy.url().should('not.include', '/auth')
  cy.get('#auth-modal').should('not.exist')
})

// Command to verify dashboard has public badge
Cypress.Commands.add('verifyDashboardIsPublic', (dashboardTitle) => {
  cy.contains('h5.mantine-Title-root', dashboardTitle)
    .parents('.mantine-Card-root')
    .within(() => {
      cy.get('.mantine-Badge-root')
        .contains('Public')
        .should('be.visible')
    })
})

// Command to verify dashboard badges and metadata
Cypress.Commands.add('verifyDashboardBadges', (dashboardTitle, expectedBadges) => {
  cy.contains('h5.mantine-Title-root', dashboardTitle)
    .parents('.mantine-Card-root')
    .within(() => {
      if (expectedBadges.public) {
        cy.get('.mantine-Badge-root').contains('Public').should('be.visible')
      }
      if (expectedBadges.private) {
        cy.get('.mantine-Badge-root').contains('Private').should('be.visible')
      }
      if (expectedBadges.project) {
        cy.get('.mantine-Badge-root').contains('Project:').should('be.visible')
      }
      if (expectedBadges.owner) {
        cy.get('.mantine-Badge-root').contains('Owner:').should('be.visible')
      }
    })
})
