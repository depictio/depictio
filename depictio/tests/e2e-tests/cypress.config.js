const { defineConfig } = require('cypress')

module.exports = defineConfig({
    e2e: {
        // watchForFileChanges: true,
        baseUrl: 'http://localhost:5080',
        specPattern: 'cypress/e2e/**/*.cy.js',
        supportFile: 'cypress/support/e2e.js',
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
        // Define environment variables with defaults
        env: {
            UNAUTHENTICATED_MODE: false
        },
        setupNodeEvents(on, config) {
            // Allow setting environment variables from command line
            if (process.env.CYPRESS_UNAUTHENTICATED_MODE) {
                config.env.UNAUTHENTICATED_MODE = process.env.CYPRESS_UNAUTHENTICATED_MODE === 'true'
            }

            // Add task for logging
            on('task', {
                log(message) {
                    console.log(message)
                    return null
                }
            })

            return config
        }
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
