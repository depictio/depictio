// ***********************************************************
// This example support/e2e.js is processed and
// loaded automatically before your test files.
//
// This is a great place to put global configuration and
// behavior that modifies Cypress.
//
// You can change the location of this file or turn off
// automatically serving support files with the
// 'supportFile' configuration option.
//
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

// Import commands.js using ES2015 syntax:
import './commands'
import './unauthenticated-commands'

// Alternatively you can use CommonJS syntax:
// require('./commands')

// Global configuration for all tests
Cypress.on('uncaught:exception', (err, runnable) => {
  // Prevent Cypress from failing the test on uncaught exceptions
  // This might be needed if the app has some expected errors
  return false
})

// Add global before hook to log test mode
beforeEach(() => {
  const isUnauthenticated = Cypress.env('UNAUTHENTICATED_MODE')
  cy.log(`Running in ${isUnauthenticated ? 'UNAUTHENTICATED' : 'AUTHENTICATED'} mode`)
})
