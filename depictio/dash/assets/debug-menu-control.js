// Auto-collapse Dash debug menu on page load with better debugging
(function() {
    let hasBeenCollapsed = false;
    let attempts = 0;
    const maxAttempts = 20;
    
    function logDebugInfo() {
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
        
        // Also try alternative selectors
        const alternativeSelectors = [
            '[class*="dash-debug-menu"]',
            '[class*="debug-menu"]',
            '[class*="dash-debug"]'
        ];
        
        alternativeSelectors.forEach(selector => {
            const elements = document.querySelectorAll(selector);
            if (elements.length > 0) {
                console.log(`Found ${elements.length} elements with selector:`, selector);
                elements.forEach((el, i) => {
                    console.log(`  Element ${i}:`, el.className);
                });
            }
        });
    }
    
    function tryCollapseDebugMenu() {
        attempts++;
        console.log(`Attempt ${attempts}/${maxAttempts} to collapse debug menu`);
        
        if (hasBeenCollapsed || attempts > maxAttempts) {
            return;
        }
        
        logDebugInfo();
        
        // Try multiple selectors
        const selectors = [
            '.dash-debug-menu__outer',
            '[class*="dash-debug-menu__outer"]',
            'div[class*="debug-menu"]'
        ];
        
        let debugMenu = null;
        for (const selector of selectors) {
            debugMenu = document.querySelector(selector);
            if (debugMenu) {
                console.log('Found debug menu with selector:', selector);
                break;
            }
        }
        
        if (debugMenu) {
            const isExpanded = debugMenu.classList.contains('dash-debug-menu__outer--expanded') ||
                             debugMenu.className.includes('expanded');
            
            console.log('Debug menu expanded state:', isExpanded);
            
            if (isExpanded) {
                // Try multiple toggle button selectors
                const toggleSelectors = [
                    '.dash-debug-menu__toggle',
                    '[class*="dash-debug-menu__toggle"]',
                    'button[class*="toggle"]'
                ];
                
                let toggleButton = null;
                for (const selector of toggleSelectors) {
                    toggleButton = debugMenu.querySelector(selector);
                    if (toggleButton) {
                        console.log('Found toggle button with selector:', selector);
                        break;
                    }
                }
                
                if (toggleButton) {
                    console.log('Clicking toggle button to collapse menu');
                    toggleButton.click();
                    hasBeenCollapsed = true;
                    console.log('Debug menu collapse attempted');
                    return;
                } else {
                    console.log('No toggle button found');
                }
            } else {
                console.log('Debug menu already collapsed or not expanded');
                hasBeenCollapsed = true;
                return;
            }
        } else {
            console.log('Debug menu not found yet');
        }
        
        // Continue trying if we haven't succeeded
        if (!hasBeenCollapsed && attempts < maxAttempts) {
            setTimeout(tryCollapseDebugMenu, 250);
        }
    }
    
    // Start trying when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(tryCollapseDebugMenu, 100);
        });
    } else {
        setTimeout(tryCollapseDebugMenu, 100);
    }
    
    // Also try when window loads
    window.addEventListener('load', function() {
        setTimeout(tryCollapseDebugMenu, 200);
    });
    
    // Try with MutationObserver to catch dynamic loading
    if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList') {
                    const addedNodes = Array.from(mutation.addedNodes);
                    const hasDebugMenu = addedNodes.some(node => 
                        node.nodeType === 1 && 
                        (node.className && node.className.includes('dash-debug-menu') ||
                         node.querySelector && node.querySelector('[class*="dash-debug-menu"]'))
                    );
                    
                    if (hasDebugMenu && !hasBeenCollapsed) {
                        console.log('Debug menu detected via MutationObserver');
                        setTimeout(tryCollapseDebugMenu, 100);
                    }
                }
            });
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        
        // Stop observing after 10 seconds
        setTimeout(() => {
            observer.disconnect();
        }, 10000);
    }
})();