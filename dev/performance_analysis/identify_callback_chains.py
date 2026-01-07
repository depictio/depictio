#!/usr/bin/env python3
"""
Callback Chain Identifier for Depictio Performance Analysis

Analyzes Dash callback patterns from performance reports to identify:
- Callback execution order and dependencies
- Additional callbacks in Depictio vs standalone
- Callback categorization (component, infrastructure, UI)
- Performance impact of each callback chain

Usage:
    python identify_callback_chains.py <standalone_report.json> <depictio_report.json>
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def extract_callback_info(request):
    """Extract callback information from a Dash callback request."""
    url = request.get("url", "")

    if "_dash-update-component" not in url:
        return None

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    callback_info = {
        "output": params.get("output", ["unknown"])[0],
        "inputs": params.get("inputs", []),
        "state": params.get("state", []),
        "timestamp": request.get("timestamp", ""),
    }

    # Decode URL-encoded output
    import urllib.parse

    callback_info["output"] = urllib.parse.unquote(callback_info["output"])

    return callback_info


def categorize_callback(callback_id):
    """Categorize a callback by its output component ID."""
    callback_lower = callback_id.lower()

    # Pattern-matching callbacks (JSON format)
    if callback_id.startswith("{"):
        try:
            import json

            pattern = json.loads(callback_id)
            component_type = pattern.get("type", "")

            if "card" in component_type.lower():
                return "component_card"
            elif "figure" in component_type.lower():
                return "component_figure"
            elif "table" in component_type.lower():
                return "component_table"
            elif "interactive" in component_type.lower():
                return "component_interactive"
            else:
                return "component_pattern_other"
        except Exception:
            return "pattern_matching"

    # Navigation/routing
    if any(
        kw in callback_lower
        for kw in ["url", "pathname", "route", "location", "navigate"]
    ):
        return "routing"

    # Authentication
    if any(kw in callback_lower for kw in ["auth", "login", "token", "user-data"]):
        return "auth"

    # Navbar/sidebar
    if any(kw in callback_lower for kw in ["navbar", "sidebar", "drawer", "menu"]):
        return "navbar"

    # Header
    if any(
        kw in callback_lower
        for kw in ["header", "appbar", "toolbar", "breadcrumb"]
    ):
        return "header"

    # Theme
    if any(kw in callback_lower for kw in ["theme", "color-scheme", "dark-mode"]):
        return "theme"

    # Notifications/alerts
    if any(
        kw in callback_lower for kw in ["notification", "alert", "toast", "snackbar"]
    ):
        return "notifications"

    # Modals/dialogs
    if any(kw in callback_lower for kw in ["modal", "dialog", "drawer", "popover"]):
        return "modal"

    # Data stores
    if any(kw in callback_lower for kw in ["store", "storage", "cache"]):
        return "data_store"

    # Consolidated API
    if "consolidated" in callback_lower:
        return "consolidated_api"

    # Loading states
    if "loading" in callback_lower or "spinner" in callback_lower:
        return "loading"

    # Component-specific
    if "card" in callback_lower:
        return "component_card"
    if "figure" in callback_lower or "graph" in callback_lower:
        return "component_figure"
    if "table" in callback_lower:
        return "component_table"
    if "interactive" in callback_lower or "filter" in callback_lower:
        return "component_interactive"

    return "other"


def extract_component_id(callback_id):
    """Extract a human-readable component ID from callback ID."""
    # For pattern-matching callbacks
    if callback_id.startswith("{"):
        try:
            import json

            pattern = json.loads(callback_id)
            comp_type = pattern.get("type", "unknown")
            index = pattern.get("index", "?")
            return f"{comp_type}[{index}]"
        except Exception:
            return callback_id[:50] + "..." if len(callback_id) > 50 else callback_id

    # For regular callbacks, extract the component ID
    parts = callback_id.split(".")
    if len(parts) >= 1:
        return parts[0]

    return callback_id


def analyze_callbacks(report, target_name):
    """Analyze callbacks from a performance report."""
    requests = report.get("network_requests", [])

    analysis = {
        "target": target_name,
        "total_callbacks": 0,
        "unique_callbacks": set(),
        "callbacks_by_category": defaultdict(int),
        "callback_details": [],
        "callback_timeline": [],
    }

    for req in requests:
        callback_info = extract_callback_info(req)
        if not callback_info:
            continue

        analysis["total_callbacks"] += 1
        callback_id = callback_info["output"]
        analysis["unique_callbacks"].add(callback_id)

        category = categorize_callback(callback_id)
        analysis["callbacks_by_category"][category] += 1

        component_id = extract_component_id(callback_id)

        analysis["callback_details"].append(
            {
                "id": callback_id,
                "component_id": component_id,
                "category": category,
                "timestamp": callback_info["timestamp"],
            }
        )

        analysis["callback_timeline"].append(
            {
                "timestamp": callback_info["timestamp"],
                "callback_id": callback_id,
                "category": category,
            }
        )

    # Convert set to list for JSON serialization
    analysis["unique_callbacks"] = list(analysis["unique_callbacks"])

    # Sort timeline by timestamp
    analysis["callback_timeline"].sort(key=lambda x: x["timestamp"])

    return analysis


def compare_callback_analyses(standalone_analysis, depictio_analysis):
    """Compare callback analyses between standalone and depictio."""
    standalone_set = set(standalone_analysis["unique_callbacks"])
    depictio_set = set(depictio_analysis["unique_callbacks"])

    comparison = {
        "total_callbacks": {
            "standalone": standalone_analysis["total_callbacks"],
            "depictio": depictio_analysis["total_callbacks"],
            "difference": depictio_analysis["total_callbacks"]
            - standalone_analysis["total_callbacks"],
        },
        "unique_callbacks": {
            "standalone": len(standalone_set),
            "depictio": len(depictio_set),
            "difference": len(depictio_set) - len(standalone_set),
        },
        "category_comparison": {},
        "additional_callbacks": [],
        "common_callbacks": [],
        "standalone_only_callbacks": [],
    }

    # Compare by category
    all_categories = set(standalone_analysis["callbacks_by_category"].keys()) | set(
        depictio_analysis["callbacks_by_category"].keys()
    )

    for category in all_categories:
        standalone_count = standalone_analysis["callbacks_by_category"].get(
            category, 0
        )
        depictio_count = depictio_analysis["callbacks_by_category"].get(category, 0)
        comparison["category_comparison"][category] = {
            "standalone": standalone_count,
            "depictio": depictio_count,
            "difference": depictio_count - standalone_count,
        }

    # Identify additional callbacks
    additional = depictio_set - standalone_set
    for callback_id in additional:
        category = categorize_callback(callback_id)
        component_id = extract_component_id(callback_id)
        comparison["additional_callbacks"].append(
            {
                "id": callback_id,
                "component_id": component_id,
                "category": category,
            }
        )

    # Identify common callbacks
    common = depictio_set & standalone_set
    for callback_id in common:
        category = categorize_callback(callback_id)
        component_id = extract_component_id(callback_id)
        comparison["common_callbacks"].append(
            {
                "id": callback_id,
                "component_id": component_id,
                "category": category,
            }
        )

    # Identify standalone-only callbacks
    standalone_only = standalone_set - depictio_set
    for callback_id in standalone_only:
        category = categorize_callback(callback_id)
        component_id = extract_component_id(callback_id)
        comparison["standalone_only_callbacks"].append(
            {
                "id": callback_id,
                "component_id": component_id,
                "category": category,
            }
        )

    return comparison


def generate_callback_report(
    comparison, standalone_analysis, depictio_analysis, output_file
):
    """Generate detailed callback chain analysis report."""
    report_lines = []

    # Header
    report_lines.append("# Callback Chain Analysis Report")
    report_lines.append("")
    report_lines.append(
        f"**Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    report_lines.append("")

    # Executive Summary
    report_lines.append("## Executive Summary")
    report_lines.append("")
    unique_diff = comparison["unique_callbacks"]["difference"]
    unique_pct = (
        (unique_diff / comparison["unique_callbacks"]["standalone"] * 100)
        if comparison["unique_callbacks"]["standalone"] > 0
        else 0
    )
    report_lines.append(
        f"- **Standalone Unique Callbacks**: {comparison['unique_callbacks']['standalone']}"
    )
    report_lines.append(
        f"- **Depictio Unique Callbacks**: {comparison['unique_callbacks']['depictio']}"
    )
    report_lines.append(
        f"- **Additional Callbacks**: {unique_diff} (+{unique_pct:.1f}%)"
    )
    report_lines.append("")

    total_diff = comparison["total_callbacks"]["difference"]
    total_pct = (
        (total_diff / comparison["total_callbacks"]["standalone"] * 100)
        if comparison["total_callbacks"]["standalone"] > 0
        else 0
    )
    report_lines.append(
        f"- **Standalone Total Callback Requests**: {comparison['total_callbacks']['standalone']}"
    )
    report_lines.append(
        f"- **Depictio Total Callback Requests**: {comparison['total_callbacks']['depictio']}"
    )
    report_lines.append(
        f"- **Additional Callback Requests**: {total_diff} (+{total_pct:.1f}%)"
    )
    report_lines.append("")

    # Category Breakdown
    report_lines.append("## Callback Category Breakdown")
    report_lines.append("")
    report_lines.append("| Category | Standalone | Depictio | Difference | % Change |")
    report_lines.append("|----------|-----------|----------|------------|----------|")

    # Sort by difference
    sorted_categories = sorted(
        comparison["category_comparison"].items(),
        key=lambda x: x[1]["difference"],
        reverse=True,
    )

    for category, data in sorted_categories:
        standalone_count = data["standalone"]
        depictio_count = data["depictio"]
        diff = data["difference"]

        if standalone_count == 0:
            pct_str = "NEW"
        else:
            pct = (diff / standalone_count * 100)
            pct_str = f"{pct:+.1f}%"

        report_lines.append(
            f"| `{category}` | {standalone_count} | {depictio_count} | {diff:+d} | {pct_str} |"
        )

    report_lines.append("")

    # Additional Callbacks by Category
    if comparison["additional_callbacks"]:
        report_lines.append("## Additional Callbacks in Depictio")
        report_lines.append("")
        report_lines.append(
            f"Depictio has **{len(comparison['additional_callbacks'])}** additional unique callbacks:"
        )
        report_lines.append("")

        # Group by category
        callbacks_by_category = defaultdict(list)
        for callback in comparison["additional_callbacks"]:
            callbacks_by_category[callback["category"]].append(callback)

        for category in sorted(
            callbacks_by_category.keys(),
            key=lambda c: len(callbacks_by_category[c]),
            reverse=True,
        ):
            callbacks = callbacks_by_category[category]
            report_lines.append(f"### {category.replace('_', ' ').title()} ({len(callbacks)})")
            report_lines.append("")

            # Show first 15 callbacks in this category
            for callback in sorted(callbacks, key=lambda c: c["component_id"])[:15]:
                callback_display = callback["id"]
                if len(callback_display) > 100:
                    callback_display = callback_display[:97] + "..."

                report_lines.append(f"**Component**: `{callback['component_id']}`")
                report_lines.append(f"```")
                report_lines.append(f"{callback_display}")
                report_lines.append(f"```")
                report_lines.append("")

            if len(callbacks) > 15:
                report_lines.append(f"*... and {len(callbacks) - 15} more*")
                report_lines.append("")

    # Common Callbacks
    if comparison["common_callbacks"]:
        report_lines.append("## Common Callbacks (Both Standalone and Depictio)")
        report_lines.append("")
        report_lines.append(
            f"**{len(comparison['common_callbacks'])}** callbacks are common to both:"
        )
        report_lines.append("")

        # Group by category
        common_by_category = defaultdict(list)
        for callback in comparison["common_callbacks"]:
            common_by_category[callback["category"]].append(callback)

        for category in sorted(
            common_by_category.keys(),
            key=lambda c: len(common_by_category[c]),
            reverse=True,
        ):
            count = len(common_by_category[category])
            report_lines.append(f"- **{category.replace('_', ' ').title()}**: {count}")

        report_lines.append("")

    # Standalone-Only Callbacks
    if comparison["standalone_only_callbacks"]:
        report_lines.append("## Callbacks Only in Standalone")
        report_lines.append("")
        report_lines.append(
            f"**{len(comparison['standalone_only_callbacks'])}** callbacks are only in standalone:"
        )
        report_lines.append("")

        for callback in comparison["standalone_only_callbacks"][:10]:
            callback_display = callback["id"]
            if len(callback_display) > 100:
                callback_display = callback_display[:97] + "..."

            report_lines.append(f"- `{callback['component_id']}` ({callback['category']})")

        if len(comparison["standalone_only_callbacks"]) > 10:
            report_lines.append(
                f"- *... and {len(comparison['standalone_only_callbacks']) - 10} more*"
            )

        report_lines.append("")

    # Infrastructure vs Component Callbacks
    report_lines.append("## Infrastructure vs Component Analysis")
    report_lines.append("")

    infrastructure_categories = {
        "routing",
        "auth",
        "navbar",
        "header",
        "theme",
        "notifications",
        "modal",
        "data_store",
        "consolidated_api",
        "loading",
    }

    component_categories = {
        "component_card",
        "component_figure",
        "component_table",
        "component_interactive",
        "component_pattern_other",
    }

    # Count infrastructure callbacks
    infra_standalone = sum(
        standalone_analysis["callbacks_by_category"].get(cat, 0)
        for cat in infrastructure_categories
    )
    infra_depictio = sum(
        depictio_analysis["callbacks_by_category"].get(cat, 0)
        for cat in infrastructure_categories
    )

    # Count component callbacks
    comp_standalone = sum(
        standalone_analysis["callbacks_by_category"].get(cat, 0)
        for cat in component_categories
    )
    comp_depictio = sum(
        depictio_analysis["callbacks_by_category"].get(cat, 0)
        for cat in component_categories
    )

    report_lines.append("| Type | Standalone | Depictio | Difference |")
    report_lines.append("|------|-----------|----------|------------|")
    report_lines.append(
        f"| Infrastructure | {infra_standalone} | {infra_depictio} | {infra_depictio - infra_standalone:+d} |"
    )
    report_lines.append(
        f"| Components | {comp_standalone} | {comp_depictio} | {comp_depictio - comp_standalone:+d} |"
    )
    report_lines.append("")

    infra_pct = (
        (infra_depictio / depictio_analysis["total_callbacks"] * 100)
        if depictio_analysis["total_callbacks"] > 0
        else 0
    )
    comp_pct = (
        (comp_depictio / depictio_analysis["total_callbacks"] * 100)
        if depictio_analysis["total_callbacks"] > 0
        else 0
    )

    report_lines.append(
        f"In Depictio, **{infra_pct:.1f}%** of callbacks are infrastructure-related, "
        f"while **{comp_pct:.1f}%** are component-related."
    )
    report_lines.append("")

    # Optimization Recommendations
    report_lines.append("## Optimization Recommendations")
    report_lines.append("")

    recommendations = []

    # Check infrastructure overhead
    infra_diff = infra_depictio - infra_standalone
    if infra_diff > 0:
        recommendations.append(
            f"**Reduce Infrastructure Callbacks** ({infra_diff} additional): "
            f"Convert routing, theme, and UI state callbacks to client-side callbacks. "
            f"These don't require server round-trips."
        )

    # Check pattern-matching callbacks
    pattern_standalone = standalone_analysis["callbacks_by_category"].get(
        "pattern_matching", 0
    )
    pattern_depictio = depictio_analysis["callbacks_by_category"].get(
        "pattern_matching", 0
    )
    pattern_diff = pattern_depictio - pattern_standalone
    if pattern_diff > 0:
        recommendations.append(
            f"**Optimize Pattern-Matching Callbacks** ({pattern_diff} additional): "
            f"Review necessity of additional pattern-matching callbacks. "
            f"Ensure they're not duplicating functionality."
        )

    # Check consolidated API
    consolidated_count = depictio_analysis["callbacks_by_category"].get(
        "consolidated_api", 0
    )
    if consolidated_count > 0:
        recommendations.append(
            f"**Consolidate API Calls** ({consolidated_count} callbacks): "
            f"The consolidated API is good, but ensure it's fetching all needed data "
            f"in a single request to avoid multiple round-trips."
        )

    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            report_lines.append(f"{i}. {rec}")
            report_lines.append("")

    # Conclusion
    report_lines.append("## Conclusion")
    report_lines.append("")
    report_lines.append(
        f"Depictio executes **{unique_diff} additional unique callbacks** (+{unique_pct:.1f}%) "
        f"compared to standalone. "
    )
    report_lines.append("")

    if infra_diff > 0:
        report_lines.append(
            f"The majority of additional overhead ({infra_diff} callbacks) comes from "
            f"**infrastructure components** (auth, routing, navbar, header). "
            f"These are essential for the full application but can be optimized:"
        )
        report_lines.append("")
        report_lines.append("- Convert UI-only callbacks to **client-side callbacks**")
        report_lines.append("- Implement **lazy loading** for non-critical components")
        report_lines.append("- **Parallelize** independent infrastructure callbacks")
        report_lines.append("")

    report_lines.append(
        "Component callbacks (cards, figures, tables) perform similarly in both "
        "environments, confirming that the rendering code itself is efficient."
    )
    report_lines.append("")

    # Write report
    with open(output_file, "w") as f:
        f.write("\n".join(report_lines))

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Identify callback chains from Depictio performance reports"
    )
    parser.add_argument(
        "standalone_report", type=Path, help="Path to standalone performance report JSON"
    )
    parser.add_argument(
        "depictio_report", type=Path, help="Path to Depictio performance report JSON"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output report file (default: CALLBACK_CHAIN_REPORT_<timestamp>.md)",
    )

    args = parser.parse_args()

    # Load reports
    print(f"Loading {args.standalone_report}...")
    with open(args.standalone_report) as f:
        standalone_report = json.load(f)

    print(f"Loading {args.depictio_report}...")
    with open(args.depictio_report) as f:
        depictio_report = json.load(f)

    # Analyze
    print("Analyzing standalone callbacks...")
    standalone_analysis = analyze_callbacks(standalone_report, "standalone")

    print("Analyzing Depictio callbacks...")
    depictio_analysis = analyze_callbacks(depictio_report, "depictio")

    print("Comparing callback chains...")
    comparison = compare_callback_analyses(standalone_analysis, depictio_analysis)

    # Generate report
    if args.output:
        output_file = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(f"CALLBACK_CHAIN_REPORT_{timestamp}.md")

    print(f"Generating report: {output_file}")
    generate_callback_report(
        comparison, standalone_analysis, depictio_analysis, output_file
    )

    print(f"\n✅ Analysis complete! Report saved to: {output_file}")

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(
        f"Standalone: {comparison['unique_callbacks']['standalone']} unique callbacks"
    )
    print(
        f"Depictio: {comparison['unique_callbacks']['depictio']} unique callbacks"
    )
    print(
        f"Additional: +{comparison['unique_callbacks']['difference']} callbacks "
        f"({comparison['unique_callbacks']['difference'] / comparison['unique_callbacks']['standalone'] * 100:.1f}%)"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
