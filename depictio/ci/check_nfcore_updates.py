"""nf-core pipeline update checker for Depictio CI/CD.

Polls GitHub for new nf-core pipeline releases, diffs the tools list
via modules.json, checks dashboard MultiQC references, and generates
a markdown report suitable for GitHub Issues.

Usage:
    python -m depictio.ci.check_nfcore_updates --projects-dir depictio/projects/nf-core -v
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a semver-like string into a comparable tuple.

    Args:
        version_str: Version string like "2.14.0".

    Returns:
        Tuple of ints, e.g. (2, 14, 0).
    """
    parts: list[int] = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def discover_tracked_pipelines(projects_dir: Path) -> list[dict]:
    """Scan depictio/projects/nf-core/ for tracked pipelines.

    Looks for ``<pipeline>/<version>/project.yaml`` and picks the latest
    version per pipeline using semantic version sorting.

    Args:
        projects_dir: Path to the nf-core projects directory.

    Returns:
        List of dicts with keys: name, version, project_path, config.

    Raises:
        FileNotFoundError: If *projects_dir* does not exist.
    """
    if not projects_dir.exists():
        raise FileNotFoundError(f"Projects directory not found: {projects_dir}")

    pipelines: list[dict] = []

    for pipeline_dir in sorted(projects_dir.iterdir()):
        if not pipeline_dir.is_dir() or pipeline_dir.name.startswith("."):
            continue

        versions: list[str] = []
        for version_dir in pipeline_dir.iterdir():
            if version_dir.is_dir() and (version_dir / "project.yaml").exists():
                versions.append(version_dir.name)

        if not versions:
            logger.warning("No versioned project.yaml for pipeline: %s", pipeline_dir.name)
            continue

        latest = sorted(versions, key=_parse_version)[-1]
        project_path = pipeline_dir / latest

        try:
            config = yaml.safe_load((project_path / "project.yaml").read_text())
        except Exception as exc:
            logger.error("Failed to parse %s/project.yaml: %s", project_path, exc)
            continue

        pipelines.append(
            {
                "name": pipeline_dir.name,
                "version": latest,
                "project_path": project_path,
                "config": config,
            }
        )

    return pipelines


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"


def fetch_latest_release(
    pipeline: str,
    token: str | None = None,
) -> dict | None:
    """Fetch the latest stable release of an nf-core pipeline.

    Args:
        pipeline: Pipeline name, e.g. ``"ampliseq"``.
        token: Optional GitHub token for higher rate limits.

    Returns:
        Dict with version, tag_name, url, published_at – or *None*.
    """
    url = f"{GITHUB_API}/repos/nf-core/{pipeline}/releases"
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(url, headers=headers, params={"per_page": 10}, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("GitHub API error for %s: %s", pipeline, exc)
        return None

    for item in resp.json():
        if item.get("prerelease") or item.get("draft"):
            continue
        return {
            "version": item["tag_name"].lstrip("v"),
            "tag_name": item["tag_name"],
            "url": item.get("html_url", ""),
            "published_at": item.get("published_at", ""),
        }

    return None


def fetch_nfcore_tools(
    pipeline: str,
    version: str,
    token: str | None = None,
) -> set[str]:
    """Fetch the set of tool names from a pipeline's modules.json.

    Parses ``repos -> <url> -> modules -> nf-core -> <tool_name>`` and
    normalises path-like names (e.g. ``kraken2/kraken2`` -> ``kraken2``).

    Args:
        pipeline: Pipeline name.
        version: Git tag / version string.
        token: Optional GitHub token.

    Returns:
        Set of normalised tool names (lowercase).
    """
    url = f"{GITHUB_RAW}/nf-core/{pipeline}/{version}/modules.json"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(url, headers=headers, timeout=30.0)
        if resp.status_code == 404:
            logger.warning("modules.json not found for %s@%s", pipeline, version)
            return set()
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch modules.json for %s@%s: %s", pipeline, version, exc)
        return set()

    return extract_tools_from_modules_json(resp.json())


def extract_tools_from_modules_json(modules_json: dict) -> set[str]:
    """Extract tool names from a parsed modules.json dict.

    Args:
        modules_json: The parsed JSON content of modules.json.

    Returns:
        Set of normalised tool names.
    """
    tools: set[str] = set()
    for _repo_url, repo_data in modules_json.get("repos", {}).items():
        for _ns, ns_modules in repo_data.get("modules", {}).items():
            for tool_name in ns_modules:
                tools.add(tool_name.split("/")[-1].lower())
    return tools


# ---------------------------------------------------------------------------
# Diffing & validation
# ---------------------------------------------------------------------------


def diff_tools(current: set[str], new: set[str]) -> dict[str, list[str]]:
    """Compute added / removed / unchanged tools between two versions.

    Args:
        current: Tool set from the currently tracked version.
        new: Tool set from the new version.

    Returns:
        Dict with sorted lists under keys ``added``, ``removed``, ``unchanged``.
    """
    return {
        "added": sorted(new - current),
        "removed": sorted(current - new),
        "unchanged": sorted(current & new),
    }


def extract_multiqc_modules_from_project(config: dict) -> set[str]:
    """Extract declared MultiQC module names from a project.yaml config.

    Looks inside ``workflows[*].data_collections[*].config`` for entries
    where ``type`` is ``"MultiQC"`` (case-insensitive) and reads
    ``dc_specific_properties.modules``.

    Args:
        config: Parsed project.yaml dict.

    Returns:
        Set of module name strings.
    """
    modules: set[str] = set()
    for wf in config.get("workflows", []):
        for dc in wf.get("data_collections", []):
            dc_cfg = dc.get("config", {})
            if dc_cfg.get("type", "").lower() == "multiqc":
                dc_modules = dc_cfg.get("dc_specific_properties", {}).get("modules", [])
                modules.update(dc_modules)
    return modules


def check_dashboard_multiqc_refs(
    dashboard_path: Path,
    available_modules: set[str],
) -> list[str]:
    """Check that dashboard MultiQC components reference available modules.

    Args:
        dashboard_path: Path to a dashboard YAML file.
        available_modules: Set of module names considered available
            (including ``"general_stats"`` implicitly).

    Returns:
        List of human-readable warning strings.
    """
    if not dashboard_path.exists():
        return [f"Dashboard file not found: {dashboard_path}"]

    try:
        dashboard = yaml.safe_load(dashboard_path.read_text())
    except Exception as exc:
        return [f"Failed to parse {dashboard_path}: {exc}"]

    warnings: list[str] = []
    allowed = available_modules | {"general_stats"}

    components: list[dict] = []
    main = dashboard.get("main_dashboard") or {}
    components.extend(main.get("components", []))
    for tab in dashboard.get("tabs", []):
        components.extend(tab.get("components", []))

    for comp in components:
        if comp.get("component_type") != "multiqc":
            continue
        module = comp.get("selected_module", "")
        if module and module not in allowed:
            tag = comp.get("tag", "<no tag>")
            warnings.append(
                f"Component '{tag}' references MultiQC module '{module}' "
                f"which is not in the available set"
            )

    return warnings


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    pipeline: str,
    current_ver: str,
    new_ver: str,
    tool_diff: dict[str, list[str]],
    mqc_warnings: list[str],
    release_url: str,
) -> str:
    """Generate a markdown report for a GitHub issue body.

    Args:
        pipeline: Pipeline name.
        current_ver: Currently tracked version.
        new_ver: Newly available version.
        tool_diff: Output of :func:`diff_tools`.
        mqc_warnings: Output of :func:`check_dashboard_multiqc_refs`.
        release_url: URL to the GitHub release page.

    Returns:
        Markdown string.
    """
    has_breaking = bool(tool_diff["removed"]) or bool(mqc_warnings)
    status = "BREAKING" if has_breaking else "compatible"

    lines: list[str] = [
        f"## nf-core/{pipeline}: {current_ver} -> {new_ver} ({status})",
        "",
        f"**Release**: {release_url}",
        "",
    ]

    if tool_diff["removed"]:
        lines.append("### Removed tools")
        for t in tool_diff["removed"]:
            lines.append(f"- `{t}`")
        lines.append("")

    if tool_diff["added"]:
        lines.append("### New tools")
        for t in tool_diff["added"]:
            lines.append(f"- `{t}`")
        lines.append("")

    if tool_diff["unchanged"]:
        lines.append(f"**Unchanged**: {', '.join(f'`{t}`' for t in tool_diff['unchanged'])}")
        lines.append("")

    if mqc_warnings:
        lines.append("### Dashboard MultiQC warnings")
        for w in mqc_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend(
        [
            "### Action items",
            "",
            f"- [ ] Create `depictio/projects/nf-core/{pipeline}/{new_ver}/`",
            f"- [ ] Copy & update project.yaml from {current_ver}",
            "- [ ] Run pipeline with new version and validate MultiQC output",
            "- [ ] Update dashboard YAML if modules changed",
            "- [ ] `depictio validate-project-config` + `depictio dashboard validate`",
            "",
            "---",
            "*Auto-generated by nf-core pipeline update checker*",
        ]
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry-point for the nf-core pipeline update checker."""
    parser = argparse.ArgumentParser(
        description="Check nf-core pipelines tracked in Depictio for new releases",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path("depictio/projects/nf-core"),
        help="Path to nf-core projects directory (default: depictio/projects/nf-core)",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Write markdown report to file",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        pipelines = discover_tracked_pipelines(args.projects_dir)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    logger.info("Discovered %d tracked pipeline(s)", len(pipelines))

    updates: list[dict] = []
    errors: list[str] = []

    for pl in pipelines:
        name, cur_ver = pl["name"], pl["version"]
        logger.info("Checking %s@%s ...", name, cur_ver)

        release = fetch_latest_release(name, token=args.github_token)
        if release is None:
            errors.append(f"{name}: failed to fetch releases")
            continue

        if _parse_version(release["version"]) <= _parse_version(cur_ver):
            logger.info("  %s is up to date", name)
            continue

        new_ver = release["version"]
        logger.info("  New version available: %s", new_ver)

        # Fetch tools for both versions
        current_tools = fetch_nfcore_tools(name, cur_ver, token=args.github_token)
        new_tools = fetch_nfcore_tools(name, release["tag_name"], token=args.github_token)
        tdiff = diff_tools(current_tools, new_tools)

        # Check dashboard refs against new tool set
        mqc_modules = extract_multiqc_modules_from_project(pl["config"])
        new_mqc_available = mqc_modules - set(tdiff["removed"]) | set(tdiff["added"])

        mqc_warnings: list[str] = []
        dashboards_dir = pl["project_path"] / "dashboards"
        if dashboards_dir.exists():
            for dashboard_file in dashboards_dir.glob("*.yaml"):
                mqc_warnings.extend(check_dashboard_multiqc_refs(dashboard_file, new_mqc_available))

        report = generate_report(name, cur_ver, new_ver, tdiff, mqc_warnings, release["url"])

        updates.append(
            {
                "name": name,
                "current_version": cur_ver,
                "new_version": new_ver,
                "report": report,
                "has_breaking": bool(tdiff["removed"]) or bool(mqc_warnings),
            }
        )

    # Output
    if updates:
        full_report = "\n\n---\n\n".join(u["report"] for u in updates)
        if args.output_file:
            args.output_file.write_text(full_report)
            logger.info("Report written to %s", args.output_file)
        else:
            print(full_report)
    else:
        msg = "All pipelines up to date." if not errors else "No updates (with errors)."
        logger.info(msg)

    # GitHub Actions outputs
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"has_updates={'true' if updates else 'false'}\n")
            f.write(f"update_count={len(updates)}\n")

        for i, upd in enumerate(updates):
            status = "BREAKING" if upd["has_breaking"] else "compatible"
            title = f"[nf-core/{upd['name']}] {upd['new_version']} available ({status})"
            labels = "nf-core,pipeline-update"
            if upd["has_breaking"]:
                labels += ",breaking-change"

            body_file = Path(f"/tmp/issue_body_{i}.md")
            body_file.write_text(upd["report"])

            with open(gh_output, "a") as f:
                f.write(f"issue_title_{i}={title}\n")
                f.write(f"issue_labels_{i}={labels}\n")
                f.write(f"issue_body_file_{i}={body_file}\n")

    if errors:
        for e in errors:
            logger.error(e)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
