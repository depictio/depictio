describe('Simple Dashboard Creation', () => {
    let adminUser;
    let dashboardComponents = []; // Track created components

    beforeEach(() => {
        // Clean up any existing test dashboards before each test
        // This ensures a clean state regardless of previous test failures
        cy.cleanupTestDashboards('adminUser', 'Simple Test Dashboard')
    })

    // Define components to create
    const componentsToCreate = [
        {
            type: 'card',
            title: 'TEST Cypress card',
            column: 'sepal.length',
            aggregation: 'average'
        },
        {
            type: 'interactive',
            title: 'TEST Cypress interactive',
            column: 'sepal.length', // Changed to sepal.length which has range 4.3-7.9 to allow 7.0
            component: 'RangeSlider'
        }
        // Add more components here: figure, table, text
    ];

    // Modular utility functions

    /**
     * Set RangeSlider to a specific target value by dragging thumb to mark position
     * @param {Object} component - Component object with id and type
     * @param {number} targetValue - Target value to set (e.g., 7.0)
     * @param {string} thumbType - 'left' or 'right' thumb (default: 'right')
     */
    const setRangeSliderValue = (component, targetValue, thumbType = 'right') => {
        cy.log(`🎛️ Setting ${thumbType} thumb of RangeSlider to ${targetValue}`)

        cy.get(`#box-${component.id}`).within(() => {
            // Find all slider thumbs and identify left/right based on values
            cy.get('.mantine-Slider-thumb').then($thumbs => {
                const thumbs = Array.from($thumbs).map(thumb => ({
                    element: thumb,
                    value: parseFloat(thumb.getAttribute('aria-valuenow') || '0')
                }))

                thumbs.sort((a, b) => a.value - b.value)
                const targetThumb = thumbType === 'left' ? thumbs[0] : thumbs[thumbs.length - 1]

                cy.log(`🎛️ Current ${thumbType} thumb value: ${targetThumb.value}`)
                cy.log(`🎯 Target value: ${targetValue}`)

                // Find the mark wrapper with the target value
                cy.get('.mantine-Slider-markWrapper').then($wrappers => {
                    const targetWrapper = Array.from($wrappers).find(wrapper => {
                        const hasTargetLabel = wrapper.textContent.includes(targetValue.toString())
                        return hasTargetLabel
                    })

                    if (targetWrapper) {
                        cy.log(`📍 Found ${targetValue} mark wrapper`)

                        // Get the position of the target mark and drag the thumb to it
                        const markRect = targetWrapper.getBoundingClientRect()
                        const thumbElement = targetThumb.element

                        cy.log(`📍 ${targetValue} mark position: ${markRect.left}, ${markRect.top}`)
                        cy.log(`📍 Dragging ${thumbType} thumb to ${targetValue} mark position`)

                        // Drag the thumb to the target mark position
                        cy.wrap(thumbElement)
                            .trigger('mousedown', { which: 1, force: true })
                            .wait(200)

                        cy.wrap(thumbElement)
                            .trigger('mousemove', {
                                clientX: markRect.left + markRect.width / 2,
                                clientY: markRect.top + markRect.height / 2,
                                force: true
                            })
                            .wait(200)
                            .trigger('mouseup', { force: true })
                            .wait(1000)

                        // Verify the value was set
                        cy.get('.mantine-Slider-thumb').then($updatedThumbs => {
                            const updatedThumbs = Array.from($updatedThumbs).map(thumb => ({
                                value: parseFloat(thumb.getAttribute('aria-valuenow') || '0')
                            }))
                            updatedThumbs.sort((a, b) => a.value - b.value)

                            const updatedValue = thumbType === 'left' ? updatedThumbs[0].value : updatedThumbs[updatedThumbs.length - 1].value
                            cy.log(`✅ ${thumbType} thumb updated to: ${updatedValue}`)

                            if (Math.abs(updatedValue - targetValue) < 0.1) {
                                cy.log(`✅ Successfully set slider to ~${targetValue}: ${updatedValue}`)
                            } else {
                                cy.log(`⚠️ Slider set to ${updatedValue}, target was ${targetValue}`)
                            }
                        })
                    } else {
                        cy.log(`❌ Could not find mark for value ${targetValue}`)
                    }
                })
            })
        })
    }

    /**
     * Verify card component shows expected value after filter changes
     * @param {Object} component - Card component object with id and type
     * @param {number} expectedValue - Expected numeric value in the card
     * @param {number} tolerance - Allowed tolerance for the comparison (default: 0.1)
     * @param {string} description - Description of what triggered the change
     */
    const verifyCardValue = (component, expectedValue, tolerance = 0.1, description = 'interaction') => {
        cy.log(`🎯 Verifying card component shows expected value after ${description}`)

        cy.get(`#box-${component.id}`).within(() => {
            cy.get('.card-body, .mantine-Card-section, [class*="value"], [class*="metric"]')
                .should('be.visible')
                .then($cardContent => {
                    const cardText = $cardContent.text()
                    cy.log(`📊 Card content after ${description}: ${cardText}`)

                    // Extract the numeric value from the card
                    const numberMatches = cardText.match(/\d+\.\d+/g)
                    if (numberMatches && numberMatches.length > 0) {
                        const cardValue = parseFloat(numberMatches[0])
                        cy.log(`📊 Extracted card value: ${cardValue}`)

                        // Check if the value matches expectation
                        if (Math.abs(cardValue - expectedValue) < tolerance) {
                            cy.log(`✅ Card shows expected value: ${cardValue} (expected ~${expectedValue})`)
                        } else {
                            cy.log(`⚠️ Card value (${cardValue}) differs from expected (${expectedValue}) by ${Math.abs(cardValue - expectedValue).toFixed(4)}`)
                        }

                        // Exact assertion: the card should show the exact expected value
                        expect(cardValue).to.equal(expectedValue)
                    } else {
                        cy.log(`❌ Could not extract numeric value from card: "${cardText}"`)
                        throw new Error(`Could not extract numeric value from card: "${cardText}"`)
                    }
                })
        })
    }

    // Modular utility functions (continued)
    const extractAndTrackComponent = (componentData, inputSelector) => {
        cy.get(inputSelector).then($input => {
            const inputId = $input.attr('id')
            cy.log(`🔍 Extracting from input ID: ${inputId}`)

            // More robust regex to extract 32-character hex UUID
            const matches = inputId.match(/([a-f0-9]{8}[a-f0-9]{4}[a-f0-9]{4}[a-f0-9]{4}[a-f0-9]{12})/i)
            if (!matches) {
                cy.log(`❌ Could not extract UUID from: ${inputId}`)
                return
            }

            const rawId = matches[1].toLowerCase()
            const dashedId = rawId.replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5')

            cy.log(`🆔 Raw ID: ${rawId}`)
            cy.log(`🆔 Dashed ID: ${dashedId}`)
            cy.log(`📦 Box ID will be: box-${dashedId}`)
            cy.log(`🖱️ Drag handle ID will be: dash_drag_handle_${rawId}`)

            const component = {
                ...componentData,
                id: dashedId,
                rawId: rawId
            }
            dashboardComponents.push(component)
            cy.wrap(component).as(`component_${dashboardComponents.length - 1}`)
            cy.wrap(dashboardComponents).as('allComponents')

            cy.log(`✅ Created ${component.type}: ${component.title} (ID: ${component.id})`)
        })
    }

    // Grid-compliant movement and resize functions
    // Based on draggable.py: rowHeight=50px, cols={lg: 12} (12-column grid)
    const moveComponent = (component, gridCols = 2, gridRows = 1) => {
        // Calculate grid-compliant movement: ~266px per column (typical), 50px per row
        const deltaX = gridCols * 266 // Move by grid columns
        const deltaY = gridRows * 50  // Move by grid rows

        cy.log(`📐 Moving component ${gridCols} grid columns (${deltaX}px) and ${gridRows} grid rows (${deltaY}px)`)

        cy.get(`#box-${component.id}`).then($box => {
            const initialPos = $box.position()
            cy.log(`📍 Initial box position: left=${initialPos.left}px, top=${initialPos.top}px`)
        })

        cy.get(`#box-${component.id}`).within(() => {
            cy.get(`#dash_drag_handle_${component.rawId}`)
                .then($handle => {
                    const handlePos = $handle.offset()
                    cy.log(`🖱️ Drag handle position: left=${handlePos.left}px, top=${handlePos.top}px`)

                    const startX = handlePos.left
                    const startY = handlePos.top
                    const endX = startX + deltaX
                    const endY = startY + deltaY

                    cy.log(`🎯 Drag from (${startX}, ${startY}) to (${endX}, ${endY})`)

                    cy.wrap($handle)
                        .trigger('mousedown', { clientX: startX, clientY: startY, which: 1, force: true })
                        .wait(100)
                        .trigger('mousemove', { clientX: endX, clientY: endY, force: true })
                        .wait(100)
                        .trigger('mouseup', { clientX: endX, clientY: endY, force: true })
                })
        })

        cy.wait(500)
        cy.get(`#box-${component.id}`).then($box => {
            const finalPos = $box.position()
            cy.log(`📍 Final box position: left=${finalPos.left}px, top=${finalPos.top}px`)
        })
    }

    const resizeComponent = (component, gridCols = 2, gridRows = 2) => {
        // Calculate grid-compliant resize: expand by specified grid units
        const deltaX = gridCols * 133 // Resize by grid columns (half-column increments)
        const deltaY = gridRows * 50  // Resize by grid rows

        cy.log(`📐 Resizing component +${gridCols} grid columns (${deltaX}px) and +${gridRows} grid rows (${deltaY}px)`)

        cy.get(`#box-${component.id}`).parents('.react-grid-item').then($gridItem => {
            const initialSize = { width: $gridItem.width(), height: $gridItem.height() }
            const initialStyle = $gridItem.attr('style')
            cy.log(`📏 Initial grid item size: ${initialSize.width}x${initialSize.height}px`)
            cy.log(`📏 Initial grid item style: ${initialStyle}`)
        })

        cy.get(`#box-${component.id}`).parents('.react-grid-item').within(() => {
            cy.get('.react-resizable-handle-se')
                .then($handle => {
                    const handlePos = $handle.offset()
                    cy.log(`📏 Resize handle position: left=${handlePos.left}px, top=${handlePos.top}px`)

                    const startX = handlePos.left
                    const startY = handlePos.top
                    const endX = startX + deltaX
                    const endY = startY + deltaY

                    cy.log(`🎯 Resize from (${startX}, ${startY}) to (${endX}, ${endY})`)

                    cy.wrap($handle)
                        .trigger('mousedown', { clientX: startX, clientY: startY, which: 1, force: true })
                        .wait(100)
                        .trigger('mousemove', { clientX: endX, clientY: endY, force: true })
                        .wait(100)
                        .trigger('mouseup', { clientX: endX, clientY: endY, force: true })
                })
        })

        cy.wait(500)
        cy.get(`#box-${component.id}`).parents('.react-grid-item').then($gridItem => {
            const finalSize = { width: $gridItem.width(), height: $gridItem.height() }
            const finalStyle = $gridItem.attr('style')
            cy.log(`📏 Final grid item size: ${finalSize.width}x${finalSize.height}px`)
            cy.log(`📏 Final grid item style: ${finalStyle}`)
        })
    }

    // Component creation functions
    const createCardComponent = (componentData) => {
        cy.get('#add-button').click()
        cy.wait(1000)

        cy.contains('Card').click()
        cy.contains('button', 'Next step').click()
        cy.wait(1000)

        // Log and extract card component IDs
        cy.get('input[id*="dash_card_input"]').then($input => {
            const titleInputId = $input.attr('id')
            cy.log(`🎯 Card Title Input ID: ${titleInputId}`)
        })

        cy.get('input[id^="dash_card_dropdown_column_"]').then($input => {
            const columnInputId = $input.attr('id')
            cy.log(`🎯 Card Column Dropdown ID: ${columnInputId}`)
        })

        cy.get('input[id^="dash_card_dropdown_aggregation_"]').then($input => {
            const aggregationInputId = $input.attr('id')
            cy.log(`🎯 Card Aggregation Dropdown ID: ${aggregationInputId}`)
        })

        // Extract and track component
        extractAndTrackComponent(componentData, 'input[id*="dash_card_input"]')

        // Configure card component
        cy.typeRobust('input[id*="dash_card_input"]', componentData.title)

        cy.get('input[id^="dash_card_dropdown_column_"]').click()
        cy.wait(500)
        cy.get('.mantine-Select-dropdown').first().within(() => {
            cy.contains('.mantine-Select-option', componentData.column).click()
        })
        cy.wait(500)

        cy.get('input[id^="dash_card_dropdown_aggregation_"]').click()
        cy.wait(1000)
        cy.get('.mantine-Select-dropdown').last().within(() => {
            cy.contains('.mantine-Select-option', componentData.aggregation).click()
        })
        cy.wait(500)

        // Complete creation
        cy.contains('button', 'Next step').click()
        cy.wait(1000)
        cy.contains('button', 'Add to dashboard').click()
        cy.wait(2000)
    }

    const createInteractiveComponent = (componentData) => {
        cy.get('#add-button').click()
        cy.wait(1000)

        cy.contains('Interactive').click()
        cy.contains('button', 'Next step').click()
        cy.wait(1000)

        // Log and extract interactive component IDs
        cy.get('input[id*="dash_input_title_"]').then($input => {
            const titleInputId = $input.attr('id')
            cy.log(`🎯 Interactive Title Input ID: ${titleInputId}`)
        })

        cy.get('input[id*="dash_input_dropdown_column_"]').then($input => {
            const columnInputId = $input.attr('id')
            cy.log(`🎯 Interactive Column Dropdown ID: ${columnInputId}`)
        })

        cy.get('input[id*="dash_input_dropdown_method_"]').then($input => {
            const methodInputId = $input.attr('id')
            cy.log(`🎯 Interactive Method Dropdown ID: ${methodInputId}`)
        })

        // Extract and track component using the title input
        extractAndTrackComponent(componentData, 'input[id*="dash_input_title_"]')

        // Configure interactive component
        cy.typeRobust('input[id*="dash_input_title_"]', componentData.title)

        // Select column from dropdown
        cy.get('input[id*="dash_input_dropdown_column_"]').click()
        cy.wait(500)
        cy.get('.mantine-Select-dropdown').first().within(() => {
            cy.contains('.mantine-Select-option', componentData.column).click()
        })
        cy.wait(500)

        // Select interactive component type from dropdown
        cy.get('input[id*="dash_input_dropdown_method_"]').click()
        cy.wait(1000)

        // Target the correct dropdown by finding the one associated with the method input we just clicked
        cy.get('input[id*="dash_input_dropdown_method_"]').then($methodInput => {
            const methodInputId = $methodInput.attr('id')
            cy.log(`🎯 Method input ID: ${methodInputId}`)

            // Find dropdown that's visible and corresponds to the method input
            cy.get('.mantine-Select-dropdown').each(($dropdown, index) => {
                const isVisible = $dropdown.is(':visible') && $dropdown.css('display') !== 'none'
                cy.log(`📋 Dropdown ${index}: visible=${isVisible}`)

                if (isVisible) {
                    cy.wrap($dropdown).within(() => {
                        cy.get('.mantine-Select-option').then($options => {
                            const optionTexts = Array.from($options).map(el => el.textContent.trim())
                            cy.log(`🎯 Dropdown ${index} options:`, optionTexts.join(', '))

                            // Check if this dropdown has interactive component options (not scale options)
                            if (optionTexts.includes('RangeSlider') || optionTexts.some(opt => opt.toLowerCase().includes('slider'))) {
                                cy.log(`✅ Found interactive component dropdown: ${index}`)

                                const targetOption = componentData.component
                                if (optionTexts.includes(targetOption)) {
                                    cy.log(`✅ Found exact match: ${targetOption}`)
                                    cy.contains('.mantine-Select-option', targetOption).click()
                                } else if (optionTexts.some(opt => opt.toLowerCase().includes(targetOption.toLowerCase()))) {
                                    const matchedOption = optionTexts.find(opt => opt.toLowerCase().includes(targetOption.toLowerCase()))
                                    cy.log(`✅ Found partial match: ${matchedOption}`)
                                    cy.contains('.mantine-Select-option', matchedOption).click()
                                } else {
                                    cy.log(`🔄 Selecting first option as fallback: ${optionTexts[0]}`)
                                    cy.get('.mantine-Select-option').first().click()
                                }
                                return false // Break out of each loop
                            } else {
                                cy.log(`⏭️ Skipping dropdown ${index} (scale options, not component options)`)
                            }
                        })
                    })
                }
            })
        })
        cy.wait(500)

        // Complete creation
        cy.contains('button', 'Next step').click()
        cy.wait(1000)
        cy.contains('button', 'Add to dashboard').click()
        cy.wait(2000)
    }

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

    it('creates a simple dashboard', () => {
        // Fast token-based login
        cy.loginWithTokenAsTestUser('adminUser')

        // Navigate to dashboards page
        cy.visit('/dashboards')
        cy.wait(2000)

        cy.url().should('include', '/dashboards')

        // Create a new dashboard
        cy.contains('+ New Dashboard').click()

        // Wait for modal to load
        cy.wait(1000)

        // Input dashboard title with timestamp for uniqueness
        const timestamp = new Date().toISOString().replace(/:/g, '-');
        const uniqueTitle = `Simple Test Dashboard ${timestamp}`;
        cy.typeRobust('input[placeholder="Enter dashboard title"]', uniqueTitle)

        // Select project from dropdown
        cy.get('#dashboard-projects').click()
        cy.contains('Iris Dataset Project Data Analysis (646b0f3c1e4a2d7f8e5b8c9a)').click()

        // Create dashboard
        cy.get('#create-dashboard-submit').click()

        // Wait for creation
        cy.wait(3000)

        // Verify dashboard was created
        cy.get('.mantine-Card-root').should('have.length.greaterThan', 0)

        // Debug: Log the unique title we're looking for
        cy.log(`🔍 Looking for dashboard with title: ${uniqueTitle}`)

        // Check if dashboard exists (may be clipped, so use exists instead of visible)
        cy.contains(uniqueTitle).should('exist')

        // Alternative verification: check if a card with our title exists anywhere
        cy.get('.mantine-Card-root').should('contain.text', 'Simple Test Dashboard')

        // Click on the dashboard thumbnail to enter dashboard view
        // Use force click to handle potential clipping issues
        cy.contains(uniqueTitle)
            .parents('.mantine-Card-root')
            .find('.mantine-Card-section')
            .click({ force: true })

        // Wait for dashboard to load
        cy.wait(3000)

        // Create components based on predefined metadata
        componentsToCreate.forEach((componentData, index) => {
            cy.log(`Creating component ${index + 1}: ${componentData.type} - ${componentData.title}`)

            if (componentData.type === 'card') {
                createCardComponent(componentData)
            } else if (componentData.type === 'interactive') {
                createInteractiveComponent(componentData)
            }
            // Add more component types here as needed:
            // else if (componentData.type === 'figure') {
            //     createFigureComponent(componentData)
            // }
        })


        // Debug: Check current dashboard state before manipulation
        cy.get('.react-grid-item').then($items => {
            cy.log(`🔍 Found ${$items.length} grid items on dashboard`)
            $items.each((index, item) => {
                const $item = Cypress.$(item)
                const style = $item.attr('style')
                cy.log(`🔍 Grid item ${index}: ${style}`)
            })
        })

        // Manipulate all created components using grid-compliant modular functions
        cy.get('@allComponents').then(components => {
            cy.log(`🎯 Total components created: ${components.length}`)

            components.forEach((component, index) => {
                cy.log(`🎯 Manipulating component ${index + 1}: ${component.type} (ID: ${component.id})`)

                // Verify component exists and is visible
                cy.get(`#box-${component.id}`).should('be.visible').then(() => {
                    cy.log(`✅ Component box found and visible: ${component.type}`)
                })

                cy.get(`#dash_drag_handle_${component.rawId}`).should('exist').then($handle => {
                    const isVisible = $handle.is(':visible')
                    cy.log(`🖱️ Drag handle exists, visible: ${isVisible}`)
                })

                // Move components to different grid positions to avoid overlap
                if (index === 0) {
                    // First component: move 3 columns right, same row
                    cy.log(`🔄 Moving first component (${component.type}) 3 columns right`)
                    moveComponent(component, 3, 0)
                } else if (index === 1) {
                    // Second component: move 1 column right, 3 rows down
                    cy.log(`🔄 Moving second component (${component.type}) 1 column right, 3 rows down`)
                    moveComponent(component, 1, 3)
                } else {
                    // Additional components: stagger them
                    cy.log(`🔄 Moving component ${index + 1} (${component.type}) with stagger`)
                    moveComponent(component, 2 + index, 1 + index)
                }
                cy.wait(1000)

                // Resize components to different grid sizes for variety
                if (component.type === 'card') {
                    // Card: make it 3 columns wide, 2 rows tall
                    cy.log(`📏 Resizing card component to 3x2`)
                    resizeComponent(component, 3, 2)
                } else if (component.type === 'interactive') {
                    // Interactive: make it 4 columns wide, 3 rows tall
                    cy.log(`📏 Resizing interactive component to 4x3`)
                    resizeComponent(component, 4, 3)
                } else {
                    // Default: 2 columns wide, 2 rows tall
                    cy.log(`📏 Resizing component to default 2x2`)
                    resizeComponent(component, 2, 2)
                }
                cy.wait(500)
            })
        })

        // Test interactive component functionality: adjust RangeSlider and verify card update
        cy.log('🎛️ Testing RangeSlider interaction and card value update')

        cy.get('@allComponents').then(components => {
            const interactiveComponent = components.find(c => c.type === 'interactive')
            const cardComponent = components.find(c => c.type === 'card')

            if (!interactiveComponent || !cardComponent) {
                cy.log('⚠️ Missing components for interaction test')
                return
            }

            cy.log(`🎯 Found interactive component: ${interactiveComponent.id}`)
            cy.log(`🎯 Found card component: ${cardComponent.id}`)

            // Use the reusable function to set RangeSlider to 7.0
            setRangeSliderValue(interactiveComponent, 7.0, 'right')

            // Wait for the dashboard to update based on the slider change
            cy.wait(2000)

            // Use the reusable function to verify the card value changed to 5.7014
            verifyCardValue(cardComponent, 5.7014, 0.1, 'RangeSlider interaction')

            cy.log('🎉 Interactive component test completed')
        })
    });
});
