#!/usr/bin/env python3
"""
Standalone Dashboard Benchmark Runner

Launches the standalone Iris dashboard and runs performance monitoring.
Provides comparison with full Depictio dashboard performance.

Usage:
    python run_standalone_benchmark.py [--compare REPORT_FILE]

Options:
    --compare REPORT_FILE   Compare standalone performance with existing report
"""

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright

# Configuration
STANDALONE_URL = "http://localhost:5081"
STANDALONE_PORT = 5081
STANDALONE_SCRIPT = Path(__file__).parent / "standalone_iris_dashboard.py"
REPORTS_DIR = Path(__file__).parent


class StandalonePerformanceMonitor:
    """Performance monitor optimized for standalone dashboard (no auth, no docker logs)"""

    def __init__(self):
        self.network_requests = []
        self.console_logs = []
        self.performance_metrics = {}
        self.start_time = None

    async def monitor_dashboard_load(self, url: str = STANDALONE_URL):
        """Monitor standalone dashboard loading with full performance capture"""

        async with async_playwright() as p:
            # Launch browser with debugging enabled
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )

            page = await context.new_page()

            # Set up request monitoring
            async def handle_request(request):
                request_data = {
                    "timestamp": datetime.now().isoformat(),
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "headers": dict(request.headers) if request.headers else {},
                }
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

                response_data = {
                    "timestamp": datetime.now().isoformat(),
                    "type": "response",
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "size": size,
                    "timing": {
                        "dns": timing.get("domainLookupEnd", 0) - timing.get("domainLookupStart", 0)
                        if timing else 0,
                        "connect": timing.get("connectEnd", 0) - timing.get("connectStart", 0)
                        if timing else 0,
                        "request": timing.get("responseStart", 0) - timing.get("requestStart", 0)
                        if timing else 0,
                        "response": timing.get("responseEnd", 0) - timing.get("responseStart", 0)
                        if timing else 0,
                        "total": timing.get("responseEnd", 0) if timing else 0,
                    } if timing else None,
                }

                self.network_requests.append(response_data)

            page.on("response", handle_response)

            # Set up console monitoring
            page.on(
                "console",
                lambda msg: self.console_logs.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": msg.type,
                    "text": msg.text,
                    "location": msg.location,
                })
            )

            # Clear captured data before dashboard load
            self.network_requests = []
            self.console_logs = []
            self.start_time = datetime.now()

            # Navigate to dashboard
            print(f"[{datetime.now().isoformat()}] Loading standalone dashboard...")
            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Wait a bit for async rendering
            print(f"[{datetime.now().isoformat()}] Dashboard loaded! Waiting 3s for async renders...")
            await asyncio.sleep(3)

            # Capture performance metrics
            print(f"[{datetime.now().isoformat()}] Capturing performance metrics...")
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

            # Generate and save report
            report_path = self.save_report()

            print(f"\n[{datetime.now().isoformat()}] Monitoring complete!")
            print("Browser will stay open for 5 seconds for inspection...")

            await asyncio.sleep(5)
            await browser.close()

            return report_path

    def generate_summary(self) -> dict[str, Any]:
        """Generate performance summary for comparison"""

        nav = self.performance_metrics.get("navigation", {})
        paint = self.performance_metrics.get("paint", {})
        resources = self.performance_metrics.get("resources", {})

        # Calculate key metrics
        total_load_time = nav.get("totalLoadTime", 0)
        first_contentful_paint = paint.get("firstContentfulPaint", 0)
        total_transfer_size = resources.get("totalTransferSize", 0)
        num_resources = resources.get("totalResources", 0)

        # Count errors and warnings
        errors = [log for log in self.console_logs if log["type"] == "error"]
        warnings = [log for log in self.console_logs if log["type"] == "warning"]

        return {
            "total_load_time_ms": total_load_time,
            "first_contentful_paint_ms": first_contentful_paint,
            "total_transfer_size_bytes": total_transfer_size,
            "num_resources": num_resources,
            "num_errors": len(errors),
            "num_warnings": len(warnings),
            "num_console_logs": len(self.console_logs),
            "timestamp": self.start_time.isoformat() if self.start_time else None,
        }

    def print_report(self):
        """Print performance report to console"""

        print("\n" + "="*80)
        print("STANDALONE DASHBOARD PERFORMANCE REPORT")
        print("="*80)

        nav = self.performance_metrics.get("navigation", {})
        paint = self.performance_metrics.get("paint", {})
        resources = self.performance_metrics.get("resources", {})
        memory = self.performance_metrics.get("memory")

        print("\n⚡ PERFORMANCE METRICS")
        print("-"*80)

        print("\nPage Load Timing:")
        print(f"  - Total Load Time: {nav.get('totalLoadTime', 0):.2f}ms")
        print(f"  - DOM Content Loaded: {nav.get('domContentLoaded', 0):.2f}ms")
        print(f"  - First Paint: {paint.get('firstPaint', 0):.2f}ms")
        print(f"  - First Contentful Paint: {paint.get('firstContentfulPaint', 0):.2f}ms")

        print("\nResource Loading:")
        print(f"  - Total Resources: {resources.get('totalResources', 0)}")
        print(f"  - Total Transfer Size: {resources.get('totalTransferSize', 0) / 1024 / 1024:.2f}MB")
        print(f"  - Total Duration: {resources.get('totalDuration', 0):.2f}ms")

        if memory:
            print("\nMemory Usage:")
            print(f"  - Used JS Heap: {memory.get('usedJSHeapSize', 0) / 1024 / 1024:.2f}MB")
            print(f"  - Total JS Heap: {memory.get('totalJSHeapSize', 0) / 1024 / 1024:.2f}MB")

        # Console logs
        print("\n\n📝 CONSOLE LOGS ANALYSIS")
        print("-"*80)

        errors = [log for log in self.console_logs if log["type"] == "error"]
        warnings = [log for log in self.console_logs if log["type"] == "warning"]

        print(f"\nTotal Console Messages: {len(self.console_logs)}")
        print(f"Errors: {len(errors)}")
        print(f"Warnings: {len(warnings)}")

        if errors:
            print("\n❌ ERRORS:")
            for error in errors[:5]:
                print(f"  - {error['text'][:100]}")

        if warnings:
            print("\n⚠️  WARNINGS:")
            for warning in warnings[:5]:
                print(f"  - {warning['text'][:100]}")

        # Network requests
        print("\n\n📊 NETWORK ANALYSIS")
        print("-"*80)

        responses = [r for r in self.network_requests if r.get("type") == "response"]
        print(f"\nTotal Network Requests: {len(responses)}")

        if responses:
            total_size = sum(r.get("size", 0) for r in responses)
            print(f"Total Data Transferred: {total_size / 1024:.2f}KB")

    def save_report(self) -> Path:
        """Save detailed report to JSON file"""

        report_data = {
            "type": "standalone",
            "timestamp": datetime.now().isoformat(),
            "url": STANDALONE_URL,
            "network_requests": self.network_requests,
            "console_logs": self.console_logs,
            "performance_metrics": self.performance_metrics,
            "summary": self.generate_summary(),
        }

        output_file = (
            REPORTS_DIR / f"standalone_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(output_file, "w") as f:
            json.dump(report_data, f, indent=2)

        print(f"\n💾 Detailed report saved to: {output_file}")
        self.print_report()
        print("="*80 + "\n")

        return output_file


def compare_reports(standalone_report: Path, depictio_report: Path):
    """Compare standalone vs full Depictio dashboard performance"""

    print("\n" + "="*80)
    print("PERFORMANCE COMPARISON: Standalone vs Full Depictio")
    print("="*80 + "\n")

    with open(standalone_report) as f:
        standalone_data = json.load(f)

    with open(depictio_report) as f:
        depictio_data = json.load(f)

    standalone_summary = standalone_data.get("summary", {})
    depictio_nav = depictio_data.get("performance_metrics", {}).get("navigation", {})
    depictio_paint = depictio_data.get("performance_metrics", {}).get("paint", {})
    depictio_resources = depictio_data.get("performance_metrics", {}).get("resources", {})

    # Comparison table
    print("Metric                          | Standalone      | Full Depictio   | Difference")
    print("-" * 80)

    # Total load time
    standalone_load = standalone_summary.get("total_load_time_ms", 0)
    depictio_load = depictio_nav.get("totalLoadTime", 0)
    diff_load = standalone_load - depictio_load
    diff_pct_load = (diff_load / depictio_load * 100) if depictio_load else 0

    print(f"Total Load Time                 | {standalone_load:>10.1f}ms | {depictio_load:>10.1f}ms | "
          f"{diff_load:>+8.1f}ms ({diff_pct_load:>+6.1f}%)")

    # First contentful paint
    standalone_fcp = standalone_summary.get("first_contentful_paint_ms", 0)
    depictio_fcp = depictio_paint.get("firstContentfulPaint", 0)
    diff_fcp = standalone_fcp - depictio_fcp
    diff_pct_fcp = (diff_fcp / depictio_fcp * 100) if depictio_fcp else 0

    print(f"First Contentful Paint          | {standalone_fcp:>10.1f}ms | {depictio_fcp:>10.1f}ms | "
          f"{diff_fcp:>+8.1f}ms ({diff_pct_fcp:>+6.1f}%)")

    # Transfer size
    standalone_size = standalone_summary.get("total_transfer_size_bytes", 0) / 1024 / 1024
    depictio_size = depictio_resources.get("totalTransferSize", 0) / 1024 / 1024
    diff_size = standalone_size - depictio_size
    diff_pct_size = (diff_size / depictio_size * 100) if depictio_size else 0

    print(f"Total Transfer Size             | {standalone_size:>10.2f}MB | {depictio_size:>10.2f}MB | "
          f"{diff_size:>+8.2f}MB ({diff_pct_size:>+6.1f}%)")

    # Number of resources
    standalone_res = standalone_summary.get("num_resources", 0)
    depictio_res = depictio_resources.get("totalResources", 0)
    diff_res = standalone_res - depictio_res

    print(f"Number of Resources             | {standalone_res:>14d} | {depictio_res:>14d} | {diff_res:>+14d}")

    # Console errors
    standalone_errors = standalone_summary.get("num_errors", 0)
    depictio_console = depictio_data.get("console_logs", [])
    depictio_errors = len([log for log in depictio_console if log.get("type") == "error"])
    diff_errors = standalone_errors - depictio_errors

    print(f"Console Errors                  | {standalone_errors:>14d} | {depictio_errors:>14d} | {diff_errors:>+14d}")

    print("\n" + "="*80)

    # Analysis
    print("\n📊 ANALYSIS:")

    if diff_load < 0:
        improvement = abs(diff_pct_load)
        print(f"  ✅ Standalone is {improvement:.1f}% FASTER than full Depictio for total load time")
    else:
        print(f"  ⚠️  Standalone is {diff_pct_load:.1f}% SLOWER than full Depictio for total load time")

    if diff_fcp < 0:
        improvement = abs(diff_pct_fcp)
        print(f"  ✅ Standalone has {improvement:.1f}% FASTER first contentful paint")
    else:
        print(f"  ⚠️  Standalone has {diff_pct_fcp:.1f}% SLOWER first contentful paint")

    if diff_size < 0:
        reduction = abs(diff_pct_size)
        print(f"  ✅ Standalone transfers {reduction:.1f}% LESS data")
    else:
        print(f"  ⚠️  Standalone transfers {diff_pct_size:.1f}% MORE data")

    print("\n" + "="*80 + "\n")


async def check_server_ready(url: str, timeout: int = 30) -> bool:
    """Check if server is ready to accept connections"""

    print(f"[{datetime.now().isoformat()}] Waiting for server at {url}...")

    start_time = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start_time < timeout:
            try:
                response = await client.get(url, timeout=2.0)
                if response.status_code == 200:
                    print(f"[{datetime.now().isoformat()}] ✅ Server is ready!")
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout):
                await asyncio.sleep(0.5)
                continue

    print(f"[{datetime.now().isoformat()}] ❌ Server failed to start within {timeout}s")
    return False


async def main(compare_with: str | None = None):
    """Main benchmark execution"""

    print("\n" + "="*80)
    print("STANDALONE DASHBOARD BENCHMARK")
    print("="*80 + "\n")

    # Start standalone dashboard
    print(f"[{datetime.now().isoformat()}] Starting standalone dashboard...")
    print(f"Script: {STANDALONE_SCRIPT}")
    print(f"Port: {STANDALONE_PORT}\n")

    proc = subprocess.Popen(
        [sys.executable, str(STANDALONE_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        # Wait for server to be ready
        server_ready = await check_server_ready(STANDALONE_URL, timeout=30)

        if not server_ready:
            print("❌ Failed to start standalone dashboard")
            proc.terminate()
            proc.wait(timeout=5)
            return 1

        # Run performance monitoring
        monitor = StandalonePerformanceMonitor()
        report_path = await monitor.monitor_dashboard_load(STANDALONE_URL)

        # Compare with full Depictio if requested
        if compare_with:
            compare_report_path = Path(compare_with)
            if compare_report_path.exists():
                compare_reports(report_path, compare_report_path)
            else:
                print(f"\n⚠️  Comparison report not found: {compare_report_path}")
                print("Run the full Depictio dashboard benchmark first:\n")
                print("  python dev/performance_analysis/performance_monitor.py\n")

        print(f"\n✅ Benchmark complete!")
        print(f"Report saved to: {report_path}\n")

    finally:
        # Clean up: terminate standalone server
        print(f"[{datetime.now().isoformat()}] Shutting down standalone server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run standalone dashboard benchmark")
    parser.add_argument(
        "--compare",
        type=str,
        help="Path to full Depictio performance report for comparison"
    )

    args = parser.parse_args()

    exit_code = asyncio.run(main(compare_with=args.compare))
    sys.exit(exit_code)
