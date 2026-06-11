#!/usr/bin/env python3
"""Monitor nf-core pipeline releases and report megatest output drift.

Maintainer/CI tool (NOT part of the shipped ``depictio-cli`` package). depictio
ships template projects for nf-core pipelines under
``depictio/projects/nf-core/{pipeline}/{version}/``. Each version pins an nf-core
release and its recipes read specific files from that release's output layout.
When nf-core ships a newer version, output files can move/rename and silently
break our recipes.

This script does two things:

* ``check``  — detect when a newer nf-core version exists for the pipelines we
  template (GitHub releases API vs. our pinned version dirs).
* ``report`` — for a pipeline with an update, list that version's AWS megatest
  results (anonymous S3) and report which recipe source paths no longer resolve.

Path-resolution only: no file downloads, no recipe execution (those are phase-2).

Usage::

    python scripts/nfcore_monitor.py check [--json]
    python scripts/nfcore_monitor.py report --pipeline ampliseq [--results-hash H] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from fnmatch import fnmatch
from pathlib import Path
from xml.etree import ElementTree as ET

from packaging.version import InvalidVersion, Version

# Allow `python scripts/nfcore_monitor.py` to import the in-repo `depictio`
# package even when it is not pip-installed (CI installs it editable; this keeps
# direct script runs working too).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# nf-core pipeline templates live here, one folder per pipeline, with one
# sub-folder per pinned version (plus a non-version ``recipes/`` folder).
NFCORE_PROJECTS_DIR = _REPO_ROOT / "depictio" / "projects" / "nf-core"

# Public bucket holding the AWS "megatest" full-scale test results per release.
MEGATEST_BUCKET = "nf-core-awsmegatests"
MEGATEST_REGION = os.environ.get("NFCORE_MEGATEST_REGION", "eu-west-1")

GITHUB_API = "https://api.github.com"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


# ---------------------------------------------------------------------------
# Network helper
# ---------------------------------------------------------------------------
def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> bytes:
    """GET ``url`` and return the raw body (mirrors catalog.py: refresh-index)."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


# ---------------------------------------------------------------------------
# Detection: local version dirs vs. nf-core releases
# ---------------------------------------------------------------------------
def discover_pipelines(projects_dir: Path = NFCORE_PROJECTS_DIR) -> dict[str, list[Version]]:
    """Map each templated nf-core pipeline to its pinned (semver) version dirs."""
    pipelines: dict[str, list[Version]] = {}
    if not projects_dir.is_dir():
        return pipelines
    for pipeline_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        versions: list[Version] = []
        for child in pipeline_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                versions.append(Version(child.name))
            except InvalidVersion:
                continue  # e.g. the shared `recipes/` folder
        if versions:
            pipelines[pipeline_dir.name] = sorted(versions)
    return pipelines


def local_latest_version(versions: list[Version]) -> Version:
    """Return the highest pinned version."""
    return max(versions)


def fetch_latest_release(pipeline: str, token: str | None = None) -> str | None:
    """Return nf-core's latest release tag for ``pipeline`` (``v`` stripped).

    Returns ``None`` when the lookup fails (network/rate-limit/no releases) so a
    single flaky pipeline never breaks the whole run.
    """
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "depictio-nfcore-monitor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API}/repos/nf-core/{pipeline}/releases/latest"
    try:
        data = json.loads(_get(url, headers=headers))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        print(f"  ! could not fetch latest release for {pipeline}: {exc}", file=sys.stderr)
        return None
    tag = str(data.get("tag_name", "")).lstrip("v")
    return tag or None


def check_updates(
    projects_dir: Path = NFCORE_PROJECTS_DIR, token: str | None = None
) -> list[dict[str, object]]:
    """Compare each pipeline's local-latest version against nf-core's release."""
    results: list[dict[str, object]] = []
    for pipeline, versions in discover_pipelines(projects_dir).items():
        local = local_latest_version(versions)
        remote_str = fetch_latest_release(pipeline, token)
        update_available = False
        if remote_str is not None:
            try:
                update_available = Version(remote_str) > local
            except InvalidVersion:
                update_available = False
        results.append(
            {
                "pipeline": pipeline,
                "local": str(local),
                "remote": remote_str,
                "update_available": update_available,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Megatest results listing (anonymous S3 REST)
# ---------------------------------------------------------------------------
def _s3_list(
    prefix: str,
    region: str = MEGATEST_REGION,
    delimiter: str | None = None,
    continuation_token: str | None = None,
    max_keys: int | None = None,
) -> ET.Element:
    """One anonymous ListObjectsV2 call against the megatest bucket -> XML root."""
    params: dict[str, str] = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    if continuation_token:
        params["continuation-token"] = continuation_token
    if max_keys is not None:
        params["max-keys"] = str(max_keys)
    url = f"https://{MEGATEST_BUCKET}.s3.{region}.amazonaws.com/?" + urllib.parse.urlencode(params)
    return ET.fromstring(_get(url))


def _prefix_last_modified(prefix: str, region: str = MEGATEST_REGION) -> str:
    """LastModified of the first object under ``prefix`` (cheap recency signal)."""
    root = _s3_list(prefix, region=region, max_keys=1)
    lm = root.find(f"{_S3_NS}Contents/{_S3_NS}LastModified")
    return lm.text or "" if lm is not None else ""


def resolve_results_prefix(
    pipeline: str, results_hash: str | None = None, region: str = MEGATEST_REGION
) -> str:
    """Resolve the S3 ``{pipeline}/results-<hash>/`` prefix to inspect.

    With ``results_hash`` the choice is explicit. Otherwise pick the
    most-recently-modified real ``results-<40hex>/`` dir (skipping ``results-dev``
    and ``results-test-*``). NOTE: the hash does not encode the pipeline version,
    so this is a recency heuristic — pass ``--results-hash`` to pin an exact run.
    """
    if results_hash:
        h = results_hash.removeprefix("results-")
        return f"{pipeline}/results-{h}/"

    root = _s3_list(f"{pipeline}/", region=region, delimiter="/")
    candidates: list[str] = []
    for cp in root.findall(f"{_S3_NS}CommonPrefixes/{_S3_NS}Prefix"):
        text = (cp.text or "").rstrip("/")
        name = text.rsplit("/", 1)[-1]
        suffix = name.removeprefix("results-")
        if len(suffix) == 40 and all(c in "0123456789abcdef" for c in suffix):
            candidates.append(text + "/")
    if not candidates:
        raise RuntimeError(f"No megatest results-<hash> dirs found for {pipeline}")
    return max(candidates, key=lambda p: _prefix_last_modified(p, region))


def list_keys(prefix: str, region: str = MEGATEST_REGION) -> list[str]:
    """All object keys under ``prefix``, returned relative to it (paginated)."""
    keys: list[str] = []
    token: str | None = None
    while True:
        root = _s3_list(prefix, region=region, continuation_token=token)
        for contents in root.findall(f"{_S3_NS}Contents"):
            key_el = contents.find(f"{_S3_NS}Key")
            if key_el is not None and key_el.text:
                keys.append(key_el.text[len(prefix) :])
        truncated = root.findtext(f"{_S3_NS}IsTruncated", "false") == "true"
        token = root.findtext(f"{_S3_NS}NextContinuationToken")
        if not truncated or not token:
            break
    return keys


# ---------------------------------------------------------------------------
# Template + recipe source-path extraction
# ---------------------------------------------------------------------------
def load_template(pipeline: str, version: str, projects_dir: Path = NFCORE_PROJECTS_DIR) -> dict:
    """Parse the ``template.yaml`` for a pinned pipeline version."""
    import yaml

    path = projects_dir / pipeline / version / "template.yaml"
    return yaml.safe_load(path.read_text())


def substitute_vars(path: str, variables: dict[str, str]) -> str:
    """Resolve ``{VAR}`` tokens in a recipe path against template ``reference.vars``.

    ``{DATA_ROOT}`` is dropped (megatest keys are relative to the results root);
    other vars are filled from ``variables``. Unknown tokens are left intact so
    they surface as unresolved in the report.
    """
    out = path.replace("{DATA_ROOT}/", "").replace("{DATA_ROOT}", "")
    for name, value in variables.items():
        out = out.replace(f"{{{name}}}", value)
    return out


def collect_recipe_source_paths(
    template: dict, pipeline: str, version: str
) -> list[tuple[str, str, str, bool]]:
    """Extract ``(dc_tag, source_ref, resolved_path, optional)`` for every recipe.

    Mirrors ``templates._check_dc_source_files``: load each transformed DC's
    recipe, take its file-based ``SOURCES`` (skipping ``dc_ref`` joins), apply the
    DC's ``source_overrides``, and substitute template variables.
    """
    from depictio.recipes import RecipeError, load_recipe

    reference = (template.get("template", {}).get("reference", {}) or {}).get("vars", {}) or {}
    variables = {k: str(v) for k, v in reference.items()}

    entries: list[tuple[str, str, str, bool]] = []
    for workflow in template.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            config = dc.get("config", {})
            if config.get("source") != "transformed":
                continue
            transform = config.get("transform", {})
            recipe_name = transform.get("recipe")
            if not recipe_name:
                continue
            try:
                module = load_recipe(recipe_name, version)
            except (RecipeError, Exception) as exc:  # noqa: BLE001 - report, don't crash
                print(f"  ! could not load recipe {recipe_name}: {exc}", file=sys.stderr)
                continue
            overrides = {
                ref: (so.get("path", "") if isinstance(so, dict) else so)
                for ref, so in (transform.get("source_overrides") or {}).items()
            }
            tag = dc.get("data_collection_tag", "")
            for src in module.SOURCES:
                if src.dc_ref is not None:
                    continue  # joined source, not a file path
                raw = overrides.get(src.ref, src.path)
                if not raw:
                    continue
                entries.append((tag, src.ref, substitute_vars(raw, variables), bool(src.optional)))
    return entries


# ---------------------------------------------------------------------------
# Drift report
# ---------------------------------------------------------------------------
def _path_resolves(path: str, keys: list[str], key_set: set[str]) -> bool:
    """A path resolves if it is an exact key, a glob match, or a dir prefix."""
    if path in key_set:
        return True
    if any(ch in path for ch in "*?[") and any(fnmatch(k, path) for k in keys):
        return True
    prefix = path.rstrip("/") + "/"
    return any(k.startswith(prefix) for k in keys)


def _nearest_prefix(path: str, keys: list[str]) -> str | None:
    """Longest leading directory of ``path`` that still exists in ``keys``."""
    parts = path.split("/")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:cut]) + "/"
        if any(k.startswith(candidate) for k in keys):
            return candidate
    return None


def build_drift_report(
    pipeline: str,
    local_version: str,
    new_version: str,
    results_prefix: str,
    source_paths: list[tuple[str, str, str, bool]],
    keys: list[str],
) -> tuple[str, int]:
    """Render a markdown drift report. Returns ``(markdown, n_missing)``."""
    key_set = set(keys)
    resolved: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str, str]] = []
    for tag, ref, path, optional in source_paths:
        if _path_resolves(path, keys, key_set) or optional:
            resolved.append((tag, ref, path))
        else:
            missing.append((tag, ref, path))

    lines = [
        f"# nf-core/{pipeline} drift report — {local_version} → {new_version}",
        "",
        f"Megatest: `s3://{MEGATEST_BUCKET}/{results_prefix}`",
        f"Template: `nf-core/{pipeline}/{local_version}` — "
        f"{len(source_paths)} recipe source paths checked, **{len(missing)} missing**.",
        "",
    ]
    if missing:
        lines.append(f"## ❌ Missing — likely renamed/moved in {new_version} ({len(missing)})")
        for tag, ref, path in missing:
            lines.append(f"- `{tag}` ({ref}) → {path}")
            hint = _nearest_prefix(path, keys)
            if hint:
                lines.append(f"  - _nearest existing prefix:_ `{hint}`")
        lines.append("")
        lines.append(
            "➡️ A maintainer should update the affected recipe / `source_overrides` "
            f"paths when scaffolding the `{new_version}` template."
        )
        lines.append("")
    lines.append(f"## ✅ Resolved ({len(resolved)})")
    for tag, ref, path in resolved:
        lines.append(f"- `{tag}` ({ref}) → {path}")
    lines.append("")
    return "\n".join(lines), len(missing)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    results = check_updates(token=token)
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    print(f"{'Pipeline':<14}{'Local':<10}{'nf-core latest':<16}Update?")
    for r in results:
        flag = "⬆  yes" if r["update_available"] else "—  up to date"
        remote = r["remote"] or "?"
        print(f"{r['pipeline']:<14}{r['local']:<10}{remote:<16}{flag}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    pipeline = args.pipeline
    pipelines = discover_pipelines()
    if pipeline not in pipelines:
        print(f"Unknown pipeline '{pipeline}' (have: {', '.join(pipelines)})", file=sys.stderr)
        return 2
    local = str(local_latest_version(pipelines[pipeline]))
    new_version = fetch_latest_release(pipeline, os.environ.get("GITHUB_TOKEN")) or local

    print(f"→ nf-core/{pipeline}: {local} (local) → {new_version} (release)", file=sys.stderr)
    results_prefix = resolve_results_prefix(pipeline, args.results_hash)
    print(f"→ megatest results: {results_prefix}", file=sys.stderr)
    keys = list_keys(results_prefix)
    print(f"→ listing s3://{MEGATEST_BUCKET}/{results_prefix}  ({len(keys)} keys)", file=sys.stderr)

    template = load_template(pipeline, local)
    source_paths = collect_recipe_source_paths(template, pipeline, local)
    print(f"→ checking {len(source_paths)} recipe source paths", file=sys.stderr)

    report, n_missing = build_drift_report(
        pipeline, local, new_version, results_prefix, source_paths, keys
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(f"Report written to {out}", file=sys.stderr)
    else:
        print(report)

    if n_missing:
        print(f"✗ {n_missing} of {len(source_paths)} paths no longer resolve", file=sys.stderr)
    else:
        print(
            f"✓ {len(source_paths)} of {len(source_paths)} paths resolve — no drift",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Detect new nf-core releases for templated pipelines")
    p_check.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    p_check.set_defaults(func=cmd_check)

    p_report = sub.add_parser("report", help="Report megatest output drift for a pipeline")
    p_report.add_argument("--pipeline", required=True, help="Pipeline name, e.g. ampliseq")
    p_report.add_argument(
        "--results-hash", help="Pin a specific megatest results-<hash> (else newest is used)"
    )
    p_report.add_argument("--out", help="Write the markdown report to this file instead of stdout")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
