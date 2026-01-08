/**
 * Layout Change Tracker
 *
 * Monitors dashboard grid layout changes (drag operations) and updates
 * the layout-saved-state store to trigger visual feedback on the save button.
 */

console.log('🔧 LAYOUT TRACKER: Script loaded');

// Debounce timer to prevent rapid-fire triggers
let debounceTimer = null;
let lastTriggerTime = 0;

// Function to mark layout as unsaved by triggering the hidden button
function markLayoutUnsaved() {
    // Debounce: Only trigger once every 500ms to prevent loops
    const now = Date.now();
    if (now - lastTriggerTime < 500) {
        console.log('⏸️ LAYOUT TRACKER: Debounced (too soon)');
        return;
    }
    lastTriggerTime = now;

    console.log('⚠️ LAYOUT TRACKER: Marking layout as unsaved');

    // Find and click the hidden trigger button
    const triggerButton = document.getElementById('layout-change-trigger');
    if (triggerButton) {
        console.log('🎯 LAYOUT TRACKER: Triggering button click');
        triggerButton.click();

        // Check store value after a brief delay
        setTimeout(() => {
            const store = document.getElementById('layout-saved-state');
            if (store && store._dashprivate_layout && store._dashprivate_layout.props) {
                console.log('📊 LAYOUT TRACKER: Store value after click:', store._dashprivate_layout.props.data);
            }
        }, 100);
    } else {
        console.warn('⚠️ LAYOUT TRACKER: Button not found, will retry');
        setTimeout(markLayoutUnsaved, 100);
    }
}

// Set up MutationObserver to detect layout changes
function setupLayoutTracking() {
    console.log('🔧 LAYOUT TRACKER: Setting up observers');

    // Find all grid containers
    const findGrids = function() {
        const grids = document.querySelectorAll('[id*="left-panel-grid"], [id*="right-panel-grid"]');
        console.log('🔍 LAYOUT TRACKER: Found', grids.length, 'grid(s)');
        return grids;
    };

    // Set up observer for each grid
    const observeGrid = function(gridElement) {
        console.log('👀 LAYOUT TRACKER: Observing grid:', gridElement.id);

        const observer = new MutationObserver(function(mutations) {
            // Check if any mutation involves position/layout changes
            let layoutChanged = false;

            for (let mutation of mutations) {
                const target = mutation.target;

                // IGNORE: Anything outside the grid containers
                if (!target.closest('[id*="panel-grid"]')) {
                    continue;
                }

                // IGNORE: Save button and other control buttons
                if (target.id === 'save-button-dashboard' ||
                    target.closest('#save-button-dashboard') ||
                    target.closest('button') ||
                    target.closest('[role="button"]') ||
                    target.closest('.mantine-Button-root')) {
                    continue;
                }

                // Check if style attribute changed (position changes when dragging)
                if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                    // Only track actual grid items with transform changes (position)
                    if (target.classList && target.classList.contains('react-grid-item')) {
                        // Check if the style change includes transform (actual position change)
                        const style = target.getAttribute('style');
                        if (style && (style.includes('transform') || style.includes('translate'))) {
                            console.log('🎯 LAYOUT TRACKER: Grid item position changed');
                            layoutChanged = true;
                            break;
                        }
                    }
                }

                // Check for structural changes (items added/removed from grid)
                if (mutation.type === 'childList' && (mutation.addedNodes.length > 0 || mutation.removedNodes.length > 0)) {
                    // Only count if it's actual grid items being added/removed
                    let hasGridItemChange = false;
                    mutation.addedNodes.forEach(node => {
                        if (node.classList && node.classList.contains('react-grid-item')) {
                            hasGridItemChange = true;
                        }
                    });
                    mutation.removedNodes.forEach(node => {
                        if (node.classList && node.classList.contains('react-grid-item')) {
                            hasGridItemChange = true;
                        }
                    });

                    if (hasGridItemChange) {
                        console.log('🎯 LAYOUT TRACKER: Grid items added/removed');
                        layoutChanged = true;
                        break;
                    }
                }
            }

            if (layoutChanged) {
                markLayoutUnsaved();
            }
        });

        // Observe the grid container for changes
        observer.observe(gridElement, {
            attributes: true,
            attributeFilter: ['style'],
            childList: true,
            subtree: true,
        });

        console.log('✅ LAYOUT TRACKER: Observer active');
    };

    // Set up observers for all grids
    const setupObservers = function() {
        const grids = findGrids();
        if (grids.length > 0) {
            grids.forEach(observeGrid);
        } else {
            console.log('⏳ LAYOUT TRACKER: Grids not ready, retrying...');
            setTimeout(setupObservers, 500);
        }
    };

    setupObservers();
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupLayoutTracking);
} else {
    // DOM already loaded
    setupLayoutTracking();
}

console.log('🔧 LAYOUT TRACKER: Initialization complete');
