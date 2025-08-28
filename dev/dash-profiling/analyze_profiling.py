#!/usr/bin/env python3
"""
Fresh Profiling Analysis Tool
Analyzes newly generated profiling files to identify performance bottlenecks.
"""

import os
import pstats
import glob
import re
from pathlib import Path
from collections import defaultdict, Counter
from typing import List, Dict, Tuple
import argparse


def parse_filename(filename: str) -> Dict[str, str]:
    """Extract metadata from profiling filename."""
    basename = os.path.basename(filename)
    
    # Pattern: METHOD.endpoint.duration.timestamp.prof
    parts = basename.replace('.prof', '').split('.')
    
    info = {
        'filename': basename,
        'full_path': filename,
        'method': 'UNKNOWN',
        'endpoint': 'unknown',
        'duration_ms': 0,
        'timestamp': 0
    }
    
    if len(parts) >= 2:
        info['method'] = parts[0]
        
        # Extract duration (look for pattern like "123ms")
        for part in parts:
            if 'ms' in part:
                try:
                    info['duration_ms'] = int(part.replace('ms', ''))
                    break
                except ValueError:
                    pass
        
        # Extract timestamp (usually last numeric part)
        for part in reversed(parts):
            if part.isdigit():
                info['timestamp'] = int(part)
                break
        
        # Reconstruct endpoint (everything except method, duration, timestamp)
        endpoint_parts = []
        for part in parts[1:]:
            if not ('ms' in part or part.isdigit()):
                endpoint_parts.append(part)
        info['endpoint'] = '.'.join(endpoint_parts) if endpoint_parts else 'unknown'
    
    return info


def analyze_single_profile(filename: str, top_n: int = 50) -> Dict:
    """Analyze a single profile file with detailed function breakdown."""
    try:
        stats = pstats.Stats(filename)
        stats.sort_stats('cumulative')
        
        # Get comprehensive function analysis
        all_functions = []
        bytearray_functions = []
        ndarray_functions = []
        serialization_functions = []
        dash_functions = []
        
        for func, (cc, nc, tt, ct, callers) in stats.stats.items():
            filename_part, line_num, func_name = func
            func_info = {
                'function': f"{os.path.basename(filename_part)}:{line_num}({func_name})",
                'full_path': filename_part,
                'cumulative_time': ct,
                'total_time': tt,
                'call_count': cc,
                'per_call': ct / cc if cc > 0 else 0,
                'per_call_own': tt / cc if cc > 0 else 0,
                'percentage': (ct / stats.total_tt * 100) if stats.total_tt > 0 else 0
            }
            
            all_functions.append(func_info)
            
            # Categorize functions by type
            func_str = func_info['function'].lower()
            
            if 'bytearray' in func_str:
                bytearray_functions.append(func_info)
            
            if 'ndarray' in func_str or 'numpy' in func_str:
                ndarray_functions.append(func_info)
                
            if any(word in func_str for word in ['serialize', 'json', 'pickle', 'dump', 'encode']):
                serialization_functions.append(func_info)
                
            if any(word in func_str for word in ['dash', 'plotly', 'callback']):
                dash_functions.append(func_info)
        
        # Sort by cumulative time
        all_functions.sort(key=lambda x: x['cumulative_time'], reverse=True)
        bytearray_functions.sort(key=lambda x: x['cumulative_time'], reverse=True)
        ndarray_functions.sort(key=lambda x: x['cumulative_time'], reverse=True)
        serialization_functions.sort(key=lambda x: x['cumulative_time'], reverse=True)
        dash_functions.sort(key=lambda x: x['cumulative_time'], reverse=True)
        
        return {
            'top_functions': all_functions[:top_n],
            'bytearray_functions': bytearray_functions[:20],
            'ndarray_functions': ndarray_functions[:20],
            'serialization_functions': serialization_functions[:20],
            'dash_functions': dash_functions[:20],
            'total_time': stats.total_tt,
            'total_calls': sum(cc for (cc, nc, tt, ct, callers) in stats.stats.values()),
            'function_count': len(all_functions)
        }
    except Exception as e:
        return {'error': str(e)}


def find_bottlenecks(prof_dir: str, min_duration_ms: int = 50) -> Dict:
    """Find and analyze performance bottlenecks in profiling files."""
    
    prof_files = glob.glob(os.path.join(prof_dir, "*.prof"))
    
    if not prof_files:
        return {
            'error': 'No profiling files found. Make sure profiling is enabled.',
            'suggestion': 'Set DEPICTIO_PROFILING_ENABLED=true and DEPICTIO_PROFILING_WERKZEUG_ENABLED=true'
        }
    
    print(f"📊 Analyzing {len(prof_files)} profiling files...")
    
    # Parse and categorize files
    file_info = []
    slow_requests = []
    endpoint_stats = defaultdict(list)
    method_stats = defaultdict(list)
    
    for prof_file in prof_files:
        info = parse_filename(prof_file)
        file_info.append(info)
        
        # Track slow requests
        if info['duration_ms'] >= min_duration_ms:
            slow_requests.append(info)
        
        # Group by endpoint and method
        endpoint_stats[info['endpoint']].append(info)
        method_stats[info['method']].append(info)
    
    # Sort by duration
    slow_requests.sort(key=lambda x: x['duration_ms'], reverse=True)
    
    # Analyze top slow requests
    detailed_analysis = []
    for slow_req in slow_requests[:5]:  # Top 5 slowest
        print(f"🔍 Analyzing slow request: {slow_req['filename']} ({slow_req['duration_ms']}ms)")
        analysis = analyze_single_profile(slow_req['full_path'])
        analysis.update(slow_req)
        detailed_analysis.append(analysis)
    
    # Calculate endpoint statistics
    endpoint_summary = {}
    for endpoint, requests in endpoint_stats.items():
        durations = [r['duration_ms'] for r in requests]
        endpoint_summary[endpoint] = {
            'count': len(requests),
            'avg_duration': sum(durations) / len(durations),
            'max_duration': max(durations),
            'min_duration': min(durations),
            'total_time': sum(durations)
        }
    
    return {
        'total_files': len(prof_files),
        'slow_requests': len(slow_requests),
        'slowest_requests': slow_requests[:10],
        'endpoint_summary': dict(sorted(endpoint_summary.items(), 
                                      key=lambda x: x[1]['avg_duration'], reverse=True)),
        'detailed_analysis': detailed_analysis,
        'recommendations': generate_recommendations(slow_requests, endpoint_summary)
    }


def generate_recommendations(slow_requests: List[Dict], endpoint_summary: Dict) -> List[str]:
    """Generate optimization recommendations based on analysis."""
    recommendations = []
    
    if not slow_requests:
        recommendations.append("✅ No slow requests found! Performance looks good.")
        return recommendations
    
    # Find most problematic endpoints
    slow_endpoints = []
    for endpoint, stats in endpoint_summary.items():
        if stats['avg_duration'] > 100 or stats['max_duration'] > 500:
            slow_endpoints.append((endpoint, stats))
    
    slow_endpoints.sort(key=lambda x: x[1]['avg_duration'], reverse=True)
    
    if slow_endpoints:
        recommendations.append(f"🎯 Focus on these slow endpoints:")
        for endpoint, stats in slow_endpoints[:3]:
            recommendations.append(f"   - {endpoint}: avg {stats['avg_duration']:.1f}ms, max {stats['max_duration']}ms")
    
    # Check for specific bottlenecks
    common_patterns = Counter()
    for req in slow_requests[:10]:
        if 'dash-update-component' in req['endpoint']:
            common_patterns['dash_callbacks'] += 1
        elif 'component_data' in req['endpoint']:
            common_patterns['component_loading'] += 1
        elif 'deltatables' in req['endpoint']:
            common_patterns['data_loading'] += 1
    
    for pattern, count in common_patterns.most_common(3):
        if pattern == 'dash_callbacks':
            recommendations.append(f"🔧 {count} slow Dash callbacks found - consider caching or optimization")
        elif pattern == 'component_loading':
            recommendations.append(f"📊 {count} slow component loads - check if bulk loading is working")
        elif pattern == 'data_loading':
            recommendations.append(f"💾 {count} slow data loads - verify DataFrame caching")
    
    return recommendations


def print_analysis_report(analysis: Dict):
    """Print a formatted analysis report."""
    if 'error' in analysis:
        print(f"❌ Error: {analysis['error']}")
        if 'suggestion' in analysis:
            print(f"💡 {analysis['suggestion']}")
        return
    
    print("=" * 80)
    print("🚀 PROFILING ANALYSIS REPORT")
    print("=" * 80)
    
    print(f"\n📈 SUMMARY:")
    print(f"   Total requests analyzed: {analysis['total_files']}")
    print(f"   Slow requests (>50ms): {analysis['slow_requests']}")
    
    if analysis['slowest_requests']:
        print(f"\n🐌 SLOWEST REQUESTS:")
        for i, req in enumerate(analysis['slowest_requests'][:5], 1):
            print(f"   {i}. {req['method']} {req['endpoint']}")
            print(f"      Duration: {req['duration_ms']}ms")
            print(f"      File: {req['filename']}")
    
    if analysis['endpoint_summary']:
        print(f"\n📊 ENDPOINT PERFORMANCE:")
        for endpoint, stats in list(analysis['endpoint_summary'].items())[:5]:
            print(f"   {endpoint}:")
            print(f"      Avg: {stats['avg_duration']:.1f}ms | Max: {stats['max_duration']}ms | Count: {stats['count']}")
    
    if analysis['detailed_analysis']:
        print(f"\n🔍 DETAILED FUNCTION ANALYSIS:")
        for i, details in enumerate(analysis['detailed_analysis'][:1], 1):  # Focus on slowest request
            if 'error' not in details:
                print(f"   Request #{i}: {details['endpoint']} ({details['duration_ms']}ms)")
                print(f"   Total functions analyzed: {details.get('function_count', 0)}")
                
                # Top overall functions
                print(f"\n   📊 TOP FUNCTIONS BY TIME:")
                for j, func in enumerate(details['top_functions'][:15], 1):
                    print(f"      {j:2d}. {func['function'][:80]}")
                    print(f"          Time: {func['cumulative_time']:.4f}s ({func['percentage']:.2f}%) | Calls: {func['call_count']:,} | Per-call: {func['per_call']*1000:.2f}ms")
                
                # Bytearray operations
                if details.get('bytearray_functions'):
                    print(f"\n   🧬 BYTEARRAY OPERATIONS:")
                    for j, func in enumerate(details['bytearray_functions'][:10], 1):
                        print(f"      {j:2d}. {func['function'][:80]}")
                        print(f"          Time: {func['cumulative_time']:.4f}s ({func['percentage']:.2f}%) | Calls: {func['call_count']:,}")
                
                # Serialization functions
                if details.get('serialization_functions'):
                    print(f"\n   📦 SERIALIZATION OPERATIONS:")
                    for j, func in enumerate(details['serialization_functions'][:10], 1):
                        print(f"      {j:2d}. {func['function'][:80]}")
                        print(f"          Time: {func['cumulative_time']:.4f}s ({func['percentage']:.2f}%) | Calls: {func['call_count']:,}")
                
                # Dash-related functions
                if details.get('dash_functions'):
                    print(f"\n   ⚡ DASH/PLOTLY OPERATIONS:")
                    for j, func in enumerate(details['dash_functions'][:10], 1):
                        print(f"      {j:2d}. {func['function'][:80]}")
                        print(f"          Time: {func['cumulative_time']:.4f}s ({func['percentage']:.2f}%) | Calls: {func['call_count']:,}")
                
                # NumPy/ndarray functions
                if details.get('ndarray_functions'):
                    print(f"\n   🔢 NUMPY/NDARRAY OPERATIONS:")
                    for j, func in enumerate(details['ndarray_functions'][:10], 1):
                        print(f"      {j:2d}. {func['function'][:80]}")
                        print(f"          Time: {func['cumulative_time']:.4f}s ({func['percentage']:.2f}%) | Calls: {func['call_count']:,}")
    
    print(f"\n💡 RECOMMENDATIONS:")
    for rec in analysis['recommendations']:
        print(f"   {rec}")
    
    print(f"\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Analyze profiling files for bottlenecks")
    parser.add_argument("--prof-dir", default="./prof_files", help="Profiling files directory")
    parser.add_argument("--min-duration", type=int, default=50, help="Minimum duration (ms) to consider slow")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top functions to analyze per file")
    
    args = parser.parse_args()
    
    analysis = find_bottlenecks(args.prof_dir, args.min_duration)
    print_analysis_report(analysis)


if __name__ == "__main__":
    main()