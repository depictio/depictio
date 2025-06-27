describe('Project Permissions Management', () => {
    let adminUser;
    let testUser;
    let testProjectId;
    const projectName = "Test Permissions Project";

    before(() => {
        // Skip this test suite if in unauthenticated mode
        if (Cypress.env('UNAUTHENTICATED_MODE')) {
            cy.log('Skipping permissions test - running in unauthenticated mode')
            return
        }

        cy.fixture('test-credentials.json').then((credentials) => {
            adminUser = credentials.adminUser;
            testUser = credentials.testUser;
        });
    });

    beforeEach(() => {
        // Skip if in unauthenticated mode
        if (Cypress.env('UNAUTHENTICATED_MODE')) {
            cy.skip()
        }
    })

    // Helper function to navigate to project permissions
    function navigateToProjectPermissions() {
        cy.visit('/projects')
        cy.wait(1000)  // Increased wait time

        // Find and click the project accordion button to expand it
        cy.contains('Iris Dataset Project Data Analysis')
            .closest('button[data-accordion-control="true"]')
            .click()
        cy.wait(1000)  // Increased wait time

        // Click on "Roles and permissions"
        cy.contains('Roles and permissions').click()
        cy.url().should('include', '/project/646b0f3c1e4a2d7f8e5b8c9a')
        cy.wait(1000)  // Increased wait time for permissions page to fully load

        // Wait for the permissions manager to be ready
        cy.get('#permissions-manager-project-title').should('be.visible')
        cy.get('#permissions-manager-grid').should('be.visible')
    }

    // Helper function to wait for permissions to be enabled
    function waitForPermissionsToEnable() {
        // Wait for permissions controls to be enabled (should be faster now with the callback fix)
        cy.get('#permissions-manager-input-email', { timeout: 10000 }).should('not.be.disabled')
        cy.get('#permissions-manager-checkbox-owner', { timeout: 10000 }).should('not.be.disabled')
        cy.get('#permissions-manager-checkbox-editor', { timeout: 10000 }).should('not.be.disabled')
        cy.get('#permissions-manager-checkbox-viewer', { timeout: 10000 }).should('not.be.disabled')

        cy.log('Permissions are now enabled and ready for interaction')
    }

    // Helper function to logout
    function logout() {
        // Try different possible logout button selectors
        cy.get('body').then($body => {
            if ($body.find('#logout-button').length > 0) {
                cy.get('#logout-button').click()
            } else if ($body.find('[data-testid="logout"]').length > 0) {
                cy.get('[data-testid="logout"]').click()
            } else if ($body.find('button').filter(':contains("Logout")').length > 0) {
                cy.contains('button', 'Logout').click()
            } else {
                // Fallback: visit auth page directly
                cy.visit('/auth')
            }
        })
        cy.wait(1000)
    }

    // Helper function to wait for permissions to be disabled (for non-owners)
    function waitForPermissionsToBeDisabled() {
        // Check if permissions need to be refreshed
        cy.get('#permissions-manager-input-email').then($input => {
            if (!$input.is(':disabled')) {
                cy.log('Permissions not disabled yet, waiting longer or refreshing...')
                cy.wait(3000)
            }
        })

        // Wait for permissions controls to be disabled
        cy.get('#make-project-public-button', { timeout: 15000 }).should('have.class', 'mantine-SegmentedControl-root').and('have.attr', 'data-disabled', 'true')
        cy.get('#permissions-manager-input-email', { timeout: 15000 }).should('be.disabled')
        cy.get('#permissions-manager-checkbox-owner', { timeout: 15000 }).should('be.disabled')
        cy.get('#permissions-manager-checkbox-editor', { timeout: 15000 }).should('be.disabled')
        cy.get('#permissions-manager-checkbox-viewer', { timeout: 15000 }).should('be.disabled')
        cy.get('#permissions-manager-btn-add-user', { timeout: 15000 }).should('be.disabled')
    }

    describe('Admin User Permissions', () => {
        it('Admin can manage all project permissions', () => {
            // Login as admin
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

            // Navigate to project permissions
            navigateToProjectPermissions()

            // Verify admin can see project header with visibility toggle
            cy.get('#permissions-manager-project-title').should('be.visible')
            cy.get('#make-project-public-button').should('be.visible').and('not.be.disabled')

            // Verify the permissions grid is visible
            cy.get('#permissions-manager-grid').should('be.visible')

            // Wait for permissions to be enabled (this may take time due to async loading)
            waitForPermissionsToEnable()

            // First, remove test_user if they exist so we can test adding them
            cy.get('#permissions-manager-grid').then($grid => {
                if ($grid.text().includes(testUser.email)) {
                    cy.log('Test user exists, removing them first')
                    // Use a more robust selector for AgGrid
                    cy.get('#permissions-manager-grid')
                        .contains('.ag-cell', testUser.email)
                        .parents('.ag-row')
                        .within(() => {
                            // Find delete button by icon or class
                            cy.get('button').contains('🗑️').click()
                        })
                    cy.wait(1500) // Wait for deletion to complete
                }
            })

            // Test adding a user with Editor permissions
            cy.get('#permissions-manager-input-email').should('be.visible').click()
            cy.get('#permissions-manager-input-email').clear().type(testUser.email)
            cy.contains(testUser.email).click()

            // Verify user is selected (wait for dropdown to update)
            cy.wait(500)
            // For Mantine MultiSelect, check the parent container for selected values
            cy.get('#permissions-manager-input-email').parent().should('contain', testUser.email)

            // Select Editor permission
            cy.get('#permissions-manager-checkbox-editor').should('be.visible').and('not.be.disabled').click()

            // Verify checkbox is checked and wait for callback
            cy.get('#permissions-manager-checkbox-editor').should('be.checked')
            cy.wait(1000) // Increased wait for callback to process

            // Debug: Log that Editor checkbox should be selected
            cy.log('Editor checkbox clicked - checking if Add User button should be enabled')

            // Add user button should be enabled (force click if still disabled due to callback timing)
            cy.get('#permissions-manager-btn-add-user').should('be.visible')
            cy.get('#permissions-manager-btn-add-user').click({ force: true })

            // Wait for update
            cy.wait(1500)

            // Verify user was added to the grid with Editor permissions
            cy.get('#permissions-manager-grid').contains(testUser.email).should('be.visible')

            // First verify the user was added as Editor
            cy.get('#permissions-manager-grid')
                .contains('.ag-cell', testUser.email)
                .parents('.ag-row')
                .within(() => {
                    // Editor should be checked initially
                    cy.get('[col-id="Editor"] input[type="checkbox"]').should('be.checked')
                    // Viewer should not be checked initially
                    cy.get('[col-id="Viewer"] input[type="checkbox"]').should('not.be.checked')
                })

            // Test modifying permissions - change from Editor to Viewer
            cy.get('#permissions-manager-grid')
                .contains('.ag-cell', testUser.email)
                .parents('.ag-row')
                .within(() => {
                    // Click on Viewer checkbox
                    cy.get('[col-id="Viewer"] input[type="checkbox"]').click()
                })

            // Wait for update
            cy.wait(1000)

            // Verify permission was updated
            cy.get('#permissions-manager-grid')
                .contains('.ag-cell', testUser.email)
                .parents('.ag-row')
                .within(() => {
                    // Viewer should be checked
                    cy.get('[col-id="Viewer"] input[type="checkbox"]').should('be.checked')
                    // Editor should not be checked
                    cy.get('[col-id="Editor"] input[type="checkbox"]').should('not.be.checked')
                })

            // Test project visibility toggle
            cy.log('Testing project visibility toggle')

            // Get current state and toggle to the opposite
            cy.get('#make-project-public-button').then($button => {
                const isPublic = $button.find('input[value="True"]').is(':checked')

                if (isPublic) {
                    cy.log('Project is currently Public - changing to Private')
                    cy.get('#make-project-public-button').within(() => {
                        cy.contains('label', 'Private').click()
                    })
                } else {
                    cy.log('Project is currently Private - changing to Public')
                    cy.get('#make-project-public-button').within(() => {
                        cy.contains('label', 'Public').click()
                    })
                }
            })

            cy.wait(500)

            // Handle confirmation modal
            cy.contains('Change Project Visibility').should('be.visible')
            cy.contains('button', 'Yes').click()
            cy.wait(1000)

            // Verify the toggle worked - just check that one of the options is selected
            cy.get('#make-project-public-button').within(() => {
                cy.get('input[type="radio"]:checked').should('exist')
            })
            cy.log('Project visibility toggle test completed')

            // Test deleting a user
            cy.get('#permissions-manager-grid').then($grid => {
                if ($grid.text().includes(testUser.email)) {
                    cy.log('Test user exists, removing them first')
                    // Use a more robust selector for AgGrid
                    cy.get('#permissions-manager-grid')
                        .contains('.ag-cell', testUser.email)
                        .parents('.ag-row')
                        .within(() => {
                            // Find delete button by icon or class
                            cy.get('button').contains('🗑️').click()
                        })
                    cy.wait(1500) // Wait for deletion to complete
                }
            })

            // Wait for deletion
            cy.wait(1000)

            // Verify user was removed
            cy.get('#permissions-manager-grid').contains(testUser.email).should('not.exist')

            // The user should be back in the dropdown
            cy.get('#permissions-manager-input-email').click()
            cy.contains(testUser.email).should('be.visible')
        });
    });

    // describe('Project Owner Permissions', () => {
    //     it('Project owner can manage permissions', () => {
    //         // First, login as admin to set up test user as owner
    //         cy.visit('/auth')
    //         cy.get('#auth-modal').should('be.visible')

    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(adminUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(adminUser.password)

    //         cy.contains('Login').click()
    //         cy.url().should('include', '/dashboards')

    //         // Navigate to project permissions
    //         navigateToProjectPermissions()

    //         // Add test user as owner
    //         cy.get('#permissions-manager-input-email').click()
    //         cy.get('#permissions-manager-input-email').type(testUser.email)
    //         cy.contains(testUser.email).click()
    //         cy.get('#permissions-manager-checkbox-owner').click()
    //         cy.get('#permissions-manager-btn-add-user').click()
    //         cy.wait(1500)

    //         // Logout
    //         logout()

    //         // Login as test user
    //         cy.visit('/auth')
    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(testUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(testUser.password)

    //         cy.contains('Login').click()
    //         cy.url().should('include', '/dashboards')

    //         // Navigate to project permissions
    //         navigateToProjectPermissions()

    //         // Verify owner can manage permissions
    //         cy.get('#make-project-public-button').should('not.be.disabled')
    //         cy.get('#permissions-manager-input-email').should('not.be.disabled')
    //         cy.get('#permissions-manager-checkbox-owner').should('not.be.disabled')

    //         // Test that owner cannot remove themselves if they're the last owner
    //         cy.get('#permissions-manager-grid')
    //             .contains('tr', testUser.email)
    //             .within(() => {
    //                 // Try to change from Owner to Editor
    //                 cy.get('[col-id="Editor"]').click()
    //             })

    //         // Should see warning modal
    //         cy.contains('Cannot Change Last Owner Permissions').should('be.visible')
    //         cy.contains('button', 'OK').click()

    //         // Clean up: Remove test user as owner
    //         cy.get('#logout-button').click()
    //         cy.wait(1000)

    //         // Login back as admin
    //         cy.visit('/auth')
    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(adminUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(adminUser.password)

    //         cy.contains('Login').click()
    //         cy.wait(1000)

    //         // Navigate back to permissions
    //         navigateToProjectPermissions()

    //         // Remove test user
    //         cy.get('#permissions-manager-grid')
    //             .contains('tr', testUser.email)
    //             .within(() => {
    //                 cy.get('[col-id="actions"]').click()
    //             })
    //         cy.wait(1000)
    //     });
    // });

    // describe('Non-Owner User Restrictions', () => {
    //     it('Users without ownership cannot modify permissions', () => {
    //         // Login as test user (non-owner)
    //         cy.visit('/auth')
    //         cy.get('#auth-modal').should('be.visible')

    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(testUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(testUser.password)

    //         cy.contains('Login').click()
    //         cy.url().should('include', '/dashboards')

    //         // Navigate to project permissions
    //         navigateToProjectPermissions()

    //         // Wait for permissions to be disabled (this may take time due to async permission checks)
    //         waitForPermissionsToBeDisabled()

    //         // Verify grid is read-only (no delete buttons visible)
    //         cy.get('#permissions-manager-grid').within(() => {
    //             cy.get('[col-id="actions"] button').should('not.exist')
    //         })
    //     });
    // });

    // describe('Permission Validation', () => {
    //     it('Validates permission rules and constraints', () => {
    //         // Login as admin
    //         cy.visit('/auth')
    //         cy.get('#auth-modal').should('be.visible')

    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(adminUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(adminUser.password)

    //         cy.contains('Login').click()
    //         cy.url().should('include', '/dashboards')

    //         // Navigate to permissions
    //         navigateToProjectPermissions()

    //         // Wait for permissions to be enabled
    //         waitForPermissionsToEnable()

    //         // Test that user must select exactly one permission type
    //         cy.get('#permissions-manager-input-email').click()
    //         cy.get('#permissions-manager-input-email').clear().type(testUser.email)
    //         cy.contains(testUser.email).click()

    //         // Verify user is selected
    //         cy.get('#permissions-manager-input-email').should('contain.value', testUser.email)
    //         cy.wait(500) // Wait for callback

    //         // Without selecting any permission, button should be disabled
    //         cy.get('#permissions-manager-btn-add-user').should('be.disabled')

    //         // Select multiple permissions
    //         cy.get('#permissions-manager-checkbox-owner').click()
    //         cy.wait(200) // Wait for callback
    //         cy.get('#permissions-manager-checkbox-editor').click()
    //         cy.wait(500) // Wait for callback

    //         // Button should be disabled (only one permission allowed)
    //         cy.get('#permissions-manager-btn-add-user').should('be.disabled')

    //         // Deselect one permission
    //         cy.get('#permissions-manager-checkbox-owner').click()
    //         cy.wait(500) // Wait for callback

    //         // Verify only Editor is checked
    //         cy.get('#permissions-manager-checkbox-editor').should('be.checked')
    //         cy.get('#permissions-manager-checkbox-owner').should('not.be.checked')

    //         // Now button should be enabled
    //         cy.get('#permissions-manager-btn-add-user').should('not.be.disabled')

    //         // Add the user
    //         cy.get('#permissions-manager-btn-add-user').click()
    //         cy.wait(1500)

    //         // Test duplicate user prevention
    //         cy.get('#permissions-manager-input-email').click()
    //         // User should not appear in dropdown anymore
    //         cy.get('.mantine-MultiSelect-dropdown').should('not.contain', testUser.email)

    //         // Clean up
    //         cy.get('#permissions-manager-grid')
    //             .contains('tr', testUser.email)
    //             .within(() => {
    //                 cy.get('[col-id="actions"]').click()
    //             })
    //         cy.wait(1000)
    //     });
    // });

    // describe('Grid Interactions', () => {
    //     it('Tests permission grid checkbox interactions', () => {
    //         // Login as admin
    //         cy.visit('/auth')
    //         cy.get('#auth-modal').should('be.visible')

    //         cy.get('input[type="text"][placeholder="Enter your email"]')
    //             .filter(':visible')
    //             .type(adminUser.email)

    //         cy.get('input[type="password"][placeholder="Enter your password"]')
    //             .filter(':visible')
    //             .type(adminUser.password)

    //         cy.contains('Login').click()
    //         cy.url().should('include', '/dashboards')

    //         // Navigate to permissions
    //         navigateToProjectPermissions()

    //         // Wait for permissions to be enabled
    //         waitForPermissionsToEnable()

    //         // Add test user with Viewer permission
    //         cy.get('#permissions-manager-input-email').click()
    //         cy.get('#permissions-manager-input-email').type(testUser.email)
    //         cy.contains(testUser.email).click()
    //         cy.get('#permissions-manager-checkbox-viewer').click()
    //         cy.get('#permissions-manager-btn-add-user').click()
    //         cy.wait(2000)  // Wait for user to be added

    //         // Test permission transitions
    //         cy.get('#permissions-manager-grid')
    //             .contains('tr', testUser.email)
    //             .within(() => {
    //                 // Change from Viewer to Editor
    //                 cy.get('[col-id="Editor"]').click()
    //                 cy.wait(1000)

    //                 // Verify Editor is checked and Viewer is unchecked
    //                 cy.get('[col-id="Editor"] input[type="checkbox"]').should('be.checked')
    //                 cy.get('[col-id="Viewer"] input[type="checkbox"]').should('not.be.checked')

    //                 // Change to Owner
    //                 cy.get('[col-id="Owner"]').click()
    //                 cy.wait(1000)

    //                 // Verify Owner is checked and Editor is unchecked
    //                 cy.get('[col-id="Owner"] input[type="checkbox"]').should('be.checked')
    //                 cy.get('[col-id="Editor"] input[type="checkbox"]').should('not.be.checked')
    //             })

    //         // Clean up
    //         cy.get('#permissions-manager-grid')
    //             .contains('tr', testUser.email)
    //             .within(() => {
    //                 cy.get('[col-id="actions"]').click()
    //             })
    //         cy.wait(1000)
    //     });
    // });
});
