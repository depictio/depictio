"""Read-only catalog of the project templates shipped in ``depictio/projects/``.

``GET /projects/templates`` backs the builder UI's template picker: it lists
every template the CLI resolver can see, with the metadata the UI needs to
drive a "create project from manifest" form (variables, dashboards, and
whether the template is manifest-capable). Purely filesystem-derived — no
database access.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from depictio.models.logging import logger


class TemplateVariableInfo(BaseModel):
    name: str
    description: str | None = None
    required: bool = True


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


def list_templates_catalog() -> TemplateCatalog:
    """Scan the shipped templates and describe each one for the picker UI.

    Templates that fail to load are skipped with a warning rather than
    failing the whole listing — one broken fixture must not blank the picker.
    """
    # CLI template machinery is imported lazily, same convention as the
    # manifest endpoints (keep API import-time cheap).
    from depictio.cli.cli.utils.templates import (
        _list_available_templates,
        _load_yaml,
        locate_template,
    )

    from .from_manifest import _manifest_dcs

    package_root = Path(__file__).resolve().parents[5]  # …/projects_endpoints -> repo root
    catalog = TemplateCatalog()
    for template_id in _list_available_templates(package_root):
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
    return catalog
