#!/usr/bin/env python3
"""
Dash Callback Flow Analyzer
Traces callback execution timeline, identifies cascades, and provides optimization recommendations
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


class CallbackFlowAnalyzer:
    def __init__(self, report_path, show_source=False, verbose=False):
        with open(report_path) as f:
            self.data = json.load(f)

        self.callbacks = []
        self.page_load_time = None
        self.callback_map = {}  # Maps component outputs to their callbacks
        self.show_source = show_source
        self.verbose = verbose
        self.callback_registry = self.load_callback_registry() if show_source else {}

    def parse_callback_data(self, post_data):
        """Extract inputs, outputs, and state from Dash callback POST data"""
        result = {
            "outputs": [],
            "inputs": [],
            "state": [],
        }

        if not post_data:
            return result

        try:
            data = json.loads(post_data)

            # Extract outputs
            if "outputs" in data:
                result["outputs"] = data["outputs"] if isinstance(data["outputs"], list) else [data["outputs"]]

            # Extract inputs
            if "inputs" in data:
                result["inputs"] = data["inputs"] if isinstance(data["inputs"], list) else [data["inputs"]]

            # Extract state
            if "state" in data:
                result["state"] = data["state"] if isinstance(data["state"], list) else [data["state"]]

        except (json.JSONDecodeError, TypeError):
            pass

        return result

    def load_callback_registry(self):
        """Load pre-built callback registry from JSON"""
        registry_path = Path(__file__).parent / "callback_registry.json"
        if registry_path.exists():
            try:
                with open(registry_path) as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  Error loading callback registry: {e}")
                return {}
        else:
            print("⚠️  Callback registry not found. Run: python callback_registry_builder.py")
            return {}

    def match_callback_to_source(self, callback):
        """Match callback inputs/outputs to source function using registry"""
        if not self.callback_registry:
            return None

        # Strategy 1: Match by output component IDs
        output_patterns = []
        for output in callback.get("outputs", []):
            if isinstance(output, dict):
                comp_id = output.get("id", "unknown")
                prop = output.get("property", "unknown")

                # Simplify pattern-matching IDs
                if isinstance(comp_id, dict):
                    comp_id = "pattern"
                elif isinstance(comp_id, str) and len(comp_id) > 30:
                    comp_id = comp_id[:27] + "..."

                output_patterns.append(f"{comp_id}.{prop}")

        if output_patterns:
            # Try exact match
            pattern_key = "→".join(sorted(output_patterns))
            if pattern_key in self.callback_registry:
                return self.callback_registry[pattern_key]

            # Try single output match
            for pattern in output_patterns:
                if pattern in self.callback_registry:
                    return self.callback_registry[pattern]

        # Strategy 2: Fuzzy match by checking if any registry output matches
        for reg_pattern, reg_info in self.callback_registry.items():
            # Check if output properties overlap
            for output in callback.get("outputs", []):
                if isinstance(output, dict):
                    output_str = str(output.get("property", ""))
                    if output_str and output_str in reg_pattern:
                        return reg_info

        return None

    def analyze_callbacks(self):
        """Build timeline of callbacks with durations"""

        network_requests = self.data.get("network_requests", [])

        # Find page load time (first request)
        for req in network_requests:
            if "dashboard" in req.get("url", ""):
                self.page_load_time = datetime.fromisoformat(req["timestamp"])
                break

        # Match callback requests with responses
        pending_requests = {}

        for req in network_requests:
            url = req.get("url", "")

            if "_dash-update-component" not in url:
                continue

            timestamp = datetime.fromisoformat(req["timestamp"])

            if req.get("type") == "request" or "method" in req:
                # This is a request - parse POST data
                post_data = req.get("post_data")
                callback_data = self.parse_callback_data(post_data)

                # Use a unique key combining URL and timestamp
                request_key = f"{url}_{timestamp.isoformat()}"
                pending_requests[request_key] = {
                    "start_time": timestamp,
                    "inputs": callback_data["inputs"],
                    "outputs": callback_data["outputs"],
                    "state": callback_data["state"],
                    "url": url,
                    "post_data": post_data,
                }

            elif req.get("type") == "response":
                # This is a response - match with most recent request for this URL
                matched_key = None
                for key in pending_requests:
                    if key.startswith(url):
                        matched_key = key
                        break

                if matched_key:
                    request_data = pending_requests[matched_key]
                    duration = (timestamp - request_data["start_time"]).total_seconds() * 1000

                    callback = {
                        "start_time": request_data["start_time"],
                        "end_time": timestamp,
                        "duration": duration,
                        "inputs": request_data["inputs"],
                        "outputs": request_data["outputs"],
                        "state": request_data["state"],
                        "status": req.get("status"),
                        "size": req.get("size", 0),
                        "response_body": req.get("response_body"),
                        "relative_start": (request_data["start_time"] - self.page_load_time).total_seconds() * 1000
                        if self.page_load_time
                        else 0,
                    }

                    self.callbacks.append(callback)

                    # Build callback map for cascade detection
                    flat_outputs = []
                    for output in request_data["outputs"]:
                        if isinstance(output, list):
                            flat_outputs.extend(output)
                        else:
                            flat_outputs.append(output)

                    for output in flat_outputs:
                        if isinstance(output, dict):
                            key = f"{output.get('id', 'unknown')}.{output.get('property', 'unknown')}"
                            if key not in self.callback_map:
                                self.callback_map[key] = []
                            self.callback_map[key].append(callback)

                    del pending_requests[matched_key]

        # Sort callbacks by start time
        self.callbacks.sort(key=lambda x: x["start_time"])

    def format_io(self, io_list):
        """Format inputs/outputs for display"""
        if not io_list:
            return "none"

        # Flatten if io_list is a list of lists
        flat_list = []
        for item in io_list:
            if isinstance(item, list):
                flat_list.extend(item)
            else:
                flat_list.append(item)

        if not flat_list:
            return "none"

        # Verbose mode: show ALL items with full details
        if self.verbose:
            return self.format_io_verbose(flat_list)

        # Normal mode: show first 3 items, truncated
        formatted = []
        for item in flat_list[:3]:  # Limit to first 3 items
            if not isinstance(item, dict):
                formatted.append(str(item))
                continue

            comp_id = item.get("id", "unknown")
            prop = item.get("property", "unknown")

            # Shorten long IDs
            if isinstance(comp_id, str) and len(comp_id) > 30:
                comp_id = comp_id[:27] + "..."
            elif isinstance(comp_id, dict):
                # Sometimes ID is a dict with nested structure
                comp_id = str(comp_id)[:27] + "..."

            formatted.append(f"{comp_id}.{prop}")

        if len(flat_list) > 3:
            formatted.append(f"... +{len(flat_list) - 3} more")

        return ", ".join(formatted)

    def format_io_verbose(self, io_list):
        """Format inputs/outputs for verbose display (all items, full details)"""
        lines = []
        for i, item in enumerate(io_list, 1):
            if not isinstance(item, dict):
                lines.append(f"       [{i}] {item}")
                continue

            comp_id = item.get("id", "unknown")
            prop = item.get("property", "unknown")

            # Show full ID for pattern-matching
            if isinstance(comp_id, dict):
                comp_id_str = str(comp_id)
            else:
                comp_id_str = str(comp_id)

            lines.append(f"       [{i}] {comp_id_str}.{prop}")

        return "\n" + "\n".join(lines) if lines else "none"

    def explain_status_code(self, status):
        """Explain HTTP status code in Dash callback context"""
        explanations = {
            200: "✅ Normal - Callback returned data",
            204: "✅ Optimized - PreventUpdate or no_update (GOOD - callback was skipped)",
            500: "❌ Error - Callback failed with exception",
            400: "❌ Bad Request - Invalid callback data",
            404: "❌ Not Found - Callback endpoint missing",
        }
        return explanations.get(status, "Unknown status")

    def identify_cascades(self):
        """Find callback chains where one callback's output triggers another's input"""

        cascades = []
        visited = set()

        def flatten_io(io_list):
            """Flatten nested lists in inputs/outputs"""
            flat = []
            for item in io_list:
                if isinstance(item, list):
                    flat.extend(item)
                else:
                    flat.append(item)
            return flat

        def find_chain(callback, chain=None):
            if chain is None:
                chain = []

            chain.append(callback)
            callback_id = id(callback)

            if callback_id in visited:
                return [chain]

            visited.add(callback_id)

            # Check if any of this callback's outputs trigger other callbacks
            triggered_callbacks = []
            for output in flatten_io(callback["outputs"]):
                if not isinstance(output, dict):
                    continue

                output_key = f"{output.get('id', 'unknown')}.{output.get('property', 'unknown')}"

                # Find callbacks triggered by this output
                for other_callback in self.callbacks:
                    if other_callback == callback:
                        continue

                    # Check if this output is in other callback's inputs
                    for inp in flatten_io(other_callback["inputs"]):
                        if not isinstance(inp, dict):
                            continue

                        input_key = f"{inp.get('id', 'unknown')}.{inp.get('property', 'unknown')}"
                        if input_key == output_key and other_callback["start_time"] > callback["end_time"]:
                            triggered_callbacks.append(other_callback)

            if not triggered_callbacks:
                return [chain]

            # Recursively find chains
            all_chains = []
            for triggered in triggered_callbacks:
                sub_chains = find_chain(triggered, chain.copy())
                all_chains.extend(sub_chains)

            return all_chains if all_chains else [chain]

        # Find all cascade chains
        for callback in self.callbacks:
            if id(callback) not in visited:
                chains = find_chain(callback)
                for chain in chains:
                    if len(chain) > 1:  # Only report actual cascades
                        total_duration = sum(c["duration"] for c in chain)
                        cascades.append({"chain": chain, "total_duration": total_duration})

        return cascades

    def generate_timeline(self):
        """Generate ASCII timeline visualization"""

        print("\n" + "=" * 100)
        print("DASH CALLBACK EXECUTION TIMELINE")
        print("=" * 100)

        if not self.callbacks:
            print("\nNo callbacks found in the performance report.")
            return

        # Group callbacks by time window (identify parallel execution)
        time_windows = []
        window_size = 50  # ms

        for callback in self.callbacks:
            placed = False
            for window in time_windows:
                if abs(callback["relative_start"] - window["start"]) < window_size:
                    window["callbacks"].append(callback)
                    placed = True
                    break

            if not placed:
                time_windows.append({"start": callback["relative_start"], "callbacks": [callback]})

        # Display timeline
        for i, callback in enumerate(self.callbacks, 1):
            # Calculate bar length for duration visualization
            bar_length = int(callback["duration"] / 10)  # 1 char = 10ms
            bar = "█" * min(bar_length, 40)

            # Check if parallel with next callback
            is_parallel = ""
            if i < len(self.callbacks):
                next_cb = self.callbacks[i]
                time_gap = next_cb["relative_start"] - callback["relative_start"]
                if time_gap < 50:  # Started within 50ms
                    is_parallel = " ⚡PARALLEL"

            # Format display
            print(f"\n[{i:2d}] T={callback['relative_start']:.0f}ms")
            print(f"     ⏱️  {callback['duration']:.0f}ms {bar}{is_parallel}")

            # Show callback source if available
            if self.show_source:
                source_info = self.match_callback_to_source(callback)
                if source_info:
                    print(f"     📍 CALLBACK: {source_info['function']}()")
                    print(f"        FILE: {source_info['file']}:{source_info['line']}")
                    if source_info.get('docstring'):
                        print(f"        DOC: {source_info['docstring']}")
                else:
                    print(f"     📍 [Unknown callback - no source match]")

            print(f"     IN:  {self.format_io(callback['inputs'])}")
            print(f"     OUT: {self.format_io(callback['outputs'])}")

            if callback["status"] != 200:
                status_explanation = self.explain_status_code(callback["status"])
                print(f"     ⚠️  Status: {callback['status']} - {status_explanation}")

    def generate_statistics(self):
        """Generate callback statistics"""

        if not self.callbacks:
            return

        durations = [c["duration"] for c in self.callbacks]
        total_time = sum(durations)
        avg_time = total_time / len(durations)
        max_time = max(durations)
        min_time = min(durations)

        print("\n\n" + "=" * 100)
        print("CALLBACK STATISTICS")
        print("=" * 100)

        print(f"\nTotal Callbacks: {len(self.callbacks)}")
        print(f"Total Sequential Time: {total_time:.0f}ms ({total_time/1000:.2f}s)")
        print(f"Average Duration: {avg_time:.0f}ms")
        print(f"Min Duration: {min_time:.0f}ms")
        print(f"Max Duration: {max_time:.0f}ms")

        # Distribution
        slow_callbacks = [c for c in self.callbacks if c["duration"] > 100]
        very_slow_callbacks = [c for c in self.callbacks if c["duration"] > 200]

        print(f"\nCallbacks > 100ms: {len(slow_callbacks)} ({len(slow_callbacks)/len(self.callbacks)*100:.1f}%)")
        print(f"Callbacks > 200ms: {len(very_slow_callbacks)} ({len(very_slow_callbacks)/len(self.callbacks)*100:.1f}%)")

        # Status codes with explanations
        status_counts = defaultdict(int)
        for cb in self.callbacks:
            status_counts[cb["status"]] += 1

        print("\nStatus Codes:")
        for status, count in sorted(status_counts.items()):
            explanation = self.explain_status_code(status)
            print(f"  {status}: {count} callbacks - {explanation}")

    def generate_cascade_report(self):
        """Generate cascade analysis report"""

        cascades = self.identify_cascades()

        if not cascades:
            print("\n\n" + "=" * 100)
            print("NO CALLBACK CASCADES DETECTED")
            print("=" * 100)
            print("\nAll callbacks appear to be independent - this is good!")
            return

        # Sort by total duration
        cascades.sort(key=lambda x: x["total_duration"], reverse=True)

        print("\n\n" + "=" * 100)
        print("CALLBACK CASCADES DETECTED")
        print("=" * 100)

        for i, cascade in enumerate(cascades[:10], 1):
            chain = cascade["chain"]
            total_duration = cascade["total_duration"]

            print(f"\n🔗 CASCADE CHAIN #{i}")
            print(f"   Total Duration: {total_duration:.0f}ms ({total_duration/1000:.2f}s)")
            print(f"   Chain Length: {len(chain)} callbacks")
            print(f"   Flow:")

            for j, callback in enumerate(chain):
                arrow = " ↓ " if j < len(chain) - 1 else ""
                print(f"      [{j+1}] {self.format_io(callback['outputs'])} ({callback['duration']:.0f}ms){arrow}")

    def generate_recommendations(self):
        """Generate actionable optimization recommendations"""

        print("\n\n" + "=" * 100)
        print("💡 OPTIMIZATION RECOMMENDATIONS")
        print("=" * 100)

        recommendations = []

        # 1. Check for callbacks with no inputs (likely need prevent_initial_call)
        no_input_callbacks = [c for c in self.callbacks if not c["inputs"] or c["inputs"] == [{"id": "unknown"}]]
        if no_input_callbacks:
            recommendations.append(
                f"1. ADD prevent_initial_call=True: {len(no_input_callbacks)} callbacks have no clear inputs"
            )
            print(f"\n1. ⚠️  ADD prevent_initial_call=True")
            print(f"   {len(no_input_callbacks)} callbacks appear to have no user-triggered inputs.")
            print(f"   Consider adding prevent_initial_call=True to:")
            for cb in no_input_callbacks[:5]:
                print(f"      - Outputs: {self.format_io(cb['outputs'])}")

        # 2. Identify slow callbacks (backend optimization needed)
        slow_callbacks = sorted([c for c in self.callbacks if c["duration"] > 100], key=lambda x: x["duration"], reverse=True)
        if slow_callbacks:
            recommendations.append(f"2. OPTIMIZE BACKEND: {len(slow_callbacks)} callbacks take >100ms")
            print(f"\n2. 🐌 OPTIMIZE BACKEND CALLBACKS")
            print(f"   {len(slow_callbacks)} callbacks are taking >100ms (likely backend processing)")
            print(f"   Top 5 slowest:")
            for i, cb in enumerate(slow_callbacks[:5], 1):
                print(f"      {i}. {cb['duration']:.0f}ms - Outputs: {self.format_io(cb['outputs'])}")
            print(f"\n   Actions:")
            print(f"      - Profile these callback functions with cProfile")
            print(f"      - Add caching (@lru_cache or Redis)")
            print(f"      - Optimize database queries")
            print(f"      - Consider background processing for heavy operations")

        # 3. Check for repeated inputs (potential consolidation)
        input_groups = defaultdict(list)
        for cb in self.callbacks:
            input_key = self.format_io(cb["inputs"])
            input_groups[input_key].append(cb)

        frequent_inputs = {k: v for k, v in input_groups.items() if len(v) > 3}
        if frequent_inputs:
            recommendations.append(f"3. REVIEW ARCHITECTURE: {len(frequent_inputs)} inputs trigger multiple callbacks")
            print(f"\n3. 🔍 REVIEW CALLBACK ARCHITECTURE")
            print(f"   {len(frequent_inputs)} inputs each trigger 3+ callbacks")
            print(f"   Consider if these can be optimized:")
            for inp, callbacks in list(frequent_inputs.items())[:3]:
                print(f"\n      Input: {inp}")
                print(f"      Triggers {len(callbacks)} callbacks:")
                for cb in callbacks[:3]:
                    print(f"         → {self.format_io(cb['outputs'])}")

        # 4. Cascades
        cascades = self.identify_cascades()
        if cascades:
            long_cascades = [c for c in cascades if len(c["chain"]) > 2]
            if long_cascades:
                recommendations.append(f"4. BREAK CASCADES: {len(long_cascades)} callback chains detected")
                print(f"\n4. ⛓️  BREAK CALLBACK CASCADES")
                print(f"   {len(long_cascades)} chains of 3+ callbacks detected")
                print(f"   Consider fetching data directly instead of chaining:")
                for i, cascade in enumerate(long_cascades[:3], 1):
                    chain = cascade["chain"]
                    print(f"\n      Chain #{i}: {len(chain)} callbacks, {cascade['total_duration']:.0f}ms total")
                    print(f"         {self.format_io(chain[0]['outputs'])} → ... → {self.format_io(chain[-1]['outputs'])}")

        # 5. Client-side callback opportunities
        ui_only_callbacks = []
        for cb in self.callbacks:
            # Check if outputs are UI-related properties
            outputs_str = str(cb["outputs"])
            if any(prop in outputs_str.lower() for prop in ["style", "classname", "hidden", "disabled", "children"]):
                if cb["size"] < 1000:  # Small response suggests UI-only
                    ui_only_callbacks.append(cb)

        if ui_only_callbacks:
            recommendations.append(f"5. CLIENT-SIDE CALLBACKS: {len(ui_only_callbacks)} callbacks could be client-side")
            print(f"\n5. ⚡ USE CLIENT-SIDE CALLBACKS")
            print(f"   {len(ui_only_callbacks)} callbacks appear to be UI-only updates")
            print(f"   Consider converting to clientside_callback:")
            for cb in ui_only_callbacks[:5]:
                print(f"      - {self.format_io(cb['outputs'])} ({cb['duration']:.0f}ms saved)")

        # Summary
        if recommendations:
            print(f"\n\n" + "=" * 100)
            print(f"PRIORITY ACTIONS:")
            print("=" * 100)
            for rec in recommendations:
                print(f"   {rec}")
        else:
            print(f"\n✅ No major issues detected! Your callback structure looks good.")

        # Estimate performance gains
        potential_savings = 0
        if no_input_callbacks:
            potential_savings += sum(c["duration"] for c in no_input_callbacks)
        if ui_only_callbacks:
            potential_savings += sum(c["duration"] * 0.5 for c in ui_only_callbacks)

        if potential_savings > 0:
            print(f"\n📈 ESTIMATED PERFORMANCE GAIN: {potential_savings:.0f}ms ({potential_savings/1000:.2f}s)")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Dash callback execution performance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic analysis
  python callback_flow_analyzer.py performance_report.json

  # Show callback source locations
  python callback_flow_analyzer.py performance_report.json --show-source

  # Verbose mode with full I/O details
  python callback_flow_analyzer.py performance_report.json --verbose

  # Build registry and analyze
  python callback_flow_analyzer.py performance_report.json --show-source --build-registry

  # All options combined
  python callback_flow_analyzer.py performance_report.json --show-source --verbose
        """
    )
    parser.add_argument("report", nargs="?", default="performance_report_20251016_103721.json",
                       help="Performance report JSON file (default: performance_report_20251016_103721.json)")
    parser.add_argument("--show-source", action="store_true",
                       help="Show callback source locations (function names, files, line numbers)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show full input/output details for all callbacks")
    parser.add_argument("--build-registry", action="store_true",
                       help="Rebuild callback registry before analysis")

    args = parser.parse_args()

    # Rebuild registry if requested
    if args.build_registry:
        print("\n" + "=" * 100)
        print("BUILDING CALLBACK REGISTRY")
        print("=" * 100 + "\n")
        try:
            from callback_registry_builder import CallbackRegistryBuilder
            builder = CallbackRegistryBuilder()
            builder.build_registry()
            print("\n✅ Callback registry rebuilt successfully")
        except Exception as e:
            print(f"\n❌ Error building registry: {e}")
            print("   Continuing with existing registry (if available)...")

    # Resolve report path
    report_path = Path(__file__).parent / args.report
    if not report_path.exists():
        # Try as absolute path
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"❌ Error: Report file not found: {args.report}")
            sys.exit(1)

    print(f"\nAnalyzing: {report_path.name}")
    print("=" * 100)

    if args.show_source:
        print("📍 Source location mode enabled")
    if args.verbose:
        print("📋 Verbose I/O mode enabled")
    print()

    analyzer = CallbackFlowAnalyzer(report_path, show_source=args.show_source, verbose=args.verbose)
    analyzer.analyze_callbacks()
    analyzer.generate_timeline()
    analyzer.generate_statistics()
    analyzer.generate_cascade_report()
    analyzer.generate_recommendations()

    print("\n" + "=" * 100)
    print("ANALYSIS COMPLETE")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
