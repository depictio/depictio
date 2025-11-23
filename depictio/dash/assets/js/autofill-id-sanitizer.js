/**
 * Autofill ID Sanitizer for Dash Pattern-Matching Components
 *
 * This script fixes browser autofill extension issues with Dash pattern-matching IDs.
 * The problem: Browser extensions try to parse JSON-structured IDs as CSS selectors,
 * which fails due to unescaped quotes and braces.
 *
 * Solution: Replace problematic JSON IDs with CSS-safe alternatives in the DOM,
 * while preserving Dash callback functionality.
 */

(function() {
    'use strict';

    // Track the original IDs for Dash callback mapping if needed
    window.dashOriginalIds = window.dashOriginalIds || new Map();

    /**
     * Convert a pattern-matching ID to a CSS-safe string
     * @param {string} originalId - Original JSON-structured ID
     * @returns {string} - CSS-safe ID
     */
    function createSafeId(originalId) {
        try {
            // Parse the JSON ID to extract type and index
            const idObj = JSON.parse(originalId);
            const type = (idObj.type || 'component').replace(/-/g, '_');
            const index = (idObj.index || '').replace(/[-_]/g, '');
            return `dash_${type}_${index}`;
        } catch (e) {
            // If it's not JSON, just sanitize it
            return originalId.replace(/[-_{}",:\s]/g, '');
        }
    }

    /**
     * Sanitize element IDs that contain JSON structures
     */
    function sanitizePatternMatchingIds() {
        // Find all elements with JSON-like IDs (containing braces and quotes)
        // Handle both escaped and unescaped quote patterns
        const selectors = [
            '[id*="{\\"type\\""]',     // Escaped quotes: {"type":
            '[id*=\'{"type"\']',       // Single quotes with double quotes inside: {"type"
            '[id*=\'{"index"\']',      // Single quotes with index: {"index"
            '[id*="{\\"index\\""]'    // Escaped quotes with index: {"index"
        ];

        let elementsWithJsonIds = new Set();

        // Try each selector and combine results
        selectors.forEach(selector => {
            try {
                const elements = document.querySelectorAll(selector);
                elements.forEach(el => elementsWithJsonIds.add(el));
            } catch (e) {
                // Skip invalid selectors
                console.debug(`Skipping selector "${selector}": ${e.message}`);
            }
        });

        // Also find elements by scanning all IDs for JSON-like patterns
        const allElementsWithId = document.querySelectorAll('[id]');
        allElementsWithId.forEach(element => {
            const id = element.id;
            if (id && (id.includes('{"type"') || id.includes('{"index"'))) {
                elementsWithJsonIds.add(element);
            }
        });

        let sanitizedCount = 0;

        elementsWithJsonIds.forEach((element) => {
            const originalId = element.id;

            // Skip if already processed
            if (originalId.startsWith('dash_')) {
                return;
            }

            const safeId = createSafeId(originalId);

            // Store the mapping for potential future reference
            window.dashOriginalIds.set(safeId, originalId);
            window.dashOriginalIds.set(originalId, safeId);

            // Update the element ID
            element.id = safeId;

            // Update any labels pointing to this element
            // Use a safer approach since originalId might contain special characters
            try {
                const associatedLabels = document.querySelectorAll(`label[for="${originalId}"]`);
                associatedLabels.forEach(label => {
                    label.setAttribute('for', safeId);
                });
            } catch (e) {
                // If the selector fails, find labels manually
                const allLabels = document.querySelectorAll('label[for]');
                allLabels.forEach(label => {
                    if (label.getAttribute('for') === originalId) {
                        label.setAttribute('for', safeId);
                    }
                });
            }

            sanitizedCount++;
        });

        if (sanitizedCount > 0) {
            console.debug(`🔧 Sanitized ${sanitizedCount} pattern-matching IDs for autofill compatibility`);
        } else if (elementsWithJsonIds.size > 0) {
            console.debug(`⚠️ Found ${elementsWithJsonIds.size} elements with JSON IDs but none were sanitized (already processed?)`);
        }
    }

    /**
     * Set up mutation observer to handle dynamically added elements
     */
    function setupMutationObserver() {
        const observer = new MutationObserver((mutations) => {
            let shouldSanitize = false;

            mutations.forEach((mutation) => {
                // Check for added nodes
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            // CRITICAL: Check for label elements with JSON 'for' attributes
                            // This catches DMC components creating labels before browser extensions query them
                            if (node.tagName === 'LABEL') {
                                const forAttr = node.getAttribute('for');
                                if (forAttr && (forAttr.includes('{"type"') || forAttr.includes('{"index"'))) {
                                    // Sanitize the label's 'for' attribute immediately
                                    const safeId = createSafeId(forAttr);
                                    node.setAttribute('for', safeId);
                                    console.debug('🏷️ Sanitized label[for] immediately:', forAttr, '->', safeId);
                                }
                            }

                            // Check if the added element or its children have JSON IDs
                            if (node.id && (node.id.includes('{"type"') || node.id.includes('{"index"'))) {
                                shouldSanitize = true;
                            } else if (node.querySelectorAll) {
                                // Check children for JSON-like IDs
                                const childrenWithJsonIds = node.querySelectorAll('[id]');
                                for (let child of childrenWithJsonIds) {
                                    if (child.id && (child.id.includes('{"type"') || child.id.includes('{"index"'))) {
                                        shouldSanitize = true;
                                        break;
                                    }
                                }

                                // Also check for labels with JSON 'for' attributes
                                const labelsWithJsonFor = node.querySelectorAll('label[for]');
                                labelsWithJsonFor.forEach(label => {
                                    const forAttr = label.getAttribute('for');
                                    if (forAttr && (forAttr.includes('{"type"') || forAttr.includes('{"index"'))) {
                                        const safeId = createSafeId(forAttr);
                                        label.setAttribute('for', safeId);
                                        console.debug('🏷️ Sanitized label[for] from children:', forAttr, '->', safeId);
                                    }
                                });
                            }
                        }
                    });
                }

                // Check for ID attribute changes
                if (mutation.type === 'attributes' && mutation.attributeName === 'id') {
                    const newId = mutation.target.getAttribute('id');
                    if (newId && (newId.includes('{"type"') || newId.includes('{"index"'))) {
                        shouldSanitize = true;
                    }
                }

                // CRITICAL: Monitor label 'for' attribute changes
                if (mutation.type === 'attributes' && mutation.attributeName === 'for') {
                    const forAttr = mutation.target.getAttribute('for');
                    if (forAttr && (forAttr.includes('{"type"') || forAttr.includes('{"index"'))) {
                        const safeId = createSafeId(forAttr);
                        mutation.target.setAttribute('for', safeId);
                        console.debug('🏷️ Sanitized label[for] attribute change:', forAttr, '->', safeId);
                    }
                }
            });

            if (shouldSanitize) {
                // Use requestIdleCallback for better performance
                if (window.requestIdleCallback) {
                    window.requestIdleCallback(sanitizePatternMatchingIds);
                } else {
                    setTimeout(sanitizePatternMatchingIds, 0);
                }
            }
        });

        // Start observing
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['id', 'for']  // Monitor both 'id' and 'for' attributes
        });

        return observer;
    }

    /**
     * Initialize the ID sanitization system
     */
    function initialize() {
        console.log('🔧 Initializing autofill ID sanitizer for Dash pattern-matching components');

        // Initial sanitization
        sanitizePatternMatchingIds();

        // Set up observer for dynamic content
        setupMutationObserver();

        // Also override querySelectorAll to catch problematic selectors in real-time
        interceptQuerySelectorAll();

        console.log('✅ Autofill ID sanitizer initialized successfully');
    }

    /**
     * Intercept querySelectorAll calls to prevent CSS selector errors
     */
    function interceptQuerySelectorAll() {
        const originalQuerySelectorAll = Document.prototype.querySelectorAll;

        Document.prototype.querySelectorAll = function(selector) {
            try {
                // Check if selector contains problematic JSON patterns
                if (selector && typeof selector === 'string' && selector.includes('{"')) {
                    console.debug('🛡️ Intercepted problematic selector:', selector);

                    // Try to fix the selector by escaping quotes
                    let fixedSelector = selector.replace(/"/g, '\\"');

                    try {
                        return originalQuerySelectorAll.call(this, fixedSelector);
                    } catch (e) {
                        console.debug('🚫 Fixed selector still invalid, returning empty result');
                        return document.createDocumentFragment().querySelectorAll('*');
                    }
                }

                return originalQuerySelectorAll.call(this, selector);
            } catch (error) {
                console.debug('🚫 Query selector error intercepted:', error.message);
                // Return empty NodeList instead of throwing
                return document.createDocumentFragment().querySelectorAll('*');
            }
        };

        console.debug('🛡️ querySelectorAll interceptor installed');
    }

    // CRITICAL: Install interceptor IMMEDIATELY, before DOM is ready
    // This needs to happen before any other scripts can call querySelectorAll
    interceptQuerySelectorAll();

    // Also install global error handler to catch any missed selector errors
    window.addEventListener('error', function(event) {
        if (event.error && event.error.message &&
            event.error.message.includes('querySelectorAll') &&
            event.error.message.includes('not a valid selector')) {
            console.log('🚨 Caught autofill selector error:', event.error.message);
            // Try to sanitize immediately
            setTimeout(sanitizePatternMatchingIds, 0);
            // Prevent error from reaching console
            event.preventDefault();
            return false;
        }
    }, true);

    // CRITICAL: Handle Promise rejections from browser extensions (e.g., bootstrap-autofill-overlay)
    // These async errors bypass the synchronous error handler above
    window.addEventListener('unhandledrejection', function(event) {
        if (event.reason && event.reason.message) {
            const message = event.reason.message;
            // Check for autofill/querySelectorAll errors
            if ((message.includes('querySelectorAll') || message.includes('querySelector')) &&
                (message.includes('not a valid selector') || message.includes('SyntaxError'))) {
                console.debug('🚨 Caught async autofill selector error (Promise):', message);
                // Try to sanitize immediately
                setTimeout(sanitizePatternMatchingIds, 0);
                // Prevent error from reaching console
                event.preventDefault();
                return false;
            }
        }
    });

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }

    // Also run after delays to catch any late-loading components
    setTimeout(initialize, 1000);
    setTimeout(sanitizePatternMatchingIds, 2000);
    setTimeout(sanitizePatternMatchingIds, 5000);

    // Also trigger on page visibility change (useful for SPAs)
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            setTimeout(sanitizePatternMatchingIds, 100);
        }
    });

})();
