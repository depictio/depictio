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

    // ENABLED: Client-side performance monitoring active
    // Remove the early return to enable profiling
    // return;

    // Performance data store
    const performanceData = {
        callbacks: {},
        renders: []
    };

    // Intercept Dash callback requests
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const url = args[0];
        const options = args[1] || {};

        // Only track Dash callback requests
        if (typeof url === 'string' && url.includes('_dash-update-component')) {
            const startTime = performance.now();

            // Parse request body to extract callback details
            let requestBody = null;
            let inputs = [];
            let state = [];

            if (options.body) {
                try {
                    requestBody = JSON.parse(options.body);
                    inputs = requestBody.inputs || [];
                    state = requestBody.state || [];
                } catch (e) {
                    // Unable to parse request body
                }
            }

            // Extract outputs from URL
            const outputs = extractOutputs(url);
            const callbackId = outputs.length > 0 ? outputs[0].id : extractCallbackId(url);

            // Create detailed callback info
            const callbackInfo = {
                url: url,
                outputs: outputs,
                inputs: inputs.map(inp => ({
                    id: inp.id,
                    property: inp.property,
                    value: truncateValue(inp.value)
                })),
                state: state.map(st => ({
                    id: st.id,
                    property: st.property
                }))
            };

            console.log(`⏱️ CLIENT PROFILING: Callback Request`);
            console.log(`  📤 Outputs: ${outputs.map(o => `${o.id}.${o.property}`).join(', ')}`);
            console.log(`  📥 Inputs: ${callbackInfo.inputs.map(i => `${i.id}.${i.property}`).join(', ')}`);
            if (callbackInfo.state.length > 0) {
                console.log(`  📋 State: ${callbackInfo.state.map(s => `${s.id}.${s.property}`).join(', ')}`);
            }

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

                    // Analyze response structure
                    const responseInfo = analyzeResponse(data);

                    // Store performance data
                    performanceData.callbacks[callbackId] = {
                        startTime: startTime,
                        networkTime: networkTime,
                        deserializeTime: deserializeTime,
                        payloadSize: payloadSize,
                        timestamp: new Date().toISOString(),
                        callbackInfo: callbackInfo,
                        responseInfo: responseInfo
                    };

                    console.log(
                        `⏱️ CLIENT PROFILING: Callback Response\n` +
                        `  ⏱️  Network: ${networkTime.toFixed(1)}ms, ` +
                        `Deserialize: ${deserializeTime.toFixed(1)}ms, ` +
                        `Payload: ${(payloadSize / 1024).toFixed(1)}KB\n` +
                        `  📦 Response: ${responseInfo.summary}`
                    );

                    // Schedule render time measurement
                    requestAnimationFrame(() => {
                        measureRenderTime(callbackId, deserializeEnd, callbackInfo, responseInfo);
                    });

                    return response;
                }).catch(err => {
                    // JSON parse error - likely not a callback response
                    console.debug(`⏱️ CLIENT PROFILING: Skipped non-JSON response`);
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

    function extractOutputs(url) {
        // Extract output components from URL
        const match = url.match(/output=([^&]+)/);
        if (!match) return [];

        try {
            const decoded = decodeURIComponent(match[1]);
            const outputs = JSON.parse(decoded);
            return Array.isArray(outputs) ? outputs : [outputs];
        } catch (e) {
            return [];
        }
    }

    function truncateValue(value) {
        // Truncate large values for display
        if (value === null || value === undefined) return value;
        const str = JSON.stringify(value);
        return str.length > 50 ? str.substring(0, 50) + '...' : str;
    }

    function analyzeResponse(data) {
        // Analyze response payload structure
        if (!data || !data.response) {
            return { summary: 'Empty response', details: {} };
        }

        const response = data.response;
        const keys = Object.keys(response);

        const details = {};
        let totalItems = 0;

        keys.forEach(key => {
            const value = response[key];
            if (Array.isArray(value)) {
                details[key] = `Array[${value.length}]`;
                totalItems += value.length;
            } else if (value && typeof value === 'object') {
                const objKeys = Object.keys(value);
                details[key] = `Object{${objKeys.length} keys}`;
                totalItems += objKeys.length;
            } else if (typeof value === 'string') {
                details[key] = `String[${value.length} chars]`;
            } else {
                details[key] = typeof value;
            }
        });

        const summary = keys.length > 0
            ? `${keys.length} output(s): ${keys.map(k => `${k}=${details[k]}`).join(', ')}`
            : 'No outputs';

        return { summary, details, totalItems };
    }

    function measureRenderTime(callbackId, deserializeEndTime, callbackInfo, responseInfo) {
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
                    `⏱️ CLIENT PROFILING: Callback Render Complete\n` +
                    `  🎨 Render: ${renderTime.toFixed(1)}ms, ` +
                    `Mutations: ${mutations.length}`
                );

                // Print total breakdown
                const callbackData = performanceData.callbacks[callbackId];
                if (callbackData) {
                    const total = callbackData.networkTime + callbackData.deserializeTime + renderTime;
                    console.log(
                        `⏱️ CLIENT PROFILING: COMPLETE BREAKDOWN\n` +
                        `  📤 Output: ${callbackInfo.outputs.map(o => `${o.id}.${o.property}`).join(', ')}\n` +
                        `  📥 Input:  ${callbackInfo.inputs.map(i => `${i.id}.${i.property}=${i.value}`).join(', ')}\n` +
                        `  ⏱️  Timing:\n` +
                        `     Network:     ${callbackData.networkTime.toFixed(1)}ms (${(callbackData.networkTime / total * 100).toFixed(1)}%)\n` +
                        `     Deserialize: ${callbackData.deserializeTime.toFixed(1)}ms (${(callbackData.deserializeTime / total * 100).toFixed(1)}%)\n` +
                        `     Render:      ${renderTime.toFixed(1)}ms (${(renderTime / total * 100).toFixed(1)}%)\n` +
                        `     TOTAL:       ${total.toFixed(1)}ms\n` +
                        `  📦 Payload: ${(callbackData.payloadSize / 1024).toFixed(1)}KB - ${responseInfo.summary}`
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
                console.log(`⏱️ CLIENT PROFILING: No render detected (timeout) for ${callbackInfo.outputs.map(o => o.id).join(', ')}`);
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
