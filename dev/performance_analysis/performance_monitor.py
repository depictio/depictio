#!/usr/bin/env python3
"""
Dashboard Performance Monitor
Captures network requests, console logs, and performance metrics during dashboard load
ENHANCED: Now includes backend profiling from Docker logs for comprehensive analysis
MODULAR: Supports both standalone and full depictio dashboards via CLI arguments
"""

import argparse
import asyncio
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

# ============================================================================
# Configuration
# ============================================================================


@dataclass
class MonitorConfig:
    """Configuration for performance monitoring targets"""

    target: str  # "standalone" or "depictio"
    dashboard_url: str
    enable_auth: bool
    enable_backend_profiling: bool
    container_name: str | None
    description: str


# Predefined configurations for different monitoring targets
CONFIGS = {
    "standalone": MonitorConfig(
        target="standalone",
        dashboard_url="http://localhost:5081",
        enable_auth=False,
        enable_backend_profiling=False,
        container_name=None,
        description="Standalone Iris Dashboard (minimal overhead)",
    ),
    "depictio": MonitorConfig(
        target="depictio",
        dashboard_url="http://localhost:5080/dashboard/68ffe9aab7e81518cd000996",
        enable_auth=True,
        enable_backend_profiling=True,
        container_name="depictio-frontend",
        description="Full Depictio Dashboard",
    ),
}

# API credentials for automatic authentication (depictio only)
API_BASE_URL = "http://localhost:8058/depictio/api/v1"
API_USERNAME = "admin@example.com"
API_PASSWORD = "changeme"


async def get_auth_token(config: MonitorConfig):
    """
    Authenticate via API and return local-store compatible token data.

    Args:
        config: MonitorConfig instance controlling authentication behavior

    Returns:
        dict: Authentication data ready for localStorage injection, or None if auth disabled
    """
    if not config.enable_auth:
        print(f"[{datetime.now().isoformat()}] ⏭️  Skipping authentication (standalone mode)")
        return None

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


class BackendProfiler:
    """Captures and parses backend performance data from Docker logs"""

    def __init__(self, enabled: bool = True, container_name: str = "depictio-frontend"):
        self.enabled = enabled
        self.container_name = container_name
        self.backend_logs = []
        self.backend_timings = {}

    def clear_logs(self):
        """Clear docker logs before starting monitoring"""
        if not self.enabled:
            return

        try:
            subprocess.run(
                ["docker", "logs", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            print(
                f"[{datetime.now().isoformat()}] 🧹 Cleared docker logs for {self.container_name}"
            )
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] ⚠️  Failed to clear docker logs: {e}")

    def capture_logs(self, since_timestamp=None):
        """Capture docker logs after dashboard load"""
        if not self.enabled:
            print(f"[{datetime.now().isoformat()}] ⏭️  Skipping backend profiling (disabled)")
            return

        try:
            cmd = ["docker", "logs", self.container_name, "--tail", "2000"]
            if since_timestamp:
                # Format timestamp for docker --since flag
                since_str = since_timestamp.strftime("%Y-%m-%dT%H:%M:%S")
                cmd.extend(["--since", since_str])

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.backend_logs = result.stdout.split("\n") + result.stderr.split("\n")
            self.backend_logs = [
                log for log in self.backend_logs if log.strip()
            ]  # Remove empty lines

            print(
                f"[{datetime.now().isoformat()}] 📋 Captured {len(self.backend_logs)} backend log lines"
            )
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] ⚠️  Failed to capture docker logs: {e}")
            self.backend_logs = []

    def parse_timings(self):
        """Parse timing information from backend logs"""
        timing_pattern = re.compile(r"⏱️\s*PERF\s*\[(.*?)\]:\s*([\d.]+)ms")
        cache_hit_pattern = re.compile(r"(CACHE HIT|🚀.*CACHE HIT)")
        redis_hit_pattern = re.compile(r"(REDIS CACHE HIT|🚀 REDIS)")
        cache_miss_pattern = re.compile(r"(CACHE MISS|❌.*CACHE MISS)")

        timings = defaultdict(list)
        cache_stats = {"hits": 0, "misses": 0, "redis_hits": 0}

        for line in self.backend_logs:
            # Extract timing measurements
            timing_match = timing_pattern.search(line)
            if timing_match:
                operation = timing_match.group(1)
                duration_ms = float(timing_match.group(2))
                timings[operation].append(duration_ms)

            # Extract cache statistics
            if redis_hit_pattern.search(line):
                cache_stats["redis_hits"] += 1
                cache_stats["hits"] += 1  # Redis hits are also cache hits
            elif cache_hit_pattern.search(line):
                cache_stats["hits"] += 1
            elif cache_miss_pattern.search(line):
                cache_stats["misses"] += 1

        self.backend_timings = {
            "operations": dict(timings),
            "cache_stats": cache_stats,
            "summary": self._generate_summary(timings),
        }

        return self.backend_timings

    def _generate_summary(self, timings):
        """Generate statistical summary of backend operations"""
        summary = {}
        for operation, durations in timings.items():
            if durations:  # Only process if we have data
                summary[operation] = {
                    "count": len(durations),
                    "total_ms": sum(durations),
                    "avg_ms": sum(durations) / len(durations),
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                }
        return summary


class PerformanceMonitor:
    def __init__(self, config: MonitorConfig):
        self.config = config
        self.network_requests = []
        self.console_logs = []
        self.performance_metrics = {}
        self.start_time = None
        # Initialize backend profiler only if enabled
        self.backend_profiler = (
            BackendProfiler(
                enabled=config.enable_backend_profiling, container_name=config.container_name
            )
            if config.enable_backend_profiling
            else None
        )

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

            # Conditional authentication (only for depictio)
            if self.config.enable_auth:
                # Get fresh authentication token
                auth_token = await get_auth_token(self.config)

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

            # Clear backend logs before monitoring starts (if enabled)
            if self.backend_profiler:
                self.backend_profiler.clear_logs()

            # Navigate to dashboard
            print(f"[{datetime.now().isoformat()}] Loading {self.config.description}...")
            await page.goto(self.config.dashboard_url, wait_until="networkidle", timeout=60000)

            # Wait for user to indicate dashboard is fully loaded
            print(f"\n[{datetime.now().isoformat()}] Dashboard loaded!")
            print("=" * 80)
            print("WAIT for all callbacks to complete, then press ENTER to capture metrics...")
            print("=" * 80)
            await asyncio.get_event_loop().run_in_executor(None, input)

            # Capture and parse backend logs (if enabled)
            if self.backend_profiler:
                print(f"\n[{datetime.now().isoformat()}] Capturing backend logs...")
                self.backend_profiler.capture_logs(since_timestamp=self.start_time)
                self.backend_profiler.parse_timings()

            # Capture performance metrics (including client-side profiling data)
            print(f"[{datetime.now().isoformat()}] Capturing frontend performance metrics...")
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
        print(f"PERFORMANCE REPORT: {self.config.description.upper()}")
        print("=" * 80)
        print(f"Target: {self.config.target}")
        print(f"URL: {self.config.dashboard_url}")
        print(f"Auth: {'Enabled' if self.config.enable_auth else 'Disabled'}")
        print(
            f"Backend Profiling: {'Enabled' if self.config.enable_backend_profiling else 'Disabled'}"
        )
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
                    print(f"  - Total Payload: {sum(all_payload_sizes) / 1024 / 1024:.2f}MB")

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
                log for log in profiling_logs if "TOTAL BREAKDOWN" in log.get("text", "")
            ]

            if breakdown_logs:
                print(f"\n📊 Callback Breakdowns Logged: {len(breakdown_logs)}")
                for i, log in enumerate(breakdown_logs[:5], 1):
                    print(f"\n{i}. {log['text'][:200]}...")
        else:
            print("\nNo client-side profiling logs found in console")
            print("Make sure performance-monitor.js is loaded and callbacks are executing")

        # Backend Profiling Analysis
        print("\n\n🔧 BACKEND PROFILING (Docker Logs)")
        print("-" * 80)

        if self.backend_profiler and self.backend_profiler.enabled:
            backend_timings = self.backend_profiler.backend_timings
            if backend_timings and backend_timings.get("summary"):
                backend_summary = backend_timings["summary"]
                cache_stats = backend_timings.get("cache_stats", {})

                print(f"\nBackend Operations Profiled: {len(backend_summary)}")

                # Cache Statistics
                total_cache_ops = cache_stats.get("hits", 0) + cache_stats.get("misses", 0)
                if total_cache_ops > 0:
                    hit_rate = (cache_stats.get("hits", 0) / total_cache_ops) * 100
                    redis_rate = (
                        (cache_stats.get("redis_hits", 0) / cache_stats.get("hits", 1)) * 100
                        if cache_stats.get("hits", 0) > 0
                        else 0
                    )

                    print("\n📊 Cache Statistics:")
                    print(f"  - Total Cache Operations: {total_cache_ops}")
                    print(f"  - Cache Hits: {cache_stats.get('hits', 0)} ({hit_rate:.1f}%)")
                    print(f"  - Cache Misses: {cache_stats.get('misses', 0)}")
                    print(
                        f"  - Redis Hits: {cache_stats.get('redis_hits', 0)} ({redis_rate:.1f}% of hits)"
                    )

                # Backend operation timings
                if backend_summary:
                    print("\n🐌 Slowest Backend Operations:")

                    # Sort by total time (count * avg)
                    sorted_ops = sorted(
                        backend_summary.items(),
                        key=lambda x: x[1]["total_ms"],
                        reverse=True,
                    )

                    for i, (operation, stats) in enumerate(sorted_ops[:10], 1):
                        print(f"\n{i}. {operation}")
                        print(f"   - Calls: {stats['count']}")
                        print(f"   - Total Time: {stats['total_ms']:.1f}ms")
                        print(f"   - Avg Time: {stats['avg_ms']:.1f}ms")
                        print(f"   - Min/Max: {stats['min_ms']:.1f}ms / {stats['max_ms']:.1f}ms")

                    # Calculate total backend processing time
                    total_backend_time = sum(op["total_ms"] for op in backend_summary.values())
                    print(f"\n⏱️  Total Backend Processing Time: {total_backend_time:.1f}ms")
            else:
                print("\nNo backend profiling data captured.")
                print("Make sure timing markers are present in backend logs.")
                print("Expected format: ⏱️ PERF [operation]: XXXms")
        else:
            print("\nBackend profiling disabled (standalone mode)")

        # Frontend/Backend Correlation Analysis
        print("\n\n🔗 FRONTEND/BACKEND CORRELATION ANALYSIS")
        print("-" * 80)

        # Check if we have both frontend and backend data
        client_profiling = self.performance_metrics.get("clientSideProfiling")
        backend_timings = self.backend_profiler.backend_timings if self.backend_profiler else None

        if (
            client_profiling
            and client_profiling.get("callbacks")
            and backend_timings
            and backend_timings.get("summary")
        ):
            callbacks = client_profiling.get("callbacks", {})
            renders = client_profiling.get("renders", [])
            backend_summary = backend_timings["summary"]

            # Calculate total times
            total_frontend_network = sum(cb.get("networkTime", 0) for cb in callbacks.values())
            total_frontend_deserialize = sum(
                cb.get("deserializeTime", 0) for cb in callbacks.values()
            )
            total_frontend_render = sum(r.get("renderTime", 0) for r in renders)
            total_backend_processing = sum(op["total_ms"] for op in backend_summary.values())

            total_frontend = (
                total_frontend_network + total_frontend_deserialize + total_frontend_render
            )

            print("\n📊 Time Budget Breakdown:")
            print(f"  - Total Frontend Time: {total_frontend:.1f}ms")
            print(f"    • Network (waiting): {total_frontend_network:.1f}ms")
            print(f"    • Deserialization: {total_frontend_deserialize:.1f}ms")
            print(f"    • DOM Rendering: {total_frontend_render:.1f}ms")
            print(f"\n  - Total Backend Processing: {total_backend_processing:.1f}ms")

            # Calculate overhead
            network_overhead = total_frontend_network - total_backend_processing
            if network_overhead > 0:
                overhead_pct = (network_overhead / total_frontend_network) * 100
                print("\n⚠️  Network/Serialization Overhead:")
                print(f"  - Overhead Time: {network_overhead:.1f}ms")
                print(f"  - Overhead Percentage: {overhead_pct:.1f}% of network time")
                print("\n  Analysis:")
                print(f"  Frontend waited {total_frontend_network:.1f}ms for network responses,")
                print(f"  but backend only spent {total_backend_processing:.1f}ms processing.")
                print(f"  The {network_overhead:.1f}ms difference is overhead from:")
                print("    • Network latency (HTTP request/response)")
                print("    • JSON serialization/deserialization on server")
                print("    • Dash framework overhead (callback routing, validation)")
            else:
                print("\n✅ Backend processing time exceeds frontend network time")
                print("   This suggests backend operations are well-measured in logs")

            # Show backend efficiency
            backend_efficiency = (
                (total_backend_processing / total_frontend_network) * 100
                if total_frontend_network > 0
                else 0
            )
            print("\n⚡ Backend Efficiency:")
            print(f"  - Backend represents {backend_efficiency:.1f}% of frontend network wait time")

            if backend_efficiency < 50:
                print("  ⚠️  Most time spent in network/serialization overhead, not backend logic")
            elif backend_efficiency > 80:
                print("  ⚠️  Backend processing is the primary bottleneck")
            else:
                print("  ✅ Balanced between backend processing and network overhead")

            # Cache effectiveness analysis
            cache_stats = backend_timings.get("cache_stats", {})
            total_cache_ops = cache_stats.get("hits", 0) + cache_stats.get("misses", 0)
            if total_cache_ops > 0:
                hit_rate = (cache_stats.get("hits", 0) / total_cache_ops) * 100
                print("\n💾 Cache Effectiveness:")
                print(f"  - Cache Hit Rate: {hit_rate:.1f}%")

                if hit_rate < 50:
                    print("  ⚠️  Low cache hit rate - consider increasing cache size or TTL")
                elif hit_rate > 80:
                    print("  ✅ Excellent cache hit rate - caching is working well")
                else:
                    print("  ℹ️  Moderate cache hit rate - room for improvement")

        else:
            print("\nInsufficient data for correlation analysis.")
            print("Need both frontend (client-side profiling) and backend (docker logs) data.")

        # Save detailed JSON report
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "target": self.config.target,
            "dashboard_url": self.config.dashboard_url,
            "network_requests": self.network_requests,
            "console_logs": self.console_logs,
            "performance_metrics": self.performance_metrics,
            "backend_profiling": (
                self.backend_profiler.backend_timings if self.backend_profiler else None
            ),
        }

        output_file = (
            Path(__file__).parent
            / f"performance_report_{self.config.target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(output_file, "w") as f:
            json.dump(report_data, f, indent=2)

        print(f"\n\n💾 Detailed report saved to: {output_file}")
        print("=" * 80 + "\n")


async def main():
    """Main entry point with CLI argument parsing"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Performance monitoring for Depictio dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor standalone dashboard
  python performance_monitor.py --target standalone

  # Monitor full depictio dashboard
  python performance_monitor.py --target depictio

  # Monitor custom URL (depictio mode)
  python performance_monitor.py --target depictio --url http://localhost:5080/dashboard/OTHER_ID
        """,
    )

    parser.add_argument(
        "--target",
        choices=["standalone", "depictio"],
        required=True,
        help="Target dashboard to monitor",
    )

    parser.add_argument("--url", help="Override dashboard URL (optional)")

    parser.add_argument(
        "--no-backend-profiling",
        action="store_true",
        help="Disable backend profiling even for depictio",
    )

    args = parser.parse_args()

    # Get configuration
    config = CONFIGS[args.target]

    # Apply overrides
    if args.url:
        config.dashboard_url = args.url

    if args.no_backend_profiling:
        config.enable_backend_profiling = False

    # Print configuration
    print("\n" + "=" * 80)
    print("PERFORMANCE MONITOR CONFIGURATION")
    print("=" * 80)
    print(f"Target: {config.target}")
    print(f"Description: {config.description}")
    print(f"URL: {config.dashboard_url}")
    print(f"Authentication: {'Enabled' if config.enable_auth else 'Disabled'}")
    print(f"Backend Profiling: {'Enabled' if config.enable_backend_profiling else 'Disabled'}")
    if config.enable_backend_profiling:
        print(f"Container: {config.container_name}")
    print("=" * 80 + "\n")

    # Create and run monitor
    monitor = PerformanceMonitor(config)
    await monitor.monitor_dashboard_load()


if __name__ == "__main__":
    asyncio.run(main())
