/**
 * Depictio Dashboard Performance Profiler
 *
 * Manual browser console script to identify performance bottlenecks during dashboard refresh.
 *
 * USAGE:
 * 1. Navigate to dashboard page in browser
 * 2. Open browser DevTools (F12)
 * 3. Go to Console tab
 * 4. Paste this entire script
 * 5. Press F5 to refresh the page
 * 6. Wait for dashboard to fully load
 * 7. Check console for detailed performance breakdown
 *
 * The script will measure:
 * - Navigation timing (DNS, TCP, request, response)
 * - JavaScript execution time
 * - React component mounting
 * - DOM rendering and painting
 * - Callback execution timing
 * - Resource loading timeline
 */

(function() {
    'use strict';

    console.log('🚀 Depictio Performance Profiler initialized');

    const profiler = {
        startTime: performance.now(),
        marks: {},
        componentMounts: [],
        callbackTimes: [],
        resourceTimings: [],

        // Mark a timing point
        mark(label) {
            const timestamp = performance.now();
            this.marks[label] = timestamp;
            console.log(`⏱️  ${label}: ${(timestamp - this.startTime).toFixed(2)}ms`);
            return timestamp;
        },

        // Measure duration between two marks
        measure(startLabel, endLabel) {
            const start = this.marks[startLabel];
            const end = this.marks[endLabel];
            if (start && end) {
                const duration = end - start;
                console.log(`📊 ${startLabel} → ${endLabel}: ${duration.toFixed(2)}ms`);
                return duration;
            }
            return null;
        },

        // Track React component mounts
        observeComponentMounts() {
            const observer = new MutationObserver((mutations) => {
                mutations.forEach(mutation => {
                    mutation.addedNodes.forEach(node => {
                        if (node.nodeType === 1) { // Element node
                            // Track grid items (dashboard components)
                            if (node.classList && node.classList.contains('react-grid-item')) {
                                const timestamp = performance.now();
                                const componentId = node.getAttribute('data-grid') || 'unknown';
                                this.componentMounts.push({
                                    id: componentId,
                                    timestamp: timestamp,
                                    elapsed: timestamp - this.startTime
                                });
                                console.log(`🎨 Component mounted: ${componentId} at ${(timestamp - this.startTime).toFixed(2)}ms`);
                            }

                            // Track card components
                            if (node.id && node.id.includes('card-value')) {
                                const timestamp = performance.now();
                                console.log(`📇 Card rendered: ${node.id} at ${(timestamp - this.startTime).toFixed(2)}ms`);
                            }

                            // Track figure components
                            if (node.classList && node.classList.contains('plotly')) {
                                const timestamp = performance.now();
                                console.log(`📈 Plotly figure rendered at ${(timestamp - this.startTime).toFixed(2)}ms`);
                            }
                        }
                    });
                });
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true
            });

            this.mark('MutationObserver started');
        },

        // Monitor Dash callback network requests
        interceptCallbacks() {
            const originalFetch = window.fetch;
            const self = this;

            window.fetch = function(...args) {
                const startTime = performance.now();
                const url = args[0];

                // Track Dash callback requests
                if (url.includes('_dash-update-component')) {
                    console.log(`🔄 Callback started: ${url.substring(url.lastIndexOf('/') + 1, Math.min(url.length, url.lastIndexOf('/') + 30))}...`);
                }

                return originalFetch.apply(this, args).then(response => {
                    const endTime = performance.now();
                    const duration = endTime - startTime;

                    if (url.includes('_dash-update-component')) {
                        self.callbackTimes.push({
                            url: url,
                            duration: duration,
                            timestamp: endTime
                        });
                        console.log(`✅ Callback completed in ${duration.toFixed(2)}ms`);
                    }

                    return response;
                });
            };

            this.mark('Fetch interceptor installed');
        },

        // Analyze Navigation Timing API
        analyzeNavigationTiming() {
            const nav = performance.getEntriesByType('navigation')[0];
            if (!nav) {
                console.warn('⚠️  Navigation Timing API not available');
                return;
            }

            console.log('\n📡 NAVIGATION TIMING BREAKDOWN:');
            console.log(`  DNS Lookup: ${(nav.domainLookupEnd - nav.domainLookupStart).toFixed(2)}ms`);
            console.log(`  TCP Connection: ${(nav.connectEnd - nav.connectStart).toFixed(2)}ms`);
            console.log(`  Request Time: ${(nav.responseStart - nav.requestStart).toFixed(2)}ms`);
            console.log(`  Response Time: ${(nav.responseEnd - nav.responseStart).toFixed(2)}ms`);
            console.log(`  DOM Processing: ${(nav.domComplete - nav.domLoading).toFixed(2)}ms`);
            console.log(`  DOM Interactive: ${(nav.domInteractive - nav.fetchStart).toFixed(2)}ms`);
            console.log(`  DOM Content Loaded: ${(nav.domContentLoadedEventEnd - nav.fetchStart).toFixed(2)}ms`);
            console.log(`  Load Complete: ${(nav.loadEventEnd - nav.fetchStart).toFixed(2)}ms`);
            console.log(`  Total (from fetchStart): ${(nav.loadEventEnd - nav.fetchStart).toFixed(2)}ms\n`);
        },

        // Analyze Resource Timing
        analyzeResourceTiming() {
            const resources = performance.getEntriesByType('resource');

            console.log('\n📦 RESOURCE LOADING SUMMARY:');

            const byType = {};
            resources.forEach(resource => {
                const type = resource.initiatorType;
                if (!byType[type]) {
                    byType[type] = { count: 0, totalDuration: 0, resources: [] };
                }
                byType[type].count++;
                byType[type].totalDuration += resource.duration;
                byType[type].resources.push({
                    name: resource.name.substring(resource.name.lastIndexOf('/') + 1),
                    duration: resource.duration
                });
            });

            Object.keys(byType).forEach(type => {
                const data = byType[type];
                console.log(`  ${type}: ${data.count} resources, ${data.totalDuration.toFixed(2)}ms total`);

                // Show slowest resources of each type
                const slowest = data.resources.sort((a, b) => b.duration - a.duration).slice(0, 3);
                slowest.forEach(r => {
                    console.log(`    ↳ ${r.name}: ${r.duration.toFixed(2)}ms`);
                });
            });
            console.log('');
        },

        // Wait for dashboard to be fully loaded
        waitForDashboardReady() {
            return new Promise((resolve) => {
                const checkInterval = setInterval(() => {
                    const gridItems = document.querySelectorAll('.react-grid-item');
                    const cards = document.querySelectorAll('[id*="card-value"]');
                    const figures = document.querySelectorAll('.plotly');

                    // Check if we have rendered components
                    if (gridItems.length > 0 && (cards.length > 0 || figures.length > 0)) {
                        clearInterval(checkInterval);
                        const endTime = performance.now();
                        console.log(`\n✨ Dashboard fully loaded at ${(endTime - this.startTime).toFixed(2)}ms`);
                        console.log(`   Grid items: ${gridItems.length}`);
                        console.log(`   Cards: ${cards.length}`);
                        console.log(`   Figures: ${figures.length}\n`);
                        resolve(endTime);
                    }
                }, 100);

                // Timeout after 15 seconds
                setTimeout(() => {
                    clearInterval(checkInterval);
                    console.warn('⚠️  Timeout waiting for dashboard to load');
                    resolve(performance.now());
                }, 15000);
            });
        },

        // Generate final report
        async generateReport() {
            await this.waitForDashboardReady();

            const totalTime = performance.now() - this.startTime;

            console.log('\n' + '='.repeat(80));
            console.log('📊 DEPICTIO PERFORMANCE ANALYSIS REPORT');
            console.log('='.repeat(80));

            console.log(`\n⏱️  TOTAL LOAD TIME: ${totalTime.toFixed(2)}ms (${(totalTime / 1000).toFixed(2)}s)\n`);

            // Navigation timing
            this.analyzeNavigationTiming();

            // Resource timing
            this.analyzeResourceTiming();

            // Component mounting timeline
            console.log('🎨 COMPONENT MOUNTING TIMELINE:');
            if (this.componentMounts.length > 0) {
                this.componentMounts.forEach((mount, idx) => {
                    console.log(`  ${idx + 1}. ${mount.id} at ${mount.elapsed.toFixed(2)}ms`);
                });
                const firstMount = this.componentMounts[0].elapsed;
                const lastMount = this.componentMounts[this.componentMounts.length - 1].elapsed;
                console.log(`  First component: ${firstMount.toFixed(2)}ms`);
                console.log(`  Last component: ${lastMount.toFixed(2)}ms`);
                console.log(`  Mounting duration: ${(lastMount - firstMount).toFixed(2)}ms`);
            } else {
                console.log('  ⚠️  No components detected');
            }
            console.log('');

            // Callback timing
            console.log('🔄 CALLBACK EXECUTION SUMMARY:');
            if (this.callbackTimes.length > 0) {
                const totalCallbackTime = this.callbackTimes.reduce((sum, cb) => sum + cb.duration, 0);
                const avgCallbackTime = totalCallbackTime / this.callbackTimes.length;
                const slowestCallback = this.callbackTimes.reduce((max, cb) => cb.duration > max.duration ? cb : max);

                console.log(`  Total callbacks: ${this.callbackTimes.length}`);
                console.log(`  Total time: ${totalCallbackTime.toFixed(2)}ms`);
                console.log(`  Average time: ${avgCallbackTime.toFixed(2)}ms`);
                console.log(`  Slowest callback: ${slowestCallback.duration.toFixed(2)}ms`);

                // Show top 5 slowest callbacks
                const slowest = [...this.callbackTimes].sort((a, b) => b.duration - a.duration).slice(0, 5);
                console.log('\n  Top 5 slowest callbacks:');
                slowest.forEach((cb, idx) => {
                    const urlPart = cb.url.substring(cb.url.lastIndexOf('/') + 1, Math.min(cb.url.length, cb.url.lastIndexOf('/') + 50));
                    console.log(`    ${idx + 1}. ${cb.duration.toFixed(2)}ms - ${urlPart}...`);
                });
            } else {
                console.log('  ⚠️  No callbacks tracked');
            }
            console.log('');

            // Performance marks
            console.log('🏁 PERFORMANCE MARKS:');
            Object.keys(this.marks).forEach(label => {
                console.log(`  ${label}: ${(this.marks[label] - this.startTime).toFixed(2)}ms`);
            });
            console.log('');

            // Identify bottleneck
            console.log('🔍 BOTTLENECK ANALYSIS:');
            const nav = performance.getEntriesByType('navigation')[0];
            if (nav) {
                const networkTime = nav.responseEnd - nav.fetchStart;
                const domProcessing = nav.domComplete - nav.domLoading;
                const renderingTime = totalTime - nav.loadEventEnd;
                const callbackTime = this.callbackTimes.reduce((sum, cb) => sum + cb.duration, 0);

                console.log(`  Network time: ${networkTime.toFixed(2)}ms (${(networkTime / totalTime * 100).toFixed(1)}%)`);
                console.log(`  DOM processing: ${domProcessing.toFixed(2)}ms (${(domProcessing / totalTime * 100).toFixed(1)}%)`);
                console.log(`  Callback time: ${callbackTime.toFixed(2)}ms (${(callbackTime / totalTime * 100).toFixed(1)}%)`);
                console.log(`  Post-load rendering: ${renderingTime.toFixed(2)}ms (${(renderingTime / totalTime * 100).toFixed(1)}%)`);

                const unaccounted = totalTime - networkTime - callbackTime - renderingTime;
                console.log(`  Unaccounted time: ${unaccounted.toFixed(2)}ms (${(unaccounted / totalTime * 100).toFixed(1)}%)`);

                // Identify primary bottleneck
                const bottlenecks = [
                    { name: 'Network', time: networkTime },
                    { name: 'DOM Processing', time: domProcessing },
                    { name: 'Callbacks', time: callbackTime },
                    { name: 'Rendering', time: renderingTime },
                    { name: 'Unaccounted', time: unaccounted }
                ].sort((a, b) => b.time - a.time);

                console.log(`\n  🎯 PRIMARY BOTTLENECK: ${bottlenecks[0].name} (${bottlenecks[0].time.toFixed(2)}ms, ${(bottlenecks[0].time / totalTime * 100).toFixed(1)}%)`);
            }

            console.log('\n' + '='.repeat(80));
            console.log('📋 Copy this entire console output to share with the development team');
            console.log('='.repeat(80) + '\n');
        }
    };

    // Initialize profiler
    profiler.mark('Profiler initialized');
    profiler.observeComponentMounts();
    profiler.interceptCallbacks();

    // Wait for page load, then generate report
    if (document.readyState === 'complete') {
        profiler.mark('Page already loaded');
        profiler.generateReport();
    } else {
        window.addEventListener('load', () => {
            profiler.mark('Window load event');
            profiler.generateReport();
        });
    }

    // Store profiler in window for manual access
    window.depictioProfiler = profiler;

    console.log('✅ Profiler ready. Refresh the page (F5) to start measurements.');
    console.log('📌 Access profiler manually with: window.depictioProfiler');
})();
