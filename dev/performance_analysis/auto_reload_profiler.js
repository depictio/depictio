/**
 * Auto-Reloading Performance Profiler for Depictio Dashboard
 *
 * This script:
 * 1. Stores monitoring flag in sessionStorage
 * 2. Auto-runs on page load to measure performance
 * 3. Measures two-stage rendering: wrappers (fast) vs content (slow)
 * 4. Reports results to console after content loads
 *
 * USAGE:
 * 1. Paste this script in console on dashboard page
 * 2. Script will auto-activate
 * 3. Press F5 to refresh
 * 4. Wait for dashboard to load (your 5s experience)
 * 5. Check console for timing breakdown
 */

(function() {
    const ACTIVE_KEY = 'depictio_profiler_active';
    const RESULTS_KEY = 'depictio_profiler_results';

    // Check if we're in a fresh load (after F5)
    const navigationTiming = performance.getEntriesByType('navigation')[0];
    const isFreshLoad = navigationTiming && navigationTiming.type === 'reload';

    console.log(`🚀 Depictio Auto-Reload Profiler ${isFreshLoad ? '(FRESH LOAD - F5)' : '(Initial injection)'}`);

    if (!isFreshLoad) {
        // First injection - set flag for monitoring after reload
        sessionStorage.setItem(ACTIVE_KEY, 'true');
        console.log('✅ Profiler activated. Press F5 to refresh and measure performance.');
        console.log('📊 Timing data will be captured automatically on reload.');
        return;
    }

    // Check if profiler should be active
    if (sessionStorage.getItem(ACTIVE_KEY) !== 'true') {
        console.log('⏭️  Profiler not active. Run script again to enable.');
        return;
    }

    // We're in a fresh load - measure performance!
    const startTime = performance.now();
    const measurements = {
        startTime: startTime,
        wrapperTime: null,
        contentStartTime: null,
        contentEndTime: null,
        componentTimings: [],
        callbackTimings: []
    };

    console.log(`⏱️  [${0}ms] Profiler started on fresh page load`);

    // Intercept Dash callbacks to measure timing
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const callbackStart = performance.now();
        const url = args[0];

        if (url && url.includes('_dash-update-component')) {
            const elapsed = (callbackStart - startTime).toFixed(2);
            console.log(`🔄 [${elapsed}ms] Callback started`);
        }

        return originalFetch.apply(this, args).then(response => {
            const callbackEnd = performance.now();
            const callbackDuration = callbackEnd - callbackStart;

            if (url && url.includes('_dash-update-component')) {
                const elapsed = (callbackEnd - startTime).toFixed(2);
                console.log(`✅ [${elapsed}ms] Callback completed (duration: ${callbackDuration.toFixed(2)}ms)`);
                measurements.callbackTimings.push({
                    start: callbackStart - startTime,
                    duration: callbackDuration
                });
            }

            return response;
        });
    };

    // Monitor DOM for component appearance
    let wrappersDetected = false;
    let contentDetectedCards = new Set();
    let contentDetectedFigures = new Set();

    const observer = new MutationObserver(() => {
        const now = performance.now();
        const elapsed = (now - startTime).toFixed(2);

        // Phase 1: Detect wrapper boxes
        const wrapperSelectors = [
            '.react-grid-item',
            '.mantine-Card-root',
            '[class*="card-wrapper"]'
        ];

        let wrapperCount = 0;
        for (const selector of wrapperSelectors) {
            const elements = document.querySelectorAll(selector);
            if (elements.length > 0) {
                wrapperCount = Math.max(wrapperCount, elements.length);
            }
        }

        if (wrapperCount > 0 && !wrappersDetected) {
            wrappersDetected = true;
            measurements.wrapperTime = elapsed;
            console.log(`📦 [${elapsed}ms] PHASE 1: ${wrapperCount} wrapper boxes rendered (FAST)`);
        }

        // Phase 2: Detect content population
        const cards = document.querySelectorAll('[id*="card-value"]');
        const figures = document.querySelectorAll('.plotly .plot-container');

        cards.forEach((card, idx) => {
            const hasContent = card.textContent.trim().length > 0;
            const cardKey = card.id || `card-${idx}`;

            if (hasContent && !contentDetectedCards.has(cardKey)) {
                contentDetectedCards.add(cardKey);
                if (!measurements.contentStartTime) {
                    measurements.contentStartTime = elapsed;
                    console.log(`📊 [${elapsed}ms] PHASE 2 START: First content populated (SLOW PHASE BEGINS)`);
                }
                const timeSinceWrappers = measurements.wrapperTime ? (elapsed - measurements.wrapperTime).toFixed(2) : 'N/A';
                console.log(`  └─ [${elapsed}ms] Card content rendered (${timeSinceWrappers}ms after wrappers)`);
                measurements.componentTimings.push({
                    type: 'card',
                    id: cardKey,
                    time: elapsed,
                    deltaFromWrappers: parseFloat(timeSinceWrappers) || 0
                });
            }
        });

        figures.forEach((fig, idx) => {
            const hasPlot = fig.querySelector('.js-plotly-plot') !== null;
            const figKey = `figure-${idx}`;

            if (hasPlot && !contentDetectedFigures.has(figKey)) {
                contentDetectedFigures.add(figKey);
                if (!measurements.contentStartTime) {
                    measurements.contentStartTime = elapsed;
                    console.log(`📈 [${elapsed}ms] PHASE 2 START: First content populated (SLOW PHASE BEGINS)`);
                }
                const timeSinceWrappers = measurements.wrapperTime ? (elapsed - measurements.wrapperTime).toFixed(2) : 'N/A';
                console.log(`  └─ [${elapsed}ms] Plotly figure rendered (${timeSinceWrappers}ms after wrappers)`);
                measurements.componentTimings.push({
                    type: 'figure',
                    id: figKey,
                    time: elapsed,
                    deltaFromWrappers: parseFloat(timeSinceWrappers) || 0
                });
            }
        });

        // Check if all content is loaded
        const expectedCards = cards.length;
        const expectedFigures = figures.length;
        const totalExpected = expectedCards + expectedFigures;
        const totalDetected = contentDetectedCards.size + contentDetectedFigures.size;

        if (totalExpected > 0 && totalDetected >= totalExpected && !measurements.contentEndTime) {
            measurements.contentEndTime = elapsed;
            generateReport();
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true
    });

    // Fallback: generate report after 15 seconds even if not all content detected
    setTimeout(() => {
        if (!measurements.contentEndTime) {
            console.log('⏱️  Timeout reached - generating report with available data');
            measurements.contentEndTime = (performance.now() - startTime).toFixed(2);
            generateReport();
        }
    }, 15000);

    function generateReport() {
        observer.disconnect();

        const totalTime = parseFloat(measurements.contentEndTime);
        const phase1Time = parseFloat(measurements.wrapperTime) || 0;
        const phase2StartTime = parseFloat(measurements.contentStartTime) || phase1Time;
        const phase2Duration = totalTime - phase2StartTime;

        console.log('\n' + '='.repeat(80));
        console.log('📊 DEPICTIO TWO-STAGE RENDERING REPORT');
        console.log('='.repeat(80));

        console.log(`\n⏱️  TOTAL LOAD TIME: ${totalTime}ms (${(totalTime / 1000).toFixed(2)}s)`);

        console.log(`\n📦 PHASE 1: Wrapper Boxes (Empty containers)`);
        console.log(`   Time to render: ${phase1Time}ms`);
        console.log(`   Percentage: ${((phase1Time / totalTime) * 100).toFixed(1)}%`);
        console.log(`   Status: ${phase1Time < 500 ? '✅ FAST' : '⚠️  SLOW'}`);

        console.log(`\n📊 PHASE 2: Content Population (Card values, Plotly charts)`);
        console.log(`   Start time: ${phase2StartTime}ms`);
        console.log(`   Duration: ${phase2Duration}ms`);
        console.log(`   Percentage: ${((phase2Duration / totalTime) * 100).toFixed(1)}%`);
        console.log(`   Status: ${phase2Duration > 2000 ? '🔴 BOTTLENECK!' : phase2Duration > 1000 ? '⚠️  SLOW' : '✅ FAST'}`);

        console.log(`\n🔄 CALLBACK ANALYSIS:`);
        if (measurements.callbackTimings.length > 0) {
            const totalCallbackTime = measurements.callbackTimings.reduce((sum, cb) => sum + cb.duration, 0);
            const avgCallbackTime = totalCallbackTime / measurements.callbackTimings.length;
            const slowestCallback = measurements.callbackTimings.reduce((max, cb) =>
                cb.duration > max.duration ? cb : max
            );

            console.log(`   Total callbacks: ${measurements.callbackTimings.length}`);
            console.log(`   Total callback time: ${totalCallbackTime.toFixed(2)}ms`);
            console.log(`   Average per callback: ${avgCallbackTime.toFixed(2)}ms`);
            console.log(`   Slowest callback: ${slowestCallback.duration.toFixed(2)}ms`);

            // Timeline of callbacks
            console.log(`\n   Callback timeline:`);
            measurements.callbackTimings.forEach((cb, idx) => {
                console.log(`   ${idx + 1}. Started at ${cb.start.toFixed(2)}ms, duration ${cb.duration.toFixed(2)}ms`);
            });
        } else {
            console.log(`   ⚠️  No callbacks detected`);
        }

        console.log(`\n🎨 COMPONENT RENDERING:`);
        if (measurements.componentTimings.length > 0) {
            console.log(`   Total components: ${measurements.componentTimings.length}`);

            const avgDeltaFromWrappers = measurements.componentTimings.reduce((sum, c) =>
                sum + c.deltaFromWrappers, 0) / measurements.componentTimings.length;

            console.log(`   Avg time after wrappers: ${avgDeltaFromWrappers.toFixed(2)}ms`);

            // First vs last component
            const firstComponent = measurements.componentTimings[0];
            const lastComponent = measurements.componentTimings[measurements.componentTimings.length - 1];

            console.log(`   First component: ${firstComponent.type} at ${firstComponent.time}ms`);
            console.log(`   Last component: ${lastComponent.type} at ${lastComponent.time}ms`);
            console.log(`   Rendering spread: ${(parseFloat(lastComponent.time) - parseFloat(firstComponent.time)).toFixed(2)}ms`);
        } else {
            console.log(`   ⚠️  No components detected`);
        }

        console.log(`\n🎯 BOTTLENECK IDENTIFICATION:`);
        if (phase2Duration > totalTime * 0.7) {
            console.log(`   🔴 PRIMARY BOTTLENECK: Phase 2 (Content Population)`);
            console.log(`      - ${phase2Duration}ms spent populating content`);
            console.log(`      - This is ${((phase2Duration / totalTime) * 100).toFixed(1)}% of total load time`);

            if (measurements.callbackTimings.length > 0) {
                const totalCallbackTime = measurements.callbackTimings.reduce((sum, cb) => sum + cb.duration, 0);
                const callbackPercent = (totalCallbackTime / phase2Duration) * 100;

                console.log(`\n   🔍 Breakdown of Phase 2:`);
                console.log(`      - Callback network time: ${totalCallbackTime.toFixed(2)}ms (${callbackPercent.toFixed(1)}%)`);
                console.log(`      - Other (render, deserialize): ${(phase2Duration - totalCallbackTime).toFixed(2)}ms (${(100 - callbackPercent).toFixed(1)}%)`);

                if (callbackPercent > 60) {
                    console.log(`\n   💡 RECOMMENDATION: Network callbacks are the bottleneck`);
                    console.log(`      Consider: Request batching, parallel callbacks, or caching`);
                } else {
                    console.log(`\n   💡 RECOMMENDATION: Client-side processing is the bottleneck`);
                    console.log(`      Consider: Optimize rendering logic, reduce DOM operations`);
                }
            }
        } else {
            console.log(`   ✅ No obvious bottleneck - performance is balanced`);
        }

        console.log('\n' + '='.repeat(80));
        console.log('💾 Copy this report to share with the development team');
        console.log('='.repeat(80) + '\n');

        // Store results in sessionStorage for retrieval
        sessionStorage.setItem(RESULTS_KEY, JSON.stringify(measurements, null, 2));
        console.log('📌 Results saved to sessionStorage["depictio_profiler_results"]');
    }

    console.log('\n✅ Profiler active - monitoring two-stage rendering...');
})();
