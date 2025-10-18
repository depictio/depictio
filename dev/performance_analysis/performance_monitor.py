#!/usr/bin/env python3
"""
Dashboard Performance Monitor
Captures network requests, console logs, and performance metrics during dashboard load
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

DASHBOARD_URL = "http://localhost:5080/dashboard/68f0f80e913db3d98f48122d"
DASHBOARD_URL = "http://localhost:5080/dashboard/6824cb3b89d2b72169309737"  # Large dashboard with many callbacks

# API credentials for automatic authentication
API_BASE_URL = "http://localhost:8058/depictio/api/v1"
API_USERNAME = "admin@example.com"
API_PASSWORD = "changeme"


async def get_auth_token():
    """
    Authenticate via API and return local-store compatible token data.

    Returns:
        dict: Authentication data ready for localStorage injection
    """
    print(f"[{datetime.now().isoformat()}] Authenticating with API...")

    async with httpx.AsyncClient() as client:
        # Login via API
        login_response = await client.post(
            f"{API_BASE_URL}/auth/login",
            data={"username": API_USERNAME, "password": API_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if login_response.status_code != 200:
            raise Exception(f"Login failed: {login_response.status_code} - {login_response.text}")

        token_data = login_response.json()
        print(f"[{datetime.now().isoformat()}] ✅ Authentication successful!")
        print(f"   User ID: {token_data.get('user_id')}")
        print(f"   Token expires: {token_data.get('expire_datetime')}")

        # Add logged_in flag for Dash compatibility
        token_data["logged_in"] = True

        return token_data


class PerformanceMonitor:
    def __init__(self):
        self.network_requests = []
        self.console_logs = []
        self.performance_metrics = {}
        self.start_time = None

    async def monitor_dashboard_load(self):
        """Monitor dashboard loading with full performance capture"""

        async with async_playwright() as p:
            # Launch browser with debugging enabled
            browser = await p.chromium.launch(
                headless=False, args=["--disable-blink-features=AutomationControlled"]
            )

            context = await browser.new_context(viewport={"width": 1920, "height": 1080})

            page = await context.new_page()

            # Set up request monitoring with POST data capture
            async def handle_request(request):
                request_data = {
                    "timestamp": datetime.now().isoformat(),
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "headers": dict(request.headers) if request.headers else {},
                }

                # Capture POST body for Dash callbacks
                if "_dash-update-component" in request.url and request.method == "POST":
                    try:
                        request_data["post_data"] = request.post_data
                    except Exception:
                        request_data["post_data"] = None

                self.network_requests.append(request_data)

            page.on("request", handle_request)

            # Set up response monitoring
            async def handle_response(response):
                try:
                    timing = await response.request.timing()
                    body = await response.body() if response.ok else b""
                    size = len(body)
                except Exception:
                    timing = None
                    size = 0
                    body = b""

                response_data = {
                    "timestamp": datetime.now().isoformat(),
                    "type": "response",
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "size": size,
                    "timing": {
                        "dns": timing.get("domainLookupEnd", 0) - timing.get("domainLookupStart", 0)
                        if timing
                        else 0,
                        "connect": timing.get("connectEnd", 0) - timing.get("connectStart", 0)
                        if timing
                        else 0,
                        "request": timing.get("responseStart", 0) - timing.get("requestStart", 0)
                        if timing
                        else 0,
                        "response": timing.get("responseEnd", 0) - timing.get("responseStart", 0)
                        if timing
                        else 0,
                        "total": timing.get("responseEnd", 0) if timing else 0,
                    }
                    if timing
                    else None,
                }

                # Capture response body for Dash callbacks
                if "_dash-update-component" in response.url and body and size > 0:
                    try:
                        response_data["response_body"] = body.decode("utf-8")
                    except Exception:
                        response_data["response_body"] = None

                self.network_requests.append(response_data)

            page.on("response", handle_response)

            # Set up console monitoring
            page.on(
                "console",
                lambda msg: self.console_logs.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "type": msg.type,
                        "text": msg.text,
                        "location": msg.location,
                    }
                ),
            )

            # Get fresh authentication token
            auth_token = await get_auth_token()

            # Navigate to auth page first
            print(f"[{datetime.now().isoformat()}] Navigating to auth page...")
            await page.goto("http://localhost:5080/auth")

            # Inject authentication
            print(f"[{datetime.now().isoformat()}] Injecting authentication...")
            await page.evaluate(
                f"localStorage.setItem('local-store', JSON.stringify({json.dumps(auth_token)}))"
            )

            # Clear captured data before dashboard load
            self.network_requests = []
            self.console_logs = []
            self.start_time = datetime.now()

            # Navigate to dashboard
            print(f"[{datetime.now().isoformat()}] Loading dashboard...")
            await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=60000)

            # Wait for user to indicate dashboard is fully loaded
            print(f"\n[{datetime.now().isoformat()}] Dashboard loaded!")
            print("=" * 80)
            print("WAIT for all callbacks to complete, then press ENTER to capture metrics...")
            print("=" * 80)
            await asyncio.get_event_loop().run_in_executor(None, input)

            # Capture performance metrics (including client-side profiling data)
            print(f"\n[{datetime.now().isoformat()}] Capturing performance metrics...")
            self.performance_metrics = await page.evaluate("""
                () => {
                    const perfData = performance.getEntriesByType('navigation')[0];
                    const paintData = performance.getEntriesByType('paint');
                    const resourceData = performance.getEntriesByType('resource');

                    return {
                        navigation: {
                            domContentLoaded: perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart,
                            domComplete: perfData.domComplete,
                            loadComplete: perfData.loadEventEnd,
                            totalLoadTime: perfData.loadEventEnd - perfData.fetchStart
                        },
                        paint: {
                            firstPaint: paintData.find(p => p.name === 'first-paint')?.startTime || 0,
                            firstContentfulPaint: paintData.find(p => p.name === 'first-contentful-paint')?.startTime || 0
                        },
                        resources: {
                            totalResources: resourceData.length,
                            totalTransferSize: resourceData.reduce((sum, r) => sum + (r.transferSize || 0), 0),
                            totalDuration: resourceData.reduce((sum, r) => sum + r.duration, 0)
                        },
                        memory: performance.memory ? {
                            usedJSHeapSize: performance.memory.usedJSHeapSize,
                            totalJSHeapSize: performance.memory.totalJSHeapSize,
                            jsHeapSizeLimit: performance.memory.jsHeapSizeLimit
                        } : null,
                        clientSideProfiling: window.depictioPerformance ? window.depictioPerformance.getData() : null
                    }
                }
            """)

            # Generate report
            self.generate_report()

            print(
                f"\n[{datetime.now().isoformat()}] Monitoring complete. Browser will stay open for inspection."
            )
            print("Press Ctrl+C to close...")

            try:
                await asyncio.sleep(3600)  # Keep browser open
            except KeyboardInterrupt:
                pass

            await browser.close()

    def generate_report(self):
        """Generate performance analysis report"""

        print("\n" + "=" * 80)
        print("DASHBOARD LOAD PERFORMANCE REPORT")
        print("=" * 80)

        # Network Analysis
        print("\n📊 NETWORK REQUESTS ANALYSIS")
        print("-" * 80)

        api_requests = [r for r in self.network_requests if "depictio/api" in r.get("url", "")]

        if api_requests:
            print(f"\nTotal API Requests: {len(api_requests)}")

            # Group by endpoint
            from collections import defaultdict

            endpoints = defaultdict(list)
            for req in api_requests:
                if req.get("type") == "response":
                    url = req["url"].split("?")[0]  # Remove query params
                    endpoint = (
                        url.split("/depictio/api/v1/")[-1] if "/depictio/api/v1/" in url else url
                    )
                    endpoints[endpoint].append(req)

            # Analyze slowest endpoints
            print("\n🐌 SLOWEST API ENDPOINTS:")
            endpoint_stats = []
            for endpoint, responses in endpoints.items():
                avg_time = sum(r.get("timing", {}).get("total", 0) for r in responses) / len(
                    responses
                )
                total_size = sum(r.get("size", 0) for r in responses)
                endpoint_stats.append(
                    {
                        "endpoint": endpoint,
                        "count": len(responses),
                        "avg_time": avg_time,
                        "total_size": total_size,
                    }
                )

            endpoint_stats.sort(key=lambda x: x["avg_time"], reverse=True)

            for i, stat in enumerate(endpoint_stats[:10], 1):
                print(f"\n{i}. {stat['endpoint']}")
                print(f"   - Calls: {stat['count']}")
                print(f"   - Avg Time: {stat['avg_time']:.2f}ms")
                print(f"   - Total Size: {stat['total_size'] / 1024:.2f}KB")

        # Console Logs Analysis
        print("\n\n📝 CONSOLE LOGS ANALYSIS")
        print("-" * 80)

        errors = [log for log in self.console_logs if log["type"] == "error"]
        warnings = [log for log in self.console_logs if log["type"] == "warning"]

        print(f"\nTotal Console Messages: {len(self.console_logs)}")
        print(f"Errors: {len(errors)}")
        print(f"Warnings: {len(warnings)}")

        if errors:
            print("\n❌ ERRORS:")
            for error in errors[:10]:
                print(f"  - {error['text'][:100]}")

        if warnings:
            print("\n⚠️  WARNINGS:")
            for warning in warnings[:10]:
                print(f"  - {warning['text'][:100]}")

        # Performance Metrics
        print("\n\n⚡ PERFORMANCE METRICS")
        print("-" * 80)

        nav = self.performance_metrics.get("navigation", {})
        paint = self.performance_metrics.get("paint", {})
        resources = self.performance_metrics.get("resources", {})
        memory = self.performance_metrics.get("memory", {})

        print("\nPage Load Timing:")
        print(f"  - Total Load Time: {nav.get('totalLoadTime', 0):.2f}ms")
        print(f"  - DOM Content Loaded: {nav.get('domContentLoaded', 0):.2f}ms")
        print(f"  - First Paint: {paint.get('firstPaint', 0):.2f}ms")
        print(f"  - First Contentful Paint: {paint.get('firstContentfulPaint', 0):.2f}ms")

        print("\nResource Loading:")
        print(f"  - Total Resources: {resources.get('totalResources', 0)}")
        print(
            f"  - Total Transfer Size: {resources.get('totalTransferSize', 0) / 1024 / 1024:.2f}MB"
        )
        print(f"  - Total Duration: {resources.get('totalDuration', 0):.2f}ms")

        if memory:
            print("\nMemory Usage:")
            print(f"  - Used JS Heap: {memory.get('usedJSHeapSize', 0) / 1024 / 1024:.2f}MB")
            print(f"  - Total JS Heap: {memory.get('totalJSHeapSize', 0) / 1024 / 1024:.2f}MB")

        # Client-Side Profiling Analysis
        client_profiling = self.performance_metrics.get("clientSideProfiling")
        if client_profiling and client_profiling.get("callbacks"):
            print("\n\n🔬 CLIENT-SIDE PROFILING (Network + Deserialize + Render)")
            print("-" * 80)

            callbacks = client_profiling.get("callbacks", {})
            renders = client_profiling.get("renders", [])

            if callbacks:
                print(f"\nTotal Callbacks Profiled: {len(callbacks)}")

                # Calculate statistics
                all_network_times = []
                all_deserialize_times = []
                all_render_times = []
                all_payload_sizes = []

                for callback_id, callback_data in callbacks.items():
                    network_time = callback_data.get("networkTime", 0)
                    deserialize_time = callback_data.get("deserializeTime", 0)
                    payload_size = callback_data.get("payloadSize", 0)

                    all_network_times.append(network_time)
                    all_deserialize_times.append(deserialize_time)
                    all_payload_sizes.append(payload_size)

                    # Find matching render data
                    render_data = next(
                        (r for r in renders if r.get("callbackId") == callback_id), None
                    )
                    if render_data:
                        all_render_times.append(render_data.get("renderTime", 0))

                # Summary statistics
                if all_network_times:
                    print("\n📊 Callback Performance Breakdown:")
                    print(
                        f"  - Avg Network Time: {sum(all_network_times) / len(all_network_times):.1f}ms"
                    )
                    print(
                        f"  - Avg Deserialize Time: {sum(all_deserialize_times) / len(all_deserialize_times):.1f}ms"
                    )
                    if all_render_times:
                        print(
                            f"  - Avg Render Time: {sum(all_render_times) / len(all_render_times):.1f}ms"
                        )
                    print(
                        f"  - Avg Payload Size: {sum(all_payload_sizes) / len(all_payload_sizes) / 1024:.1f}KB"
                    )
                    print(
                        f"  - Total Payload: {sum(all_payload_sizes) / 1024 / 1024:.2f}MB"
                    )

                # Top 5 slowest callbacks by total time
                print("\n🐌 Top 5 Slowest Callbacks (Total Time):")
                callback_list = []
                for callback_id, callback_data in callbacks.items():
                    network_time = callback_data.get("networkTime", 0)
                    deserialize_time = callback_data.get("deserializeTime", 0)
                    payload_size = callback_data.get("payloadSize", 0)

                    # Find matching render data
                    render_data = next(
                        (r for r in renders if r.get("callbackId") == callback_id), None
                    )
                    render_time = render_data.get("renderTime", 0) if render_data else 0

                    total_time = network_time + deserialize_time + render_time

                    callback_list.append(
                        {
                            "id": callback_id,
                            "network": network_time,
                            "deserialize": deserialize_time,
                            "render": render_time,
                            "total": total_time,
                            "payload": payload_size,
                        }
                    )

                callback_list.sort(key=lambda x: x["total"], reverse=True)

                for i, cb in enumerate(callback_list[:5], 1):
                    print(f"\n{i}. {cb['id'][:80]}...")
                    print(f"   Total: {cb['total']:.1f}ms")
                    print(
                        f"   - Network: {cb['network']:.1f}ms ({cb['network'] / cb['total'] * 100:.1f}%)"
                    )
                    print(
                        f"   - Deserialize: {cb['deserialize']:.1f}ms ({cb['deserialize'] / cb['total'] * 100:.1f}%)"
                    )
                    if cb["render"] > 0:
                        print(
                            f"   - Render: {cb['render']:.1f}ms ({cb['render'] / cb['total'] * 100:.1f}%)"
                        )
                    print(f"   - Payload: {cb['payload'] / 1024:.1f}KB")

        # Parse client-side profiling logs from console
        print("\n\n🔍 CLIENT-SIDE PROFILING LOGS (from console)")
        print("-" * 80)

        profiling_logs = [
            log for log in self.console_logs if "CLIENT PROFILING" in log.get("text", "")
        ]

        if profiling_logs:
            print(f"\nFound {len(profiling_logs)} client-side profiling log messages")

            # Extract callback breakdown logs
            breakdown_logs = [
                log
                for log in profiling_logs
                if "TOTAL BREAKDOWN" in log.get("text", "")
            ]

            if breakdown_logs:
                print(f"\n📊 Callback Breakdowns Logged: {len(breakdown_logs)}")
                for i, log in enumerate(breakdown_logs[:5], 1):
                    print(f"\n{i}. {log['text'][:200]}...")
        else:
            print("\nNo client-side profiling logs found in console")
            print("Make sure performance-monitor.js is loaded and callbacks are executing")

        # Save detailed JSON report
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "dashboard_url": DASHBOARD_URL,
            "network_requests": self.network_requests,
            "console_logs": self.console_logs,
            "performance_metrics": self.performance_metrics,
        }

        output_file = (
            Path(__file__).parent
            / f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(output_file, "w") as f:
            json.dump(report_data, f, indent=2)

        print(f"\n\n💾 Detailed report saved to: {output_file}")
        print("=" * 80 + "\n")


async def main():
    monitor = PerformanceMonitor()
    await monitor.monitor_dashboard_load()


if __name__ == "__main__":
    asyncio.run(main())
