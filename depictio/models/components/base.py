"""
Base Component Model.

Provides the common fields shared by all dashboard component types.
Inherits from BaseLiteComponent and adds runtime fields.
"""

import uuid
from typing import Any

from pydantic import Field

from depictio.models.components.lite import BaseLiteComponent


class BaseComponent(BaseLiteComponent):
    """Base class for all dashboard components.

    Extends BaseLiteComponent with runtime fields needed for rendering.
    """

    # Override index to auto-generate UUID if not provided
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override tags to be optional (resolved from IDs at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Resolved data source IDs (populated at runtime)
    wf_id: str | None = None
    dc_id: str | None = None
    project_id: str | None = None

    # Full data collection config (populated at runtime)
    dc_config: dict[str, Any] = Field(default_factory=dict)

    # Column specifications cache
    cols_json: dict[str, Any] = Field(default_factory=dict)

    # Parent reference (for nested components)
    parent_index: str | None = None
