"""The project summary a static bundle ships (``BundleManifest.project``).

A bundle's project page shows what can be known about the dashboard's project
without a server: its name and description, the template and workflows it was
built from, its data collections, the links between them and the run
parameters the template recorded. Producer A reads all of it from the project
document; this module decides what of that document may leave the instance.

The rule is an allow-list. Only display facts are copied: never the ACL
(``permissions``, owners and their emails, ``pending_owner_email``), never
storage (``data_location``, ``scan`` locations, ``delta_location``, the
template's ``data_root`` / ``variables`` / ``config_snapshot``), never
migration internals (``provenance``, ``published_lock``). A field the project
model gains later stays out until someone adds it here on purpose.

Run parameters are the one place where free text reaches the bundle, and they
routinely hold server paths (``--input /data/runs/x/samplesheet.csv``) and,
now and then, a credential. :func:`safe_parameter_value` keeps the last part of
a path or object-store URI, drops a URL's user info, and withholds the value of
any key that looks like a secret.
"""

from __future__ import annotations

import re
from typing import Any

from depictio.models.models.serverless import (
    ProjectDataCollectionSummary,
    ProjectJoinSummary,
    ProjectLinkSummary,
    ProjectSummary,
    ProjectTemplateSummary,
    ProjectWorkflowSummary,
    RunParameter,
)

WITHHELD = "(withheld)"

# Keys whose value is a credential however it is spelled: `aws_secret_access_key`,
# `api-token`, `db.password`, `github_pat`. Substrings for the unambiguous
# words, whole key parts for the short ones (`auth` must not catch `author`).
_SECRET_SUBSTRINGS = (
    "passw",
    "secret",
    "token",
    "apikey",
    "api_key",
    "api-key",
    "credential",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
)
_SECRET_PARTS = frozenset({"pwd", "auth", "authorization", "cookie", "pat", "session", "sas"})
# An absolute POSIX path, a home-relative one, or a Windows drive path.
_ABS_PATH_RE = re.compile(r"^(/|~|[A-Za-z]:[\\/])")
# An object-store or file URI: its bucket and prefix are the storage layout.
_STORE_URI_RE = re.compile(r"^(s3|s3a|gs|gcs|az|abfss?|wasbs?|file|hdfs)://", re.IGNORECASE)
# user:password@ (or token@) in an http(s) URL.
_URL_USERINFO_RE = re.compile(r"^(https?://)[^/@\s]+@", re.IGNORECASE)


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _oid(value: Any) -> str | None:
    """A Mongo id (``ObjectId``, ``{"$oid": ...}`` or a string) as a string."""
    if isinstance(value, dict) and "$oid" in value:
        value = value["$oid"]
    return _str(value)


def public_http_url(value: Any) -> str | None:
    """``value`` when it is an absolute http(s) URL without user info, else None.

    A link in a bundle is only worth keeping when it still resolves from the
    reader's machine; anything else (a relative path, an internal scheme) is a
    dead link at best and a leaked location at worst.
    """
    text = _str(value)
    if not text or not re.match(r"^https?://", text, re.IGNORECASE):
        return None
    return _URL_USERINFO_RE.sub(r"\1", text)


def _last_part(path: str) -> str:
    """``…/samplesheet.tsv`` for any path or URI; the bare name when it has none."""
    stripped = path.rstrip("/\\")
    tail = re.split(r"[\\/]", stripped)[-1] if stripped else ""
    if not tail or tail == stripped:
        return tail or "…"
    return f"…/{tail}"


def is_secret_key(key: str | None) -> bool:
    """True when a parameter named ``key`` most likely holds a credential."""
    lowered = (key or "").lower()
    if any(word in lowered for word in _SECRET_SUBSTRINGS):
        return True
    return any(part in _SECRET_PARTS for part in re.split(r"[^a-z0-9]+", lowered))


def safe_parameter_value(key: str, value: Any) -> str:
    """A run parameter's value as safe to put in a shared file (module docstring)."""
    text = "" if value is None else str(value)
    if text and is_secret_key(key):
        return WITHHELD
    stripped = text.strip()
    if _STORE_URI_RE.match(stripped) or _ABS_PATH_RE.match(stripped):
        return _last_part(stripped)
    if re.match(r"^https?://", stripped, re.IGNORECASE):
        return _URL_USERINFO_RE.sub(r"\1", stripped)
    return text


def _template(origin: dict[str, Any]) -> ProjectTemplateSummary | None:
    template_id = _str(origin.get("template_id"))
    if not template_id:
        return None
    return ProjectTemplateSummary(
        template_id=template_id,
        template_version=_str(origin.get("template_version")),
        applied_at=_str(origin.get("applied_at") or origin.get("imported_at")),
    )


def _workflow(workflow: dict[str, Any]) -> ProjectWorkflowSummary | None:
    wf_id = _oid(workflow.get("_id") or workflow.get("id"))
    name = _str(workflow.get("name")) or _str(workflow.get("workflow_tag"))
    if not wf_id or not name:
        return None
    engine = workflow.get("engine") if isinstance(workflow.get("engine"), dict) else {}
    catalog = workflow.get("catalog") if isinstance(workflow.get("catalog"), dict) else {}
    return ProjectWorkflowSummary(
        id=wf_id,
        name=name,
        tag=_str(workflow.get("workflow_tag")),
        engine=_str(engine.get("name")),
        engine_version=_str(engine.get("version")),
        version=_str(workflow.get("version")),
        repository_url=public_http_url(workflow.get("repository_url")),
        catalog=_str(catalog.get("name")),
    )


def _data_collection(
    dc: dict[str, Any], workflow_id: str | None
) -> ProjectDataCollectionSummary | None:
    dc_id = _oid(dc.get("_id") or dc.get("id"))
    tag = _str(dc.get("data_collection_tag"))
    if not dc_id or not tag:
        return None
    config = dc.get("config") if isinstance(dc.get("config"), dict) else {}
    return ProjectDataCollectionSummary(
        id=dc_id,
        tag=tag,
        type=_str(config.get("type")) or "table",
        metatype=_str(config.get("metatype")),
        workflow_id=workflow_id,
        description=_str(dc.get("description") or config.get("description")),
    )


def _link(link: dict[str, Any]) -> ProjectLinkSummary | None:
    source = _oid(link.get("source_dc_id"))
    target = _oid(link.get("target_dc_id"))
    column = _str(link.get("source_column"))
    if not source or not target or not column:
        return None
    config = link.get("link_config") if isinstance(link.get("link_config"), dict) else {}
    return ProjectLinkSummary(
        id=_oid(link.get("_id") or link.get("id")) or f"{source}:{column}:{target}",
        source_dc_id=source,
        source_dc_tag=_str(link.get("source_dc_tag")),
        source_column=column,
        target_dc_id=target,
        target_dc_tag=_str(link.get("target_dc_tag")),
        target_type=_str(link.get("target_type")) or "table",
        resolver=_str(config.get("resolver")) or "direct",
        target_field=_str(config.get("target_field")),
        description=_str(link.get("description")),
        enabled=link.get("enabled", True) is not False,
    )


def _join(join: dict[str, Any]) -> ProjectJoinSummary | None:
    left = _str(join.get("left_dc") or join.get("dc1") or join.get("dc_tag1"))
    right = _str(join.get("right_dc") or join.get("dc2") or join.get("dc_tag2"))
    if not left or not right:
        return None
    on = join.get("on_columns")
    return ProjectJoinSummary(
        name=_str(join.get("name")),
        left_dc=left,
        right_dc=right,
        on_columns=[str(c) for c in on] if isinstance(on, list) else [],
        how=_str(join.get("how")),
        description=_str(join.get("description")),
    )


def _run_parameters(origin: dict[str, Any]) -> list[RunParameter]:
    out: list[RunParameter] = []
    for entry in origin.get("run_provenance") or []:
        if not isinstance(entry, dict) or not _str(entry.get("key")):
            continue
        key = str(entry["key"])
        out.append(
            RunParameter(
                source=_str(entry.get("source")) or "",
                group=_str(entry.get("group")) or "Other",
                key=key,
                value=safe_parameter_value(key, entry.get("value")),
                highlight=bool(entry.get("highlight", False)),
            )
        )
    return out


def build_project_summary(
    project_doc: dict[str, Any] | None, base_url: str | None = None
) -> ProjectSummary | None:
    """The bundle's :class:`ProjectSummary` for a project document, or None.

    ``base_url`` is the instance's declared public URL (producer A's
    ``_public_base_url``); with it the summary links the live project page.
    """
    if not project_doc:
        return None
    project_id = _oid(project_doc.get("_id") or project_doc.get("id"))
    name = _str(project_doc.get("name"))
    if not project_id or not name:
        return None

    workflows: list[ProjectWorkflowSummary] = []
    data_collections: list[ProjectDataCollectionSummary] = []
    for raw in project_doc.get("workflows") or []:
        if not isinstance(raw, dict):
            continue
        workflow = _workflow(raw)
        if workflow is not None:
            workflows.append(workflow)
        for dc in raw.get("data_collections") or []:
            if isinstance(dc, dict):
                summary = _data_collection(dc, workflow.id if workflow else None)
                if summary is not None:
                    data_collections.append(summary)
    for dc in project_doc.get("data_collections") or []:
        if isinstance(dc, dict):
            summary = _data_collection(dc, None)
            if summary is not None:
                data_collections.append(summary)

    origin = project_doc.get("template_origin")
    origin = origin if isinstance(origin, dict) else {}
    files = [
        _last_part(str(f)).removeprefix("…/")
        for f in origin.get("run_provenance_files") or []
        if _str(f)
    ]
    base = public_http_url(base_url)
    return ProjectSummary(
        id=project_id,
        name=name,
        description=_str(project_doc.get("description")),
        project_type=_str(project_doc.get("project_type")),
        registered_at=_str(project_doc.get("registration_time")),
        external_url=public_http_url(project_doc.get("data_management_platform_project_url")),
        project_url=f"{base.rstrip('/')}/projects/{project_id}" if base else None,
        template=_template(origin),
        workflows=workflows,
        data_collections=data_collections,
        links=[
            s
            for s in (_link(x) for x in project_doc.get("links") or [] if isinstance(x, dict))
            if s
        ],
        joins=[
            s
            for s in (_join(x) for x in project_doc.get("joins") or [] if isinstance(x, dict))
            if s
        ],
        run_parameters=_run_parameters(origin),
        run_parameter_files=files,
    )
