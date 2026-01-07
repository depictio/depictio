/**
 * Client-Side Performance Monitor
 *
 * Measures the gap between server-side execution and browser-perceived performance:
 * - HTTP round-trip time
 * - JSON deserialization time
 * - React rendering time
 *
 * This complements server-side Python profiling to identify where time is really spent.
 */

(function() {
    'use strict';

    // Performance data store
    const performanceData = {
        callbacks: {},
        renders: []
    };

    // Intercept Dash callback requests
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const url = args[0];

        // Only track Dash callback requests
        if (typeof url === 'string' && url.includes('_dash-update-component')) {
            const callbackId = extractCallbackId(url);
            const startTime = performance.now();

            console.log(`⏱️ CLIENT PROFILING: Callback ${callbackId} - Request sent`);

            return originalFetch.apply(this, args).then(response => {
                const networkTime = performance.now() - startTime;

                // Only parse JSON responses (check Content-Type header)
                const contentType = response.headers.get('content-type');
                const isJson = contentType && contentType.includes('application/json');

                if (!isJson) {
                    // Non-JSON response, skip profiling
                    return response;
                }

                // Clone response to read body without consuming it
                return response.clone().json().then(data => {
                    const deserializeEnd = performance.now();
                    const deserializeTime = deserializeEnd - (startTime + networkTime);

                    // Calculate payload size
                    const payloadSize = new Blob([JSON.stringify(data)]).size;

                    // Store performance data
                    performanceData.callbacks[callbackId] = {
                        startTime: startTime,
                        networkTime: networkTime,
                        deserializeTime: deserializeTime,
                        payloadSize: payloadSize,
                        timestamp: new Date().toISOString()
                    };

                    console.log(
                        `⏱️ CLIENT PROFILING: Callback ${callbackId} - Network: ${networkTime.toFixed(1)}ms, ` +
                        `Deserialize: ${deserializeTime.toFixed(1)}ms, ` +
                        `Payload: ${(payloadSize / 1024).toFixed(1)}KB`
                    );

                    // Schedule render time measurement
                    requestAnimationFrame(() => {
                        measureRenderTime(callbackId, deserializeEnd);
                    });

                    return response;
                }).catch(err => {
                    // JSON parse error - likely not a callback response
                    console.debug(`⏱️ CLIENT PROFILING: Skipped non-JSON response for ${callbackId}`);
                    return response;
                });
            });
        }

        return originalFetch.apply(this, args);
    };

    function extractCallbackId(url) {
        // Extract meaningful callback identifier from URL
        const match = url.match(/output=([^&]+)/);
        return match ? decodeURIComponent(match[1]) : 'unknown';
    }

    function measureRenderTime(callbackId, deserializeEndTime) {
        // Use MutationObserver to detect DOM changes
        let renderComplete = false;
        const renderStart = performance.now();

        const observer = new MutationObserver((mutations) => {
            if (!renderComplete && mutations.length > 0) {
                renderComplete = true;
                const renderEnd = performance.now();
                const renderTime = renderEnd - renderStart;
                const totalTime = renderEnd - deserializeEndTime;

                performanceData.renders.push({
                    callbackId: callbackId,
                    renderTime: renderTime,
                    mutationCount: mutations.length,
                    timestamp: new Date().toISOString()
                });

                console.log(
                    `⏱️ CLIENT PROFILING: Callback ${callbackId} - Render: ${renderTime.toFixed(1)}ms, ` +
                    `Mutations: ${mutations.length}, ` +
                    `Total (deserialize + render): ${totalTime.toFixed(1)}ms`
                );

                // Print total breakdown
                const callbackData = performanceData.callbacks[callbackId];
                if (callbackData) {
                    const total = callbackData.networkTime + callbackData.deserializeTime + renderTime;
                    console.log(
                        `⏱️ CLIENT PROFILING: Callback ${callbackId} - TOTAL BREAKDOWN:\n` +
                        `  Network: ${callbackData.networkTime.toFixed(1)}ms (${(callbackData.networkTime / total * 100).toFixed(1)}%)\n` +
                        `  Deserialize: ${callbackData.deserializeTime.toFixed(1)}ms (${(callbackData.deserializeTime / total * 100).toFixed(1)}%)\n` +
                        `  Render: ${renderTime.toFixed(1)}ms (${(renderTime / total * 100).toFixed(1)}%)\n` +
                        `  TOTAL: ${total.toFixed(1)}ms\n` +
                        `  Payload: ${(callbackData.payloadSize / 1024).toFixed(1)}KB`
                    );
                }

                observer.disconnect();
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            characterData: true
        });

        // Disconnect after 2 seconds if no mutations detected
        setTimeout(() => {
            if (!renderComplete) {
                observer.disconnect();
                console.log(`⏱️ CLIENT PROFILING: Callback ${callbackId} - No render detected (timeout)`);
            }
        }, 2000);
    }

    // Expose performance data for debugging
    window.depictioPerformance = {
        getData: () => performanceData,
        getCallbackStats: (callbackId) => performanceData.callbacks[callbackId],
        getSummary: () => {
            const callbacks = Object.values(performanceData.callbacks);
            if (callbacks.length === 0) return null;

            const totalNetwork = callbacks.reduce((sum, c) => sum + c.networkTime, 0);
            const totalDeserialize = callbacks.reduce((sum, c) => sum + c.deserializeTime, 0);
            const totalPayload = callbacks.reduce((sum, c) => sum + c.payloadSize, 0);

            return {
                callbackCount: callbacks.length,
                avgNetworkTime: totalNetwork / callbacks.length,
                avgDeserializeTime: totalDeserialize / callbacks.length,
                totalPayloadKB: totalPayload / 1024,
                avgPayloadKB: totalPayload / 1024 / callbacks.length
            };
        },
        clear: () => {
            performanceData.callbacks = {};
            performanceData.renders = [];
            console.log('⏱️ CLIENT PROFILING: Performance data cleared');
        }
    };

    console.log('⏱️ CLIENT PROFILING: Performance monitor initialized');
    console.log('⏱️ CLIENT PROFILING: Use window.depictioPerformance.getSummary() to view stats');
})();
