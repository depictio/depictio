/**
 * Dash Debug Menu Auto-Collapse
 *
 * Ensures the Dash debug menu starts collapsed on page load.
 * Users can still expand it manually by clicking the toggle button.
 */

(function() {
    'use strict';

    function collapseDebugMenu() {
        // Find the debug menu outer container
        const debugMenuOuter = document.querySelector('.dash-debug-menu__outer');
        const debugMenuToggle = document.querySelector('.dash-debug-menu__toggle');

        if (debugMenuOuter && debugMenuToggle) {
            // Remove expanded classes to collapse the menu
            debugMenuOuter.classList.remove('dash-debug-menu__outer--expanded');
            debugMenuToggle.classList.remove('dash-debug-menu__toggle--expanded');

            console.log('Dash debug menu collapsed on page load');
        }
    }

    // Collapse immediately if DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', collapseDebugMenu);
    } else {
        collapseDebugMenu();
    }

    // Also collapse after a short delay to catch late-rendered debug menu
    setTimeout(collapseDebugMenu, 100);
    setTimeout(collapseDebugMenu, 500);
})();
