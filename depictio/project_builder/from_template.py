"""A template shipped with Depictio, found by id, and nothing else on disk.

The id comes from a browser ("Edit in the builder"), so only ids that resolve
inside the shipped projects folders are accepted: neither a path nor a dot
segment may reach a file outside them. What the builder does with the template
is :mod:`depictio.project_builder.overlay`: it is shown read-only and edited
as a list of changes, never converted.
"""

from __future__ import annotations

from pathlib import Path

from depictio.project_builder.errors import BuilderRefused


def _shipped_roots() -> list[Path]:
    from depictio.cli.cli.utils.templates import _projects_roots

    return [root.resolve() for root in _projects_roots()]


def locate_shipped_template(template_id: str) -> Path:
    """The ``template.yaml`` of a template shipped with Depictio (``latest`` resolves)."""
    from depictio.cli.cli.utils.templates import TemplateNotFoundError, locate_template

    cleaned = (template_id or "").strip()
    segments = cleaned.split("/")
    if (
        not cleaned
        or len(cleaned) > 200
        or cleaned.startswith(("/", "~"))
        or "\\" in cleaned
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        raise BuilderRefused(400, f"{template_id!r} is not a template id.", "template_invalid")
    try:
        located = locate_template(cleaned)
    except (TemplateNotFoundError, FileNotFoundError) as exc:
        raise BuilderRefused(
            404, f"No template {cleaned!r} is shipped with this Depictio.", "template_not_found"
        ) from exc
    resolved = located.resolve()
    if not any(resolved.is_relative_to(root) for root in _shipped_roots()):
        # Only a CLI-context path lookup gets here; the builder serves shipped templates only.
        raise BuilderRefused(
            404, f"No template {cleaned!r} is shipped with this Depictio.", "template_not_found"
        )
    return resolved
