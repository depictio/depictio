#!/usr/bin/env python3
"""
Analyze the performance report and generate actionable insights
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def analyze_report(report_file):
    """Analyze the performance report and generate insights"""

    with open(report_file) as f:
        data = json.load(f)

    print("=" * 80)
    print("DASH PERFORMANCE ANALYSIS - KEY BOTTLENECKS")
    print("=" * 80)

    # Performance Metrics Overview
    perf = data.get("performance_metrics", {})
    nav = perf.get("navigation", {})
    paint = perf.get("paint", {})
    resources = perf.get("resources", {})
    memory = perf.get("memory", {})

    print("\n📊 OVERALL PERFORMANCE")
    print("-" * 80)
    print(f"Total Load Time: {nav.get('totalLoadTime', 0):.2f}ms ({nav.get('totalLoadTime', 0)/1000:.2f}s)")
    print(f"DOM Content Loaded: {nav.get('domContentLoaded', 0):.2f}ms")
    print(f"First Contentful Paint: {paint.get('firstContentfulPaint', 0):.2f}ms")
    print(f"Total Resources Loaded: {resources.get('totalResources', 0)}")
    print(f"Total Data Transfer: {resources.get('totalTransferSize', 0) / 1024 / 1024:.2f}MB")
    if memory:
        print(f"JS Heap Used: {memory.get('usedJSHeapSize', 0) / 1024 / 1024:.2f}MB")

    # Analyze Network Requests
    network = data.get("network_requests", [])
    api_responses = [r for r in network if r.get("type") == "response" and "/depictio/api/v1/" in r.get("url", "")]

    print(f"\n\n🌐 NETWORK ANALYSIS")
    print("-" * 80)
    print(f"Total Network Requests: {len([r for r in network if r.get('type') == 'response'])}")
    print(f"API Requests: {len(api_responses)}")

    # Group API requests by endpoint
    endpoints = defaultdict(list)
    for req in api_responses:
        url = req["url"].split("?")[0]
        endpoint = url.split("/depictio/api/v1/")[-1] if "/depictio/api/v1/" in url else url
        endpoints[endpoint].append(req)

    # Calculate stats per endpoint
    endpoint_stats = []
    for endpoint, responses in endpoints.items():
        timings = [r.get("timing", {}) for r in responses if r.get("timing")]
        total_times = [t.get("total", 0) for t in timings if t and t.get("total")]

        if total_times:
            avg_time = sum(total_times) / len(total_times)
            max_time = max(total_times)
        else:
            avg_time = 0
            max_time = 0

        total_size = sum(r.get("size", 0) for r in responses)

        endpoint_stats.append({
            "endpoint": endpoint,
            "count": len(responses),
            "avg_time": avg_time,
            "max_time": max_time,
            "total_size": total_size,
            "total_time": sum(total_times) if total_times else 0
        })

    # Sort by total time (impact)
    endpoint_stats.sort(key=lambda x: x["total_time"], reverse=True)

    print("\n🔴 TOP 10 SLOWEST ENDPOINTS (by total time impact):")
    for i, stat in enumerate(endpoint_stats[:10], 1):
        print(f"\n{i}. /{stat['endpoint']}")
        print(f"   Calls: {stat['count']}")
        print(f"   Avg Time: {stat['avg_time']:.2f}ms")
        print(f"   Max Time: {stat['max_time']:.2f}ms")
        print(f"   Total Time: {stat['total_time']:.2f}ms ({stat['total_time']/1000:.2f}s)")
        print(f"   Total Size: {stat['total_size'] / 1024:.2f}KB")

    # Identify slow individual requests
    slow_requests = []
    for req in api_responses:
        timing = req.get("timing")
        if timing and timing.get("total", 0) > 500:  # Slower than 500ms
            slow_requests.append({
                "url": req["url"],
                "time": timing.get("total", 0),
                "size": req.get("size", 0)
            })

    slow_requests.sort(key=lambda x: x["time"], reverse=True)

    if slow_requests:
        print(f"\n\n⚠️  INDIVIDUAL SLOW REQUESTS (>500ms):")
        print("-" * 80)
        for i, req in enumerate(slow_requests[:10], 1):
            endpoint = req["url"].split("/depictio/api/v1/")[-1] if "/depictio/api/v1/" in req["url"] else req["url"]
            print(f"{i}. {endpoint[:80]}")
            print(f"   Time: {req['time']:.2f}ms ({req['time']/1000:.2f}s)")
            print(f"   Size: {req['size'] / 1024:.2f}KB")

    # Console Errors/Warnings
    console = data.get("console_logs", [])
    errors = [log for log in console if log.get("type") == "error"]
    warnings = [log for log in console if log.get("type") == "warning"]

    print(f"\n\n🔍 CONSOLE ANALYSIS")
    print("-" * 80)
    print(f"Total Console Messages: {len(console)}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    if errors:
        print("\n❌ ERRORS (first 10):")
        for i, error in enumerate(errors[:10], 1):
            print(f"{i}. {error.get('text', '')[:150]}")

    if warnings:
        print("\n⚠️  WARNINGS (first 10):")
        for i, warning in enumerate(warnings[:10], 1):
            print(f"{i}. {warning.get('text', '')[:150]}")

    # Recommendations
    print("\n\n💡 RECOMMENDATIONS")
    print("=" * 80)

    recommendations = []

    # Check for slow endpoints
    if endpoint_stats and endpoint_stats[0]["avg_time"] > 1000:
        recommendations.append(
            f"1. CRITICAL: Optimize '{endpoint_stats[0]['endpoint']}' endpoint - averaging {endpoint_stats[0]['avg_time']:.0f}ms per request"
        )

    # Check for multiple calls to same endpoint
    frequent_endpoints = [s for s in endpoint_stats if s["count"] > 5]
    if frequent_endpoints:
        recommendations.append(
            f"2. Reduce duplicate API calls: '{frequent_endpoints[0]['endpoint']}' called {frequent_endpoints[0]['count']} times"
        )

    # Check for large payloads
    large_payloads = [s for s in endpoint_stats if s["total_size"] > 500 * 1024]  # >500KB
    if large_payloads:
        recommendations.append(
            f"3. Optimize data payload size for '{large_payloads[0]['endpoint']}' ({large_payloads[0]['total_size'] / 1024:.0f}KB total)"
        )

    # Check total load time
    if nav.get("totalLoadTime", 0) > 5000:
        recommendations.append(
            f"4. Total page load time is {nav.get('totalLoadTime', 0)/1000:.1f}s - consider lazy loading components"
        )

    # Check errors
    if errors:
        recommendations.append(
            f"5. Fix {len(errors)} JavaScript errors that may be blocking rendering"
        )

    for rec in recommendations:
        print(rec)

    print("\n" + "=" * 80)


if __name__ == "__main__":
    report_file = sys.argv[1] if len(sys.argv) > 1 else "performance_report_20251016_103721.json"
    report_path = Path(__file__).parent / report_file

    if not report_path.exists():
        print(f"Error: Report file not found: {report_path}")
        sys.exit(1)

    analyze_report(report_path)
