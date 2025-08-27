const { defineConfig } = require('cypress')

module.exports = defineConfig({
    e2e: {
        // No baseUrl - allows tests to visit external sites directly
        specPattern: 'cypress/e2e/**/*.cy.js',
        supportFile: false, // Disable support file to avoid dependencies
        viewportWidth: 1920,
        viewportHeight: 1080,
        video: false,
        screenshotOnRunFailure: false,
        // Shorter timeouts for simple validation tests
        defaultCommandTimeout: 5000,
        requestTimeout: 10000,
        responseTimeout: 10000,
        pageLoadTimeout: 15000,
    },
    chromeWebSecurity: false
})
