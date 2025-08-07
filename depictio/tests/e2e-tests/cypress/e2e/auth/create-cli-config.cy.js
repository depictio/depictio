describe('Create CLI Config Test', () => {
  let testUser;
  let configName; // Variable to store the dynamic config name

  before(() => {
    // Skip this test suite if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.log('Skipping CLI config test - running in unauthenticated mode')
      return
    }

    cy.fixture('test-credentials.json').then((credentials) => {
      testUser = credentials.testUser;
    });
  });

  beforeEach(() => {
    // Skip if in unauthenticated mode
    if (Cypress.env('UNAUTHENTICATED_MODE')) {
      cy.skip()
    }
  })

  it('creates a new CLI configuration', () => {
    // Fast token-based login
    cy.loginWithTokenAsTestUser('testUser')

    // Navigate to dashboard
    cy.wait(1000)

    // Check if we're redirected off auth page (more flexible)
    cy.url().should('not.include', '/auth')

    // If not on dashboards yet, navigate there explicitly
    cy.url().then((url) => {
      if (!url.includes('/dashboards')) {
        cy.visit('/dashboards')
        cy.wait(2000)
      }
    })

    // Final verification we're on dashboards
    cy.url().should('include', '/dashboards')

    // Go to profile page
    cy.visit('/profile')

    // Click on CLI-Agents button
    cy.contains('button', 'CLI Agents').click()

    // Wait for the page to load
    cy.url().should('include', '/cli_configs')

    // Click on Add New Configuration button
    cy.contains('button', 'Add New Configuration').click()

    // Generate config name with timestamp and store it
    // Use a simpler format to avoid typing issues
    const timestamp = Date.now();
    configName = `Test_CLI_Config_${timestamp}`;
    cy.log(`Creating config with name: ${configName}`);

    // Fill in CLI config fields with the stored name using robust typing
    cy.typeRobust('[placeholder="Enter a name for your CLI configuration"]', configName)

    // Save the configuration
    cy.contains('button', 'Save').click()

    // Check if present in the list
    cy.get('#config-created-success').should('be.visible')

    // Retrieve content of agent-config-md
    cy.get('#agent-config-md')
      .first()
      .invoke('text')
      .then((text) => {
        cy.log(`Agent Config MD Content: ${text}`)
        expect(text).to.contain('base_url')
      })

    // Close the modal
    cy.get('.mantine-Modal-close').click();

    // Wait for modal to close and list to refresh
    cy.wait(2000);

    // Check if the new configuration is present in the list using the exact name
    // Try multiple selectors in case the structure changed
    cy.get('body').then(($body) => {
      if ($body.text().includes(configName)) {
        cy.log(`Found config name in page: ${configName}`);
      } else {
        cy.log(`Config name not found in page: ${configName}`);
        // If not found, try reloading the page
        cy.reload();
        cy.wait(2000);
      }
    });

    // Now check for the config
    cy.contains(configName).should('exist');

    // Find the specific Paper container that contains our config name
    cy.contains('.mantine-Text-root', configName)
      .closest('.mantine-Paper-root')  // Go up to the Paper container
      .within(() => {
        // Find the Delete button within this container
        cy.contains('button', 'Delete').click();
      });

    // Handle the confirmation dialog
    // Wait for the confirmation dialog to appear
    cy.contains('Confirm Deletion').should('be.visible');

    // Type "delete" in the confirmation field using robust typing
    cy.wait(1000); // Wait for dialog to fully render
    cy.typeRobust('.mantine-Modal-content input, .mantine-TextInput-input, input[type="text"]', 'delete')

    // Click the "Confirm Delete" button
    cy.contains('button', 'Confirm Delete').click();

    // Verify the configuration was deleted using the exact name
    cy.contains('.mantine-Text-root', configName).should('not.exist');
  })
})
