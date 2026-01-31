"""
Component Metadata Union Type.

Provides a discriminated union of all component types for type-safe
component handling in dashboards.
"""

from typing import Annotated, Union

from pydantic import Discriminator

from depictio.models.components.card import CardComponent
from depictio.models.components.figure import FigureComponent
from depictio.models.components.interactive import InteractiveComponent
from depictio.models.components.table import TableComponent

# Discriminated union of all component types
# The discriminator uses "component_type" field to determine the correct model
ComponentMetadata = Annotated[
    Union[CardComponent, FigureComponent, InteractiveComponent, TableComponent],
    Discriminator("component_type"),
]
