const { defineConfig } = require('cypress')

module.exports = defineConfig({
    e2e: {
        experimentalStudio: true,
        // watchForFileChanges: true,
        baseUrl: 'http://localhost:5080',
        specPattern: 'cypress/e2e/**/*.cy.js',
        supportFile: 'cypress/support/e2e.js',
        viewportWidth: 1920,
        viewportHeight: 1080,
        experimentalRunAllSpecs: true,
        // Improved timeouts for CI stability
        defaultCommandTimeout: 10000,
        requestTimeout: 15000,
        responseTimeout: 15000,
        pageLoadTimeout: 30000,
        // Better handling of CI environments
        animationDistanceThreshold: 5,
        waitForAnimations: true,
        watchOptions: {
            watchFileChanges: true,
            pollInterval: 1000
        },
        env: {
            UNAUTHENTICATED_MODE: false,
            PUBLIC_MODE: false,
            DEMO_MODE: false
        },
        setupNodeEvents(on, config) {
            // Allow setting environment variables from command line
            if (process.env.CYPRESS_UNAUTHENTICATED_MODE) {
                config.env.UNAUTHENTICATED_MODE = process.env.CYPRESS_UNAUTHENTICATED_MODE === 'true'
            }
            if (process.env.CYPRESS_PUBLIC_MODE) {
                config.env.PUBLIC_MODE = process.env.CYPRESS_PUBLIC_MODE === 'true'
            }
            if (process.env.CYPRESS_DEMO_MODE) {
                config.env.DEMO_MODE = process.env.CYPRESS_DEMO_MODE === 'true'
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
    chromeWebSecurity: false
})
