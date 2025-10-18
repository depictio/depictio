#!/usr/bin/env python3
"""
Extract detailed callback information from performance report.
Specifically looking for callbacks #26-27 to identify their source.
"""

import json
from datetime import datetime
from pathlib import Path


def extract_callback_details(report_path):
    """Extract POST data for specific callbacks to identify their source."""

    with open(report_path) as f:
        data = json.load(f)

    network_requests = data.get("network_requests", [])

    # Find page load time
    page_load_time = None
    for req in network_requests:
        if "dashboard" in req.get("url", ""):
            page_load_time = datetime.fromisoformat(req["timestamp"])
            break

    # Match callback requests with responses
    callbacks = []
    pending_requests = {}

    for req in network_requests:
        url = req.get("url", "")

        if "_dash-update-component" not in url:
            continue

        timestamp = datetime.fromisoformat(req["timestamp"])

        if req.get("type") == "request" or "method" in req:
            # This is a request - parse POST data
            post_data = req.get("post_data")

            if post_data:
                try:
                    callback_data = json.loads(post_data)
                    request_key = f"{url}_{timestamp.isoformat()}"
                    pending_requests[request_key] = {
                        "start_time": timestamp,
                        "callback_data": callback_data,
                        "url": url,
                    }
                except json.JSONDecodeError:
                    pass

        elif req.get("type") == "response":
            # Match with most recent request
            matched_key = None
            for key in pending_requests:
                if key.startswith(url):
                    matched_key = key
                    break

            if matched_key:
                request_data = pending_requests[matched_key]
                duration = (timestamp - request_data["start_time"]).total_seconds() * 1000

                relative_start = (
                    (request_data["start_time"] - page_load_time).total_seconds() * 1000
                    if page_load_time
                    else 0
                )

                callback = {
                    "relative_start": relative_start,
                    "duration": duration,
                    "callback_data": request_data["callback_data"],
                    "status": req.get("status"),
                }

                callbacks.append(callback)
                del pending_requests[matched_key]

    # Sort by start time
    callbacks.sort(key=lambda x: x["relative_start"])

    print(f"Total callbacks found: {len(callbacks)}\n")

    # Find callbacks around T=1490ms (where #26-27 should be)
    target_time = 1490
    window = 100  # ms

    print(f"Looking for callbacks around T={target_time}ms (±{window}ms):\n")
    print("=" * 100)

    for i, cb in enumerate(callbacks, 1):
        if abs(cb["relative_start"] - target_time) < window and cb["duration"] > 1000:
            print(f"\nCallback #{i}")
            print(f"Start: T={cb['relative_start']:.0f}ms")
            print(f"Duration: {cb['duration']:.0f}ms")
            print(f"Status: {cb['status']}")
            print("\nCallback Data:")
            print(json.dumps(cb["callback_data"], indent=2))
            print("\n" + "-" * 100)

    # Also show slowest callbacks overall
    print("\n\n" + "=" * 100)
    print("SLOWEST CALLBACKS (>1000ms):")
    print("=" * 100)

    slow_callbacks = sorted(
        [(i + 1, cb) for i, cb in enumerate(callbacks) if cb["duration"] > 1000],
        key=lambda x: x[1]["duration"],
        reverse=True,
    )

    for idx, cb in slow_callbacks[:10]:
        print(f"\nCallback #{idx}")
        print(f"T={cb['relative_start']:.0f}ms, Duration={cb['duration']:.0f}ms")

        outputs = cb["callback_data"].get("outputs", [])
        if outputs:
            first_output = outputs[0] if isinstance(outputs, list) else outputs
            if isinstance(first_output, dict):
                output_id = first_output.get("id", "unknown")
                output_prop = first_output.get("property", "unknown")

                # Truncate long IDs
                if isinstance(output_id, str) and len(output_id) > 40:
                    output_id_display = output_id[:37] + "..."
                elif isinstance(output_id, dict):
                    # Extract index if it's a pattern-matching ID
                    index = output_id.get("index", "unknown")
                    type_name = output_id.get("type", "unknown")
                    if isinstance(index, str) and len(index) > 30:
                        index_display = index[:27] + "..."
                    else:
                        index_display = index
                    output_id_display = f"{{'type': '{type_name}', 'index': '{index_display}'}}"
                else:
                    output_id_display = str(output_id)

                print(f"Output: {output_id_display}.{output_prop}")

        inputs = cb["callback_data"].get("inputs", [])
        if inputs:
            first_input = inputs[0] if isinstance(inputs, list) else inputs
            if isinstance(first_input, dict):
                input_id = first_input.get("id", "unknown")
                input_prop = first_input.get("property", "unknown")

                if isinstance(input_id, str) and len(input_id) > 40:
                    input_id_display = input_id[:37] + "..."
                elif isinstance(input_id, dict):
                    index = input_id.get("index", "unknown")
                    type_name = input_id.get("type", "unknown")
                    if isinstance(index, str) and len(index) > 30:
                        index_display = index[:27] + "..."
                    else:
                        index_display = index
                    input_id_display = f"{{'type': '{type_name}', 'index': '{index_display}'}}"
                else:
                    input_id_display = str(input_id)

                print(f"Input:  {input_id_display}.{input_prop}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        report_file = "performance_report_20251016_213310.json"
    else:
        report_file = sys.argv[1]

    report_path = Path(__file__).parent / report_file

    if not report_path.exists():
        print(f"Error: Report file not found: {report_path}")
        sys.exit(1)

    print(f"Analyzing: {report_path.name}\n")
    extract_callback_details(report_path)
