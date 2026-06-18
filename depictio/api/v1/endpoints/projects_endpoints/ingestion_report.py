"""Ingestion report — a traceable summary of what a template execution ingested.

Compares a project's frozen expected-DC manifest (``TemplateOrigin.expected_data_collections``,
written at template-resolution time) against what was actually identified during the CLI scan
(``runs.scan_results[].dc_stats``) and aggregated (``deltatables`` / ``multiqc`` collections).

Pure read: builds the report from existing documents, mutates nothing. The "ingested" check
mirrors ``depictio/projects/nf-core/report_validation.py`` (delta doc for table DCs, multiqc doc
for MultiQC DCs), promoted here to a server-side endpoint so the React viewer can render it.
"""

from __future__ import annotations

import os

from bson import ObjectId
from pydantic import BaseModel, Field

from depictio.api.v1.db import (
    deltatables_collection,
    files_collection,
    multiqc_collection,
    runs_collection,
)

# DC statuses surfaced in the report.
STATUS_IDENTIFIED = "identified"  # included + files found and/or aggregated
STATUS_FOUND_ZERO = "found_zero"  # included but nothing matched / not aggregated
STATUS_GATED_OUT = "gated_out"  # excluded by a template conditional / missing-file prune

# Manifest provenance: a faithful template manifest vs. a best-effort live-project fallback
# (legacy projects created before the manifest was persisted — gated-out DCs are unknown there).
SOURCE_MANIFEST = "template_manifest"
SOURCE_LIVE = "live_project"

# Recipe source lives in the depictio repo; link to it on the default branch.
RECIPE_REPO_BASE = "https://github.com/depictio/depictio/blob/main/"


def _recipe_github_url(recipe_ref: str | None) -> str | None:
    """GitHub blob URL for a recipe ref, resolved to its actual repo path.

    Recipes resolve to either a module-owned (catalog) or shared (projects) file,
    so we resolve the real path and make it repo-relative rather than guessing.
    Best-effort: returns None if the recipe can't be located.
    """
    if not recipe_ref:
        return None
    try:
        from pathlib import Path

        import depictio.recipes as recipes_pkg
        from depictio.recipes import resolve_recipe_path

        repo_root = Path(recipes_pkg.__file__).resolve().parents[2]
        rel = resolve_recipe_path(recipe_ref).resolve().relative_to(repo_root)
        return RECIPE_REPO_BASE + str(rel)
    except Exception:
        return None


def _as_object_ids(value) -> list:
    """Candidate match values for a stored id: ObjectId form and raw string.

    DC ids are written as ObjectId or plain string depending on the code path, so
    queries match both (same defensive approach as the validation reporter).
    Accepts either a str or an ObjectId input and always yields both forms.
    """
    out: list = []
    if not value:
        return out
    text = str(value)
    try:
        out.append(ObjectId(text))
    except Exception:
        pass
    out.append(text)
    return out


def _dc_has_document(collection, dc_id: str | None) -> bool:
    """True if `collection` holds at least one document for this data-collection id."""
    candidates = _as_object_ids(dc_id)
    if not candidates:
        return False
    return collection.count_documents({"data_collection_id": {"$in": candidates}}, limit=1) > 0


def _dc_table_location(dc_id: str | None) -> str | None:
    """Delta-table storage location for a DC, if it has been aggregated.

    Recipe / canonical DCs have no source files of their own — their data lives in
    this aggregated table — so the report shows this path instead of a file list.
    """
    candidates = _as_object_ids(dc_id)
    if not candidates:
        return None
    doc = deltatables_collection.find_one(
        {"data_collection_id": {"$in": candidates}}, {"delta_table_location": 1}
    )
    return doc.get("delta_table_location") if doc else None


def _dc_file_count(dc_id: str | None) -> int:
    """Number of files registered for a DC in ``files_collection``.

    This is the ground truth for "how many files were identified" — the scan's
    per-run ``dc_stats`` only covers the recursive multi-DC scan path (single-file
    and recipe-derived DCs bypass it), so it under-reports. The expandable file
    list in the UI reads the same collection, keeping count and list consistent.
    """
    candidates = _as_object_ids(dc_id)
    if not candidates:
        return 0
    return files_collection.count_documents({"data_collection_id": {"$in": candidates}})


class IngestionVariable(BaseModel):
    name: str
    value: str


class IngestionDataCollection(BaseModel):
    data_collection_tag: str
    type: str | None = None
    optional: bool = False
    status: str
    removal_reason: str | None = None
    files_found: int = 0
    files_new: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    ingested: bool = False
    table_location: str | None = None
    source_inputs: list[str] = Field(default_factory=list)
    recipe: str | None = None  # recipe ref for transformed/derived DCs
    recipe_url: str | None = None  # GitHub link to the recipe source


class IngestionRun(BaseModel):
    run_tag: str
    run_location: str | None = None
    scan_time: str | None = None
    status: str  # ok | partial | no_scan


class IngestionSummary(BaseModel):
    # "total" counts only DCs *expected in this configuration* (i.e. included).
    # Conditionally gated-out DCs are intentional exclusions counted under `gated`
    # — never as a gap — even when the template declares them required.
    required_total: int = 0
    required_identified: int = 0
    required_missing: int = 0
    optional_total: int = 0
    optional_identified: int = 0
    optional_missing: int = 0
    gated: int = 0  # DCs (required or optional) excluded by a template condition / prune
    health: str = "ok"  # ok | partial | missing_required


class IngestionReportProject(BaseModel):
    id: str
    name: str
    project_type: str | None = None


class IngestionTemplate(BaseModel):
    template_id: str | None = None
    template_version: str | None = None
    applied_at: str | None = None
    data_root: str | None = None


class IngestionReport(BaseModel):
    project: IngestionReportProject
    template: IngestionTemplate | None = None
    manifest_source: str = SOURCE_LIVE
    variables: list[IngestionVariable] = Field(default_factory=list)
    data_collections: list[IngestionDataCollection] = Field(default_factory=list)
    runs: list[IngestionRun] = Field(default_factory=list)
    summary: IngestionSummary = Field(default_factory=IngestionSummary)
    scanned_at: str | None = None


def _collect_live_dcs(project: dict) -> dict[str, dict]:
    """Flatten workflows[].data_collections[] into {tag: {id, type, optional}}."""
    live: dict[str, dict] = {}
    for workflow in project.get("workflows", []) or []:
        for dc in workflow.get("data_collections", []) or []:
            tag = dc.get("data_collection_tag")
            if not tag:
                continue
            live[tag] = {
                "id": dc.get("_id") or dc.get("id"),
                "type": (dc.get("config") or {}).get("type"),
                "optional": bool(dc.get("optional", False)),
                "config": dc.get("config") or {},
            }
    return live


def _dc_source_inputs(config: dict, data_root: str | None) -> list[str]:
    """Resolve the input paths a recipe-derived (``transformed``) DC aggregates from.

    Recipe DCs declare their inputs as recipe ``SOURCES`` — either a relative
    ``path`` under the data root, or a ``dc_ref`` to another collection. Returns the
    resolved real paths (and ``dc_ref`` markers), so the report can show *what* fed
    the aggregation. Best-effort: returns what it can, never raises.
    """
    if (config.get("source") or "") != "transformed":
        return []
    transform = config.get("transform") or {}
    recipe = transform.get("recipe")
    if not recipe:
        return []
    overrides = transform.get("source_overrides") or {}
    out: list[str] = []
    try:
        from depictio.recipes import load_recipe

        module = load_recipe(recipe)
        for src in getattr(module, "SOURCES", []):
            dc_ref = getattr(src, "dc_ref", None)
            if dc_ref:
                out.append(f"(derived from collection '{dc_ref}')")
                continue
            ref = getattr(src, "ref", None)
            override = overrides.get(ref) if isinstance(overrides, dict) else None
            rel = (override.get("path") if isinstance(override, dict) else override) or getattr(
                src, "path", None
            )
            if not rel:
                continue
            path = os.path.join(data_root, rel) if (data_root and not os.path.isabs(rel)) else rel
            out.append(os.path.realpath(path) if os.path.exists(path) else path)
    except Exception:
        return out
    return out


def _aggregate_run_stats(
    project: dict,
) -> tuple[dict[str, dict[str, int]], list[IngestionRun], str | None]:
    """Sum the latest per-DC scan stats across all of a project's runs.

    Returns (per_dc_stats keyed by DC tag, run summaries, latest scan_time seen).
    Uses only each run's most recent scan (``scan_results[-1]``) — latest state.
    """
    workflow_ids = [
        ObjectId(wf["_id"]) for wf in (project.get("workflows", []) or []) if wf.get("_id")
    ]
    per_dc: dict[str, dict[str, int]] = {}
    runs: list[IngestionRun] = []
    latest_scan_time: str | None = None

    if not workflow_ids:
        return per_dc, runs, latest_scan_time

    for run in runs_collection.find({"workflow_id": {"$in": workflow_ids}}):
        scans = run.get("scan_results") or []
        latest = scans[-1] if scans else None
        scan_time = latest.get("scan_time") if latest else None
        if scan_time and (latest_scan_time is None or scan_time > latest_scan_time):
            latest_scan_time = scan_time

        dc_stats = (latest or {}).get("dc_stats") or {}
        run_failures = 0
        for tag, stats in dc_stats.items():
            agg = per_dc.setdefault(
                tag,
                {"total_files": 0, "new_files": 0, "skipped_files": 0, "other_failure_files": 0},
            )
            for key in agg:
                agg[key] += int(stats.get(key, 0) or 0)
            run_failures += int(stats.get("other_failure_files", 0) or 0)

        if latest is None:
            status = "no_scan"
        elif run_failures > 0:
            status = "partial"
        else:
            status = "ok"
        runs.append(
            IngestionRun(
                run_tag=run.get("run_tag", ""),
                run_location=run.get("run_location"),
                scan_time=scan_time,
                status=status,
            )
        )

    return per_dc, runs, latest_scan_time


def _expected_entries(project: dict, live: dict[str, dict]) -> tuple[list[dict], str]:
    """Return the expected-DC superset to report on, plus its provenance.

    Prefers the frozen manifest (``template_origin.expected_data_collections``); falls
    back to the live project DCs for legacy projects that predate the manifest.
    """

    def _live_entry(tag: str, info: dict) -> dict:
        return {
            "data_collection_tag": tag,
            "type": info["type"],
            "optional": info["optional"],
            "included": True,
            "removal_reason": None,
        }

    template_origin = project.get("template_origin") or {}
    manifest = template_origin.get("expected_data_collections") or []

    if manifest:
        entries = [dict(m) for m in manifest]
        manifest_tags = {m.get("data_collection_tag") for m in manifest}
        # Defensively surface any live DC the manifest doesn't know about.
        for tag, info in live.items():
            if tag not in manifest_tags:
                entries.append(_live_entry(tag, info))
        return entries, SOURCE_MANIFEST

    return [_live_entry(tag, info) for tag, info in live.items()], SOURCE_LIVE


def build_ingestion_report(project: dict) -> IngestionReport:
    """Assemble the full ingestion report for a project dict (objectids stringified)."""
    live = _collect_live_dcs(project)
    per_dc_stats, runs, latest_scan_time = _aggregate_run_stats(project)
    expected, manifest_source = _expected_entries(project, live)
    data_root = (project.get("template_origin") or {}).get("data_root")

    dc_entries: list[IngestionDataCollection] = []
    summary = IngestionSummary()

    for entry in expected:
        tag = entry["data_collection_tag"]
        optional = bool(entry.get("optional", False))
        included = bool(entry.get("included", True))
        dc_type = entry.get("type") or live.get(tag, {}).get("type")
        stats = per_dc_stats.get(tag, {})
        dc_id = live.get(tag, {}).get("id")

        table_location: str | None = None
        source_inputs: list[str] = []
        recipe: str | None = None
        recipe_url: str | None = None
        if not included:
            status = STATUS_GATED_OUT
            ingested = False
            # Gated DCs were removed from the project, so there is no id to count.
            files_found = 0
        else:
            # Count actual registered files (ground truth), not the scan's
            # per-run dc_stats, which under-reports single-file / recipe DCs.
            files_found = _dc_file_count(dc_id)
            table_location = _dc_table_location(dc_id)
            cfg = live.get(tag, {}).get("config", {})
            source_inputs = _dc_source_inputs(cfg, data_root)
            if (cfg.get("source") or "") == "transformed":
                recipe = (cfg.get("transform") or {}).get("recipe")
                recipe_url = _recipe_github_url(recipe)
            # "Ingested" = a table was produced. Table DCs land a deltatable;
            # MultiQC DCs land a multiqc doc. Check both rather than trusting the
            # declared type (recipe/canonical DCs are typed "table" but some only
            # ever produce one or the other).
            ingested = _dc_has_document(deltatables_collection, dc_id) or _dc_has_document(
                multiqc_collection, dc_id
            )
            status = STATUS_IDENTIFIED if (files_found > 0 or ingested) else STATUS_FOUND_ZERO

        dc_entries.append(
            IngestionDataCollection(
                data_collection_tag=tag,
                type=dc_type,
                optional=optional,
                status=status,
                removal_reason=entry.get("removal_reason"),
                files_found=files_found,
                files_new=int(stats.get("new_files", 0) or 0),
                files_skipped=int(stats.get("skipped_files", 0) or 0),
                files_failed=int(stats.get("other_failure_files", 0) or 0),
                ingested=ingested,
                table_location=table_location,
                source_inputs=source_inputs,
                recipe=recipe,
                recipe_url=recipe_url,
            )
        )

        # Tally summary counts. Gated DCs are intentional exclusions (a template
        # can gate out even a *required* DC when its variable is absent), so they
        # are counted apart and never as a gap — only included DCs are "expected".
        if status == STATUS_GATED_OUT:
            summary.gated += 1
        elif optional:
            summary.optional_total += 1
            if status == STATUS_IDENTIFIED:
                summary.optional_identified += 1
            else:
                summary.optional_missing += 1
        else:
            summary.required_total += 1
            if status == STATUS_IDENTIFIED:
                summary.required_identified += 1
            else:
                # An included required DC with no data is a genuine gap.
                summary.required_missing += 1

    # Health reflects REQUIRED completeness only. Optional collections are
    # expected to be absent for some runs/protocols (e.g. SIDLE multiregion DCs
    # on a non-multiregion run), so their absence is surfaced in the summary
    # counts but must not degrade health — otherwise a fully-loaded run looks
    # "partial" just because some optional viz weren't produced.
    summary.health = "missing_required" if summary.required_missing > 0 else "ok"

    template_origin = project.get("template_origin") or {}
    template = (
        IngestionTemplate(
            template_id=template_origin.get("template_id"),
            template_version=template_origin.get("template_version"),
            applied_at=template_origin.get("applied_at"),
            data_root=template_origin.get("data_root"),
        )
        if template_origin
        else None
    )
    variables = [
        IngestionVariable(name=name, value=str(value))
        for name, value in (template_origin.get("variables") or {}).items()
    ]

    return IngestionReport(
        project=IngestionReportProject(
            id=str(project.get("_id") or project.get("id") or ""),
            name=project.get("name", ""),
            project_type=project.get("project_type"),
        ),
        template=template,
        manifest_source=manifest_source,
        variables=variables,
        data_collections=dc_entries,
        runs=runs,
        summary=summary,
        scanned_at=latest_scan_time,
    )
