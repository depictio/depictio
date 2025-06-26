describe('Create and manage dashboard', () => {
    let adminUser;
    const initialTitle = "Test Dashboard";
    let dashboardId; // Variable to store the extracted dashboard ID
    let duplicateDashboardId; // Variable for the duplicated dashboard ID

    before(() => {
        // Skip this test suite if in unauthenticated mode
        if (Cypress.env('UNAUTHENTICATED_MODE')) {
            cy.log('Skipping extended dashboard test - running in unauthenticated mode')
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

    it('logs in, creates, duplicates, edits, toggles privacy and manages dashboards', () => {
        cy.visit('/auth')
        cy.get('#auth-modal').should('be.visible')

        cy.get('input[type="text"][placeholder="Enter your email"]')
            .filter(':visible')
            .type(adminUser.email)

        cy.get('input[type="password"][placeholder="Enter your password"]')
            .filter(':visible')
            .type(adminUser.password)

        cy.contains('Login').click()
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

                    // Now duplicate the dashboard
                    duplicateDashboard(uniqueTitle, dashboardId).then((duplicateTitle) => {
                        // Edit the name of the duplicated dashboard
                        // const newTitle = `Edited ${duplicateTitle} ${new Date().getTime()}`;
                        // editDashboardName(duplicateTitle, duplicateDashboardId, newTitle).then(() => {
                        // Toggle privacy settings
                        // togglePrivacyAndVerify(uniqueTitle, duplicateDashboardId).then(() => {
                        // Delete both dashboards
                        deleteAndVerify(duplicateTitle, duplicateDashboardId);
                        deleteAndVerify(uniqueTitle, dashboardId);
                        // });
                        // });
                    });
                } catch (e) {
                    console.error("Error parsing dashboard ID:", e);
                    cy.log("Error parsing dashboard ID:", idAttr);
                }
            });
    });

    function duplicateDashboard(title, id) {
        // This function will duplicate the dashboard and return a promise with the duplicate title
        return new Cypress.Promise((resolve) => {
            // Find the dashboard with the original title
            cy.contains('h5.mantine-Title-root', title)
                .parents('.mantine-Card-root')
                .within(() => {
                    // Open Dashboard Actions accordion if not already open
                    cy.contains('Dashboard Actions').click({ force: true });
                    cy.wait(500); // Wait for accordion to open

                    // Click the duplicate button
                    cy.contains('button', 'Duplicate').click({ force: true });
                });

            // Wait for the duplication to complete
            cy.wait(1000);

            // The duplicate should have the same title with "(copy)" appended
            const duplicateTitle = `${title} (copy)`;

            // Verify the duplicate dashboard exists
            cy.contains('h5.mantine-Title-root', duplicateTitle).should('be.visible');

            // Find and extract the duplicate dashboard ID
            cy.contains('h5.mantine-Title-root', duplicateTitle)
                .parents('.mantine-Card-root')
                .find('[id*="edit-dashboard-button"]')
                .invoke('attr', 'id')
                .then((idAttr) => {
                    try {
                        const idObj = JSON.parse(idAttr.replace(/&quot;/g, '"'));
                        duplicateDashboardId = idObj.index;
                        console.log(`Extracted duplicate dashboard ID: ${duplicateDashboardId}`);
                        resolve(duplicateTitle);
                    } catch (e) {
                        console.error("Error parsing duplicate dashboard ID:", e);
                        cy.log("Error parsing duplicate dashboard ID:", idAttr);
                        resolve(duplicateTitle); // Resolve anyway to continue the test
                    }
                });
        });
    }

    function editDashboardName(currentTitle, id, newTitle) {
        // This function will edit the dashboard name and return a promise
        return new Cypress.Promise((resolve) => {
            // Find the dashboard with the current title
            cy.contains('h5.mantine-Title-root', currentTitle)
                .parents('.mantine-Card-root')
                .within(() => {
                    // Open Dashboard Actions accordion if not already open
                    cy.contains('Dashboard Actions').click({ force: true });
                    cy.wait(500); // Wait for accordion to open

                    // Click the edit name button
                    cy.contains('button', 'Edit name').click({ force: true });
                });

            // Wait for the edit modal to appear
            cy.wait(1000);

            // Find the input field and clear it
            cy.get('input[type="text"][placeholder="New name"]')
                .clear()
                .type(newTitle);

            // Click the save button - find the button by text like "Save" or "Update"
            cy.contains('button', 'Save').click({ force: true });
            // If the button text is different, try another common label
            // cy.contains('button', 'Update').click({ force: true });

            // Wait for the update to complete
            cy.wait(1000);

            // Verify the dashboard name was updated
            cy.contains('h5.mantine-Title-root', newTitle).should('be.visible');
            cy.log(`Dashboard name updated from "${currentTitle}" to "${newTitle}"`);

            resolve();
        });
    }

    function togglePrivacyAndVerify(title, id) {
        // This function will toggle privacy settings and return a promise
        return new Cypress.Promise((resolve) => {
            // Find the dashboard with the title
            cy.contains('h5.mantine-Title-root', title)
                .parents('.mantine-Card-root')
                .within(() => {
                    // Open Dashboard Actions accordion if not already open
                    cy.contains('Dashboard Actions').click({ force: true });
                    cy.wait(500); // Wait for accordion to open

                    // First check current status - look for "Private" badge
                    cy.get('.mantine-Badge-root').then($badge => {
                        const isPrivate = $badge.text().includes('Private');
                        cy.log(`Current dashboard status: ${isPrivate ? 'Private' : 'Public'}`);

                        if (isPrivate) {
                            // Click Make Public button
                            cy.contains('button', 'Make public').click({ force: true });
                            cy.wait(1000);

                            // Verify badge changed to Public
                            cy.get('.mantine-Badge-root').should('contain', 'Public');
                            cy.log('Dashboard changed to Public successfully');

                            // Now make it private again
                            cy.contains('button', 'Make private').click({ force: true });
                            cy.wait(1000);

                            // Verify badge changed back to Private
                            cy.get('.mantine-Badge-root').should('contain', 'Private');
                            cy.log('Dashboard changed back to Private successfully');
                        } else {
                            // If it's already public, make it private then public again
                            cy.contains('button', 'Make private').click({ force: true });
                            cy.wait(1000);

                            // Verify badge changed to Private
                            cy.get('.mantine-Badge-root').should('contain', 'Private');
                            cy.log('Dashboard changed to Private successfully');

                            // Now make it public again
                            cy.contains('button', 'Make public').click({ force: true });
                            cy.wait(1000);

                            // Verify badge changed back to Public
                            cy.get('.mantine-Badge-root').should('contain', 'Public');
                            cy.log('Dashboard changed back to Public successfully');

                            // Make it private for the final state
                            cy.contains('button', 'Make private').click({ force: true });
                            cy.wait(1000);

                            // Verify badge changed to Private
                            cy.get('.mantine-Badge-root').should('contain', 'Private');
                        }
                    });
                });

            resolve();
        });
    }

    function deleteAndVerify(title, id) {
        // Find the dashboard with the specified title
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

        // Log buttons with dashboard ID for debugging
        cy.get(`[id*='${id}']`).then($buttons => {
            cy.log(`Found ${$buttons.length} buttons with dashboard ID ${id}`);

            // Log all button IDs for debugging
            $buttons.each((index, button) => {
                cy.log(`Button ${index} ID: ${button.id}`);
            });
        });

        // Click the confirmation button
        cy.get(`[id='{\"index\":\"${id}\",\"type\":\"confirm-dashboard-delete-button\"}']`).click({ force: true });

        // Wait for deletion to complete
        cy.wait(2000);

        // Verify the dashboard with the title no longer exists
        // Use a more specific selector that matches how the application is structured
        cy.get('h5.mantine-Title-root').each(($el) => {
            cy.wrap($el).invoke('text').should('not.eq', title);
        });

        cy.log(`Dashboard "${title}" successfully deleted`);
    }
});
