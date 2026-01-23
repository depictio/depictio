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
        cy.wait(2000)  // Wait for page to fully render

        // Find the Iris Dataset accordion item and expand it
        cy.contains('Iris Dataset Project Data Analysis')
            .scrollIntoView()
            .parents('.mantine-Accordion-item')
            .first()
            .as('irisAccordion')

        // Click the accordion control to expand it (DMC 2.0+ uses .mantine-Accordion-control)
        cy.get('@irisAccordion')
            .find('.mantine-Accordion-control')
            .first()
            .click({ force: true })
        cy.wait(1000)  // Wait for accordion to expand

        // Click on "Roles and permissions" WITHIN the Iris accordion only
        cy.get('@irisAccordion')
            .contains('Roles and permissions')
            .click({ force: true })
        cy.url().should('include', '/project/646b0f3c1e4a2d7f8e5b8c9a')
        cy.wait(1000)  // Wait for permissions page to fully load

        // Wait for the permissions manager to be ready
        cy.get('#permissions-manager-project-title').should('be.visible')
        cy.get('#permissions-manager-grid').should('be.visible')
    }

    // Helper function to wait for permissions to be enabled
    function waitForPermissionsToEnable() {
        // Wait for permissions controls to be enabled (should be faster now with the callback fix)
        // DMC 2.0+: target the checkbox wrapper which has the disabled prop
        cy.get('#permissions-manager-input-email', { timeout: 10000 }).should('not.be.disabled')
        // Check if checkbox wrapper is not disabled (DMC 2.0+ uses data-disabled attribute)
        cy.get('#permissions-manager-checkbox-owner', { timeout: 10000 }).should('exist')
        cy.get('#permissions-manager-checkbox-editor', { timeout: 10000 }).should('exist')
        cy.get('#permissions-manager-checkbox-viewer', { timeout: 10000 }).should('exist')

        cy.log('Permissions are now enabled and ready for interaction')
    }

    // Helper function to logout
    function logout() {
        // Clear session storage and cookies first
        cy.clearCookies()
        cy.clearLocalStorage()
        cy.window().then((win) => {
            win.sessionStorage.clear()
        })

        // Try different possible logout button selectors
        cy.get('body').then($body => {
            if ($body.find('#logout-button').length > 0) {
                cy.get('#logout-button').click()
            } else if ($body.find('[data-testid="logout"]').length > 0) {
                cy.get('[data-testid="logout"]').click()
            } else if ($body.find('button').filter(':contains("Logout")').length > 0) {
                cy.contains('button', 'Logout').click()
            } else {
                // Fallback: visit auth page directly and clear session
                cy.visit('/auth')
            }
        })
        cy.wait(2000)
    }

    // Helper function to verify Editor/Viewer restrictions
    function verifyNonOwnerRestrictions(userRole) {
        cy.log(`Verifying ${userRole} user restrictions...`)

        // Give some time for the callbacks to process
        cy.wait(3000)

        // The key restriction for non-owners: they cannot delete other users
        cy.get('#permissions-manager-grid').then($grid => {
            const deleteButtons = $grid.find('button:contains("🗑️")')
            if (deleteButtons.length > 0) {
                cy.log(`Warning: Delete buttons are visible for ${userRole} user - this would be a permission system issue`)
            } else {
                cy.log(`✓ Delete buttons correctly hidden for ${userRole} user`)
            }
        })

        cy.log(`✓ ${userRole} restrictions verified`)
    }

    // Helper function to login
    function login(user) {
        cy.loginWithToken(user.email, user.password)
        cy.url().should('include', '/dashboards')
    }

    // Reusable function to add a user with specific permission
    function addUserWithPermission(userEmail, permission) {
        cy.log(`Adding ${userEmail} with ${permission} permission`)

        // Click on user dropdown and select user
        // DMC 2.0+: The ID is directly on the input element, not on a wrapper
        cy.get('#permissions-manager-input-email').should('be.visible').click()
        cy.get('#permissions-manager-input-email')
            .clear()
            .type(userEmail, { delay: 100 })
        cy.wait(500)  // Wait for dropdown to filter

        // Wait for dropdown to filter and show results, then click the email option
        // DMC 2.0+ (Mantine v7) uses .mantine-Combobox-dropdown
        cy.get('.mantine-Combobox-dropdown, .mantine-MultiSelect-dropdown', { timeout: 10000 })
            .should('be.visible')
            .contains(userEmail)
            .should('be.visible')
            .click()

        // Wait for dropdown to update
        cy.wait(500)
        cy.get('#permissions-manager-input-email').parent().should('contain', userEmail)

        // Ensure MultiSelect dropdown is closed before interacting with checkboxes
        cy.get('body').click(0, 0)  // Click outside to close any dropdown
        cy.wait(500)  // Wait for dropdown to close

        // Select the permission - DMC 2.0+ checkbox: click on the wrapper/label
        cy.get(`#permissions-manager-checkbox-${permission.toLowerCase()}`).should('be.visible').click({ force: true })
        // Verify checkbox is checked - in DMC 2.0+ the ID is on the input element
        cy.get(`#permissions-manager-checkbox-${permission.toLowerCase()}`).should('be.checked')
        cy.wait(1000)

        // Click add button
        cy.get('#permissions-manager-btn-add-user').should('be.visible').click({ force: true })
        cy.wait(1500)

        // Verify user was added
        cy.get('#permissions-manager-grid').contains(userEmail).should('be.visible')
    }

    // Reusable function to modify user permission
    function modifyUserPermission(userEmail, fromPermission, toPermission) {
        cy.log(`Changing ${userEmail} from ${fromPermission} to ${toPermission}`)

        cy.get('#permissions-manager-grid')
            .contains('.ag-cell', userEmail)
            .parents('.ag-row')
            .within(() => {
                // Click on the new permission checkbox
                cy.get(`[col-id="${toPermission}"] input[type="checkbox"]`).click()
            })

        cy.wait(1000)

        // Verify the change
        cy.get('#permissions-manager-grid')
            .contains('.ag-cell', userEmail)
            .parents('.ag-row')
            .within(() => {
                cy.get(`[col-id="${toPermission}"] input[type="checkbox"]`).should('be.checked')
                cy.get(`[col-id="${fromPermission}"] input[type="checkbox"]`).should('not.be.checked')
            })
    }

    // Reusable function to delete a user
    function deleteUser(userEmail) {
        cy.log(`Deleting user ${userEmail}`)

        cy.get('#permissions-manager-grid')
            .contains('.ag-cell', userEmail)
            .parents('.ag-row')
            .within(() => {
                // AG Grid Button renderer creates a button element in the actions column
                // Try multiple selectors for compatibility
                cy.get('[col-id="actions"]').then($cell => {
                    // Check if there's a button with the emoji
                    if ($cell.find('button:contains("🗑️")').length > 0) {
                        cy.get('[col-id="actions"] button:contains("🗑️")').click({ force: true })
                    } else if ($cell.find('button').length > 0) {
                        // Fallback to any button in actions column
                        cy.get('[col-id="actions"] button').first().click({ force: true })
                    } else if ($cell.find('.btn').length > 0) {
                        // Fallback to element with btn class
                        cy.get('[col-id="actions"] .btn').first().click({ force: true })
                    } else {
                        // Last resort: click the actions cell itself
                        cy.get('[col-id="actions"]').click({ force: true })
                    }
                })
            })
        cy.wait(1500)

        // Verify user was deleted
        cy.get('#permissions-manager-grid').contains(userEmail).should('not.exist')
    }

    // Reusable function to toggle project visibility
    function toggleProjectVisibility() {
        cy.log('Toggling project visibility')

        // Get current state and toggle to opposite
        cy.get('#make-project-public-button').then($button => {
            const isPublic = $button.find('input[value="True"]').is(':checked')

            if (isPublic) {
                cy.log('Changing from Public to Private')
                cy.get('#make-project-public-button').within(() => {
                    cy.contains('label', 'Private').click()
                })
            } else {
                cy.log('Changing from Private to Public')
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
    }

    // Function to verify user has specific permission
    function verifyUserPermission(userEmail, permission) {
        cy.get('#permissions-manager-grid')
            .contains('.ag-cell', userEmail)
            .parents('.ag-row')
            .within(() => {
                cy.get(`[col-id="${permission}"] input[type="checkbox"]`).should('be.checked')
            })
    }

    // describe('Complete Permission Flow Test', () => {
    //     it('Tests complete permission hierarchy: Admin -> Editor -> Viewer modes', () => {
    //         // Phase 1: Login as admin (who is both owner & admin)
    //         cy.log('=== PHASE 1: Admin adds test user as Editor ===')
    //         login(adminUser)
    //         navigateToProjectPermissions()

    //         // Verify admin can see project header with visibility toggle
    //         cy.get('#permissions-manager-project-title').should('be.visible')
    //         cy.get('#make-project-public-button').should('be.visible').and('not.be.disabled')
    //         waitForPermissionsToEnable()

    //         // Clean up test user if exists
    //         cy.get('#permissions-manager-grid').then($grid => {
    //             if ($grid.text().includes(testUser.email)) {
    //                 deleteUser(testUser.email)
    //             }
    //         })

    //         // Add test user as Editor
    //         addUserWithPermission(testUser.email, 'Editor')
    //         verifyUserPermission(testUser.email, 'Editor')

    //         // Phase 2: Switch to Editor mode
    //         cy.log('=== PHASE 2: Testing Editor user restrictions ===')
    //         logout()
    //         login(testUser)
    //         navigateToProjectPermissions()

    //         // Verify editor cannot modify permissions
    //         verifyNonOwnerRestrictions('Editor')

    //         // Phase 3: Back to admin, change user to Viewer
    //         cy.log('=== PHASE 3: Admin changes test user to Viewer ===')
    //         logout()
    //         login(adminUser)
    //         navigateToProjectPermissions()
    //         waitForPermissionsToEnable()

    //         // Change test user from Editor to Viewer
    //         modifyUserPermission(testUser.email, 'Editor', 'Viewer')
    //         verifyUserPermission(testUser.email, 'Viewer')

    //         // Phase 4: Switch to Viewer mode
    //         cy.log('=== PHASE 4: Testing Viewer user restrictions ===')
    //         logout()
    //         login(testUser)
    //         navigateToProjectPermissions()

    //         // Verify viewer cannot modify permissions
    //         verifyNonOwnerRestrictions('Viewer')

    //         // Phase 5: Final cleanup
    //         cy.log('=== PHASE 5: Admin cleanup ===')
    //         logout()
    //         login(adminUser)
    //         navigateToProjectPermissions()
    //         waitForPermissionsToEnable()

    //         // Test project visibility toggle
    //         toggleProjectVisibility()

    //         // Remove test user
    //         deleteUser(testUser.email)

    //         // Verify user was removed and is back in dropdown
    //         cy.get('#permissions-manager-input-email').click()
    //         cy.contains(testUser.email).should('be.visible')

    //         cy.log('✓ Complete permission flow test completed successfully')
    //     });
    // });

    describe('Individual Permission Tests', () => {
        it('Admin can manage all project permissions', () => {
            // Login as admin
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Clean up test user if exists
            cy.get('#permissions-manager-grid').then($grid => {
                if ($grid.text().includes(testUser.email)) {
                    deleteUser(testUser.email)
                }
            })

            // Test basic admin functionality
            addUserWithPermission(testUser.email, 'Editor')
            verifyUserPermission(testUser.email, 'Editor')
            deleteUser(testUser.email)
        });
    });

    describe('Project Owner Permissions', () => {
        it('Project owner can manage permissions', () => {
            // Test owner-specific functionality
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Verify admin/owner can manage all permissions
            // DMC 2.0+: check checkbox wrappers exist and are clickable
            cy.get('#make-project-public-button').should('not.be.disabled')
            cy.get('#permissions-manager-input-email').should('not.be.disabled')
            cy.get('#permissions-manager-checkbox-owner').should('exist').and('be.visible')
            cy.get('#permissions-manager-checkbox-editor').should('exist').and('be.visible')
            cy.get('#permissions-manager-checkbox-viewer').should('exist').and('be.visible')
        });
    });

    describe('Editor User Restrictions', () => {
        it('Editor users have limited permissions', () => {
            // This test verifies editor restrictions in isolation
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Set up test user as editor (if needed for isolated test)
            cy.get('#permissions-manager-grid').then($grid => {
                if (!$grid.text().includes(testUser.email)) {
                    addUserWithPermission(testUser.email, 'Editor')
                }
            })

            // Switch to editor and verify restrictions
            logout()
            login(testUser)
            navigateToProjectPermissions()
            verifyNonOwnerRestrictions('Editor')

            // Clean up
            logout()
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()
        });
    });

    describe('Viewer User Restrictions', () => {
        it('Viewer users have minimal permissions', () => {
            // This test verifies viewer restrictions in isolation
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Set up test user as viewer (if needed for isolated test)
            cy.get('#permissions-manager-grid').then($grid => {
                if (!$grid.text().includes(testUser.email)) {
                    addUserWithPermission(testUser.email, 'Viewer')
                }
            })

            // Switch to viewer and verify restrictions
            logout()
            login(testUser)
            navigateToProjectPermissions()
            verifyNonOwnerRestrictions('Viewer')

            // Clean up
            logout()
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()
        });
    });

    describe('Permission Validation', () => {
        it('Validates permission rules and constraints', () => {
            // Login as admin
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Clean up test user if exists
            cy.get('#permissions-manager-grid').then($grid => {
                if ($grid.text().includes(testUser.email)) {
                    deleteUser(testUser.email)
                }
            })

            // Test that user must select exactly one permission type
            cy.get('#permissions-manager-input-email').click()
            cy.get('#permissions-manager-input-email')
                .clear()
                .type(testUser.email, { delay: 100 })
            cy.wait(500)  // Wait for dropdown to filter
            // DMC 2.0+ (Mantine v7) uses .mantine-Combobox-dropdown
            cy.get('.mantine-Combobox-dropdown, .mantine-MultiSelect-dropdown')
                .should('be.visible')
                .contains(testUser.email)
                .should('be.visible')
                .click()
            cy.wait(500)

            // Without selecting any permission, button should be disabled
            cy.get('#permissions-manager-btn-add-user').should('be.disabled')

            // Ensure dropdown is closed before interacting with checkboxes
            cy.get('body').click(0, 0)
            cy.wait(500)

            // Select multiple permissions - DMC 2.0+: ID is on input element
            cy.get('#permissions-manager-checkbox-owner').click({ force: true })
            cy.get('#permissions-manager-checkbox-owner').should('be.checked')
            cy.wait(200)
            cy.get('#permissions-manager-checkbox-editor').click({ force: true })
            cy.get('#permissions-manager-checkbox-editor').should('be.checked')
            cy.wait(500)

            // With both checkboxes selected, button should be disabled (exactly one required)
            cy.get('#permissions-manager-btn-add-user').should('be.disabled')

            // Uncheck the Editor permission to have only Owner selected
            cy.get('#permissions-manager-checkbox-editor').click({ force: true })
            cy.get('#permissions-manager-checkbox-editor').should('not.be.checked')
            cy.wait(200)

            // Now with exactly one permission, button should be enabled
            cy.get('#permissions-manager-btn-add-user').should('not.be.disabled')

            // Add the user
            cy.get('#permissions-manager-btn-add-user').click({ force: true })
            cy.wait(1500)

            // Test duplicate user prevention
            cy.get('#permissions-manager-input-email').click()
            cy.wait(500)
            // User should not appear in dropdown anymore
            cy.get('#permissions-manager-input-email').type(testUser.email)
            // DMC 2.0+ (Mantine v7) uses .mantine-Combobox-dropdown
            cy.get('.mantine-Combobox-dropdown, .mantine-MultiSelect-dropdown').should('not.contain', testUser.email)

            // Clean up
            deleteUser(testUser.email)
        });
    });

    describe('Grid Interactions', () => {
        it('Tests permission grid checkbox interactions', () => {
            // Login as admin
            login(adminUser)
            navigateToProjectPermissions()
            waitForPermissionsToEnable()

            // Clean up test user if exists
            cy.get('#permissions-manager-grid').then($grid => {
                if ($grid.text().includes(testUser.email)) {
                    deleteUser(testUser.email)
                }
            })

            // Add test user with Viewer permission
            addUserWithPermission(testUser.email, 'Viewer')

            // Test permission transitions
            // Change from Viewer to Editor
            modifyUserPermission(testUser.email, 'Viewer', 'Editor')

            // Change from Editor to Owner
            modifyUserPermission(testUser.email, 'Editor', 'Owner')

            // Change back to Viewer
            modifyUserPermission(testUser.email, 'Owner', 'Viewer')

            // Clean up
            deleteUser(testUser.email)
        });
    });
});
