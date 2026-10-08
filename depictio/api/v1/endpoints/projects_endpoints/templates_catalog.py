"""Read-only catalog of the project templates shipped in ``depictio/projects/``.

``GET /projects/templates`` backs the builder UI's template picker: it lists
every template the CLI resolver can see, with the metadata the UI needs to
drive a "create project from manifest" form (variables, dashboards, and
whether the template is manifest-capable) or a "create project from a run
folder" one (whether it reads a run folder, and which pipeline it is for, so a
detected run can be matched to it). Purely filesystem-derived: no database
access.

Parsing every shipped template takes seconds, so the catalog is kept per
process and rebuilt only when a template file changes (a walk of the bundled
projects roots, which takes milliseconds, tells).
"""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from depictio.models.logging import logger

# The files a template is defined in, as the CLI resolver looks for them.
_TEMPLATE_FILENAMES = ("template.yaml", "project.yaml")


class TemplateVariableInfo(BaseModel):
    name: str
    description: str | None = None
    required: bool = True
    # Templates don't declare defaults today; kept for forward compatibility
    # with the picker UI's form contract.
    default: str | None = None


class TemplateInfo(BaseModel):
    template_id: str
    # The project name the template instantiates by default (config's `name`).
    name: str
    description: str | None = None
    version: str | None = None
    # True when at least one DC uses scan.mode manifest — only these templates
    # can back the "create from manifest" flow.
    manifest_capable: bool = False
    # True when the template reads a run folder: it resolves against
    # {DATA_ROOT} and at least one DC reads under it. Only these templates can
    # back POST /projects/from_run.
    run_folder_capable: bool = False
    # The id's first segment ("nf-core"), the id without its version
    # ("nf-core/ampliseq"), and the workflow engine the template declares.
    source: str | None = None
    pipeline: str | None = None
    engine: str | None = None
    variables: list[TemplateVariableInfo] = Field(default_factory=list)
    dashboards: list[str] = Field(default_factory=list)


class TemplateCatalog(BaseModel):
    templates: list[TemplateInfo] = Field(default_factory=list)


# (signature of the template files, catalog built from them).
_catalog_cache: tuple[tuple, TemplateCatalog] | None = None


def _bundled_roots() -> list[Path]:
    """The bundled ``projects/`` roots that exist, each once.

    ``_projects_roots`` lists the source-checkout and the installed layouts,
    which resolve to the same directory in either install.
    """
    from depictio.cli.cli.utils.templates import _projects_roots

    roots: list[Path] = []
    for root in _projects_roots():
        resolved = root.resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def _template_files_signature(roots: list[Path]) -> tuple:
    """``(path, mtime, size)`` of every template file under ``roots``.

    Equal signatures mean the catalog built from them is still current.
    """
    entries: list[tuple[str, int, int]] = []
    for root in roots:
        for filename in _TEMPLATE_FILENAMES:
            for path in root.rglob(filename):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


_DATA_ROOT = "{DATA_ROOT}"

# A version segment of a template id ("2.16.0", "1"), the same shape the
# resolver orders template directories by.
_VERSION_SEGMENT = re.compile(r"^\d+(\.\d+)*$")


def _run_folder_capable(template_id: str, config: dict[str, Any]) -> bool:
    """Whether the template reads a run folder: some data collection reads under
    ``{DATA_ROOT}``, through its own scan or through its workflow's locations.

    ``init/*`` templates are seeded demo projects, never created from a folder.
    A manifest data collection reads the documents its manifest lists, so it
    never counts.
    """
    if template_id.split("/", 1)[0] == "init":
        return False
    for workflow in config.get("workflows") or []:
        locations = (workflow.get("data_location") or {}).get("locations") or []
        under_root = any(_DATA_ROOT in str(location) for location in locations)
        for dc in workflow.get("data_collections") or []:
            dc_config = dc.get("config") or {}
            scan = dc_config.get("scan") or {}
            if str(scan.get("mode") or "").lower() == "manifest":
                continue
            if _DATA_ROOT in json.dumps(scan, default=str):
                return True
            # A recipe resolves its sources through the data root.
            recipe = (dc_config.get("transform") or {}).get("recipe")
            if under_root and (scan or recipe):
                return True
    return False


def _pipeline(template_id: str) -> str:
    """``template_id`` up to its version segment: ``nf-core/ampliseq/2.16.0`` is
    ``nf-core/ampliseq``. An id with no version segment is its own pipeline."""
    parts = template_id.split("/")
    for index, part in enumerate(parts):
        if index and _VERSION_SEGMENT.match(part):
            return "/".join(parts[:index])
    return template_id


def _engine(config: dict[str, Any]) -> str | None:
    """The workflow engine the template's first workflow declares, if any."""
    for workflow in config.get("workflows") or []:
        engine = workflow.get("engine")
        name = engine.get("name") if isinstance(engine, dict) else engine
        if name:
            return str(name)
    return None


def list_templates_catalog() -> TemplateCatalog:
    """Scan the shipped templates and describe each one for the picker UI.

    Templates that fail to load are skipped with a warning rather than
    failing the whole listing — one broken fixture must not blank the picker.
    Only the bundled projects roots are walked, never the repository or
    site-packages around them.
    """
    global _catalog_cache

    # CLI template machinery is imported lazily, same convention as the
    # manifest endpoints (keep API import-time cheap).
    from depictio.cli.cli.utils.templates import (
        _list_available_templates,
        _load_yaml,
        locate_template,
    )

    from .from_manifest import _manifest_dcs

    roots = _bundled_roots()
    signature = _template_files_signature(roots)
    if _catalog_cache is not None and _catalog_cache[0] == signature:
        return _catalog_cache[1]

    template_ids = sorted({tid for root in roots for tid in _list_available_templates(root)})
    catalog = TemplateCatalog()
    for template_id in template_ids:
        try:
            config = _load_yaml(str(locate_template(template_id)))
            meta = config.get("template") or {}
            catalog.templates.append(
                TemplateInfo(
                    template_id=template_id,
                    name=str(config.get("name") or template_id),
                    description=meta.get("description"),
                    version=meta.get("version"),
                    manifest_capable=bool(_manifest_dcs(config)),
                    run_folder_capable=_run_folder_capable(template_id, config),
                    source=template_id.split("/", 1)[0] or None,
                    pipeline=_pipeline(template_id),
                    engine=_engine(config),
                    variables=[
                        TemplateVariableInfo(
                            name=var.get("name", ""),
                            description=var.get("description"),
                            required=bool(var.get("required", True)),
                        )
                        for var in meta.get("variables") or []
                        if var.get("name")
                    ],
                    dashboards=[str(d) for d in meta.get("dashboards") or []],
                )
            )
        except Exception as exc:
            logger.warning(f"Skipping unreadable template '{template_id}': {exc}")
    _catalog_cache = (signature, catalog)
    return catalog
