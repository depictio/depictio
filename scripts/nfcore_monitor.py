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
  template (nf-co.re ``pipelines.json`` release index, GitHub releases API as
  the fallback, vs. our pinned version dirs).
* ``report`` — for a pipeline with an update, validate the template against that
  version's AWS megatest results (anonymous S3) in three layers:
    1. source-path existence (which recipe inputs moved/renamed),
    2. recipe execution — download each file-based recipe's inputs and actually
       run ``transform()`` + assert ``EXPECTED_SCHEMA`` (catches column/content
       changes, not just missing files); dc_ref/canonical recipes are skipped,
    3. ``depictio dev catalog validate`` as a static module/recipe gate.
  Pass ``--no-exec`` for the fast path-existence check only.

The megatest prefix is the release's ``tag_sha`` (``results-<tag_sha>/``); the
resolution, the empty-run check and the S3 helpers live in
``scripts/nfcore_megatest.py`` and are re-exported here. When the release's
own run is empty or missing the report degrades to the newest real run and
says so in its header.

Usage::

    python scripts/nfcore_monitor.py check [--json]
    python scripts/nfcore_monitor.py report --pipeline ampliseq [--version V] [--results-hash H] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, NamedTuple

from packaging.version import InvalidVersion, Version

# Allow `python scripts/nfcore_monitor.py` to import the in-repo `depictio`
# package even when it is not pip-installed (CI installs it editable; this keeps
# direct script runs working too), and the sibling megatest module.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nfcore_megatest import (  # noqa: E402
    _S3_NS,
    MEGATEST_BUCKET,
    MEGATEST_REGION,
    MegatestError,
    _s3_list,
    download_object,
    http_get,
    list_keys,
    list_objects,
    load_manifest,
    load_pipelines_index,
    manifest_path,
    newest_nonempty_run,
    release_for_version,
    resolve_run,
)

__all__ = [
    "MEGATEST_BUCKET",
    "MEGATEST_REGION",
    "_S3_NS",
    "_s3_list",
    "download_object",
    "list_keys",
    "list_objects",
    "resolve_results_prefix",
]

# nf-core pipeline templates live here, one folder per pipeline, with one
# sub-folder per pinned version (plus a non-version ``recipes/`` folder).
NFCORE_PROJECTS_DIR = _REPO_ROOT / "depictio" / "projects" / "nf-core"

GITHUB_API = "https://api.github.com"


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
    """Return nf-core's latest release tag for ``pipeline`` via the GitHub API (``v`` stripped).

    Fallback for pipelines the nf-co.re index does not know. Returns ``None``
    when the lookup fails (network/rate-limit/no releases) so a single flaky
    pipeline never breaks the whole run.
    """
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "depictio-nfcore-monitor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API}/repos/nf-core/{pipeline}/releases/latest"
    try:
        data = json.loads(http_get(url, headers=headers, retries=2))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        print(f"  ! could not fetch latest release for {pipeline}: {exc}", file=sys.stderr)
        return None
    tag = str(data.get("tag_name", "")).lstrip("v")
    return tag or None


def load_index_or_none() -> dict[str, Any] | None:
    """The nf-co.re release index, or ``None`` (with a warning) when unreachable."""
    try:
        return load_pipelines_index()
    except (OSError, ValueError) as exc:
        print(f"  ! nf-core pipelines index unavailable: {exc}", file=sys.stderr)
        return None


def latest_release_tag(
    pipeline: str, index: dict[str, Any] | None = None, token: str | None = None
) -> str | None:
    """Latest release tag: nf-co.re index first, GitHub releases API as fallback."""
    if index is not None:
        try:
            return str(release_for_version(index, pipeline, "latest")["tag_name"]).lstrip("v")
        except MegatestError:
            pass  # pipeline (or its releases) unknown to the index: ask GitHub
    return fetch_latest_release(pipeline, token)


def check_updates(
    projects_dir: Path = NFCORE_PROJECTS_DIR,
    token: str | None = None,
    index: dict[str, Any] | None = None,
) -> list[dict[str, object]]:
    """Compare each pipeline's local-latest version against nf-core's release.

    ``index`` is the nf-co.re release index (loaded once when not given); the
    GitHub API is only asked for pipelines the index does not cover.
    """
    if index is None:
        index = load_index_or_none()
    results: list[dict[str, object]] = []
    for pipeline, versions in discover_pipelines(projects_dir).items():
        local = local_latest_version(versions)
        remote_str = latest_release_tag(pipeline, index, token)
        update_available = False
        if remote_str is not None:
            try:
                update_available = Version(remote_str) > local
            except InvalidVersion:
                pass  # an unparseable remote tag never claims an update
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
# Megatest results prefix (listing/download helpers come from nfcore_megatest)
# ---------------------------------------------------------------------------
def resolve_results_prefix(
    pipeline: str,
    results_hash: str | None = None,
    version: str | None = None,
    index: dict[str, Any] | None = None,
    run_root: str = "",
    region: str = MEGATEST_REGION,
) -> str:
    """Resolve the S3 prefix whose keys are the template's DATA_ROOT.

    ``<pipeline>/results-<hash>/`` is the release's ``tag_sha`` in nf-co.re's
    ``pipelines.json``, so ``version`` (``latest`` when None) maps to exactly one
    run; ``nfcore_megatest.resolve_run`` does the lookup and rejects empty or
    failed runs (raising ``MegatestError`` with a table of real runs). An
    explicit ``results_hash`` is taken as-is, without network access. The
    returned prefix ends with ``run_root`` (e.g. rnaseq ``aligner_star_salmon/``)
    when the template's DATA_ROOT is a sub-directory of the run.
    """
    root = run_root.strip("/")
    root = f"{root}/" if root else ""
    if results_hash:
        h = results_hash.removeprefix("results-")
        return f"{pipeline}/results-{h}/{root}"
    run = resolve_run(pipeline, version=version, run_root=root, index=index, region=region)
    return run.root_prefix


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
    """Yield ``(dc_tag, recipe_name, module_or_None, overrides, load_error, dc_optional)``.

    Loads each transformed data collection's recipe module (reused by both the
    path-existence check and the recipe-execution check). ``dc_optional`` is the
    DC-level ``optional: true`` template flag: such DCs belong to a route the
    pipeline only produces under non-default parameters (e.g. ampliseq
    multiregion/SIDLE), so their sources being absent from the default-profile
    megatest is expected, not drift.
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
            dc_optional = bool(dc.get("optional"))
            try:
                module = load_recipe(recipe_name, version)
            except Exception as exc:  # noqa: BLE001 - reported, never crashes the run
                yield (tag, recipe_name, None, overrides, str(exc), dc_optional)
            else:
                yield (tag, recipe_name, module, overrides, None, dc_optional)


def collect_recipe_source_paths(
    template: dict, pipeline: str, version: str
) -> list[tuple[str, str, str, bool]]:
    """Extract ``(dc_tag, source_ref, resolved_path, optional)`` for every recipe.

    Loads each transformed DC's recipe, takes its file-based ``SOURCES`` (skipping
    ``dc_ref`` joins), applies the DC's ``source_overrides``, and substitutes
    template variables. ``optional`` is true when either the recipe source or the
    owning DC is optional (route-gated DCs prune cleanly when absent).
    """
    variables = _template_vars(template)
    entries: list[tuple[str, str, str, bool]] = []
    for tag, recipe_name, module, overrides, load_error, dc_optional in _iter_recipe_dcs(
        template, version
    ):
        if load_error:
            print(f"  ! could not load recipe {recipe_name}: {load_error}", file=sys.stderr)
            continue
        for src in module.SOURCES:
            if src.dc_ref is not None:
                continue  # joined source, not a file path
            raw = overrides.get(src.ref, src.path)
            if not raw:
                continue
            entries.append(
                (tag, src.ref, substitute_vars(raw, variables), bool(src.optional) or dc_optional)
            )
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
    dc_optional: bool = False,
) -> RecipeCheck:
    """Download a file-based recipe's sources and actually run it (transform + schema).

    Recipes that consume upstream DCs (``dc_ref``) don't read megatest files
    directly, so they can't break from an nf-core layout change — skipped here.
    An ``optional: true`` DC (route-gated, e.g. ampliseq multiregion/SIDLE) whose
    source is absent is likewise skipped: the megatest runs the default profile
    only, so the route's files are expected to be missing — that's pruning, not
    drift.
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
            if dc_optional or src.optional:
                return RecipeCheck(
                    dc_tag,
                    recipe_name,
                    "SKIPPED",
                    f"optional route not exercised by megatest (source absent: {rel})",
                )
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
    for tag, recipe_name, module, overrides, load_error, dc_optional in _iter_recipe_dcs(
        template, version
    ):
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
                dc_optional=dc_optional,
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
    run_root: str = "",
    note: str | None = None,
) -> tuple[str, int]:
    """Render a markdown drift report. Returns ``(markdown, n_problems)``.

    Layer 1 (always): recipe source-path existence against the new megatest.
    Layer 2 (when ``recipe_results`` given): the recipes actually run — load the
    real files, run ``transform()`` and assert ``EXPECTED_SCHEMA``.
    Layer 3 (when ``catalog_result`` given): static ``catalog validate`` gate.
    ``run_root`` names the sub-directory of the run that is the DATA_ROOT and
    ``note`` is printed under the header (e.g. when the report had to fall back
    to another run because the release's own megatest is empty).
    """
    key_set = set(keys)
    resolved: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str, str]] = []
    optional_absent: list[tuple[str, str, str]] = []
    for tag, ref, path, optional in source_paths:
        if _path_resolves(path, keys, key_set):
            resolved.append((tag, ref, path))
        elif optional:
            # Route-gated DC (template `optional: true`): the megatest's default
            # profile never produces it, so absence is expected — surfaced for
            # coverage visibility but never counted as drift.
            optional_absent.append((tag, ref, path))
        else:
            missing.append((tag, ref, path))

    failed_recipes = [r for r in (recipe_results or []) if r.status == "FAIL"]
    catalog_failed = catalog_result is not None and catalog_result[0] == "FAIL"
    n_problems = len(missing) + len(failed_recipes) + (1 if catalog_failed else 0)
    overall = "❌ action needed" if n_problems else "✅ still valid"

    megatest = f"**{overall}** · Megatest: `s3://{MEGATEST_BUCKET}/{results_prefix}`"
    if run_root:
        megatest += f" · run_root: `{run_root}`"
    lines = [
        f"# nf-core/{pipeline} drift report — {local_version} → {new_version}",
        "",
        megatest,
        "",
    ]
    if note:
        lines += [f"> ⚠️ {note}", ""]

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
        f"## Source paths — {len(resolved)} resolved, {len(missing)} missing, "
        f"{len(optional_absent)} optional-absent (of {len(source_paths)})"
    )
    for tag, ref, path in missing:
        lines.append(f"- ❌ `{tag}` ({ref}) → {path}")
        hint = _nearest_prefix(path, keys)
        if hint:
            lines.append(f"  - _nearest existing prefix:_ `{hint}`")
    for tag, ref, path in optional_absent:
        lines.append(f"- ⚪ `{tag}` ({ref}) → {path} — optional route, not exercised by megatest")
    lines.append("")

    # Next step: the bump itself is manual (demo data + seeds need a human) —
    # hand the maintainer the exact command.
    if new_version != local_version:
        lines += [
            "## Next steps",
            "Template still valid (or once the drift above is fixed), ship the new version with:",
            "```",
            f"python scripts/bump_template_version.py --pipeline {pipeline} "
            f"--new-version {new_version}",
            "```",
            "then follow the checklist it prints. Seeding, CLI (`--template …/latest`), "
            "CI and docs all pick the new version up automatically.",
            "",
        ]
    return "\n".join(lines), n_problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    results = check_updates(token=token, index=load_index_or_none())
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
    index = load_index_or_none()
    new_version = (
        args.version or latest_release_tag(pipeline, index, os.environ.get("GITHUB_TOKEN")) or local
    )

    # The template's DATA_ROOT may be a sub-directory of the megatest run
    # (rnaseq `aligner_star_salmon/`): the local version's manifest knows it.
    run_root = ""
    manifest = manifest_path(pipeline, local)
    if manifest.is_file():
        run_root = load_manifest(manifest).run_root

    print(f"→ nf-core/{pipeline}: {local} (local) → {new_version} (release)", file=sys.stderr)
    note: str | None = None
    try:
        results_prefix = resolve_results_prefix(
            pipeline, args.results_hash, version=new_version, index=index, run_root=run_root
        )
    except MegatestError as exc:
        # The release's own megatest is empty/missing: degrade to the newest
        # real run so the drift report still says something, and flag it.
        fallback = newest_nonempty_run(pipeline, index=index, run_root=run_root)
        if fallback is None:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        note = (
            f"{exc.reason}. Falling back to the newest real run "
            f"`{fallback.prefix}` (release {fallback.tag or 'unknown'})."
        )
        print(f"! {note}", file=sys.stderr)
        results_prefix = fallback.root_prefix
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
        run_root=run_root,
        note=note,
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
        "--version",
        help="Release to validate against (default: nf-core's latest); its tag_sha picks the megatest",
    )
    p_report.add_argument(
        "--results-hash",
        help="Pin a specific megatest results-<hash> (else the release's own run is used)",
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
