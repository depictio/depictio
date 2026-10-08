"""Highlight Component Model -- a figure from another tab, shown again.

Extends `HighlightLiteComponent` with the runtime fields the dashboard loader
and the discriminated union expect. A highlight binds to no data of its own
(the figure it shows does, on its own tab), so the workflow and data
collection fields are placeholders, as on a text tile.
"""

import uuid

from pydantic import Field

from depictio.models.components.lite import HighlightLiteComponent


class HighlightComponent(HighlightLiteComponent):
    """Highlight tile: another tab's figure, restyled for this one."""

    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    parent_index: str | None = None
