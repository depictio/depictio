#!/usr/bin/env python3
"""
Network Request Analyzer for Depictio Performance Analysis

Analyzes network request patterns from performance reports to identify:
- Request categorization (Dash callbacks, static resources, API calls)
- Additional requests in Depictio vs standalone
- Request timing and size analysis
- Optimization opportunities

Usage:
    python analyze_network_requests.py <standalone_report.json> <depictio_report.json>
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def categorize_request(request):
    """Categorize a network request by type."""
    url = request.get("url", "")
    resource_type = request.get("resource_type", "")
    method = request.get("method", "")

    # Dash callback requests
    if "_dash-update-component" in url:
        return "dash_callback"
    if "_dash-dependencies" in url:
        return "dash_dependencies"
    if "_dash-layout" in url:
        return "dash_layout"
    if "_reload-hash" in url:
        return "dash_reload"

    # API requests
    if "/depictio/api/" in url:
        return "api_request"

    # Component suites (Dash libraries)
    if "_dash-component-suites" in url:
        if ".css" in url:
            return "component_css"
        elif ".js" in url:
            return "component_js"
        return "component_suite"

    # Static assets
    if "/assets/" in url:
        if ".css" in url:
            return "asset_css"
        elif ".js" in url:
            return "asset_js"
        elif ".png" in url or ".jpg" in url or ".svg" in url or ".ico" in url:
            return "asset_image"
        return "asset_other"

    # Fonts
    if ".woff" in url or ".woff2" in url or ".ttf" in url:
        return "font"

    # Document (main page)
    if resource_type == "document" or method == "GET" and url.endswith("/"):
        return "document"

    # Fetch/XHR
    if resource_type in ["fetch", "xhr"]:
        return "xhr_fetch"

    return "other"


def extract_component_name(url):
    """Extract component/library name from Dash component suite URL."""
    if "_dash-component-suites" in url:
        parts = url.split("_dash-component-suites/")[1].split("/")
        if len(parts) >= 2:
            return parts[0] + "/" + parts[1].split(".")[0]
        return parts[0] if parts else "unknown"
    return None


def extract_asset_name(url):
    """Extract asset filename from URL."""
    if "/assets/" in url:
        return url.split("/assets/")[1].split("?")[0]
    return None


def analyze_network_requests(report, target_name):
    """Analyze network requests from a performance report."""
    requests = report.get("network_requests", [])

    analysis = {
        "target": target_name,
        "total_requests": 0,
        "requests_by_category": defaultdict(int),
        "requests_by_status": defaultdict(int),
        "component_suites": defaultdict(int),
        "assets": defaultdict(int),
        "api_endpoints": defaultdict(int),
        "dash_callbacks": [],
        "timing_stats": {
            "total_time": 0,
            "avg_time": 0,
            "requests_with_timing": 0,
        },
    }

    for req in requests:
        # Only count request entries, not response entries
        if req.get("type") == "response":
            continue

        analysis["total_requests"] += 1

        # Categorize
        category = categorize_request(req)
        analysis["requests_by_category"][category] += 1

        # Track component suites
        if category in ["component_css", "component_js", "component_suite"]:
            component = extract_component_name(req.get("url", ""))
            if component:
                analysis["component_suites"][component] += 1

        # Track assets
        if category.startswith("asset_"):
            asset = extract_asset_name(req.get("url", ""))
            if asset:
                analysis["assets"][asset] += 1

        # Track API endpoints
        if category == "api_request":
            url = req.get("url", "")
            if "/depictio/api/v1/" in url:
                endpoint = url.split("/depictio/api/v1/")[1].split("?")[0]
                analysis["api_endpoints"][endpoint] += 1

        # Track Dash callbacks
        if category == "dash_callback":
            url = req.get("url", "")
            # Extract output parameter (callback ID)
            if "output=" in url:
                import urllib.parse

                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                output = params.get("output", ["unknown"])[0]
                analysis["dash_callbacks"].append(output)

    return analysis


def compare_analyses(standalone_analysis, depictio_analysis):
    """Compare network analyses between standalone and depictio."""
    comparison = {
        "total_requests": {
            "standalone": standalone_analysis["total_requests"],
            "depictio": depictio_analysis["total_requests"],
            "difference": depictio_analysis["total_requests"]
            - standalone_analysis["total_requests"],
        },
        "category_comparison": {},
        "additional_component_suites": {},
        "additional_assets": {},
        "additional_api_endpoints": {},
        "additional_dash_callbacks": [],
    }

    # Compare by category
    all_categories = set(standalone_analysis["requests_by_category"].keys()) | set(
        depictio_analysis["requests_by_category"].keys()
    )

    for category in all_categories:
        standalone_count = standalone_analysis["requests_by_category"].get(category, 0)
        depictio_count = depictio_analysis["requests_by_category"].get(category, 0)
        comparison["category_comparison"][category] = {
            "standalone": standalone_count,
            "depictio": depictio_count,
            "difference": depictio_count - standalone_count,
        }

    # Compare component suites
    standalone_suites = set(standalone_analysis["component_suites"].keys())
    depictio_suites = set(depictio_analysis["component_suites"].keys())
    additional_suites = depictio_suites - standalone_suites

    for suite in additional_suites:
        comparison["additional_component_suites"][suite] = depictio_analysis[
            "component_suites"
        ][suite]

    # Compare assets
    standalone_assets = set(standalone_analysis["assets"].keys())
    depictio_assets = set(depictio_analysis["assets"].keys())
    additional_assets = depictio_assets - standalone_assets

    for asset in additional_assets:
        comparison["additional_assets"][asset] = depictio_analysis["assets"][asset]

    # Compare API endpoints
    standalone_endpoints = set(standalone_analysis["api_endpoints"].keys())
    depictio_endpoints = set(depictio_analysis["api_endpoints"].keys())
    additional_endpoints = depictio_endpoints - standalone_endpoints

    for endpoint in additional_endpoints:
        comparison["additional_api_endpoints"][endpoint] = depictio_analysis[
            "api_endpoints"
        ][endpoint]

    # Compare Dash callbacks
    standalone_callbacks = set(standalone_analysis["dash_callbacks"])
    depictio_callbacks = set(depictio_analysis["dash_callbacks"])
    additional_callbacks = depictio_callbacks - standalone_callbacks

    comparison["additional_dash_callbacks"] = sorted(list(additional_callbacks))

    return comparison


def generate_report(comparison, standalone_analysis, depictio_analysis, output_file):
    """Generate detailed network analysis report."""
    report_lines = []

    # Header
    report_lines.append("# Network Request Analysis Report")
    report_lines.append("")
    report_lines.append(f"**Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")

    # Executive Summary
    report_lines.append("## Executive Summary")
    report_lines.append("")
    total_diff = comparison["total_requests"]["difference"]
    total_pct = (
        (total_diff / comparison["total_requests"]["standalone"] * 100)
        if comparison["total_requests"]["standalone"] > 0
        else 0
    )
    report_lines.append(
        f"- **Standalone Total Requests**: {comparison['total_requests']['standalone']}"
    )
    report_lines.append(
        f"- **Depictio Total Requests**: {comparison['total_requests']['depictio']}"
    )
    report_lines.append(
        f"- **Additional Requests**: {total_diff} (+{total_pct:.1f}%)"
    )
    report_lines.append("")

    # Category Breakdown
    report_lines.append("## Request Category Breakdown")
    report_lines.append("")
    report_lines.append("| Category | Standalone | Depictio | Difference | % Change |")
    report_lines.append("|----------|-----------|----------|------------|----------|")

    # Sort by difference (most additional first)
    sorted_categories = sorted(
        comparison["category_comparison"].items(),
        key=lambda x: x[1]["difference"],
        reverse=True,
    )

    for category, data in sorted_categories:
        standalone_count = data["standalone"]
        depictio_count = data["depictio"]
        diff = data["difference"]
        pct = (
            (diff / standalone_count * 100) if standalone_count > 0 else float("inf")
        )

        if pct == float("inf"):
            pct_str = "NEW"
        else:
            pct_str = f"{pct:+.1f}%"

        report_lines.append(
            f"| `{category}` | {standalone_count} | {depictio_count} | {diff:+d} | {pct_str} |"
        )

    report_lines.append("")

    # Additional Component Suites
    if comparison["additional_component_suites"]:
        report_lines.append("## Additional Component Suites in Depictio")
        report_lines.append("")
        report_lines.append("These Dash component libraries are loaded in Depictio but not standalone:")
        report_lines.append("")
        report_lines.append("| Component Suite | Count |")
        report_lines.append("|----------------|-------|")

        for suite, count in sorted(
            comparison["additional_component_suites"].items(), key=lambda x: x[1], reverse=True
        ):
            report_lines.append(f"| `{suite}` | {count} |")

        report_lines.append("")

    # Additional Assets
    if comparison["additional_assets"]:
        report_lines.append("## Additional Assets in Depictio")
        report_lines.append("")
        report_lines.append("These static assets are loaded in Depictio but not standalone:")
        report_lines.append("")

        # Group by type
        css_assets = [k for k in comparison["additional_assets"].keys() if k.endswith(".css")]
        js_assets = [k for k in comparison["additional_assets"].keys() if k.endswith(".js")]
        img_assets = [
            k
            for k in comparison["additional_assets"].keys()
            if any(k.endswith(ext) for ext in [".png", ".jpg", ".svg", ".ico"])
        ]
        other_assets = [
            k
            for k in comparison["additional_assets"].keys()
            if k not in css_assets + js_assets + img_assets
        ]

        if css_assets:
            report_lines.append("### CSS Files")
            report_lines.append("")
            for asset in sorted(css_assets):
                report_lines.append(f"- `{asset}`")
            report_lines.append("")

        if js_assets:
            report_lines.append("### JavaScript Files")
            report_lines.append("")
            for asset in sorted(js_assets):
                report_lines.append(f"- `{asset}`")
            report_lines.append("")

        if img_assets:
            report_lines.append("### Images")
            report_lines.append("")
            for asset in sorted(img_assets):
                report_lines.append(f"- `{asset}`")
            report_lines.append("")

        if other_assets:
            report_lines.append("### Other Assets")
            report_lines.append("")
            for asset in sorted(other_assets):
                report_lines.append(f"- `{asset}`")
            report_lines.append("")

    # Additional API Endpoints
    if comparison["additional_api_endpoints"]:
        report_lines.append("## Additional API Endpoints in Depictio")
        report_lines.append("")
        report_lines.append("| Endpoint | Request Count |")
        report_lines.append("|----------|--------------|")

        for endpoint, count in sorted(
            comparison["additional_api_endpoints"].items(), key=lambda x: x[1], reverse=True
        ):
            report_lines.append(f"| `{endpoint}` | {count} |")

        report_lines.append("")

    # Additional Dash Callbacks
    if comparison["additional_dash_callbacks"]:
        report_lines.append("## Additional Dash Callbacks in Depictio")
        report_lines.append("")
        report_lines.append(
            f"Depictio has **{len(comparison['additional_dash_callbacks'])}** "
            f"additional unique callback outputs compared to standalone:"
        )
        report_lines.append("")

        # Group callbacks by pattern
        pattern_callbacks = defaultdict(list)
        for callback in comparison["additional_dash_callbacks"]:
            if callback.startswith('{"'):
                # Pattern-matching callback
                pattern_callbacks["pattern_matching"].append(callback)
            elif "navbar" in callback.lower():
                pattern_callbacks["navbar"].append(callback)
            elif "header" in callback.lower():
                pattern_callbacks["header"].append(callback)
            elif "theme" in callback.lower():
                pattern_callbacks["theme"].append(callback)
            elif "auth" in callback.lower() or "login" in callback.lower():
                pattern_callbacks["auth"].append(callback)
            elif "route" in callback.lower() or "url" in callback.lower():
                pattern_callbacks["routing"].append(callback)
            else:
                pattern_callbacks["other"].append(callback)

        for pattern, callbacks in sorted(pattern_callbacks.items()):
            report_lines.append(f"### {pattern.replace('_', ' ').title()} ({len(callbacks)})")
            report_lines.append("")
            for callback in sorted(callbacks)[:10]:  # Limit to first 10
                # Truncate long callback IDs
                if len(callback) > 80:
                    callback_display = callback[:77] + "..."
                else:
                    callback_display = callback
                report_lines.append(f"- `{callback_display}`")

            if len(callbacks) > 10:
                report_lines.append(f"- ... and {len(callbacks) - 10} more")
            report_lines.append("")

    # Optimization Recommendations
    report_lines.append("## Optimization Recommendations")
    report_lines.append("")

    # Analyze categories for recommendations
    recommendations = []

    # Check component suites
    if comparison["additional_component_suites"]:
        suite_count = sum(comparison["additional_component_suites"].values())
        recommendations.append(
            f"**Component Suites** ({suite_count} additional requests): "
            f"Review necessity of additional component libraries. "
            f"Consider lazy-loading or removing unused components."
        )

    # Check assets
    if comparison["additional_assets"]:
        asset_count = len(comparison["additional_assets"])
        recommendations.append(
            f"**Static Assets** ({asset_count} additional files): "
            f"Bundle CSS/JS files to reduce HTTP requests. "
            f"Use CDN for common libraries. Optimize image sizes."
        )

    # Check Dash callbacks
    if comparison["additional_dash_callbacks"]:
        callback_count = len(comparison["additional_dash_callbacks"])
        recommendations.append(
            f"**Dash Callbacks** ({callback_count} additional): "
            f"Convert UI-only callbacks to client-side callbacks. "
            f"Merge related callbacks where possible. "
            f"Lazy-load non-critical components."
        )

    # Check API endpoints
    if comparison["additional_api_endpoints"]:
        api_count = sum(comparison["additional_api_endpoints"].values())
        recommendations.append(
            f"**API Requests** ({api_count} total): "
            f"Batch related API calls. "
            f"Implement request coalescing for metadata. "
            f"Use aggressive caching for user/project data."
        )

    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            report_lines.append(f"{i}. {rec}")
            report_lines.append("")

    # Conclusion
    report_lines.append("## Conclusion")
    report_lines.append("")
    report_lines.append(
        f"Depictio makes **{total_diff} additional HTTP requests** (+{total_pct:.1f}%) "
        f"compared to the standalone dashboard. The primary sources are:"
    )
    report_lines.append("")

    # Top contributors
    top_categories = sorted(
        [(cat, data["difference"]) for cat, data in comparison["category_comparison"].items()],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    for category, diff in top_categories:
        if diff > 0:
            report_lines.append(f"- **{category}**: +{diff} requests")

    report_lines.append("")
    report_lines.append(
        "Focus optimization efforts on reducing static resource requests and "
        "converting server-side callbacks to client-side where appropriate."
    )
    report_lines.append("")

    # Write report
    with open(output_file, "w") as f:
        f.write("\n".join(report_lines))

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Analyze network requests from Depictio performance reports"
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
        help="Output report file (default: NETWORK_ANALYSIS_REPORT_<timestamp>.md)",
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
    print("Analyzing standalone network requests...")
    standalone_analysis = analyze_network_requests(standalone_report, "standalone")

    print("Analyzing Depictio network requests...")
    depictio_analysis = analyze_network_requests(depictio_report, "depictio")

    print("Comparing analyses...")
    comparison = compare_analyses(standalone_analysis, depictio_analysis)

    # Generate report
    if args.output:
        output_file = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(f"NETWORK_ANALYSIS_REPORT_{timestamp}.md")

    print(f"Generating report: {output_file}")
    generate_report(comparison, standalone_analysis, depictio_analysis, output_file)

    print(f"\n✅ Analysis complete! Report saved to: {output_file}")

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(
        f"Standalone: {comparison['total_requests']['standalone']} total requests"
    )
    print(
        f"Depictio: {comparison['total_requests']['depictio']} total requests"
    )
    print(
        f"Difference: +{comparison['total_requests']['difference']} requests "
        f"({comparison['total_requests']['difference'] / comparison['total_requests']['standalone'] * 100:.1f}%)"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
