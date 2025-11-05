#!/usr/bin/env python3
"""Quick performance summary from JSON report"""
import json
import sys

report_path = sys.argv[1] if len(sys.argv) > 1 else "performance_report_20251027_224455.json"

with open(report_path) as f:
    data = json.load(f)

print("=" * 80)
print("QUICK PERFORMANCE SUMMARY")
print("=" * 80)

# Backend profiling
backend = data.get('backend_profiling', {})
if backend and backend.get('summary'):
    summary = backend['summary']
    cache_stats = backend.get('cache_stats', {})

    print("\n🔧 BACKEND PROFILING:")
    total_backend_time = sum(op['total_ms'] for op in summary.values())
    print(f"  Total Backend Time: {total_backend_time:.0f}ms ({total_backend_time/1000:.2f}s)")

    # Cache
    total_cache_ops = cache_stats.get('hits', 0) + cache_stats.get('misses', 0)
    if total_cache_ops > 0:
        hit_rate = (cache_stats.get('hits', 0) / total_cache_ops) * 100
        print(f"  Cache Hit Rate: {hit_rate:.1f}% ({cache_stats.get('hits', 0)}/{total_cache_ops})")

    # Top 3 slowest operations
    print("\n  Top 3 Slowest Backend Operations:")
    sorted_ops = sorted(summary.items(), key=lambda x: x[1]['total_ms'], reverse=True)
    for i, (op, stats) in enumerate(sorted_ops[:3], 1):
        print(f"    {i}. {op}")
        print(f"       {stats['count']} calls, {stats['total_ms']:.0f}ms total, {stats['avg_ms']:.1f}ms avg")

# Client profiling
perf = data.get('performance_metrics', {})
client = perf.get('clientSideProfiling')
if client and client.get('callbacks'):
    callbacks = client['callbacks']
    renders = client.get('renders', [])

    total_network = sum(cb.get('networkTime', 0) for cb in callbacks.values())
    total_deserialize = sum(cb.get('deserializeTime', 0) for cb in callbacks.values())
    total_render = sum(r.get('renderTime', 0) for r in renders)

    print("\n⚡ FRONTEND PROFILING:")
    print(f"  Total Callbacks: {len(callbacks)}")
    print(f"  Network Time: {total_network:.0f}ms")
    print(f"  Deserialization: {total_deserialize:.0f}ms")
    print(f"  DOM Rendering: {total_render:.0f}ms")
    print(f"  TOTAL: {total_network + total_deserialize + total_render:.0f}ms")

# Correlation
if backend and backend.get('summary') and client and client.get('callbacks'):
    print("\n🔗 CORRELATION:")
    backend_total = sum(op['total_ms'] for op in backend['summary'].values())

    overhead = total_network - backend_total
    if overhead > 0:
        overhead_pct = (overhead / total_network) * 100
        print(f"  Network/Serialization Overhead: {overhead:.0f}ms ({overhead_pct:.1f}%)")

    backend_efficiency = (backend_total / total_network * 100) if total_network > 0 else 0
    print(f"  Backend Efficiency: {backend_efficiency:.1f}%")

    if backend_efficiency < 50:
        print("  → Bottleneck: Network/serialization overhead")
    elif backend_efficiency > 80:
        print("  → Bottleneck: Backend processing")
    else:
        print("  → Balanced performance")

print("\n" + "=" * 80)
