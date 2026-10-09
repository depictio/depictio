"""Read-only catalog of the project templates shipped in ``depictio/projects/``.

``GET /projects/templates`` backs the builder UI's template picker: it lists
every template the CLI resolver can see, with the metadata the UI needs to
drive a "create project from manifest" form (variables, dashboards, and
whether the template is manifest-capable). Purely filesystem-derived — no
database access.

Parsing every shipped template takes seconds, so the catalog is kept per
process and rebuilt only when a template file changes (a walk of the bundled
projects roots, which takes milliseconds, tells).
"""

from pathlib import Path

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
