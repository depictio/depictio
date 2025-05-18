const { defineConfig } = require('cypress')

module.exports = defineConfig({
    e2e: {
        // watchForFileChanges: true,
        baseUrl: 'http://localhost:5080',
        specPattern: 'cypress/e2e/**/*.cy.js',
        supportFile: false,
        viewportWidth: 1920,
        viewportHeight: 1080,
        browser: 'chrome',
        experimentalRunAllSpecs: true,
        // Add these settings to improve file watching
        watchOptions: {
            watchFileChanges: true,
            // Reduce polling interval (milliseconds)
            pollInterval: 1000
        },
    },
    chromeWebSecurity: false,
    // Add these Chrome preferences to disable password saving
    browser: {
        chromePreferences: {
            credentials_enable_service: false,
            profile: {
                password_manager_enabled: false
            }
        }
    }
})
