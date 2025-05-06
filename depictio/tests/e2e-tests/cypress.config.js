const { defineConfig } = require('cypress')

module.exports = defineConfig({
    e2e: {
        baseUrl: 'http://localhost:5080',
        specPattern: 'cypress/e2e/**/*.cy.js',
        supportFile: false,
        viewportWidth: 1920,
        viewportHeight: 1080
    },
})
