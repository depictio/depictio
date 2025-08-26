// MultiQC Core utilities and iframe access functions
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    multiqc: {
        // Core function to get iframe access with CORS handling
        getIframeAccess: function() {
            const iframe = document.querySelector('#multiqc-iframe');
            if (!iframe || !iframe.contentWindow) {
                return { 
                    success: false, 
                    error: '❌ Error: Cannot access iframe - check if MultiQC content is loaded.' 
                };
            }
            
            try {
                const iframeDoc = iframe.contentWindow.document;
                if (!iframeDoc) {
                    return {
                        success: false,
                        error: '❌ CORS BLOCKED: Cannot access iframe.contentWindow.document'
                    };
                }
                
                const originStatus = `✅ SAME-ORIGIN ACCESS CONFIRMED!\n` +
                                   `✅ iframe.contentWindow.document accessible\n` +
                                   `✅ No CORS restrictions detected\n\n`;
                
                return {
                    success: true,
                    iframe: iframe,
                    doc: iframeDoc,
                    status: originStatus
                };
            } catch (error) {
                return {
                    success: false,
                    error: `❌ CORS Error: ${error.message}`
                };
            }
        },

        // Utility to get callback context information
        getCallbackContext: function() {
            const ctx = window.dash_clientside.callback_context;
            if (!ctx.triggered.length) {
                return {
                    hasContext: false,
                    message: '🚀 MultiQC toolbox automation ready. Select samples to trigger automation.'
                };
            }
            
            const triggered = ctx.triggered[0]['prop_id'];
            const triggered_id = triggered.split('.')[0];
            const triggered_prop = triggered.split('.')[1];
            
            return {
                hasContext: true,
                triggered: triggered,
                triggered_id: triggered_id,
                triggered_prop: triggered_prop
            };
        },

        // Common MultiQC selectors (with correct working selectors)
        selectors: {
            // Highlight samples selectors
            customPatternInput: '#mqc_colour_filter',
            colorPicker: '#mqc_colour_filter_color',
            applyButton: '#mqc_cols_apply',
            plusButton: '#mqc_colour_filter_update',
            colorForm: '#mqc_color_form',
            highlightFilterList: '#mqc_col_filters',
            
            // Show/Hide samples selectors (CORRECTED from real HTML)
            hidePatternInput: '#mqc_hidesamples_filter',
            hideApplyButton: '#mqc_hide_apply', 
            hidePlusButton: '#mqc_hidesamples_filter_update',
            hideFilterList: '#mqc_hidesamples_filters',
            hideForm: '#mqc_hidesamples_form',
            
            // General
            toolboxContainer: '#mqc_cols, .mqc_filter_section, .mqc-toolbox-label'
        },

        // TEMPORARY: Add all functions directly here to test loading
        testSampleInput: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const input = iframeDoc.querySelector(this.selectors.customPatternInput);
            
            if (input) {
                input.value = '';
                input.value = '00050101';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('keyup', { bubbles: true }));
                
                return access.status + 
                       `✅ SUCCESS: Sample ID set in MultiQC Custom Pattern input!\n` +
                       `   - Element: INPUT#${input.id}\n` +
                       `   - Placeholder: "${input.placeholder}"\n` +
                       `   - Current value: "${input.value}"\n` +
                       `   - Input/change/keyup events dispatched successfully`;
            } else {
                return access.status + 
                       '❌ FAILED: Could not find #mqc_colour_filter input';
            }
        },

        clickPlusButton: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const plusButton = iframeDoc.querySelector(this.selectors.plusButton);
            
            if (plusButton) {
                plusButton.disabled = false;
                plusButton.click();
                return '✅ Plus button clicked! Samples should now be highlighted.';
            } else {
                return '❌ Plus button (#mqc_colour_filter_update) not found';
            }
        },

        clickApplyButton: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const applyButton = iframeDoc.querySelector(this.selectors.applyButton);
            
            if (applyButton) {
                // Force enable if needed
                applyButton.disabled = false;
                applyButton.classList.remove('btn-default');
                applyButton.classList.add('btn-primary');
                applyButton.click();
                return '✅ Apply button clicked! Changes applied to MultiQC charts.';
            } else {
                return '❌ Apply button (#mqc_cols_apply) not found';
            }
        },

        simulateEnterKey: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const input = iframeDoc.querySelector(this.selectors.customPatternInput);
            
            if (input) {
                input.focus();
                
                const enterEvent = new KeyboardEvent('keydown', {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true
                });
                input.dispatchEvent(enterEvent);
                
                const enterUpEvent = new KeyboardEvent('keyup', {
                    key: 'Enter',
                    code: 'Enter', 
                    keyCode: 13,
                    which: 13,
                    bubbles: true
                });
                input.dispatchEvent(enterUpEvent);
                
                const form = iframeDoc.querySelector(this.selectors.colorForm);
                if (form) {
                    form.dispatchEvent(new Event('submit', { bubbles: true }));
                }
                
                return access.status +
                       `✅ SUCCESS: Enter key + form submit attempted!\n` +
                       `   - Input: ${this.selectors.customPatternInput}\n` +
                       `   - Input value: "${input.value}"\n` +
                       `   - KeyDown + KeyUp events sent\n` +
                       `   - Form submit event sent: ${form ? 'Yes' : 'No'}`;
            } else {
                return access.status + 
                       '❌ FAILED: Could not find input for Enter key simulation';
            }
        },

        // === AUTOMATION FUNCTIONS ===
        
        // Clear all existing highlight filters in MultiQC
        clearHighlightFilters: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            
            // Find all existing filter entries and click their X buttons
            const filterList = iframeDoc.querySelector('#mqc_col_filters');
            if (filterList) {
                const closeButtons = filterList.querySelectorAll('button.close');
                let removedCount = 0;
                
                closeButtons.forEach(button => {
                    button.click();
                    removedCount++;
                });
                
                // Also clear the main input
                const input = iframeDoc.querySelector(this.selectors.customPatternInput);
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
                
                return { 
                    success: true, 
                    message: `✅ Cleared ${removedCount} existing highlight filters`
                };
            } else {
                return { 
                    success: true, 
                    message: '✅ No existing filters to clear' 
                };
            }
        },
        
        // Set pattern in MultiQC input
        setPattern: function(pattern) {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            const input = iframeDoc.querySelector(this.selectors.customPatternInput);
            
            if (input) {
                input.value = '';
                input.value = pattern;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('keyup', { bubbles: true }));
                
                return { 
                    success: true, 
                    message: `✅ Pattern "${pattern}" set in MultiQC input`
                };
            } else {
                return { 
                    success: false, 
                    message: '❌ MultiQC input not found' 
                };
            }
        },

        // Get existing filter patterns from MultiQC
        getExistingFilterPatterns: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return [];
            }
            
            const iframeDoc = access.doc;
            const filterList = iframeDoc.querySelector('#mqc_col_filters');
            if (!filterList) {
                return [];
            }
            
            const inputs = filterList.querySelectorAll('input.f_text');
            return Array.from(inputs).map(input => input.value).filter(value => value.trim() !== '');
        },

        // Remove specific filter by pattern value
        removeFilterByPattern: function(pattern) {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            const filterList = iframeDoc.querySelector('#mqc_col_filters');
            if (!filterList) {
                return { success: false, message: 'Filter list not found' };
            }
            
            // Find the input with matching value
            const inputs = filterList.querySelectorAll('input.f_text');
            for (let input of inputs) {
                if (input.value === pattern) {
                    // Find the close button in the same <li> element
                    const listItem = input.closest('li');
                    if (listItem) {
                        const closeButton = listItem.querySelector('button.close');
                        if (closeButton) {
                            closeButton.click();
                            return { success: true, message: `✅ Removed filter: "${pattern}"` };
                        }
                    }
                }
            }
            
            return { success: false, message: `❌ Filter not found: "${pattern}"` };
        },

        // Add single pattern as filter
        addSinglePattern: function(pattern) {
            const setResult = this.setPattern(pattern);
            if (setResult.success) {
                setTimeout(() => {
                    this.clickPlusButton();
                }, 50);
                return { success: true, message: `✅ Added filter: "${pattern}"` };
            }
            return { success: false, message: setResult.message };
        },

        // Differential update: only add/remove changed patterns
        updateFiltersIncremental: function(newPatterns) {
            const results = [`🚀 INCREMENTAL UPDATE: [${newPatterns.join(', ')}]`];
            
            try {
                // Get current state
                const existingPatterns = this.getExistingFilterPatterns();
                results.push(`📋 Current filters: [${existingPatterns.join(', ')}]`);
                
                // Find differences
                const toAdd = newPatterns.filter(p => !existingPatterns.includes(p));
                const toRemove = existingPatterns.filter(p => !newPatterns.includes(p));
                
                results.push(`➕ To add: [${toAdd.join(', ')}]`);
                results.push(`➖ To remove: [${toRemove.join(', ')}]`);
                
                let operationCount = 0;
                
                // Remove filters that are no longer needed
                toRemove.forEach(pattern => {
                    const removeResult = this.removeFilterByPattern(pattern);
                    if (removeResult.success) {
                        results.push(removeResult.message);
                        operationCount++;
                    }
                });
                
                // Add new filters
                let addIndex = 0;
                const addNextFilter = () => {
                    if (addIndex >= toAdd.length) {
                        // All operations done, apply changes if any were made
                        if (operationCount > 0 || toAdd.length > 0) {
                            setTimeout(() => {
                                this.clickApplyButton();
                            }, 100);
                        }
                        return;
                    }
                    
                    const pattern = toAdd[addIndex];
                    const addResult = this.addSinglePattern(pattern);
                    if (addResult.success) {
                        results.push(addResult.message);
                        operationCount++;
                    }
                    
                    addIndex++;
                    setTimeout(() => {
                        addNextFilter();
                    }, 150);
                };
                
                // Start adding new filters
                if (toAdd.length > 0) {
                    setTimeout(() => {
                        addNextFilter();
                    }, 100);
                } else if (operationCount > 0) {
                    // Only removals, apply immediately
                    setTimeout(() => {
                        this.clickApplyButton();
                    }, 100);
                }
                
                if (toAdd.length === 0 && toRemove.length === 0) {
                    results.push('✅ No changes needed');
                } else {
                    results.push('⏳ Applying changes...');
                }
                
                return results.join('\n');
                
            } catch (error) {
                return `❌ Incremental Update Error: ${error.message}`;
            }
        },

        // Full automation: Single pattern (kept for backward compatibility)
        fullAutomation: function(pattern) {
            return this.updateFiltersIncremental([pattern]);
        },

        // Handle highlight pattern changes from Dash dropdown (SCALABLE VERSION)
        handleHighlightPatternChange: function(highlight_pattern) {
            // Handle TagsInput array format
            let patterns = [];
            if (Array.isArray(highlight_pattern)) {
                patterns = highlight_pattern.filter(p => p && p.trim() !== '');
            } else if (highlight_pattern && highlight_pattern.trim() !== '') {
                patterns = [highlight_pattern];
            }
            
            // Use incremental updates - only add/remove what changed
            return this.updateFiltersIncremental(patterns);
        },

        // === SHOW/HIDE SAMPLES FUNCTIONS ===
        
        // Get existing hide filter patterns from MultiQC
        getExistingHideFilterPatterns: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return [];
            }
            
            const iframeDoc = access.doc;
            const filterList = iframeDoc.querySelector(this.selectors.hideFilterList);
            if (!filterList) {
                return [];
            }
            
            const inputs = filterList.querySelectorAll('input.f_text');
            return Array.from(inputs).map(input => input.value).filter(value => value.trim() !== '');
        },

        // Remove specific hide filter by pattern value
        removeHideFilterByPattern: function(pattern) {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            const filterList = iframeDoc.querySelector(this.selectors.hideFilterList);
            if (!filterList) {
                return { success: false, message: 'Hide filter list not found' };
            }
            
            // Find the input with matching value
            const inputs = filterList.querySelectorAll('input.f_text');
            for (let input of inputs) {
                if (input.value === pattern) {
                    // Find the close button in the same <li> element
                    const listItem = input.closest('li');
                    if (listItem) {
                        const closeButton = listItem.querySelector('button.close');
                        if (closeButton) {
                            closeButton.click();
                            return { success: true, message: `✅ Removed hide filter: "${pattern}"` };
                        }
                    }
                }
            }
            
            return { success: false, message: `❌ Hide filter not found: "${pattern}"` };
        },

        // Set pattern in MultiQC hide input
        setHidePattern: function(pattern) {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            const input = iframeDoc.querySelector(this.selectors.hidePatternInput);
            
            if (input) {
                input.value = '';
                input.value = pattern;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('keyup', { bubbles: true }));
                
                return { 
                    success: true, 
                    message: `✅ Hide pattern "${pattern}" set in MultiQC input`
                };
            } else {
                return { 
                    success: false, 
                    message: '❌ MultiQC hide input not found' 
                };
            }
        },

        // Click hide Plus button
        clickHidePlusButton: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const plusButton = iframeDoc.querySelector(this.selectors.hidePlusButton);
            
            if (plusButton) {
                plusButton.disabled = false;
                plusButton.click();
                return '✅ Hide Plus button clicked!';
            } else {
                return '❌ Hide Plus button not found';
            }
        },

        // Click hide Apply button
        clickHideApplyButton: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            const applyButton = iframeDoc.querySelector(this.selectors.hideApplyButton);
            
            if (applyButton) {
                // Force enable if needed
                applyButton.disabled = false;
                applyButton.classList.remove('btn-default');
                applyButton.classList.add('btn-primary');
                applyButton.click();
                return '✅ Hide Apply button clicked! Changes applied to MultiQC charts.';
            } else {
                return '❌ Hide Apply button not found';
            }
        },

        // Add single hide pattern as filter
        addSingleHidePattern: function(pattern) {
            const setResult = this.setHidePattern(pattern);
            if (setResult.success) {
                setTimeout(() => {
                    this.clickHidePlusButton();
                }, 50);
                return { success: true, message: `✅ Added hide filter: "${pattern}"` };
            }
            return { success: false, message: setResult.message };
        },

        // Clear all existing hide filters in MultiQC
        clearHideFilters: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            
            // Find all existing hide filter entries and click their X buttons
            const filterList = iframeDoc.querySelector(this.selectors.hideFilterList);
            let removedCount = 0;
            
            if (filterList) {
                const closeButtons = filterList.querySelectorAll('button.close');
                
                closeButtons.forEach(button => {
                    button.click();
                    removedCount++;
                });
                
                // Also clear the main hide input
                const input = iframeDoc.querySelector(this.selectors.hidePatternInput);
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }
            
            // IMPORTANT: Reset to "Hide" mode to show all samples when clearing
            const hideRadio = iframeDoc.querySelector('input[name="mqc_hidesamples_showhide"][value="hide"]');
            if (hideRadio && !hideRadio.checked) {
                hideRadio.checked = true;
                hideRadio.dispatchEvent(new Event('change', { bubbles: true }));
            }
            
            return { 
                success: true, 
                message: `✅ Cleared ${removedCount} existing hide filters and reset to "Hide" mode (shows all samples)`
            };
        },

        // Differential update for hide filters: only add/remove changed patterns
        updateHideFiltersIncremental: function(newPatterns) {
            const results = [`👁️ INCREMENTAL HIDE UPDATE: [${newPatterns.join(', ')}]`];
            
            try {
                // Get current state
                const existingPatterns = this.getExistingHideFilterPatterns();
                results.push(`📋 Current hide filters: [${existingPatterns.join(', ')}]`);
                
                // Find differences
                const toAdd = newPatterns.filter(p => !existingPatterns.includes(p));
                const toRemove = existingPatterns.filter(p => !newPatterns.includes(p));
                
                results.push(`➕ To add: [${toAdd.join(', ')}]`);
                results.push(`➖ To remove: [${toRemove.join(', ')}]`);
                
                let operationCount = 0;
                
                // Remove hide filters that are no longer needed
                toRemove.forEach(pattern => {
                    const removeResult = this.removeHideFilterByPattern(pattern);
                    if (removeResult.success) {
                        results.push(removeResult.message);
                        operationCount++;
                    }
                });
                
                // Add new hide filters
                let addIndex = 0;
                const addNextFilter = () => {
                    if (addIndex >= toAdd.length) {
                        // All operations done, apply changes if any were made
                        if (operationCount > 0 || toAdd.length > 0) {
                            setTimeout(() => {
                                // If we end up with zero patterns, reset to "Hide" mode first
                                if (willHaveZeroPatterns) {
                                    this.resetToHideMode();
                                }
                                this.clickHideApplyButton();
                            }, 100);
                        }
                        return;
                    }
                    
                    const pattern = toAdd[addIndex];
                    const addResult = this.addSingleHidePattern(pattern);
                    if (addResult.success) {
                        results.push(addResult.message);
                        operationCount++;
                    }
                    
                    addIndex++;
                    setTimeout(() => {
                        addNextFilter();
                    }, 150);
                };
                
                // Check if we're ending up with zero patterns after all operations
                const willHaveZeroPatterns = (newPatterns.length === 0) && (toRemove.length > 0);
                
                // Start adding new hide filters
                if (toAdd.length > 0) {
                    setTimeout(() => {
                        addNextFilter();
                    }, 100);
                } else if (operationCount > 0) {
                    // Only removals, apply immediately
                    setTimeout(() => {
                        // If we're removing everything, reset to "Hide" mode first
                        if (willHaveZeroPatterns) {
                            this.resetToHideMode();
                        }
                        this.clickHideApplyButton();
                    }, 100);
                }
                
                if (toAdd.length === 0 && toRemove.length === 0) {
                    results.push('✅ No changes needed');
                } else {
                    results.push('⏳ Applying hide changes...');
                }
                
                return results.join('\n');
                
            } catch (error) {
                return `❌ Incremental Hide Update Error: ${error.message}`;
            }
        },

        // Helper function to reset radio button to "Hide" mode (shows all samples)
        resetToHideMode: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return;
            }
            
            const iframeDoc = access.doc;
            const hideRadio = iframeDoc.querySelector('input[name="mqc_hidesamples_showhide"][value="hide"]');
            if (hideRadio && !hideRadio.checked) {
                hideRadio.checked = true;
                hideRadio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        },

        // Set MultiQC show/hide mode (hide vs show only)
        setShowHideMode: function(mode) {
            const access = this.getIframeAccess();
            if (!access.success) {
                return { success: false, message: access.error };
            }
            
            const iframeDoc = access.doc;
            const hideRadio = iframeDoc.querySelector('input[name="mqc_hidesamples_showhide"][value="hide"]');
            const showRadio = iframeDoc.querySelector('input[name="mqc_hidesamples_showhide"][value="show"]');
            
            if (mode === 'hide' && hideRadio) {
                hideRadio.checked = true;
                hideRadio.dispatchEvent(new Event('change', { bubbles: true }));
                return { success: true, message: '✅ Set to HIDE mode' };
            } else if (mode === 'show' && showRadio) {
                showRadio.checked = true;
                showRadio.dispatchEvent(new Event('change', { bubbles: true }));
                return { success: true, message: '✅ Set to SHOW ONLY mode' };
            }
            
            return { success: false, message: `❌ Could not set mode: ${mode}` };
        },

        // Debug: inspect show/hide section
        inspectShowHideSection: function() {
            const access = this.getIframeAccess();
            if (!access.success) {
                return access.error;
            }
            
            const iframeDoc = access.doc;
            let results = [access.status + '=== INSPECTING SHOW/HIDE SECTION ===\n'];
            
            // Check main section
            const section = iframeDoc.querySelector('#mqc_hidesamples');
            results.push(`🔍 Main section #mqc_hidesamples: ${section ? 'FOUND' : 'NOT FOUND'}`);
            
            // Check input
            const input = iframeDoc.querySelector(this.selectors.hidePatternInput);
            results.push(`🔍 Hide input ${this.selectors.hidePatternInput}: ${input ? 'FOUND' : 'NOT FOUND'}`);
            if (input) {
                results.push(`   - Placeholder: "${input.placeholder}"`);
                results.push(`   - Value: "${input.value}"`);
            }
            
            // Check buttons
            const plusBtn = iframeDoc.querySelector(this.selectors.hidePlusButton);
            results.push(`🔍 Plus button ${this.selectors.hidePlusButton}: ${plusBtn ? 'FOUND' : 'NOT FOUND'}`);
            
            const applyBtn = iframeDoc.querySelector(this.selectors.hideApplyButton);
            results.push(`🔍 Apply button ${this.selectors.hideApplyButton}: ${applyBtn ? 'FOUND' : 'NOT FOUND'}`);
            if (applyBtn) {
                results.push(`   - Disabled: ${applyBtn.disabled}`);
                results.push(`   - Classes: ${applyBtn.className}`);
            }
            
            // Check filter list
            const filterList = iframeDoc.querySelector(this.selectors.hideFilterList);
            results.push(`🔍 Filter list ${this.selectors.hideFilterList}: ${filterList ? 'FOUND' : 'NOT FOUND'}`);
            if (filterList) {
                const existingFilters = filterList.querySelectorAll('li');
                results.push(`   - Existing filters: ${existingFilters.length}`);
                existingFilters.forEach((li, i) => {
                    const input = li.querySelector('input.f_text');
                    results.push(`     [${i}] Value: "${input ? input.value : 'no input found'}"`);
                });
            }
            
            // Check radio buttons
            const hideRadio = iframeDoc.querySelector('input[value="hide"]');
            const showRadio = iframeDoc.querySelector('input[value="show"]');
            results.push(`🔍 Hide radio: ${hideRadio ? (hideRadio.checked ? 'CHECKED' : 'unchecked') : 'NOT FOUND'}`);
            results.push(`🔍 Show radio: ${showRadio ? (showRadio.checked ? 'CHECKED' : 'unchecked') : 'NOT FOUND'}`);
            
            return results.join('\n');
        },

        // Handle show/hide pattern changes from Dash dropdown (SCALABLE VERSION)
        handleShowHidePatternChange: function(showhide_pattern, showhide_mode) {
            // Handle TagsInput array format
            let patterns = [];
            if (Array.isArray(showhide_pattern)) {
                patterns = showhide_pattern.filter(p => p && p.trim() !== '');
            } else if (showhide_pattern && showhide_pattern.trim() !== '') {
                patterns = [showhide_pattern];
            }
            
            // Set the correct mode in MultiQC first
            const modeResult = this.setShowHideMode(showhide_mode);
            let results = [modeResult.message];
            
            if (patterns.length === 0) {
                // Clear all filters when empty
                this.clearHideFilters();
                setTimeout(() => {
                    this.clickHideApplyButton();
                }, 100);
                results.push('🎯 All show/hide patterns cleared from MultiQC');
                return results.join('\n');
            }
            
            // Use incremental updates - only add/remove what changed
            const updateResult = this.updateHideFiltersIncremental(patterns);
            results.push(updateResult);
            
            return results.join('\n');
        }
    }
});