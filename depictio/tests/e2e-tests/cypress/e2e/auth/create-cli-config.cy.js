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
    // Navigate to the auth page
    cy.visit('/auth')

    // Check if we're on the auth page
    cy.url().should('include', '/auth')

    // Check if the login form is present
    cy.get('#auth-modal').should('be.visible')

    // Log in with valid credentials
    cy.get('input[type="text"][placeholder="Enter your email"]')
      .filter(':visible')
      .type(testUser.email)

    cy.get('input[type="password"][placeholder="Enter your password"]')
      .filter(':visible')
      .type(testUser.password)

    cy.contains('button', 'Login').click()

    // Check if the login was successful
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
    configName = 'Test_CLI_Config_' + new Date().toISOString();

    // Fill in CLI config fields with the stored name
    cy.get('[placeholder="Enter a name for your CLI configuration"]')
      .type(configName)

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

    // Check if the new configuration is present in the list using the exact name
    cy.contains('.mantine-Text-root', configName).should('exist');

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

    // Type "delete" in the confirmation field
    cy.get('input').type('delete');

    // Click the "Confirm Delete" button
    cy.contains('button', 'Confirm Delete').click();

    // Verify the configuration was deleted using the exact name
    cy.contains('.mantine-Text-root', configName).should('not.exist');
  })
})
