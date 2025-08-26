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
            customPatternInput: '#mqc_colour_filter',
            colorPicker: '#mqc_colour_filter_color',
            applyButton: '#mqc_cols_apply',
            plusButton: '#mqc_colour_filter_update',  // CORRECT Plus button
            toolboxContainer: '#mqc_cols, .mqc_filter_section, .mqc-toolbox-label',
            colorForm: '#mqc_color_form'
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

        // Add multiple patterns as separate filters
        addMultiplePatterns: function(patterns) {
            const results = [`🚀 ADDING ${patterns.length} SEPARATE PATTERNS: [${patterns.join(', ')}]`];
            
            try {
                // Step 0: Clear existing filters first
                const clearResult = this.clearHighlightFilters();
                if (clearResult.success) {
                    results.push('✅ Step 0: ' + clearResult.message);
                }
                
                // Step 1-N: Add each pattern as a separate filter
                let addedCount = 0;
                const addNextPattern = (index) => {
                    if (index >= patterns.length) {
                        // All patterns added, now apply
                        setTimeout(() => {
                            this.clickApplyButton();
                        }, 100);
                        return;
                    }
                    
                    const pattern = patterns[index];
                    const setResult = this.setPattern(pattern);
                    if (setResult.success) {
                        // Pattern set, now click Plus to add it as a filter
                        setTimeout(() => {
                            this.clickPlusButton();
                            addedCount++;
                            // Recursively add the next pattern
                            setTimeout(() => {
                                addNextPattern(index + 1);
                            }, 100);
                        }, 100);
                    }
                };
                
                // Start adding patterns
                addNextPattern(0);
                
                results.push(`⏳ Adding each pattern as separate filter...`);
                results.push(`⏳ Final step: Apply all ${patterns.length} filters`);
                results.push('🎯 MultiQC charts will show each sample highlighted separately');
                
                return results.join('\n');
                
            } catch (error) {
                return `❌ Automation Error: ${error.message}`;
            }
        },

        // Full automation: Single pattern (kept for backward compatibility)
        fullAutomation: function(pattern) {
            return this.addMultiplePatterns([pattern]);
        },

        // Handle highlight pattern changes from Dash dropdown
        handleHighlightPatternChange: function(highlight_pattern) {
            // Handle TagsInput array format
            let patterns = [];
            if (Array.isArray(highlight_pattern)) {
                patterns = highlight_pattern.filter(p => p && p.trim() !== '');
            } else if (highlight_pattern && highlight_pattern.trim() !== '') {
                patterns = [highlight_pattern];
            }
            
            if (patterns.length === 0) {
                // Clear all existing filters when dropdown is empty
                this.clearHighlightFilters();
                setTimeout(() => {
                    this.clickApplyButton();
                }, 100);
                return '🎯 All highlight patterns cleared from MultiQC';
            }
            
            // Add each pattern as a separate filter
            return this.addMultiplePatterns(patterns);
        },

        // Handle show/hide pattern changes from Dash dropdown  
        handleShowHidePatternChange: function(showhide_pattern, showhide_mode) {
            // Handle TagsInput array format
            let patterns = [];
            if (Array.isArray(showhide_pattern)) {
                patterns = showhide_pattern.filter(p => p && p.trim() !== '');
            } else if (showhide_pattern && showhide_pattern.trim() !== '') {
                patterns = [showhide_pattern];
            }
            
            if (patterns.length === 0) {
                return '👁️ Show/hide patterns cleared';
            }
            
            // TODO: Implement show/hide functionality based on MultiQC's hide samples feature
            const pattern = patterns.length > 1 ? patterns.join('|') : patterns[0];
            
            return `🚧 SHOW/HIDE AUTOMATION (TODO):\n` +
                   `   - Pattern: "${pattern}"\n` +
                   `   - Mode: "${showhide_mode}"\n` +
                   `   - This functionality needs MultiQC's hide samples controls`;
        }
    }
});