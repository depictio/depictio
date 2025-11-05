#!/usr/bin/env python3
"""
Standalone vs Depictio Performance Comparison

Analyzes performance reports from both targets to identify:
- Callback chain differences
- Network roundtrip overhead
- Slowest callbacks in each
- Frontend/backend time distribution
- Root causes of performance differences
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_report(filepath: str) -> dict:
    """Load a performance report JSON file"""
    with open(filepath) as f:
        return json.load(f)


def analyze_callbacks(report: dict, target: str) -> dict:
    """Analyze callback information from report"""
    client_profiling = report.get("performance_metrics", {}).get("clientSideProfiling")

    if not client_profiling or not client_profiling.get("callbacks"):
        return {
            "total_callbacks": 0,
            "total_network_time": 0,
            "total_deserialize_time": 0,
            "total_render_time": 0,
            "total_payload_size": 0,
            "callbacks": [],
        }

    callbacks = client_profiling.get("callbacks", {})
    renders = client_profiling.get("renders", [])

    # Build callback list with timing breakdown
    callback_list = []
    for callback_id, callback_data in callbacks.items():
        network_time = callback_data.get("networkTime", 0)
        deserialize_time = callback_data.get("deserializeTime", 0)
        payload_size = callback_data.get("payloadSize", 0)

        # Find matching render data
        render_data = next((r for r in renders if r.get("callbackId") == callback_id), None)
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

    # Calculate totals
    total_network = sum(cb.get("networkTime", 0) for cb in callbacks.values())
    total_deserialize = sum(cb.get("deserializeTime", 0) for cb in callbacks.values())
    total_render = sum(r.get("renderTime", 0) for r in renders)
    total_payload = sum(cb.get("payloadSize", 0) for cb in callbacks.values())

    return {
        "total_callbacks": len(callbacks),
        "total_network_time": total_network,
        "total_deserialize_time": total_deserialize,
        "total_render_time": total_render,
        "total_payload_size": total_payload,
        "callbacks": sorted(callback_list, key=lambda x: x["total"], reverse=True),
    }


def analyze_network_requests(report: dict) -> dict:
    """Analyze network request information"""
    requests = report.get("network_requests", [])

    # Filter for different types
    dash_callbacks = [r for r in requests if "_dash-update-component" in r.get("url", "")]
    api_requests = [r for r in requests if "depictio/api" in r.get("url", "")]
    static_resources = [
        r
        for r in requests
        if r.get("resource_type") in ["script", "stylesheet", "image", "font"]
    ]

    return {
        "total_requests": len(requests),
        "dash_callbacks": len(dash_callbacks),
        "api_requests": len(api_requests),
        "static_resources": len(static_resources),
        "requests": requests,
    }


def analyze_backend_profiling(report: dict) -> dict:
    """Analyze backend profiling data (depictio only)"""
    backend_data = report.get("backend_profiling")

    if not backend_data or not backend_data.get("summary"):
        return {
            "enabled": False,
            "total_operations": 0,
            "total_backend_time": 0,
            "cache_hit_rate": 0,
            "operations": [],
        }

    summary = backend_data.get("summary", {})
    cache_stats = backend_data.get("cache_stats", {})

    # Calculate total backend time
    total_backend_time = sum(op["total_ms"] for op in summary.values())

    # Calculate cache hit rate
    total_cache_ops = cache_stats.get("hits", 0) + cache_stats.get("misses", 0)
    cache_hit_rate = (
        (cache_stats.get("hits", 0) / total_cache_ops * 100) if total_cache_ops > 0 else 0
    )

    # Sort operations by total time
    operations = [
        {
            "name": name,
            "count": stats["count"],
            "total_ms": stats["total_ms"],
            "avg_ms": stats["avg_ms"],
            "min_ms": stats["min_ms"],
            "max_ms": stats["max_ms"],
        }
        for name, stats in summary.items()
    ]
    operations.sort(key=lambda x: x["total_ms"], reverse=True)

    return {
        "enabled": True,
        "total_operations": len(summary),
        "total_backend_time": total_backend_time,
        "cache_hit_rate": cache_hit_rate,
        "cache_stats": cache_stats,
        "operations": operations,
    }


def generate_comparison_report(
    standalone_file: str, depictio_file: str, output_file: str = None
) -> str:
    """Generate comprehensive comparison report"""

    # Load reports
    print("Loading performance reports...")
    standalone = load_report(standalone_file)
    depictio = load_report(depictio_file)

    # Analyze both targets
    print("Analyzing standalone dashboard...")
    standalone_callbacks = analyze_callbacks(standalone, "standalone")
    standalone_network = analyze_network_requests(standalone)
    standalone_backend = analyze_backend_profiling(standalone)

    print("Analyzing depictio dashboard...")
    depictio_callbacks = analyze_callbacks(depictio, "depictio")
    depictio_network = analyze_network_requests(depictio)
    depictio_backend = analyze_backend_profiling(depictio)

    # Generate markdown report
    report_lines = []

    # Header
    report_lines.append("# Standalone vs Depictio Performance Comparison")
    report_lines.append("")
    report_lines.append(f"**Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    report_lines.append("## Reports Analyzed")
    report_lines.append(f"- **Standalone**: `{Path(standalone_file).name}`")
    report_lines.append(f"- **Depictio**: `{Path(depictio_file).name}`")
    report_lines.append("")

    # Executive Summary
    report_lines.append("## Executive Summary")
    report_lines.append("")

    total_standalone = (
        standalone_callbacks["total_network_time"]
        + standalone_callbacks["total_deserialize_time"]
        + standalone_callbacks["total_render_time"]
    )
    total_depictio = (
        depictio_callbacks["total_network_time"]
        + depictio_callbacks["total_deserialize_time"]
        + depictio_callbacks["total_render_time"]
    )

    report_lines.append(f"- **Standalone Total Time**: {total_standalone:.1f}ms")
    report_lines.append(f"- **Depictio Total Time**: {total_depictio:.1f}ms")
    if total_standalone > 0:
        report_lines.append(
            f"- **Difference**: {total_depictio - total_standalone:.1f}ms ({((total_depictio / total_standalone - 1) * 100):.1f}% slower)"
        )
    else:
        report_lines.append(
            f"- **Difference**: {total_depictio - total_standalone:.1f}ms (standalone data incomplete)"
        )
    report_lines.append("")
    report_lines.append(
        f"- **Standalone Callbacks**: {standalone_callbacks['total_callbacks']}"
    )
    report_lines.append(f"- **Depictio Callbacks**: {depictio_callbacks['total_callbacks']}")
    report_lines.append(
        f"- **Additional Callbacks**: {depictio_callbacks['total_callbacks'] - standalone_callbacks['total_callbacks']}"
    )
    report_lines.append("")

    # Callback Analysis
    report_lines.append("## Callback Chain Comparison")
    report_lines.append("")
    report_lines.append("### Callback Count")
    report_lines.append("")
    report_lines.append("| Metric | Standalone | Depictio | Difference |")
    report_lines.append("|--------|-----------|----------|------------|")
    report_lines.append(
        f"| Total Callbacks | {standalone_callbacks['total_callbacks']} | {depictio_callbacks['total_callbacks']} | +{depictio_callbacks['total_callbacks'] - standalone_callbacks['total_callbacks']} |"
    )
    report_lines.append(
        f"| Network Time | {standalone_callbacks['total_network_time']:.1f}ms | {depictio_callbacks['total_network_time']:.1f}ms | +{depictio_callbacks['total_network_time'] - standalone_callbacks['total_network_time']:.1f}ms |"
    )
    report_lines.append(
        f"| Deserialize Time | {standalone_callbacks['total_deserialize_time']:.1f}ms | {depictio_callbacks['total_deserialize_time']:.1f}ms | +{depictio_callbacks['total_deserialize_time'] - standalone_callbacks['total_deserialize_time']:.1f}ms |"
    )
    report_lines.append(
        f"| Render Time | {standalone_callbacks['total_render_time']:.1f}ms | {depictio_callbacks['total_render_time']:.1f}ms | +{depictio_callbacks['total_render_time'] - standalone_callbacks['total_render_time']:.1f}ms |"
    )
    report_lines.append(
        f"| Total Payload | {standalone_callbacks['total_payload_size'] / 1024:.1f}KB | {depictio_callbacks['total_payload_size'] / 1024:.1f}KB | +{(depictio_callbacks['total_payload_size'] - standalone_callbacks['total_payload_size']) / 1024:.1f}KB |"
    )
    report_lines.append("")

    # Network Requests
    report_lines.append("## Network Roundtrip Analysis")
    report_lines.append("")
    report_lines.append("| Metric | Standalone | Depictio | Difference |")
    report_lines.append("|--------|-----------|----------|------------|")
    report_lines.append(
        f"| Total Requests | {standalone_network['total_requests']} | {depictio_network['total_requests']} | +{depictio_network['total_requests'] - standalone_network['total_requests']} |"
    )
    report_lines.append(
        f"| Dash Callbacks | {standalone_network['dash_callbacks']} | {depictio_network['dash_callbacks']} | +{depictio_network['dash_callbacks'] - standalone_network['dash_callbacks']} |"
    )
    report_lines.append(
        f"| API Requests | {standalone_network['api_requests']} | {depictio_network['api_requests']} | +{depictio_network['api_requests'] - standalone_network['api_requests']} |"
    )
    report_lines.append(
        f"| Static Resources | {standalone_network['static_resources']} | {depictio_network['static_resources']} | +{depictio_network['static_resources'] - standalone_network['static_resources']} |"
    )
    report_lines.append("")

    # Slowest Callbacks Comparison
    report_lines.append("## Slowest Callbacks Comparison")
    report_lines.append("")
    report_lines.append("### Top 5 Slowest: Standalone")
    report_lines.append("")
    report_lines.append("| # | Callback ID | Network | Deserialize | Render | Total | Payload |")
    report_lines.append("|---|------------|---------|-------------|--------|-------|---------|")

    for i, cb in enumerate(standalone_callbacks["callbacks"][:5], 1):
        report_lines.append(
            f"| {i} | `{cb['id'][:50]}...` | {cb['network']:.1f}ms | {cb['deserialize']:.1f}ms | {cb['render']:.1f}ms | {cb['total']:.1f}ms | {cb['payload'] / 1024:.1f}KB |"
        )

    report_lines.append("")
    report_lines.append("### Top 5 Slowest: Depictio")
    report_lines.append("")
    report_lines.append("| # | Callback ID | Network | Deserialize | Render | Total | Payload |")
    report_lines.append("|---|------------|---------|-------------|--------|-------|---------|")

    for i, cb in enumerate(depictio_callbacks["callbacks"][:5], 1):
        report_lines.append(
            f"| {i} | `{cb['id'][:50]}...` | {cb['network']:.1f}ms | {cb['deserialize']:.1f}ms | {cb['render']:.1f}ms | {cb['total']:.1f}ms | {cb['payload'] / 1024:.1f}KB |"
        )

    report_lines.append("")

    # Backend Profiling (Depictio only)
    if depictio_backend["enabled"]:
        report_lines.append("## Backend Profiling Analysis (Depictio Only)")
        report_lines.append("")
        report_lines.append(
            f"- **Total Backend Operations**: {depictio_backend['total_operations']}"
        )
        report_lines.append(
            f"- **Total Backend Time**: {depictio_backend['total_backend_time']:.1f}ms"
        )
        report_lines.append(
            f"- **Cache Hit Rate**: {depictio_backend['cache_hit_rate']:.1f}%"
        )
        report_lines.append("")

        # Network overhead analysis
        network_overhead = (
            depictio_callbacks["total_network_time"] - depictio_backend["total_backend_time"]
        )
        overhead_pct = (
            (network_overhead / depictio_callbacks["total_network_time"]) * 100
            if depictio_callbacks["total_network_time"] > 0
            else 0
        )

        report_lines.append("### Network/Serialization Overhead")
        report_lines.append("")
        report_lines.append(
            f"- **Frontend Network Wait**: {depictio_callbacks['total_network_time']:.1f}ms"
        )
        report_lines.append(
            f"- **Backend Processing**: {depictio_backend['total_backend_time']:.1f}ms"
        )
        report_lines.append(f"- **Overhead**: {network_overhead:.1f}ms ({overhead_pct:.1f}%)")
        report_lines.append("")

        report_lines.append("### Top 5 Slowest Backend Operations")
        report_lines.append("")
        report_lines.append("| # | Operation | Calls | Total Time | Avg Time | Min | Max |")
        report_lines.append("|---|-----------|-------|------------|----------|-----|-----|")

        for i, op in enumerate(depictio_backend["operations"][:5], 1):
            report_lines.append(
                f"| {i} | {op['name'][:40]} | {op['count']} | {op['total_ms']:.1f}ms | {op['avg_ms']:.1f}ms | {op['min_ms']:.1f}ms | {op['max_ms']:.1f}ms |"
            )

        report_lines.append("")

    # Root Cause Analysis
    report_lines.append("## Root Cause Analysis")
    report_lines.append("")

    # Calculate key differences
    callback_diff = depictio_callbacks["total_callbacks"] - standalone_callbacks["total_callbacks"]
    network_time_diff = (
        depictio_callbacks["total_network_time"] - standalone_callbacks["total_network_time"]
    )
    payload_diff = (
        depictio_callbacks["total_payload_size"] - standalone_callbacks["total_payload_size"]
    )

    report_lines.append("### Primary Performance Bottlenecks")
    report_lines.append("")

    report_lines.append(f"1. **Additional Callbacks ({callback_diff} extra)**")
    report_lines.append(
        f"   - Depictio has {callback_diff} more callbacks than standalone"
    )
    report_lines.append("   - Likely: routing, consolidated API, navbar, header, auth callbacks")
    report_lines.append("")

    report_lines.append(f"2. **Network Time Overhead (+{network_time_diff:.1f}ms)**")
    report_lines.append("   - Additional HTTP roundtrips for auth, user data, project data")
    report_lines.append("   - Delta table loading vs in-memory DataFrames")
    report_lines.append("")

    if depictio_backend["enabled"]:
        report_lines.append(
            f"3. **Backend Processing ({depictio_backend['total_backend_time']:.1f}ms)**"
        )
        report_lines.append("   - MongoDB queries for metadata")
        report_lines.append("   - JWT validation on every request")
        report_lines.append("   - S3/Delta table reads")
        report_lines.append("")

    report_lines.append(f"4. **Payload Size (+{payload_diff / 1024:.1f}KB)**")
    report_lines.append("   - Additional metadata in responses")
    report_lines.append("   - User/project/dashboard configuration data")
    report_lines.append("")

    # Recommendations
    report_lines.append("## Optimization Recommendations")
    report_lines.append("")

    report_lines.append("### High Impact")
    report_lines.append("")
    report_lines.append("1. **Reduce Initial Callback Chain**")
    report_lines.append(
        f"   - {callback_diff} extra callbacks add significant overhead"
    )
    report_lines.append("   - Consider merging routing + consolidated API into single callback")
    report_lines.append("   - Use client-side callbacks for UI-only updates")
    report_lines.append("")

    report_lines.append("2. **Optimize Data Loading**")
    report_lines.append("   - Standalone uses pre-loaded DataFrames (instant)")
    report_lines.append("   - Depictio reads from Delta tables (slower)")
    report_lines.append("   - Consider aggressive caching for frequently accessed data")
    report_lines.append("")

    if depictio_backend["enabled"] and depictio_backend["cache_hit_rate"] < 80:
        report_lines.append("3. **Improve Cache Hit Rate**")
        report_lines.append(
            f"   - Current: {depictio_backend['cache_hit_rate']:.1f}%"
        )
        report_lines.append("   - Increase cache TTL for dashboard metadata")
        report_lines.append("   - Pre-warm cache on dashboard load")
        report_lines.append("")

    report_lines.append("### Medium Impact")
    report_lines.append("")
    report_lines.append("1. **Reduce Payload Sizes**")
    report_lines.append(
        f"   - {payload_diff / 1024:.1f}KB additional data transferred"
    )
    report_lines.append("   - Strip unnecessary metadata from API responses")
    report_lines.append("   - Use pagination for large datasets")
    report_lines.append("")

    report_lines.append("2. **Optimize Backend Operations**")
    if depictio_backend["enabled"]:
        report_lines.append(
            f"   - {depictio_backend['total_operations']} backend operations measured"
        )
        report_lines.append("   - Consider database query optimization")
        report_lines.append("   - Use connection pooling for MongoDB")
    report_lines.append("")

    # Conclusion
    report_lines.append("## Conclusion")
    report_lines.append("")
    if total_standalone > 0:
        slowdown_pct = ((total_depictio / total_standalone - 1) * 100)
        report_lines.append(
            f"Depictio is **{slowdown_pct:.1f}% slower** than standalone due to:"
        )
    else:
        report_lines.append(
            f"Depictio has **{total_depictio:.1f}ms total time** (standalone baseline incomplete) due to:"
        )
    report_lines.append("")
    report_lines.append(f"1. **{callback_diff} additional callbacks** for infrastructure")
    report_lines.append(f"2. **{network_time_diff:.1f}ms additional network time**")
    if depictio_backend["enabled"]:
        report_lines.append(
            f"3. **{depictio_backend['total_backend_time']:.1f}ms backend processing**"
        )
    report_lines.append(f"4. **{payload_diff / 1024:.1f}KB additional data transfer**")
    report_lines.append("")
    report_lines.append(
        "The primary issue is **infrastructure overhead** (auth, routing, API) rather than component rendering itself."
    )
    report_lines.append("")

    # Generate report
    report_text = "\n".join(report_lines)

    # Save to file if specified
    if output_file:
        with open(output_file, "w") as f:
            f.write(report_text)
        print(f"\n✅ Report saved to: {output_file}")

    return report_text


def main():
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage: python compare_standalone_vs_depictio.py <standalone_report.json> <depictio_report.json> [output.md]")
        sys.exit(1)

    standalone_file = sys.argv[1]
    depictio_file = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else None

    # Validate files exist
    if not Path(standalone_file).exists():
        print(f"❌ Standalone report not found: {standalone_file}")
        sys.exit(1)

    if not Path(depictio_file).exists():
        print(f"❌ Depictio report not found: {depictio_file}")
        sys.exit(1)

    # Default output filename if not specified
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"COMPARISON_REPORT_{timestamp}.md"

    # Generate report
    print("\n" + "=" * 80)
    print("STANDALONE VS DEPICTIO PERFORMANCE COMPARISON")
    print("=" * 80 + "\n")

    report = generate_comparison_report(standalone_file, depictio_file, output_file)

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print(f"\nReport: {output_file}")
    print("\n")


if __name__ == "__main__":
    main()
