// Auto-collapse Dash debug menu - Enhanced for Dash 3.x
(function() {
    let hasBeenCollapsed = false;
    let attempts = 0;
    const maxAttempts = 50; // Increased for slower page loads
    let observer = null;
    let recheckInterval = null;

    function logDebugInfo(level) {
        if (level === 'verbose') {
            console.log('=== DASH DEBUG MENU CONTROL ===');
            console.log('Looking for debug menu...');

            const debugMenu = document.querySelector('.dash-debug-menu__outer');
            console.log('Debug menu found:', !!debugMenu);

            if (debugMenu) {
                console.log('Debug menu classes:', debugMenu.className);

                const toggleButton = debugMenu.querySelector('.dash-debug-menu__toggle');
                console.log('Toggle button found:', !!toggleButton);

                if (toggleButton) {
                    console.log('Toggle button classes:', toggleButton.className);
                }

                const isExpanded = debugMenu.classList.contains('dash-debug-menu__outer--expanded');
                console.log('Is expanded:', isExpanded);
            }
        }
    }

    function collapseByClassRemoval(debugMenu) {
        // Try direct class manipulation as fallback
        try {
            debugMenu.classList.remove('dash-debug-menu__outer--expanded');
            console.log('✓ Debug menu collapsed via class removal');
            return true;
        } catch (e) {
            console.log('✗ Class removal failed:', e.message);
            return false;
        }
    }

    function tryCollapseDebugMenu() {
        attempts++;

        if (hasBeenCollapsed || attempts > maxAttempts) {
            if (attempts > maxAttempts) {
                console.log('⚠️  Debug menu auto-collapse: max attempts reached');
            }
            return;
        }

        // Only log every 5 attempts to reduce console noise
        if (attempts % 5 === 1 || attempts === 1) {
            console.log(`🔍 Attempt ${attempts}/${maxAttempts} to collapse debug menu`);
        }

        // Try multiple selectors for Dash 3.x compatibility
        const selectors = [
            '.dash-debug-menu__outer',
            '[class*="dash-debug-menu__outer"]',
            'div[class*="debug-menu"]',
            // Dash 3.x might use different structure
            'div[class*="dash-debug"]'
        ];

        let debugMenu = null;
        for (const selector of selectors) {
            debugMenu = document.querySelector(selector);
            if (debugMenu) {
                break;
            }
        }

        if (debugMenu) {
            const isExpanded = debugMenu.classList.contains('dash-debug-menu__outer--expanded') ||
                             debugMenu.className.includes('expanded');

            if (isExpanded) {
                // Method 1: Try clicking the toggle button (preferred)
                const toggleSelectors = [
                    '.dash-debug-menu__toggle',
                    '[class*="dash-debug-menu__toggle"]',
                    'button[class*="toggle"]',
                    'button[class*="debug-menu"]' // Dash 3.x alternative
                ];

                let toggleButton = null;
                for (const selector of toggleSelectors) {
                    toggleButton = debugMenu.querySelector(selector);
                    if (toggleButton) {
                        break;
                    }
                }

                if (toggleButton) {
                    console.log('✓ Debug menu found - collapsing via toggle button');
                    toggleButton.click();
                    hasBeenCollapsed = true;

                    // Verify collapse after click
                    setTimeout(() => {
                        const stillExpanded = debugMenu.classList.contains('dash-debug-menu__outer--expanded');
                        if (stillExpanded) {
                            console.log('⚠️  Menu still expanded after toggle, trying class removal');
                            collapseByClassRemoval(debugMenu);
                        } else {
                            console.log('✓ Debug menu successfully collapsed');
                        }
                        cleanup();
                    }, 100);
                    return;
                }

                // Method 2: Try direct class manipulation if toggle button not found
                console.log('⚠️  Toggle button not found, trying direct class removal');
                if (collapseByClassRemoval(debugMenu)) {
                    hasBeenCollapsed = true;
                    cleanup();
                    return;
                }
            } else {
                // Menu exists but already collapsed
                if (attempts === 1) {
                    console.log('✓ Debug menu already collapsed');
                }
                hasBeenCollapsed = true;
                cleanup();
                return;
            }
        }

        // Continue trying if we haven't succeeded
        if (!hasBeenCollapsed && attempts < maxAttempts) {
            setTimeout(tryCollapseDebugMenu, 200); // Reduced delay for faster response
        }
    }

    function cleanup() {
        // Stop observer and interval once collapsed
        if (observer) {
            observer.disconnect();
            observer = null;
        }
        if (recheckInterval) {
            clearInterval(recheckInterval);
            recheckInterval = null;
        }
    }

    function init() {
        // Start trying immediately
        tryCollapseDebugMenu();

        // Also try when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function() {
                setTimeout(tryCollapseDebugMenu, 50);
            });
        }

        // Also try when window loads
        window.addEventListener('load', function() {
            setTimeout(tryCollapseDebugMenu, 100);
        });

        // Persistent MutationObserver to catch dynamic loading
        if (typeof MutationObserver !== 'undefined') {
            observer = new MutationObserver(function(mutations) {
                if (hasBeenCollapsed) {
                    // Check if menu expanded again (shouldn't happen, but just in case)
                    const debugMenu = document.querySelector('.dash-debug-menu__outer--expanded');
                    if (debugMenu) {
                        console.log('⚠️  Debug menu expanded again, re-collapsing');
                        hasBeenCollapsed = false;
                        tryCollapseDebugMenu();
                    }
                    return;
                }

                mutations.forEach(function(mutation) {
                    if (mutation.type === 'childList' && !hasBeenCollapsed) {
                        const addedNodes = Array.from(mutation.addedNodes);
                        const hasDebugMenu = addedNodes.some(node =>
                            node.nodeType === 1 &&
                            (node.className && typeof node.className === 'string' &&
                             node.className.includes('dash-debug-menu'))
                        );

                        if (hasDebugMenu) {
                            setTimeout(tryCollapseDebugMenu, 50);
                        }
                    }

                    // Also check for class changes on the debug menu itself
                    if (mutation.type === 'attributes' &&
                        mutation.attributeName === 'class' &&
                        mutation.target.className &&
                        mutation.target.className.includes('dash-debug-menu__outer--expanded') &&
                        hasBeenCollapsed) {
                        // Menu was collapsed but expanded again
                        console.log('⚠️  Debug menu re-expanded, collapsing again');
                        hasBeenCollapsed = false;
                        tryCollapseDebugMenu();
                    }
                });
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class']
            });
        }

        // Periodic recheck for first 15 seconds (covers slow page loads)
        recheckInterval = setInterval(function() {
            if (!hasBeenCollapsed && attempts < maxAttempts) {
                tryCollapseDebugMenu();
            } else if (hasBeenCollapsed) {
                clearInterval(recheckInterval);
                recheckInterval = null;
            }
        }, 500);

        // Stop periodic recheck after 15 seconds
        setTimeout(() => {
            if (recheckInterval) {
                clearInterval(recheckInterval);
                recheckInterval = null;
            }
        }, 15000);
    }

    // Start immediately
    init();
})();
