"""Text Component Model — section heading + optional body.

Extends `TextLiteComponent` with the runtime fields that the dashboard
loader and discriminated union expect (uuid `index`, optional
workflow/data-collection placeholders). Text tiles never bind to data, so
the runtime fields are placeholders kept for shape parity with other
components.
"""

import uuid

from pydantic import Field

from depictio.models.components.lite import TextLiteComponent


class TextComponent(TextLiteComponent):
    """Text tile component (narrative heading + paragraph)."""

    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    parent_index: str | None = None
