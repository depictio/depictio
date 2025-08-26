// Main MultiQC callback dispatcher using modular functions
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    multiqc: Object.assign(window.dash_clientside.multiqc || {}, {
        
        // Main callback dispatcher that handles all MultiQC automation triggers
        handleMultiQCCallback: function(
            inspect_clicks, test_clicks, plus_clicks, apply_clicks, enter_clicks,
            highlight_clear_clicks, showhide_clear_clicks,
            highlight_pattern, showhide_pattern,
            highlight_regex, showhide_regex, showhide_mode
        ) {
            // Get callback context
            const context = window.dash_clientside.multiqc.getCallbackContext();
            if (!context.hasContext) {
                return context.message;
            }
            
            const { triggered_id, triggered_prop } = context;
            
            try {
                console.log('MultiQC callback triggered:', triggered_id, 'Pattern:', highlight_pattern);
                
                // DEBUG: Check what functions are available
                const availableFunctions = Object.keys(window.dash_clientside.multiqc);
                console.log('Available multiqc functions:', availableFunctions);
                
                // Handle dropdown pattern changes - AUTO-TRIGGER full automation
                if (triggered_id === 'highlight-pattern-input') {
                    return window.dash_clientside.multiqc.handleHighlightPatternChange(highlight_pattern);
                }
                
                if (triggered_id === 'showhide-pattern-input') {
                    return window.dash_clientside.multiqc.handleShowHidePatternChange(showhide_pattern, showhide_mode);
                }
                
                // Handle debug button clicks
                switch (triggered_id) {
                    case 'test-sample-input-btn':
                        return window.dash_clientside.multiqc.testSampleInput();
                        
                    case 'simulate-plus-btn':
                        return window.dash_clientside.multiqc.clickPlusButton();
                        
                    case 'simulate-apply-btn':
                        return window.dash_clientside.multiqc.clickApplyButton();
                        
                    case 'simulate-enter-btn':
                        return window.dash_clientside.multiqc.simulateEnterKey();
                        
                    case 'highlight-clear-btn':
                        const clearResult = window.dash_clientside.multiqc.clearHighlightFilters();
                        return clearResult.message;
                        
                    default:
                        return `DEBUG: Unknown trigger: ${triggered_id}\nAvailable functions: ${availableFunctions.join(', ')}\nChecking if testSampleInput exists: ${typeof window.dash_clientside.multiqc.testSampleInput}`;
                }
                
            } catch (error) {
                console.error('MultiQC callback error:', error);
                return `❌ JavaScript Error: ${error.message}`;
            }
        }
    })
});