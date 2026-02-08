// describe('Create and manage multiple dashboards', () => {
//     let adminUser;
//     let dashboardIds = []; // Array to store the extracted dashboard IDs

//     before(() => {
//         cy.fixture('test-credentials.json').then((credentials) => {
//             adminUser = credentials.adminUser;
//         });
//     });

//     it('logs in and creates two dashboards', () => {
//         // Login to the application
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

//         // Wait for the dashboard to load
//         cy.wait(2000)

//         // Create first dashboard
//         cy.log('Creating first dashboard')
//         const firstDashboardTitle = createDashboard("First Dashboard")

//         // Wait for the dashboard list to reload after first creation
//         cy.wait(2000)

//         // Reload the page completely to reset any state
//         cy.log('Reloading page before creating second dashboard')
//         cy.reload()
//         cy.wait(3000) // Wait for page to fully load

//         // Create second dashboard after page reload
//         cy.log('Creating second dashboard')
//         const secondDashboardTitle = createDashboard("Second Dashboard")

//         // Verify both dashboards exist
//         cy.wait(2000)
//         cy.get('.mantine-Card-root').should('have.length.at.least', 2)

//         // Clean up - delete the created dashboards
//         cy.log('Cleaning up dashboards')
//         cy.log('Dashboard IDs:', dashboardIds)

//         // Delete the first dashboard
//         cy.log('Deleting first dashboard')
//         if (dashboardIds.length > 1) {
//             deleteAndVerify(dashboardIds[0].title, dashboardIds[0].id)
//         }

//         // Delete the second dashboard
//         cy.log('Deleting second dashboard')
//         if (dashboardIds.length > 1) {
//             deleteAndVerify(dashboardIds[1].title, dashboardIds[1].id)
//         }

//     });

//     function createDashboard(prefix) {
//         // Click on New Dashboard button using its ID (similar to how we handle other IDs)
//         cy.get('[id=\'{"index":"admin@example.com","type":"create-dashboard-button"}\']')
//             .should('exist')
//             .should('be.visible')
//             .click({ force: true })

//         // Wait for modal to appear - using title selector
//         cy.log('Waiting for dashboard creation modal to appear')
//         // cy.contains('h2', 'Create New Dashboard').should('be.visible')
//         cy.wait(1000)

//         // Generate a unique title with timestamp
//         const uniqueTitle = `${prefix} ${new Date().toISOString().replace(/:/g, '-')}`;

//         // Input the dashboard title
//         cy.log('Typing dashboard title')
//         cy.get('input[type="text"][placeholder="Enter dashboard title"]')
//             .should('exist')
//             .should('be.visible')
//             .clear()
//             .type(uniqueTitle, { force: true })

//         // Handle the project dropdown with a more robust approach
//         cy.log('Selecting project from dropdown')
//         // Click directly on the select input to open the dropdown
//         cy.get('#dashboard-projects').should('exist').click({ force: true })

//         // Wait for dropdown options to appear
//         cy.wait(1000)

//         // Log the dropdown content to see what's available
//         cy.get('body').then($body => {
//             cy.log('Looking for dropdown options')
//             cy.log(`Dropdown elements found: ${$body.find('.mantine-Select-dropdown .mantine-Select-item').length}`)

//             // Try to take a screenshot to see what's happening
//             cy.screenshot(`dropdown-selection-${prefix.replace(/\s+/g, '-')}`)

//             // Check if the dropdown list is in the body
//             if ($body.find('.mantine-Select-dropdown .mantine-Select-item').length) {
//                 cy.log('Found dropdown options using mantine-Select-item')
//                 cy.get('.mantine-Select-dropdown .mantine-Select-item')
//                     .contains('Iris Dataset Project Data Analysis')
//                     .click({ force: true })
//             } else {
//                 // Alternative approach if the above selector doesn't work
//                 cy.log('Trying alternative dropdown selection method')

//                 // Try several alternative selectors
//                 const selectors = [
//                     '[role="listbox"] [role="option"]',
//                     '.mantine-Select-item',
//                     '[class*="mantine-Select-item"]',
//                     '[class*="Select-item"]',
//                     'li[role="option"]'
//                 ]

//                 // Try each selector
//                 for (const selector of selectors) {
//                     cy.log(`Trying selector: ${selector}`)
//                     cy.get('body').then($body => {
//                         if ($body.find(selector).length) {
//                             cy.log(`Found elements with selector: ${selector}`)
//                             cy.get(selector).contains('Iris Dataset Project Data Analysis').click({ force: true })
//                             return false // Break the loop if we found and clicked an element
//                         }
//                     })
//                 }

//                 // If all else fails, try clicking at coordinates where the dropdown should be
//                 cy.log('Last resort: clicking by position')
//                 // First, get the position of the dropdown trigger
//                 cy.get('#dashboard-projects').then($el => {
//                     const rect = $el[0].getBoundingClientRect()
//                     // Click 30px below the dropdown to hit the first option
//                     cy.get('body').click(rect.left + rect.width / 2, rect.bottom + 30, { force: true })
//                 })
//             }
//         })

//         // Click on Create Dashboard button
//         cy.log('Clicking Create Dashboard button')
//         cy.get('#create-dashboard-submit').should('exist').click({ force: true })

//         // Wait for the dashboard to be created and navigation to occur
//         cy.wait(3000)

//         // We should be redirected to the dashboards list after creation
//         cy.url().should('include', '/dashboards')
//         cy.log('Checking if dashboard was created')

//         // Wait for the dashboard list to load
//         cy.wait(2000)

//         // Find the newly created dashboard by its unique title
//         cy.contains('h5.mantine-Title-root', uniqueTitle).should('be.visible');
//         cy.log('Dashboard found in list')

//         // Find a dashboard button and extract the ID
//         cy.contains('h5.mantine-Title-root', uniqueTitle)
//             .parents('.mantine-Card-root')
//             .find('[id*="edit-dashboard-button"]')
//             .invoke('attr', 'id')
//             .then((idAttr) => {
//                 // Parse the JSON-like ID attribute
//                 try {
//                     const idObj = JSON.parse(idAttr.replace(/&quot;/g, '"'));
//                     const dashboardId = idObj.index;

//                     console.log(`Extracted dashboard ID: ${dashboardId}`);

//                     // Store the dashboard info for later cleanup
//                     dashboardIds.push({
//                         id: dashboardId,
//                         title: uniqueTitle
//                     });

//                 } catch (e) {
//                     console.error("Error parsing dashboard ID:", e);
//                     cy.log("Error parsing dashboard ID:", idAttr);
//                 }
//             });
//     }

//     function deleteAndVerify(title, id) {
//         // Make sure we're on the dashboards page
//         cy.log(`Deleting dashboard: "${title}"`)
//         cy.url().should('include', '/dashboards')

//         // Find the dashboard by its title
//         cy.contains('h5.mantine-Title-root', title)
//             .parents('.mantine-Card-root')
//             .within(() => {
//                 // First try to expand dashboard actions
//                 cy.log('Expanding Dashboard Actions')
//                 // Try to click on Dashboard Actions - it might be in different elements
//                 cy.contains('Dashboard Actions').click({ force: true })

//                 // Wait for expansion
//                 cy.wait(500)

//                 // Click on Delete button
//                 cy.log('Clicking Delete button')
//                 cy.contains('button', 'Delete').click({ force: true });
//             })

//         // Wait for confirmation modal
//         cy.wait(1000)

//         // We need to look for the modal in the entire document
//         // Look for a button with the ID containing the dashboardId and 'delete' keyword
//         // First, check if there is any button with our dashboard ID
//         cy.get(`[id*='${id}']`).then($buttons => {
//             cy.log(`Found ${$buttons.length} buttons with dashboard ID ${id}`);

//             // Log all button IDs for debugging
//             $buttons.each((index, button) => {
//                 cy.log(`Button ${index} ID: ${button.id}`);
//             });
//         });

//         // Now, click the button with the specific ID
//         cy.get(`[id='{\"index\":\"${id}\",\"type\":\"confirm-dashboard-delete-button\"}']`).click({ force: true });


//         // Wait for deletion to complete
//         cy.wait(1000);

//         // Verify the dashboard with the unique title no longer exists
//         cy.contains('h5.mantine-Title-root', title).should('not.exist');
//     }
// });
