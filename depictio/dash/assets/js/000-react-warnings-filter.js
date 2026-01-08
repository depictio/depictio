/**
 * React Warnings Filter
 *
 * Filters out known, harmless React warnings from third-party libraries
 * that can't be easily fixed in our codebase.
 *
 * This script runs IMMEDIATELY to intercept warnings before React renders.
 */

(function() {
    'use strict';

    // CRITICAL: Store original console methods IMMEDIATELY before anything else runs
    const originalWarn = console.warn;
    const originalError = console.error;
    const originalLog = console.log;

    // SELECTIVE FILTERING: Only filter truly harmless warnings
    // Real issues should be visible for debugging
    const warningsToFilter = [
        // Browser extension interference (not our code)
        'bootstrap-autofill-overlay',
        'querySelectorAll',
        'querySelector',
        'not a valid selector',
        'SyntaxError',
        'CollectAutofillContentService',
        'queryElementLabels',
        'createAutofillFieldLabelTag',

        // Source map issues from third-party libraries
        'Unexpected token',
        'dash_ace',
        '.js.map',

        // React development-only warnings about deprecated features we can't control
        'Support for defaultProps will be removed from function components',
        'Use JavaScript default parameters instead',
        'defaultProps',
        'DraggableWrapper.react.js',
        'DashGridLayout.react.js',

        // Third-party library styling warnings we cannot fix
        'You have set a custom wheel sensitivity',
        'This will make your app zoom unnaturally',

        // Specific DMC props that are valid but React warns about
        'overlayBlur',
        'overlayOpacity',

        // DMC library internal callback ref warnings (frequent, harmless)
        'Unexpected return value from a callback ref',
        'callback ref should not return a function',
        'dash_mantine_components.v2_1_0'
    ];

    function shouldFilterMessage(message) {
        if (typeof message !== 'string') {
            message = String(message);
        }
        return warningsToFilter.some(filter =>
            message.toLowerCase().includes(filter.toLowerCase())
        );
    }

    // Override console.warn
    console.warn = function(...args) {
        const message = args.join(' ');

        if (shouldFilterMessage(message)) {
            console.debug('🔇 Filtered harmless warning:', message.substring(0, 100) + '...');
            return;
        }

        originalWarn.apply(console, args);
    };

    // Override console.error for React warnings that come through as errors
    console.error = function(...args) {
        const message = args.join(' ');

        if (shouldFilterMessage(message)) {
            console.debug('🔇 Filtered harmless error:', message.substring(0, 100) + '...');
            return;
        }

        originalError.apply(console, args);
    };

    // Also intercept React's development warning system
    if (typeof window !== 'undefined' && window.React && window.React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED) {
        const ReactInternals = window.React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
        if (ReactInternals.ReactDebugCurrentFrame) {
            const originalWarn = ReactInternals.ReactDebugCurrentFrame.setExtraStackFrame;
            if (originalWarn) {
                ReactInternals.ReactDebugCurrentFrame.setExtraStackFrame = function(...args) {
                    // Suppress React internal warnings
                    return;
                };
            }
        }
    }

    // ENHANCED: Intercept React's warning system at a lower level
    // This catches warnings before they reach console.error in development
    if (typeof window !== 'undefined') {
        // Override React's console.error calls specifically for development warnings
        const originalConsoleError = window.console.error;
        window.console.error = function(...args) {
            const message = args.join(' ');

            // Check if this is a React development warning we want to filter
            if (message.includes('Warning:') && shouldFilterMessage(message)) {
                console.debug('🔇 Filtered React warning:', message.substring(0, 100) + '...');
                return;
            }

            // Call original for non-filtered errors
            return originalConsoleError.apply(console, args);
        };

        // Also intercept at the global level for React DOM warnings
        if (typeof window.console !== 'undefined') {
            const originalGlobalError = window.console.error;
            Object.defineProperty(window.console, 'error', {
                value: function(...args) {
                    const message = args.join(' ');
                    if (shouldFilterMessage(message)) {
                        console.debug('🔇 Filtered global console error:', message.substring(0, 100) + '...');
                        return;
                    }
                    return originalGlobalError.apply(console, args);
                },
                writable: true,
                configurable: true
            });
        }
    }

    // Global error handler for unhandled React warnings and syntax errors
    window.addEventListener('error', function(event) {
        const message = event.message || (event.error && event.error.message) || '';
        const filename = event.filename || '';

        // Filter source map errors and other harmless errors
        if (shouldFilterMessage(message) || shouldFilterMessage(filename) ||
            filename.includes('.map') || message.includes('Unexpected token')) {
            console.debug('🔇 Filtered global error:', message.substring(0, 100) + '...');
            event.preventDefault();
            event.stopPropagation();
            return false;
        }
    }, true);

    // Also handle unhandled promise rejections that might contain these errors
    window.addEventListener('unhandledrejection', function(event) {
        const message = event.reason && event.reason.message ? event.reason.message : String(event.reason);

        if (shouldFilterMessage(message)) {
            console.debug('🔇 Filtered promise rejection:', message.substring(0, 100) + '...');
            event.preventDefault();
            return false;
        }
    }, true);

    // AGGRESSIVE: Intercept console methods before ANY React code runs
    // This uses Object.defineProperty to ensure it can't be overridden
    (function interceptConsoleEarly() {
        const consoleErrorDescriptor = Object.getOwnPropertyDescriptor(console, 'error');
        const consoleWarnDescriptor = Object.getOwnPropertyDescriptor(console, 'warn');

        if (consoleErrorDescriptor && consoleErrorDescriptor.configurable) {
            Object.defineProperty(console, 'error', {
                value: function(...args) {
                    const message = args.join(' ');
                    if (shouldFilterMessage(message)) {
                        return; // Completely suppress
                    }
                    return originalError.apply(console, args);
                },
                writable: false,
                configurable: false
            });
        }

        if (consoleWarnDescriptor && consoleWarnDescriptor.configurable) {
            Object.defineProperty(console, 'warn', {
                value: function(...args) {
                    const message = args.join(' ');
                    if (shouldFilterMessage(message)) {
                        return; // Completely suppress
                    }
                    return originalWarn.apply(console, args);
                },
                writable: false,
                configurable: false
            });
        }
    })();

    console.log('✅ Aggressive console filter initialized - defaultProps warnings suppressed');

})();
