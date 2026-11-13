"""A shipped template, edited in the Project Builder without being rewritten.

"Edit in the builder" used to convert a shipped template into a builder draft,
which the builder can only hold when every collection is a plain file scan:
recipes, conditionals, variables and dashboards were dropped, which kept about
one collection in twenty. This keeps the template as it ships and records only
what the reader changed:

- ``remove``: collections taken out, with every collection built from them
  (a recipe reading one through a required ``dc_ref``, a phylogeny reading its
  tip metadata, a join). Links naming them go too, and the dashboard import
  prunes the tiles that read them, as for an optional collection a run lacks;
- ``scans``: a new file (``path``) for a single-file collection, a new pattern
  (``regex``) for a folder scan;
- ``sources``: a recipe input pointed at another file or glob
  (``source_overrides``);
- ``workflows``: what a fork changes of a workflow, its repository and its
  engine's version. Its name, version and catalog stay: dashboards name the
  workflow (``workflow_tag``, derived from name and catalog) and recipes are
  looked up by the pipeline's version;
- additions: the builder's own collections and links, held to the builder's
  rules (``validate_inline_template``). A workflow named like one of the
  template's adds its collections to it; any other is a new workflow. A link
  may target a collection of the template.

The server re-reads the shipped template for every request and applies these
edits to it (:func:`compose`), so whatever was not edited stays exactly as it
ships. Edits are applied to the raw template, before variables are resolved;
a conditional rule that would repoint an edited collection is told to leave
it alone, so the reader's choice wins over the template's routing.

:func:`describe_template` is the read-only view the builder shows of the
template's collections, so it can offer these edits.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.project_builder.assemble import DATA_ROOT
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.from_template import locate_shipped_template

EDITS_INVALID = "template_edits_invalid"
MAX_EDITS = 500

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _refuse(detail: str) -> BuilderRefused:
    return BuilderRefused(422, detail, EDITS_INVALID)


class ScanEdit(BaseModel):
    """A new location for a collection read from files: one of the two."""

    model_config = ConfigDict(extra="forbid")

    # A single-file collection: the file, relative to the data root.
    path: str | None = Field(default=None, max_length=1000)
    # A folder scan: the regex each file path is matched against.
    regex: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _one(self) -> ScanEdit:
        if (self.path is None) == (self.regex is None):
            raise ValueError("A scan edit gives a path or a regex.")
        return self


class SourceEdit(BaseModel):
    """A recipe input read from another file (``path``) or files (``glob_pattern``)."""

    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, max_length=1000)
    glob_pattern: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _one(self) -> SourceEdit:
        if (self.path is None) == (self.glob_pattern is None):
            raise ValueError("A source edit gives a path or a glob_pattern.")
        return self


class WorkflowEdit(BaseModel):
    """What may change of a template's workflow: None leaves a field as
    shipped; an empty ``repository_url``, ``catalog_name`` or ``catalog_url``
    drops it.

    A new ``name`` is the workflow's name in the project; the template's
    dashboards, which name it, are imported with it (``renamed_workflows``).
    A new ``version`` is recorded as the run's; recipes made for one version
    of the pipeline are looked for under it, then among the shared ones.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=100)
    version: str | None = Field(default=None, max_length=100)
    catalog_name: str | None = Field(default=None, max_length=100)
    catalog_url: str | None = Field(default=None, max_length=500)
    repository_url: str | None = Field(default=None, max_length=500)
    engine_version: str | None = Field(default=None, max_length=100)


# A workflow name: what a dashboard's ``workflow_tag`` can name.
_WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def renamed_workflows(edits: TemplateEdits | None) -> dict[str, str]:
    """``{shipped name: new name}`` for each workflow the edits rename."""
    if edits is None:
        return {}
    return {
        old: edit.name.strip()
        for old, edit in edits.workflows.items()
        if edit.name is not None and edit.name.strip() and edit.name.strip() != old
    }


class TemplateEdits(BaseModel):
    """What the reader changed of a shipped template (see the module docstring)."""

    model_config = ConfigDict(extra="forbid")

    remove: list[str] = Field(default_factory=list, max_length=MAX_EDITS)
    scans: dict[str, ScanEdit] = Field(default_factory=dict)
    sources: dict[str, dict[str, SourceEdit]] = Field(default_factory=dict)
    workflows: dict[str, WorkflowEdit] = Field(default_factory=dict, max_length=50)
    # The builder's own collections and links, as ``POST /builder/template``
    # assembled them (an inline template); None when nothing was added.
    additions: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _bounded(self) -> TemplateEdits:
        if len(self.scans) + sum(len(s) for s in self.sources.values()) > MAX_EDITS:
            raise ValueError(f"At most {MAX_EDITS} edits.")
        return self

    def is_empty(self) -> bool:
        return not (self.remove or self.scans or self.sources or self.workflows or self.additions)


class TemplateBase(BaseModel):
    """The shipped template a builder draft is an edit of, and the edits the
    page holds (``POST /builder/template``); the draft's own collections are
    the additions."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=200)
    remove: list[str] = Field(default_factory=list, max_length=MAX_EDITS)
    scans: dict[str, ScanEdit] = Field(default_factory=dict)
    sources: dict[str, dict[str, SourceEdit]] = Field(default_factory=dict)
    workflows: dict[str, WorkflowEdit] = Field(default_factory=dict, max_length=50)

    def edits(self, additions: dict[str, Any] | None) -> TemplateEdits:
        return TemplateEdits(
            remove=self.remove,
            scans=self.scans,
            sources=self.sources,
            workflows=self.workflows,
            additions=additions,
        )


# ── Reading the template ────────────────────────────────────────────────────


def _load(template_id: str) -> tuple[dict[str, Any], Path]:
    from depictio.cli.cli.utils.templates import _load_yaml

    path = locate_shipped_template(template_id)
    try:
        return _load_yaml(str(path)), path
    except (OSError, ValueError) as exc:
        raise BuilderRefused(
            422, f"The template {template_id!r} could not be read.", "template_unreadable"
        ) from exc


def _section(raw: dict[str, Any]) -> dict[str, Any]:
    section = raw.get("template")
    return section if isinstance(section, dict) else {}


def _workflows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    workflows = raw.get("workflows")
    return [w for w in workflows if isinstance(w, dict)] if isinstance(workflows, list) else []


def _collections(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    dcs = workflow.get("data_collections")
    return [d for d in dcs if isinstance(d, dict)] if isinstance(dcs, list) else []


def _version_of(workflow: dict[str, Any]) -> str | None:
    return str(workflow["version"]) if workflow.get("version") else None


def _tag(dc: dict[str, Any]) -> str:
    return str(dc.get("data_collection_tag") or "").strip()


def _by_tag(raw: dict[str, Any]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """``tag -> (workflow, collection)`` of every collection of the template."""
    out: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for workflow in _workflows(raw):
        for dc in _collections(workflow):
            tag = _tag(dc)
            if tag and tag not in out:
                out[tag] = (workflow, dc)
    return out


def _config(dc: dict[str, Any]) -> dict[str, Any]:
    config = dc.get("config")
    return config if isinstance(config, dict) else {}


def _type_of(dc: dict[str, Any]) -> str:
    return str(_config(dc).get("type") or "").strip().lower()


def _relative(value: Any) -> str | None:
    """A template location as written, its ``{DATA_ROOT}/`` prefix left out."""
    if not isinstance(value, str):
        return None
    if value == DATA_ROOT:
        return ""
    return value[len(DATA_ROOT) + 1 :] if value.startswith(DATA_ROOT + "/") else value


def _recipe_sources(dc: dict[str, Any], version: str | None) -> list[Any]:
    """The recipe's declared inputs (``RecipeSource``), or none when it does not load."""
    recipe = (_config(dc).get("transform") or {}).get("recipe")
    if not recipe:
        return []
    try:
        from depictio.recipes import load_recipe

        return list(load_recipe(str(recipe), version).SOURCES)
    except Exception:  # noqa: BLE001 - a recipe that does not load has no editable input
        return []


def _needs(dc: dict[str, Any], version: str | None) -> list[str]:
    """The collections ``dc`` is built from and cannot do without."""
    config = _config(dc)
    needs: list[str] = []
    for source in _recipe_sources(dc, version):
        if source.dc_ref and not source.optional:
            needs.append(str(source.dc_ref).rsplit(".", 1)[-1])
    properties = config.get("dc_specific_properties") or {}
    if isinstance(properties, dict) and properties.get("metadata_dc_tag"):
        needs.append(str(properties["metadata_dc_tag"]))
    join = config.get("join") or {}
    if isinstance(join, dict):
        needs += [str(t).rsplit(".", 1)[-1] for t in join.get("with_dc") or []]
    return sorted(set(needs))


def _kind(dc: dict[str, Any]) -> str:
    config = _config(dc)
    if isinstance(config.get("transform"), dict) and config["transform"].get("recipe"):
        return "recipe"
    if config.get("join") or str(config.get("source") or "native").lower() != "native":
        return "derived"
    mode = str((config.get("scan") or {}).get("mode") or "").lower()
    return {"single": "file", "recursive": "scan"}.get(mode, "other")


def _scan_location(dc: dict[str, Any]) -> tuple[str | None, list[str]]:
    """``(location, wildcards)``: a file's path or a scan's regex, as written."""
    scan = _config(dc).get("scan")
    if not isinstance(scan, dict):
        return None, []
    parameters = scan.get("scan_parameters") or {}
    if not isinstance(parameters, dict):
        return None, []
    mode = str(scan.get("mode") or "").lower()
    if mode == "single":
        return _relative(parameters.get("filename")), []
    if mode == "recursive":
        regex_config = parameters.get("regex_config") or {}
        if not isinstance(regex_config, dict):
            return None, []
        wildcards = [
            str(w.get("name"))
            for w in regex_config.get("wildcards") or []
            if isinstance(w, dict) and w.get("name")
        ]
        pattern = regex_config.get("pattern")
        return (str(pattern) if isinstance(pattern, str) else None), wildcards
    return None, []


def _variable_names(raw: dict[str, Any]) -> set[str]:
    variables = _section(raw).get("variables")
    return {
        str(v.get("name"))
        for v in (variables if isinstance(variables, list) else [])
        if isinstance(v, dict) and v.get("name")
    }


def _describe_collection(dc: dict[str, Any], version: str | None) -> dict[str, Any]:
    kind = _kind(dc)
    location, wildcards = _scan_location(dc) if kind in ("file", "scan") else (None, [])
    variables = sorted(set(_PLACEHOLDER.findall(location or "")) - set(wildcards))
    # A location that is only a variable (`{SAMPLESHEET_FILE}`) is set through
    # the variable, not edited as a path.
    edit = None
    if kind == "file" and location is not None and not _PLACEHOLDER.fullmatch(location):
        edit = "path"
    elif kind == "scan" and location is not None:
        edit = "regex"
    sources = []
    if kind == "recipe":
        overrides = (_config(dc).get("transform") or {}).get("source_overrides") or {}
        for source in _recipe_sources(dc, version):
            override = overrides.get(source.ref) if isinstance(overrides, dict) else None
            override = override if isinstance(override, dict) else {}
            sources.append(
                {
                    "ref": source.ref,
                    "path": override.get("path", source.path)
                    if "glob_pattern" not in override
                    else None,
                    "glob_pattern": override.get("glob_pattern", source.glob_pattern)
                    if "path" not in override
                    else None,
                    "dc_ref": source.dc_ref,
                    "optional": bool(source.optional),
                    "editable": source.dc_ref is None,
                }
            )
    description = dc.get("description")
    return {
        "tag": _tag(dc),
        "type": _type_of(dc),
        "description": description if isinstance(description, str) and description else None,
        "optional": bool(dc.get("optional", False)),
        "kind": kind,
        "location": location,
        "wildcards": wildcards,
        "variables": variables,
        "edit": edit,
        "recipe": (_config(dc).get("transform") or {}).get("recipe") if kind == "recipe" else None,
        "sources": sources,
        "needs": _needs(dc, version),
    }


def describe_template(template_id: str) -> dict[str, Any]:
    """The shipped template as the builder shows it, read-only: its workflows
    and their collections (how each is read, what it is built from), its
    variables, links and dashboards."""
    raw, _path = _load(template_id)
    section = _section(raw)
    workflows = []
    for workflow in _workflows(raw):
        engine = workflow.get("engine")
        location = workflow.get("data_location") or {}
        version = _version_of(workflow)
        workflows.append(
            {
                "name": str(workflow.get("name") or "").strip(),
                "engine": (engine.get("name") if isinstance(engine, dict) else engine) or None,
                "engine_version": engine.get("version") if isinstance(engine, dict) else None,
                "version": version,
                "repository_url": workflow.get("repository_url") or None,
                "catalog": workflow.get("catalog")
                if isinstance(workflow.get("catalog"), dict)
                else None,
                "structure": location.get("structure")
                if location.get("structure") in ("flat", "sequencing-runs")
                else "flat",
                "runs_regex": location.get("runs_regex") or None,
                "collections": [_describe_collection(dc, version) for dc in _collections(workflow)],
            }
        )
    variables = section.get("variables")
    links = raw.get("links") if isinstance(raw.get("links"), list) else []
    dashboards = section.get("dashboards")
    return {
        "template_id": str(section.get("template_id") or template_id),
        "title": str(raw["name"]) if raw.get("name") else None,
        "version": str(section["version"]) if section.get("version") else None,
        "description": raw.get("description") or section.get("description") or None,
        "workflows": workflows,
        "links": [
            {"source_tag": link.get("source_dc_tag"), "target_tag": link.get("target_dc_tag")}
            for link in links
            if isinstance(link, dict)
        ],
        "dashboards": [str(d) for d in dashboards] if isinstance(dashboards, list) else [],
        "variables": [
            {
                "name": str(v.get("name")),
                "description": v.get("description") or None,
                "required": bool(v.get("required", False)),
                "default": None if v.get("default") is None else str(v.get("default")),
            }
            for v in (variables if isinstance(variables, list) else [])
            if isinstance(v, dict) and v.get("name") and v.get("name") != "DATA_ROOT"
        ],
        "conditionals": len(section.get("conditional") or []),
    }


# ── Applying the edits ──────────────────────────────────────────────────────


def removal_closure(raw: dict[str, Any], remove: list[str]) -> dict[str, str]:
    """``tag -> reason`` for the collections ``remove`` takes out, with each
    collection built from one of them, transitively."""
    by_tag = _by_tag(raw)
    unknown = sorted(set(remove) - set(by_tag))
    if unknown:
        raise _refuse(f"{', '.join(unknown)}: not a data collection of this template.")
    needs = {tag: _needs(dc, _version_of(wf)) for tag, (wf, dc) in by_tag.items()}
    removed = {tag: "removed in the Project Builder" for tag in remove}
    changed = True
    while changed:
        changed = False
        for tag, wanted in needs.items():
            if tag in removed:
                continue
            gone = sorted(set(wanted) & set(removed))
            if gone:
                removed[tag] = f"built from {', '.join(gone)}, removed in the Project Builder"
                changed = True
    return removed


def _check_location(value: str, where: str, allowed: set[str]) -> None:
    if not value.strip():
        raise _refuse(f"{where}: give a location.")
    if "://" in value or value.startswith(("/", "~")) or "\\" in value:
        raise _refuse(f"{where}: a location relative to the data root, not {value!r}.")
    if ".." in value.split("/"):
        raise _refuse(f"{where} may not contain '..'.")
    unknown = set(_PLACEHOLDER.findall(value)) - allowed
    if unknown:
        names = ", ".join("{" + n + "}" for n in sorted(unknown))
        raise _refuse(f"{where}: {names} is not a variable of this template.")


def _check_scan_regex(value: str, where: str, wildcards: list[str], allowed: set[str]) -> None:
    if not value.strip():
        raise _refuse(f"{where}: give a pattern.")
    missing = [w for w in wildcards if f"{{{w}}}" not in value]
    if missing:
        names = ", ".join("{" + n + "}" for n in missing)
        raise _refuse(f"{where}: the pattern must keep {names}, which a column is read from.")
    unknown = set(_PLACEHOLDER.findall(value)) - set(wildcards) - allowed
    if unknown:
        names = ", ".join("{" + n + "}" for n in sorted(unknown))
        raise _refuse(f"{where}: {names} is neither a wildcard nor a variable of this template.")
    try:
        re.compile(_PLACEHOLDER.sub(".+", value))
    except (re.error, OverflowError, RecursionError) as exc:
        raise _refuse(f"{where}: invalid regex ({exc}).") from exc


def _apply_scan(dc: dict[str, Any], edit: ScanEdit, tag: str, allowed: set[str]) -> None:
    kind = _kind(dc)
    location, wildcards = _scan_location(dc)
    parameters = _config(dc)["scan"].setdefault("scan_parameters", {})
    if edit.path is not None:
        if kind != "file":
            raise _refuse(f"{tag!r} is not read from one file: give it a pattern, not a path.")
        if location is not None and _PLACEHOLDER.fullmatch(location):
            raise _refuse(f"{tag!r} reads the file a template variable names: set the variable.")
        _check_location(edit.path, f"{tag!r}", allowed)
        parameters["filename"] = f"{DATA_ROOT}/{edit.path.strip().strip('/')}"
        return
    if kind != "scan":
        raise _refuse(f"{tag!r} is not a folder scan: give it a path, not a pattern.")
    assert edit.regex is not None
    _check_scan_regex(edit.regex, f"{tag!r}", wildcards, allowed)
    regex_config = parameters.setdefault("regex_config", {})
    regex_config["pattern"] = edit.regex


def _apply_sources(
    dc: dict[str, Any], edits: dict[str, SourceEdit], tag: str, version, allowed: set[str]
) -> None:
    if _kind(dc) != "recipe":
        raise _refuse(f"{tag!r} is not built by a recipe: it has no input to repoint.")
    declared = {source.ref: source for source in _recipe_sources(dc, version)}
    transform = _config(dc)["transform"]
    overrides = transform.get("source_overrides")
    if not isinstance(overrides, dict):
        overrides = transform["source_overrides"] = {}
    for ref, edit in edits.items():
        source = declared.get(ref)
        if source is None:
            raise _refuse(f"{tag!r}: its recipe has no input named {ref!r}.")
        if source.dc_ref is not None:
            raise _refuse(f"{tag!r}: the input {ref!r} is another collection, not a file.")
        value = edit.path if edit.path is not None else edit.glob_pattern
        assert value is not None
        _check_location(value, f"{tag!r} input {ref!r}", allowed)
        overrides[ref] = {"path": value} if edit.path is not None else {"glob_pattern": value}


_URL = re.compile(r"^https?://[^\s/]+\S*$")


def _apply_workflow(workflow: dict[str, Any], edit: WorkflowEdit, name: str) -> None:
    if edit.version is not None:
        version = edit.version.strip()
        if not version:
            raise _refuse(f"{name}: the version cannot be empty.")
        workflow["version"] = version
    if edit.catalog_name is not None or edit.catalog_url is not None:
        catalog = workflow.get("catalog")
        catalog = dict(catalog) if isinstance(catalog, dict) else {}
        if edit.catalog_name is not None:
            catalog["name"] = edit.catalog_name.strip() or None
        if edit.catalog_url is not None:
            url = edit.catalog_url.strip()
            if url and not _URL.match(url):
                raise _refuse(f"{name}: the catalog URL must be an http(s) URL.")
            catalog["url"] = url or None
        if catalog.get("name") or catalog.get("url"):
            catalog.setdefault("name", None)
            catalog.setdefault("url", None)
            workflow["catalog"] = catalog
        else:
            workflow.pop("catalog", None)
    if edit.repository_url is not None:
        url = edit.repository_url.strip()
        if not url:
            workflow.pop("repository_url", None)
        elif not _URL.match(url):
            raise _refuse(f"{name}: the repository must be an http(s) URL.")
        else:
            workflow["repository_url"] = url
    if edit.engine_version is not None:
        engine = workflow.get("engine")
        engine = dict(engine) if isinstance(engine, dict) else {"name": engine}
        version = edit.engine_version.strip()
        if version:
            engine["version"] = version
        else:
            engine.pop("version", None)
        workflow["engine"] = engine


def _quiet_conditionals(raw: dict[str, Any], edits: TemplateEdits, removed: set[str]) -> None:
    """Keep the template's conditional rules off what the reader set by hand,
    and off what the reader removed."""
    for rule in _section(raw).get("conditional") or []:
        if not isinstance(rule, dict):
            continue
        if isinstance(rule.get("remove_dc_tags"), list):
            rule["remove_dc_tags"] = [t for t in rule["remove_dc_tags"] if t not in removed]
        kept = []
        for override in rule.get("override_dcs") or []:
            if not isinstance(override, dict):
                kept.append(override)
                continue
            tag = override.get("data_collection_tag")
            if tag in removed:
                continue
            if tag in edits.scans:
                override.pop("scan_pattern", None)
                override.pop("scan_filename", None)
            refs = edits.sources.get(str(tag)) or {}
            if refs and isinstance(override.get("source_overrides"), dict):
                for ref in refs:
                    override["source_overrides"].pop(ref, None)
                if not override["source_overrides"]:
                    override.pop("source_overrides")
            if set(override) - {"data_collection_tag"}:
                kept.append(override)
        if "override_dcs" in rule:
            rule["override_dcs"] = kept


def _link_types(raw: dict[str, Any]) -> dict[str, str]:
    return {tag: _type_of(dc) for tag, (_wf, dc) in _by_tag(raw).items()}


def link_targets(template_id: str) -> dict[str, str]:
    """``tag -> type`` of a shipped template's collections, the ones a link
    added in the builder may target (``assemble.build_template``)."""
    raw, _path = _load(template_id)
    return _link_types(raw)


def _merge_additions(raw: dict[str, Any], additions: dict[str, Any], *, remote: bool) -> list[str]:
    """Add the builder's collections and links; returns the warnings to show."""
    from depictio.project_builder.validate import _check_links, validate_inline_template

    warnings: list[str] = []
    template_tags = set(_by_tag(raw))
    added = copy.deepcopy(additions)
    links = added.pop("links", None) or []
    workflows = [w for w in added.get("workflows") or [] if isinstance(w, dict)]
    added["workflows"] = [w for w in workflows if w.get("data_collections")]
    if added["workflows"]:
        warnings += validate_inline_template(added, remote=remote)
    for workflow in added["workflows"]:
        for dc in _collections(workflow):
            if _tag(dc) in template_tags:
                raise _refuse(
                    f"{_tag(dc)!r} is already a collection of the template: give yours another tag."
                )

    by_name = {str(w.get("name") or "").strip(): w for w in _workflows(raw)}
    for workflow in added["workflows"]:
        target = by_name.get(str(workflow.get("name") or "").strip())
        if target is None:
            raw.setdefault("workflows", []).append(workflow)
        else:
            target.setdefault("data_collections", []).extend(workflow["data_collections"])

    if links:
        _check_links(links, _link_types(raw))
        raw.setdefault("links", []).extend(links)
    return warnings


def compose(
    template_id: str, edits: TemplateEdits, *, remote: bool
) -> tuple[dict[str, Any], Path, dict[str, str], list[str]]:
    """The shipped template with ``edits`` applied: ``(raw, template_path,
    removed, warnings)``. ``removed`` maps each collection taken out to why.

    Refuses (``BuilderRefused`` 422 ``template_edits_invalid``) an edit that
    names a collection the template does not have, or does not fit it.
    """
    raw, path = _load(template_id)
    by_tag = _by_tag(raw)
    allowed = _variable_names(raw)

    removed = removal_closure(raw, edits.remove) if edits.remove else {}
    for tag in set(edits.scans) | set(edits.sources):
        if tag not in by_tag:
            raise _refuse(f"{tag}: not a data collection of this template.")
    for tag, edit in edits.scans.items():
        if tag not in removed:
            _apply_scan(by_tag[tag][1], edit, tag, allowed)
    for tag, refs in edits.sources.items():
        if tag not in removed:
            workflow, dc = by_tag[tag]
            version = _version_of(workflow)
            _apply_sources(dc, refs, tag, version, allowed)
    _quiet_conditionals(raw, edits, set(removed))
    named = {str(w.get("name") or "").strip(): w for w in _workflows(raw)}
    for name, edit in edits.workflows.items():
        if name not in named:
            raise _refuse(f"{name}: not a workflow of this template.")
        _apply_workflow(named[name], edit, name)
    renames = renamed_workflows(edits)
    for old, new in renames.items():
        if not _WORKFLOW_NAME.match(new):
            raise _refuse(
                f"{old}: '{new}' is not a workflow name (letters, digits, '.', '_' and '-')."
            )
    kept_names = [renames.get(n, n) for n in named]
    if len(set(kept_names)) != len(kept_names):
        raise _refuse("Two workflows would have the same name.")

    if removed:
        from depictio.cli.cli.utils.templates import prune_links_for_tags

        for workflow in _workflows(raw):
            workflow["data_collections"] = [
                dc for dc in _collections(workflow) if _tag(dc) not in removed
            ]
        prune_links_for_tags(raw, set(removed))
        raw["workflows"] = [w for w in _workflows(raw) if w.get("data_collections")]

    warnings: list[str] = []
    if edits.additions:
        # The builder adds to a template workflow by its shipped name: the
        # rename comes after.
        warnings += _merge_additions(raw, edits.additions, remote=remote)
    if not any(_collections(w) for w in _workflows(raw)):
        raise _refuse("Every data collection was removed: keep or add at least one.")
    for workflow in _workflows(raw):
        old = str(workflow.get("name") or "").strip()
        if old in renames:
            workflow["name"] = renames[old]
    return raw, path, removed, warnings


COMPOSED_YAML_HEADER = """\
# {template_id}, edited in the Depictio Project Builder: the shipped template
# with the collections removed, repointed and added there. Its dashboards and
# recipes are the shipped template's, read from the Depictio that serves it.
"""


def composed_yaml(raw: dict[str, Any], template_id: str) -> str:
    import yaml

    return COMPOSED_YAML_HEADER.format(template_id=template_id) + yaml.safe_dump(
        raw, sort_keys=False, allow_unicode=True, width=100
    )
