#!/usr/bin/env python3
"""
Analyze Dash callback graph to identify performance bottlenecks.

This script fetches the callback dependency graph from a running Dash app
and analyzes it for:
- Complex callbacks with many inputs/outputs
- Pattern-matching callbacks (MATCH, ALL) that are expensive to resolve
- Callbacks with prevent_initial_call=False that fire on page load
- Cascade chains where callbacks trigger each other
"""

import json
import sys
from collections import defaultdict
from typing import Any

import requests


def fetch_callback_graph(url: str = "http://localhost:5080/_dash-dependencies") -> list[dict[str, Any]]:
    """Fetch callback graph from Dash debug endpoint."""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Failed to fetch callback graph: {e}")
        sys.exit(1)


def parse_output_string(output_str: str) -> list[str]:
    """Parse Dash's encoded output string format.

    Format: "..component-id.property...another-id.property..@hash.."
    Returns list of "component-id.property" strings.
    """
    if not output_str:
        return []

    # Remove leading/trailing ".." and "@hash.." part
    # Split by ".." to get individual outputs
    parts = []
    for segment in output_str.split(".."):
        # Skip empty segments and hash segments (those starting with @)
        if segment and not segment.startswith("@"):
            parts.append(segment)

    return parts


def count_pattern_matching(callback: dict[str, Any]) -> tuple[int, int]:
    """Count MATCH and ALL pattern usage in a callback."""
    match_count = 0
    all_count = 0

    for section in ["inputs", "state"]:
        items = callback.get(section, [])
        for item in items:
            id_value = item.get("id")

            # Try to parse JSON string ID (Dash format)
            if isinstance(id_value, str) and id_value.startswith("{"):
                try:
                    id_dict = json.loads(id_value)
                    if isinstance(id_dict, dict):
                        for key, value in id_dict.items():
                            if isinstance(value, list):
                                if "MATCH" in value:
                                    match_count += 1
                                if "ALL" in value:
                                    all_count += 1
                except json.JSONDecodeError:
                    pass
            # Also check if it's already a dict
            elif isinstance(id_value, dict):
                for key, value in id_value.items():
                    if isinstance(value, list):
                        if "MATCH" in value:
                            match_count += 1
                        if "ALL" in value:
                            all_count += 1

    # Check output too
    output = callback.get("output", "")
    if isinstance(output, str) and output.startswith("{"):
        try:
            output_dict = json.loads(output.split(".")[0])
            if isinstance(output_dict, dict):
                for key, value in output_dict.items():
                    if isinstance(value, list):
                        if "MATCH" in value:
                            match_count += 1
                        if "ALL" in value:
                            all_count += 1
        except (json.JSONDecodeError, IndexError):
            pass

    return match_count, all_count


def extract_callback_id(callback: dict[str, Any]) -> str:
    """Generate a readable ID for a callback."""
    outputs = callback.get("output", "")
    if not outputs:
        # Try to use first input as identifier
        inputs = callback.get("inputs", [])
        if inputs and len(inputs) > 0:
            first_input_id = inputs[0].get("id", "")
            if first_input_id:
                return f"triggered-by-{first_input_id}"[:60]
        return "no-output"

    # Handle single output or multiple outputs
    if isinstance(outputs, str):
        # Extract just the component ID, not the property
        if ".." in outputs:  # Multiple outputs format
            # Take first output ID
            parts = outputs.split("..")
            for part in parts:
                if part:
                    return part.split(".")[0] if "." in part else part[:50]
        return outputs.split(".")[0] if "." in outputs else outputs[:50]

    # For multiple outputs, use first one
    return str(outputs)[:50]


def analyze_callback_complexity(callbacks: list[dict[str, Any]]) -> None:
    """Analyze and report callback complexity metrics."""
    print("=" * 80)
    print("🔍 CALLBACK GRAPH ANALYSIS")
    print("=" * 80)

    total_callbacks = len(callbacks)
    clientside_callbacks = sum(1 for c in callbacks if c.get("clientside_function"))
    serverside_callbacks = total_callbacks - clientside_callbacks
    prevent_initial_false = sum(1 for c in callbacks if not c.get("prevent_initial_call", True))

    print(f"\n📊 SUMMARY:")
    print(f"   Total callbacks: {total_callbacks}")
    print(f"   Server-side: {serverside_callbacks}")
    print(f"   Client-side: {clientside_callbacks}")
    print(f"   Fire on initial load (prevent_initial_call=False): {prevent_initial_false}")

    # Analyze pattern matching
    pattern_matching_callbacks = []
    for callback in callbacks:
        match_count, all_count = count_pattern_matching(callback)
        if match_count > 0 or all_count > 0:
            pattern_matching_callbacks.append(
                {
                    "callback": callback,
                    "match_count": match_count,
                    "all_count": all_count,
                    "total_patterns": match_count + all_count,
                }
            )

    print(f"\n🔄 PATTERN-MATCHING CALLBACKS: {len(pattern_matching_callbacks)}")
    if pattern_matching_callbacks:
        # Sort by complexity (total patterns)
        pattern_matching_callbacks.sort(key=lambda x: x["total_patterns"], reverse=True)

        print("\n   Top 10 most complex pattern-matching callbacks:")
        for i, item in enumerate(pattern_matching_callbacks[:10], 1):
            cb = item["callback"]
            cb_id = extract_callback_id(cb)
            is_client = "✓" if cb.get("clientside_function") else "✗"
            prevent_initial = "✓" if not cb.get("prevent_initial_call", True) else "✗"

            # Parse outputs correctly
            output_str = cb.get("output", "")
            output_list = parse_output_string(output_str)

            print(f"\n   {i}. {cb_id[:60]}")
            print(f"      MATCH: {item['match_count']}, ALL: {item['all_count']}")
            print(
                f"      Inputs: {len(cb.get('inputs', []))}, Outputs: {len(output_list)}"
            )
            print(
                f"      Client-side: {is_client}, Fires on load: {prevent_initial}"
            )

    # Analyze initial load callbacks
    initial_load_callbacks = [c for c in callbacks if not c.get("prevent_initial_call", True)]
    initial_load_server = [c for c in initial_load_callbacks if not c.get("clientside_function")]
    initial_load_client = [c for c in initial_load_callbacks if c.get("clientside_function")]

    if initial_load_callbacks:
        print(f"\n⚡ CALLBACKS FIRING ON INITIAL LOAD: {len(initial_load_callbacks)}")
        print(f"   🔴 SERVER-SIDE: {len(initial_load_server)} (EXPENSIVE!)")
        print(f"   ✅ CLIENT-SIDE: {len(initial_load_client)} (Fast)")
        print("\n   ⚠️  These callbacks execute during the 670ms initialization gap:")
        print("   Each server-side callback adds ~10-50ms overhead!")

        # Show server-side callbacks first (most important)
        print(f"\n   📊 TOP {min(20, len(initial_load_server))} SERVER-SIDE CALLBACKS FIRING ON LOAD:")
        for i, callback in enumerate(initial_load_server[:20], 1):
            cb_id = extract_callback_id(callback)
            match_count, all_count = count_pattern_matching(callback)
            pattern_info = (
                f" (MATCH={match_count}, ALL={all_count})"
                if match_count + all_count > 0
                else ""
            )
            complexity = len(callback.get('inputs', [])) + len(callback.get('state', []))

            print(f"\n   {i}. {cb_id[:60]}{pattern_info}")
            print(f"      Complexity: {complexity} (Inputs: {len(callback.get('inputs', []))}, State: {len(callback.get('state', []))})")

            # Show input IDs to understand what triggers it
            if len(callback.get('inputs', [])) <= 3:
                inputs = callback.get('inputs', [])
                print(f"      Triggered by: {[inp.get('id', '')[:40] for inp in inputs]}")

        # Show some client-side too
        if initial_load_client:
            print(f"\n   ℹ️  CLIENT-SIDE CALLBACKS (first 5, less critical):")
            for i, callback in enumerate(initial_load_client[:5], 1):
                cb_id = extract_callback_id(callback)
                print(f"      {i}. {cb_id[:60]}")

    # Analyze callback chains (callbacks whose outputs are inputs to others)
    print(f"\n🔗 ANALYZING CALLBACK DEPENDENCY CHAINS...")

    # Build output -> callbacks map
    output_to_callbacks = defaultdict(list)
    for callback in callbacks:
        output_str = callback.get("output", "")
        output_list = parse_output_string(output_str)

        for output in output_list:
            output_to_callbacks[output].append(callback)

    # Find chains
    chains_found = 0
    max_chain_depth = 0

    for callback in callbacks:
        inputs = callback.get("inputs", [])
        for input_spec in inputs:
            input_id = input_spec.get("id", "")
            input_prop = input_spec.get("property", "")
            input_key = f"{input_id}.{input_prop}"

            # Check if this input is an output of another callback
            if input_key in output_to_callbacks:
                chains_found += 1
                # This creates a chain

    print(f"   Found {chains_found} callback dependencies (potential cascades)")

    # Find most complex server-side callbacks
    complex_callbacks = []
    for callback in callbacks:
        if not callback.get("clientside_function"):
            input_count = len(callback.get("inputs", []))
            state_count = len(callback.get("state", []))
            # Parse output string properly
            output_str = callback.get("output", "")
            output_list = parse_output_string(output_str)
            output_count = len(output_list)
            complexity = input_count + state_count + output_count

            complex_callbacks.append(
                {
                    "callback": callback,
                    "complexity": complexity,
                    "inputs": input_count,
                    "state": state_count,
                    "outputs": output_count,
                }
            )

    # Sort by complexity
    complex_callbacks.sort(key=lambda x: x["complexity"], reverse=True)

    print(f"\n⚙️  TOP 10 MOST COMPLEX SERVER-SIDE CALLBACKS:")
    for i, item in enumerate(complex_callbacks[:10], 1):
        cb = item["callback"]
        cb_id = extract_callback_id(cb)
        prevent_initial = "FIRES ON LOAD" if not cb.get("prevent_initial_call", True) else ""

        print(f"\n   {i}. {cb_id[:60]}")
        print(
            f"      Complexity: {item['complexity']} (Inputs: {item['inputs']}, State: {item['state']}, Outputs: {item['outputs']})"
        )
        if prevent_initial:
            print(f"      ⚠️  {prevent_initial}")

    # Recommendations
    print(f"\n💡 OPTIMIZATION RECOMMENDATIONS:")
    print(f"\n   1. Convert expensive server-side callbacks to client-side:")
    expensive_server = [
        c
        for c in complex_callbacks
        if c["complexity"] > 10 and not c["callback"].get("clientside_function")
    ]
    if expensive_server:
        print(f"      Found {len(expensive_server)} candidates with complexity > 10")

    print(f"\n   2. Set prevent_initial_call=True for non-essential callbacks:")
    non_essential = [
        c
        for c in callbacks
        if not c.get("prevent_initial_call", True) and not c.get("clientside_function")
    ]
    if non_essential:
        print(f"      Found {len(non_essential)} server-side callbacks firing on load")

    print(
        f"\n   3. Simplify pattern-matching callbacks (MATCH/ALL are expensive to resolve):"
    )
    if pattern_matching_callbacks:
        expensive_patterns = [p for p in pattern_matching_callbacks if p["total_patterns"] > 5]
        if expensive_patterns:
            print(f"      Found {len(expensive_patterns)} callbacks with > 5 pattern matches")

    print("\n" + "=" * 80)


def main():
    """Main entry point."""
    print("🔍 Fetching callback graph from Dash app...")

    callbacks = fetch_callback_graph()
    print(f"✅ Fetched {len(callbacks)} callbacks\n")

    analyze_callback_complexity(callbacks)


if __name__ == "__main__":
    main()
