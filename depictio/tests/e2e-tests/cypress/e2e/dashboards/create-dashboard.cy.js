describe('Create and manage dashboard', () => {
    let adminUser;
    const initialTitle = "Test Dashboard";
    let dashboardId; // Variable to store the extracted dashboard ID

    before(() => {
        // Skip this test suite if in unauthenticated mode
        if (Cypress.env('UNAUTHENTICATED_MODE')) {
            cy.log('Skipping dashboard creation test - running in unauthenticated mode')
            return
        }

        cy.fixture('test-credentials.json').then((credentials) => {
            adminUser = credentials.adminUser;
        });
    });

    beforeEach(() => {
        // Skip if in unauthenticated mode
        if (Cypress.env('UNAUTHENTICATED_MODE')) {
            cy.skip()
        }
    })

    it('logs in, creates and manages a dashboard', () => {
        // Fast token-based login (bypasses /auth UI)
        cy.loginWithTokenAsTestUser('adminUser')

        // Navigate to dashboards page
        cy.visit('/dashboards')
        cy.wait(2000)

        cy.url().should('include', '/dashboards')

        // Wait for the dashboard to load
        cy.wait(1000)

        // Create a new dashboard
        cy.contains('+ New Dashboard').click()

        // Wait for modal to load
        cy.wait(1000)

        // Input the dashboard title with timestamp for uniqueness
        const uniqueTitle = `Test Dashboard ${new Date().toISOString().replace(/:/g, '-')}`;
        cy.typeRobust('input[placeholder="Enter dashboard title"]', uniqueTitle)

        // Select the project from the dropdown
        cy.get('#dashboard-projects').click()
        cy.contains('Iris Dataset Project Data Analysis (646b0f3c1e4a2d7f8e5b8c9a)').click()

        // Click on Create Dashboard button
        cy.get('#create-dashboard-submit').click()

        // Wait for the dashboard to be created and UI to refresh
        cy.wait(3000)

        // Verify dashboard creation succeeded by checking there's at least one dashboard
        cy.get('.mantine-Card-root').should('have.length.greaterThan', 0)

        // For cleanup, find any Test Dashboard and delete one
        cy.contains('Test Dashboard').should('be.visible')

        // Click on the first Test Dashboard we find to select its card
        cy.contains('Test Dashboard')
            .parents('.mantine-Card-root')
            .within(() => {
                // Open Actions accordion
                cy.contains('Actions').click({ force: true })
                cy.wait(500)

                // Click delete button
                cy.contains('button', 'Delete').click({ force: true })
            })

        // Handle delete confirmation
        cy.wait(1000)
        cy.get('button').contains('Delete').click({ force: true })

        // Verify deletion succeeded
        cy.wait(2000)
    });
});
