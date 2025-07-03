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
        // Log in using the reusable function
        cy.loginAsTestUser('adminUser')
        cy.url().should('include', '/dashboards')

        // Wait for the dashboard to load
        cy.wait(1000)

        // Create a new dashboard
        cy.contains('+ New Dashboard').click()

        // Input the dashboard title with timestamp for uniqueness
        const uniqueTitle = `Test Dashboard ${new Date().toISOString().replace(/:/g, '-')}`;
        cy.get('input[type="text"][placeholder="Enter dashboard title"]')
            .type(uniqueTitle)

        // Select the project from the dropdown
        cy.get('#dashboard-projects').click()
        cy.contains('Iris Dataset Project Data Analysis (646b0f3c1e4a2d7f8e5b8c9a)').click()

        // Click on Create Dashboard button
        cy.get('#create-dashboard-submit').click()

        // Wait for the dashboard to be created
        cy.wait(1000)

        // Find the newly created dashboard by its unique title
        cy.contains('h5.mantine-Title-root', uniqueTitle).should('be.visible');

        // Find a dashboard button and extract the ID
        cy.contains('h5.mantine-Title-root', uniqueTitle)
            .parents('.mantine-Card-root')
            .find('[id*="edit-dashboard-button"]')
            .invoke('attr', 'id')
            .then((idAttr) => {
                // Parse the JSON-like ID attribute
                try {
                    const idObj = JSON.parse(idAttr.replace(/&quot;/g, '"'));
                    dashboardId = idObj.index;

                    console.log(`Extracted dashboard ID: ${dashboardId}`);

                    // Try to delete the dashboard
                    deleteAndVerify(uniqueTitle, dashboardId);
                } catch (e) {
                    console.error("Error parsing dashboard ID:", e);
                    cy.log("Error parsing dashboard ID:", idAttr);
                }
            });
    });

    function deleteAndVerify(title, id) {
        // Find the dashboard with the unique title
        cy.contains('h5.mantine-Title-root', title)
            .parents('.mantine-Card-root')
            .within(() => {
                // Open Dashboard Actions accordion if not already open
                cy.contains('Dashboard Actions').click({ force: true });
                cy.wait(500); // Wait for accordion to open

                // Click the delete button
                cy.contains('button', 'Delete').click({ force: true });
            });

        // Wait for the confirmation modal to appear
        cy.wait(1000);

        // We need to look for the modal in the entire document
        // Look for a button with the ID containing the dashboardId and 'delete' keyword
        // First, check if there is any button with our dashboard ID
        cy.get(`[id*='${id}']`).then($buttons => {
            cy.log(`Found ${$buttons.length} buttons with dashboard ID ${id}`);

            // Log all button IDs for debugging
            $buttons.each((index, button) => {
                cy.log(`Button ${index} ID: ${button.id}`);
            });
        });

        // Now, click the button with the specific ID
        cy.get(`[id='{\"index\":\"${id}\",\"type\":\"confirm-dashboard-delete-button\"}']`).click({ force: true });


        // Wait for deletion to complete
        cy.wait(1000);

        // Verify the dashboard with the unique title no longer exists
        cy.contains('h5.mantine-Title-root', title).should('not.exist');
    }
});
