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
* ``report`` — for a pipeline with an update, validate the template against that
  version's AWS megatest results (anonymous S3) in three layers:
    1. source-path existence (which recipe inputs moved/renamed),
    2. recipe execution — download each file-based recipe's inputs and actually
       run ``transform()`` + assert ``EXPECTED_SCHEMA`` (catches column/content
       changes, not just missing files); dc_ref/canonical recipes are skipped,
    3. ``depictio dev catalog validate`` as a static module/recipe gate.
  Pass ``--no-exec`` for the fast path-existence check only.

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
from typing import Any, NamedTuple
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


def list_objects(prefix: str, region: str = MEGATEST_REGION) -> list[tuple[str, int]]:
    """All objects under ``prefix`` as ``(key_relative_to_prefix, size)`` (paginated)."""
    objects: list[tuple[str, int]] = []
    token: str | None = None
    while True:
        root = _s3_list(prefix, region=region, continuation_token=token)
        for contents in root.findall(f"{_S3_NS}Contents"):
            key_el = contents.find(f"{_S3_NS}Key")
            size_el = contents.find(f"{_S3_NS}Size")
            if key_el is not None and key_el.text:
                size = int(size_el.text) if size_el is not None and size_el.text else 0
                objects.append((key_el.text[len(prefix) :], size))
        truncated = root.findtext(f"{_S3_NS}IsTruncated", "false") == "true"
        token = root.findtext(f"{_S3_NS}NextContinuationToken")
        if not truncated or not token:
            break
    return objects


def list_keys(prefix: str, region: str = MEGATEST_REGION) -> list[str]:
    """All object keys under ``prefix``, returned relative to it (paginated)."""
    return [key for key, _ in list_objects(prefix, region)]


def download_object(prefix: str, rel_key: str, dest: Path, region: str = MEGATEST_REGION) -> None:
    """Download one megatest object (``prefix`` + ``rel_key``) to ``dest``."""
    url = f"https://{MEGATEST_BUCKET}.s3.{region}.amazonaws.com/" + urllib.parse.quote(
        prefix + rel_key
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_get(url))


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


def _template_vars(template: dict) -> dict[str, str]:
    """The ``template.reference.vars`` map used to resolve recipe path tokens."""
    reference = (template.get("template", {}).get("reference", {}) or {}).get("vars", {}) or {}
    return {k: str(v) for k, v in reference.items()}


def _iter_recipe_dcs(template: dict, version: str):
    """Yield ``(dc_tag, recipe_name, module_or_None, overrides, load_error)`` per recipe DC.

    Loads each transformed data collection's recipe module (reused by both the
    path-existence check and the recipe-execution check).
    """
    from depictio.recipes import load_recipe

    for workflow in template.get("workflows", []):
        for dc in workflow.get("data_collections", []):
            config = dc.get("config", {})
            if config.get("source") != "transformed":
                continue
            transform = config.get("transform", {})
            recipe_name = transform.get("recipe")
            if not recipe_name:
                continue
            overrides = {
                ref: (so.get("path", "") if isinstance(so, dict) else so)
                for ref, so in (transform.get("source_overrides") or {}).items()
            }
            tag = dc.get("data_collection_tag", "")
            try:
                module = load_recipe(recipe_name, version)
            except Exception as exc:  # noqa: BLE001 - reported, never crashes the run
                yield (tag, recipe_name, None, overrides, str(exc))
            else:
                yield (tag, recipe_name, module, overrides, None)


def collect_recipe_source_paths(
    template: dict, pipeline: str, version: str
) -> list[tuple[str, str, str, bool]]:
    """Extract ``(dc_tag, source_ref, resolved_path, optional)`` for every recipe.

    Loads each transformed DC's recipe, takes its file-based ``SOURCES`` (skipping
    ``dc_ref`` joins), applies the DC's ``source_overrides``, and substitutes
    template variables.
    """
    variables = _template_vars(template)
    entries: list[tuple[str, str, str, bool]] = []
    for tag, recipe_name, module, overrides, load_error in _iter_recipe_dcs(template, version):
        if load_error:
            print(f"  ! could not load recipe {recipe_name}: {load_error}", file=sys.stderr)
            continue
        for src in module.SOURCES:
            if src.dc_ref is not None:
                continue  # joined source, not a file path
            raw = overrides.get(src.ref, src.path)
            if not raw:
                continue
            entries.append((tag, src.ref, substitute_vars(raw, variables), bool(src.optional)))
    return entries


# ---------------------------------------------------------------------------
# Recipe execution against the megatest (the deeper "do recipes still run?" layer)
# ---------------------------------------------------------------------------
class RecipeCheck(NamedTuple):
    dc_tag: str
    recipe: str
    status: str  # "PASS" | "FAIL" | "SKIPPED"
    detail: str


def _validate_one_recipe(
    dc_tag: str,
    recipe_name: str,
    module: Any,
    overrides: dict[str, str],
    variables: dict[str, str],
    results_prefix: str,
    sizes: dict[str, int],
    workdir: Path,
    version: str,
    max_file_mb: float,
) -> RecipeCheck:
    """Download a file-based recipe's sources and actually run it (transform + schema).

    Recipes that consume upstream DCs (``dc_ref``) don't read megatest files
    directly, so they can't break from an nf-core layout change — skipped here.
    """
    from depictio.recipes import execute_recipe

    sources = module.SOURCES
    if any(s.dc_ref is not None for s in sources):
        return RecipeCheck(dc_tag, recipe_name, "SKIPPED", "consumes upstream DCs (dc_ref)")

    resolved_overrides: dict[str, str] = {}
    for src in sources:
        if src.glob_pattern is not None:
            return RecipeCheck(dc_tag, recipe_name, "SKIPPED", "glob source not executed")
        raw = overrides.get(src.ref, src.path)
        if not raw:
            return RecipeCheck(dc_tag, recipe_name, "SKIPPED", f"source '{src.ref}' has no path")
        rel = substitute_vars(raw, variables)
        if "{" in rel:
            return RecipeCheck(dc_tag, recipe_name, "SKIPPED", f"unresolved var in {rel}")
        if rel not in sizes:
            return RecipeCheck(dc_tag, recipe_name, "FAIL", f"source file absent: {rel}")
        if sizes[rel] > max_file_mb * 1_000_000:
            return RecipeCheck(
                dc_tag, recipe_name, "SKIPPED", f"{rel} too large ({sizes[rel] // 1_000_000}MB)"
            )
        download_object(results_prefix, rel, workdir / rel)
        resolved_overrides[src.ref] = rel

    try:
        df = execute_recipe(
            recipe_name, workdir, overrides=resolved_overrides, pipeline_version=version
        )
    except Exception as exc:  # noqa: BLE001 - the failure IS the signal we report
        return RecipeCheck(dc_tag, recipe_name, "FAIL", f"{type(exc).__name__}: {exc}")
    return RecipeCheck(dc_tag, recipe_name, "PASS", f"{df.height} rows × {df.width} cols")


def validate_recipes(
    template: dict,
    pipeline: str,
    version: str,
    results_prefix: str,
    objects: list[tuple[str, int]],
    workdir: Path,
    max_file_mb: float = 50.0,
) -> list[RecipeCheck]:
    """Run every file-based recipe of the template against the megatest results."""
    variables = _template_vars(template)
    sizes = dict(objects)
    results: list[RecipeCheck] = []
    for tag, recipe_name, module, overrides, load_error in _iter_recipe_dcs(template, version):
        if load_error:
            results.append(RecipeCheck(tag, recipe_name, "FAIL", f"import failed: {load_error}"))
            continue
        results.append(
            _validate_one_recipe(
                tag,
                recipe_name,
                module,
                overrides,
                variables,
                results_prefix,
                sizes,
                workdir,
                version,
                max_file_mb,
            )
        )
    return results


def run_catalog_validate() -> tuple[str, str]:
    """Run ``depictio dev catalog validate`` (static module/recipe gate).

    Returns ``(status, detail)`` with status one of PASS/FAIL/SKIPPED.
    """
    import subprocess

    try:
        proc = subprocess.run(
            ["depictio", "dev", "catalog", "validate"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (FileNotFoundError, OSError) as exc:
        return ("SKIPPED", f"depictio CLI unavailable: {exc}")
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    detail = tail[-1] if tail else ""
    return ("PASS" if proc.returncode == 0 else "FAIL", detail)


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
    recipe_results: list[RecipeCheck] | None = None,
    catalog_result: tuple[str, str] | None = None,
) -> tuple[str, int]:
    """Render a markdown drift report. Returns ``(markdown, n_problems)``.

    Layer 1 (always): recipe source-path existence against the new megatest.
    Layer 2 (when ``recipe_results`` given): the recipes actually run — load the
    real files, run ``transform()`` and assert ``EXPECTED_SCHEMA``.
    Layer 3 (when ``catalog_result`` given): static ``catalog validate`` gate.
    """
    key_set = set(keys)
    resolved: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str, str]] = []
    for tag, ref, path, optional in source_paths:
        if _path_resolves(path, keys, key_set) or optional:
            resolved.append((tag, ref, path))
        else:
            missing.append((tag, ref, path))

    failed_recipes = [r for r in (recipe_results or []) if r.status == "FAIL"]
    catalog_failed = catalog_result is not None and catalog_result[0] == "FAIL"
    n_problems = len(missing) + len(failed_recipes) + (1 if catalog_failed else 0)
    overall = "❌ action needed" if n_problems else "✅ still valid"

    lines = [
        f"# nf-core/{pipeline} drift report — {local_version} → {new_version}",
        "",
        f"**{overall}** · Megatest: `s3://{MEGATEST_BUCKET}/{results_prefix}`",
        "",
    ]

    # Layer 2: recipe execution
    if recipe_results is not None:
        passed = [r for r in recipe_results if r.status == "PASS"]
        skipped = [r for r in recipe_results if r.status == "SKIPPED"]
        lines.append(
            f"## Recipe execution — {len(passed)} pass, "
            f"{len(failed_recipes)} fail, {len(skipped)} skipped"
        )
        for r in failed_recipes:
            lines.append(f"- ❌ `{r.dc_tag}` ({r.recipe}) — {r.detail}")
        for r in passed:
            lines.append(f"- ✅ `{r.dc_tag}` ({r.recipe}) — {r.detail}")
        for r in skipped:
            lines.append(f"- ⚪ `{r.dc_tag}` ({r.recipe}) — {r.detail}")
        lines.append("")

    # Layer 3: catalog validate
    if catalog_result is not None:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⚪"}.get(catalog_result[0], "")
        lines.append(f"## Catalog validate — {icon} {catalog_result[0]}")
        if catalog_result[1]:
            lines.append(f"- {catalog_result[1]}")
        lines.append("")

    # Layer 1: path existence
    lines.append(
        f"## Source paths — {len(resolved)} resolved, {len(missing)} missing "
        f"(of {len(source_paths)})"
    )
    for tag, ref, path in missing:
        lines.append(f"- ❌ `{tag}` ({ref}) → {path}")
        hint = _nearest_prefix(path, keys)
        if hint:
            lines.append(f"  - _nearest existing prefix:_ `{hint}`")
    lines.append("")
    return "\n".join(lines), n_problems


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
    objects = list_objects(results_prefix)
    keys = [k for k, _ in objects]
    print(f"→ listing s3://{MEGATEST_BUCKET}/{results_prefix}  ({len(keys)} keys)", file=sys.stderr)

    template = load_template(pipeline, local)
    source_paths = collect_recipe_source_paths(template, pipeline, local)
    print(f"→ layer 1: checking {len(source_paths)} recipe source paths", file=sys.stderr)

    recipe_results: list[RecipeCheck] | None = None
    catalog_result: tuple[str, str] | None = None
    if not args.no_exec:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            print("→ layer 2: running recipes against megatest data", file=sys.stderr)
            recipe_results = validate_recipes(
                template,
                pipeline,
                local,
                results_prefix,
                objects,
                Path(tmp),
                max_file_mb=args.max_file_mb,
            )
        print("→ layer 3: depictio dev catalog validate", file=sys.stderr)
        catalog_result = run_catalog_validate()

    report, n_problems = build_drift_report(
        pipeline,
        local,
        new_version,
        results_prefix,
        source_paths,
        keys,
        recipe_results,
        catalog_result,
    )
    status = "✅ valid" if n_problems == 0 else f"⚠️ {n_problems} issue(s)"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(f"Report written to {out}", file=sys.stderr)
        # The only stdout line: the short status, for the workflow to put in the PR title.
        print(status)
    else:
        print(report)
        print(f"\n{status}", file=sys.stderr)
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
    p_report.add_argument(
        "--no-exec",
        action="store_true",
        help="Path-existence check only (skip recipe execution + catalog validate)",
    )
    p_report.add_argument(
        "--max-file-mb",
        type=float,
        default=50.0,
        help="Skip downloading/executing recipe sources larger than this (default 50)",
    )
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
