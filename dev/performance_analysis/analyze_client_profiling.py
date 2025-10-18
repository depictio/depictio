#!/usr/bin/env python3
"""
Analyze client-side profiling data from performance report
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

def analyze_client_profiling(report_path):
    """Analyze client-side profiling data from JSON report."""

    with open(report_path, 'r') as f:
        report = json.load(f)

    print("=" * 100)
    print("CLIENT-SIDE PERFORMANCE ANALYSIS")
    print("=" * 100)
    print(f"\nReport: {Path(report_path).name}")
    print(f"Dashboard: {report['dashboard_url']}")
    print(f"Timestamp: {report['timestamp']}")

    # Extract client-side profiling data
    perf = report.get('performance_metrics', {})
    client_profiling = perf.get('clientSideProfiling')

    if not client_profiling:
        print("\n❌ No client-side profiling data found!")
        print("Make sure performance-monitor.js is loaded and callbacks are executing.")
        return

    callbacks = client_profiling.get('callbacks', {})
    renders = client_profiling.get('renders', [])

    print(f"\n📊 DATA SUMMARY")
    print("-" * 100)
    print(f"  - Callbacks profiled: {len(callbacks)}")
    print(f"  - Render events captured: {len(renders)}")

    # Analyze callbacks
    if callbacks:
        print(f"\n🔬 CALLBACK PERFORMANCE BREAKDOWN")
        print("-" * 100)

        total_network = 0
        total_deserialize = 0
        total_payload = 0

        for callback_id, data in callbacks.items():
            network = data.get('networkTime', 0)
            deserialize = data.get('deserializeTime', 0)
            payload = data.get('payloadSize', 0)

            total_network += network
            total_deserialize += deserialize
            total_payload += payload

            print(f"\nCallback: {callback_id[:80]}...")
            print(f"  - Network Time: {network:.1f}ms")
            print(f"  - Deserialize Time: {deserialize:.1f}ms")
            print(f"  - Total Time: {network + deserialize:.1f}ms")
            print(f"  - Payload Size: {payload / 1024:.2f}KB")

            # Calculate percentages
            total_time = network + deserialize
            if total_time > 0:
                print(f"  - Network %: {network / total_time * 100:.1f}%")
                print(f"  - Deserialize %: {deserialize / total_time * 100:.1f}%")

        # Summary statistics
        print(f"\n📈 AGGREGATE STATISTICS")
        print("-" * 100)
        num_callbacks = len(callbacks)
        print(f"  - Average Network Time: {total_network / num_callbacks:.1f}ms")
        print(f"  - Average Deserialize Time: {total_deserialize / num_callbacks:.1f}ms")
        print(f"  - Average Payload Size: {total_payload / num_callbacks / 1024:.2f}KB")
        print(f"  - Total Payload: {total_payload / 1024:.2f}KB")

        total_callback_time = total_network + total_deserialize
        if total_callback_time > 0:
            print(f"\n  TIME BREAKDOWN:")
            print(f"  - Network: {total_network:.1f}ms ({total_network / total_callback_time * 100:.1f}%)")
            print(f"  - Deserialize: {total_deserialize:.1f}ms ({total_deserialize / total_callback_time * 100:.1f}%)")

    # Analyze renders
    if renders:
        print(f"\n🎨 RENDER PERFORMANCE")
        print("-" * 100)

        render_times = [r.get('renderTime', 0) for r in renders]
        mutation_counts = [r.get('mutationCount', 0) for r in renders]

        print(f"  - Total Renders: {len(renders)}")
        print(f"  - Average Render Time: {sum(render_times) / len(render_times):.1f}ms")
        print(f"  - Min Render Time: {min(render_times):.1f}ms")
        print(f"  - Max Render Time: {max(render_times):.1f}ms")
        print(f"  - Average Mutations per Render: {sum(mutation_counts) / len(mutation_counts):.1f}")

        # Slowest renders
        sorted_renders = sorted(renders, key=lambda x: x.get('renderTime', 0), reverse=True)
        print(f"\n  TOP 10 SLOWEST RENDERS:")
        for i, render in enumerate(sorted_renders[:10], 1):
            render_time = render.get('renderTime', 0)
            mutations = render.get('mutationCount', 0)
            callback_id = render.get('callbackId', 'unknown')[:60]
            print(f"  {i}. {render_time:.1f}ms - {mutations} mutations - {callback_id}...")

    # Compare with server-side logs (from console)
    console_logs = report.get('console_logs', [])
    profiling_logs = [log for log in console_logs if 'PROFILING' in log.get('text', '')]

    if profiling_logs:
        print(f"\n🖥️  SERVER-SIDE PROFILING (from logs)")
        print("-" * 100)
        print(f"  - Total profiling log entries: {len(profiling_logs)}")

        # Extract server-side timings
        render_dashboard_logs = [log for log in profiling_logs if 'render_dashboard' in log.get('text', '')]
        load_data_logs = [log for log in profiling_logs if 'load_depictio_data_sync' in log.get('text', '')]

        if render_dashboard_logs:
            print(f"\n  RENDER_DASHBOARD calls: {len(render_dashboard_logs)}")
            for log in render_dashboard_logs[:3]:
                print(f"    - {log['text'][:100]}...")

        if load_data_logs:
            print(f"\n  LOAD_DEPICTIO_DATA_SYNC calls: {len(load_data_logs)}")
            for log in load_data_logs[:3]:
                print(f"    - {log['text'][:100]}...")

    # Combined analysis
    print(f"\n🎯 COMBINED ANALYSIS (Client + Server)")
    print("-" * 100)

    if callbacks and renders:
        total_client_time = total_network + total_deserialize + sum(render_times)
        print(f"\n  TOTAL CLIENT-SIDE TIME:")
        print(f"  - Network: {total_network:.1f}ms ({total_network / total_client_time * 100:.1f}%)")
        print(f"  - JSON Deserialize: {total_deserialize:.1f}ms ({total_deserialize / total_client_time * 100:.1f}%)")
        print(f"  - React Render: {sum(render_times):.1f}ms ({sum(render_times) / total_client_time * 100:.1f}%)")
        print(f"  - TOTAL: {total_client_time:.1f}ms")

        print(f"\n  BOTTLENECK ANALYSIS:")
        if total_network > total_deserialize and total_network > sum(render_times):
            print(f"  ⚠️  PRIMARY BOTTLENECK: Network Time ({total_network:.1f}ms)")
            print(f"      Recommendation: Reduce payload size, enable compression, use HTTP/2")
        elif sum(render_times) > total_network and sum(render_times) > total_deserialize:
            print(f"  ⚠️  PRIMARY BOTTLENECK: React Rendering ({sum(render_times):.1f}ms)")
            print(f"      Recommendation: Optimize React components, use memoization, virtualization")
        elif total_deserialize > total_network and total_deserialize > sum(render_times):
            print(f"  ⚠️  PRIMARY BOTTLENECK: JSON Deserialization ({total_deserialize:.1f}ms)")
            print(f"      Recommendation: Reduce JSON complexity, use binary format")
        else:
            print(f"  ✅ Relatively balanced - no single dominant bottleneck")

    # Payload size analysis
    if callbacks:
        print(f"\n  PAYLOAD SIZE ANALYSIS:")
        avg_payload = total_payload / len(callbacks)
        if avg_payload > 100 * 1024:  # > 100KB
            print(f"  ⚠️  LARGE PAYLOADS: Average {avg_payload / 1024:.1f}KB per callback")
            print(f"      Recommendation: Consider pagination, lazy loading, or data compression")
        elif avg_payload > 50 * 1024:  # > 50KB
            print(f"  ⚡ MODERATE PAYLOADS: Average {avg_payload / 1024:.1f}KB per callback")
            print(f"      Recommendation: Monitor and optimize if needed")
        else:
            print(f"  ✅ SMALL PAYLOADS: Average {avg_payload / 1024:.1f}KB per callback")

    print("\n" + "=" * 100)
    print("END OF ANALYSIS")
    print("=" * 100)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_client_profiling.py <performance_report.json>")
        sys.exit(1)

    report_path = sys.argv[1]
    analyze_client_profiling(report_path)
