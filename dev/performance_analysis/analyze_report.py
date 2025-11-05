#!/usr/bin/env python3
"""
Analyze performance report JSON and extract key bottlenecks
"""
import json
import sys
from pathlib import Path

def analyze_report(report_path):
    """Analyze performance report and print key findings"""

    with open(report_path) as f:
        report = json.load(f)

    print("=" * 80)
    print("PERFORMANCE REPORT ANALYSIS")
    print("=" * 80)
    print(f"\nReport: {report_path}")
    print(f"Timestamp: {report.get('timestamp', 'N/A')}")
    print(f"Dashboard: {report.get('dashboard_url', 'N/A')}")

    # Backend Profiling Analysis
    print("\n" + "=" * 80)
    print("BACKEND PROFILING SUMMARY")
    print("=" * 80)

    backend = report.get('backend_profiling', {})
    if backend and backend.get('summary'):
        summary = backend['summary']
        cache_stats = backend.get('cache_stats', {})

        print(f"\nBackend Operations: {len(summary)}")

        # Cache statistics
        total_cache_ops = cache_stats.get('hits', 0) + cache_stats.get('misses', 0)
        if total_cache_ops > 0:
            hit_rate = (cache_stats.get('hits', 0) / total_cache_ops) * 100
            print(f"\nCache Statistics:")
            print(f"  Total Operations: {total_cache_ops}")
            print(f"  Hits: {cache_stats.get('hits', 0)} ({hit_rate:.1f}%)")
            print(f"  Misses: {cache_stats.get('misses', 0)}")
            print(f"  Redis Hits: {cache_stats.get('redis_hits', 0)}")

        # Top 10 slowest operations
        print("\nTop 10 Slowest Backend Operations:")
        sorted_ops = sorted(summary.items(), key=lambda x: x[1]['total_ms'], reverse=True)

        total_backend_time = 0
        for i, (op, stats) in enumerate(sorted_ops[:10], 1):
            print(f"\n{i}. {op}")
            print(f"   Calls: {stats['count']}")
            print(f"   Total: {stats['total_ms']:.1f}ms")
            print(f"   Avg: {stats['avg_ms']:.1f}ms")
            print(f"   Min/Max: {stats['min_ms']:.1f}ms / {stats['max_ms']:.1f}ms")
            total_backend_time += stats['total_ms']

        print(f"\nTotal Backend Time (top 10): {total_backend_time:.1f}ms")
        print(f"Total Backend Time (all): {sum(s['total_ms'] for s in summary.values()):.1f}ms")

    else:
        print("\n⚠️  No backend profiling data found")

    # Client-Side Profiling Analysis
    print("\n" + "=" * 80)
    print("CLIENT-SIDE PROFILING SUMMARY")
    print("=" * 80)

    perf = report.get('performance_metrics', {})
    client_profiling = perf.get('clientSideProfiling')

    if client_profiling and client_profiling.get('callbacks'):
        callbacks = client_profiling['callbacks']
        renders = client_profiling.get('renders', [])

        print(f"\nTotal Callbacks: {len(callbacks)}")

        # Calculate totals
        total_network = sum(cb.get('networkTime', 0) for cb in callbacks.values())
        total_deserialize = sum(cb.get('deserializeTime', 0) for cb in callbacks.values())
        total_payload = sum(cb.get('payloadSize', 0) for cb in callbacks.values())
        total_render = sum(r.get('renderTime', 0) for r in renders)

        print(f"\nFrontend Time Breakdown:")
        print(f"  Network: {total_network:.1f}ms")
        print(f"  Deserialization: {total_deserialize:.1f}ms")
        print(f"  DOM Rendering: {total_render:.1f}ms")
        print(f"  Total: {total_network + total_deserialize + total_render:.1f}ms")
        print(f"  Total Payload: {total_payload / 1024 / 1024:.2f}MB")

        # Top 5 slowest callbacks
        print("\nTop 5 Slowest Callbacks:")
        callback_list = []
        for cb_id, cb_data in callbacks.items():
            network = cb_data.get('networkTime', 0)
            deserialize = cb_data.get('deserializeTime', 0)
            render_data = next((r for r in renders if r.get('callbackId') == cb_id), None)
            render = render_data.get('renderTime', 0) if render_data else 0
            total = network + deserialize + render

            callback_list.append({
                'id': cb_id,
                'network': network,
                'deserialize': deserialize,
                'render': render,
                'total': total,
                'payload': cb_data.get('payloadSize', 0)
            })

        callback_list.sort(key=lambda x: x['total'], reverse=True)

        for i, cb in enumerate(callback_list[:5], 1):
            print(f"\n{i}. {cb['id'][:80]}...")
            print(f"   Total: {cb['total']:.1f}ms")
            print(f"   - Network: {cb['network']:.1f}ms ({cb['network']/cb['total']*100:.1f}%)")
            print(f"   - Deserialize: {cb['deserialize']:.1f}ms ({cb['deserialize']/cb['total']*100:.1f}%)")
            if cb['render'] > 0:
                print(f"   - Render: {cb['render']:.1f}ms ({cb['render']/cb['total']*100:.1f}%)")
            print(f"   - Payload: {cb['payload']/1024:.1f}KB")

    else:
        print("\n⚠️  No client-side profiling data found")

    # Correlation Analysis
    print("\n" + "=" * 80)
    print("FRONTEND/BACKEND CORRELATION")
    print("=" * 80)

    if backend and backend.get('summary') and client_profiling and client_profiling.get('callbacks'):
        backend_total = sum(s['total_ms'] for s in backend['summary'].values())
        frontend_network = sum(cb.get('networkTime', 0) for cb in callbacks.values())
        frontend_deserialize = sum(cb.get('deserializeTime', 0) for cb in callbacks.values())
        frontend_render = sum(r.get('renderTime', 0) for r in renders)

        print(f"\nTotal Backend Processing: {backend_total:.1f}ms")
        print(f"Total Frontend Network: {frontend_network:.1f}ms")
        print(f"Total Frontend Deserialize: {frontend_deserialize:.1f}ms")
        print(f"Total Frontend Render: {frontend_render:.1f}ms")

        overhead = frontend_network - backend_total
        if overhead > 0:
            overhead_pct = (overhead / frontend_network) * 100
            print(f"\n⚠️  Network/Serialization Overhead: {overhead:.1f}ms ({overhead_pct:.1f}%)")

        backend_efficiency = (backend_total / frontend_network * 100) if frontend_network > 0 else 0
        print(f"\nBackend Efficiency: {backend_efficiency:.1f}%")

        if backend_efficiency < 50:
            print("  → Most time in network/serialization overhead")
        elif backend_efficiency > 80:
            print("  → Backend processing is primary bottleneck")
        else:
            print("  → Balanced between backend and network")

    print("\n" + "=" * 80)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python analyze_report.py <report.json>")
        sys.exit(1)

    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"Error: {report_path} not found")
        sys.exit(1)

    analyze_report(report_path)
