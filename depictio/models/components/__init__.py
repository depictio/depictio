"""
Dashboard Component Models.

This module provides typed Pydantic models for all dashboard component types,
enabling YAML validation and type-safe component handling.

Architecture:
    FigureLiteComponent (user-definable, YAML-friendly)
        ↓ inherits
    FigureComponent (adds runtime/rendering fields)

Usage:
    from depictio.models.components import (
        # Lite models (for YAML/user definition)
        FigureLiteComponent,
        CardLiteComponent,
        InteractiveLiteComponent,
        TableLiteComponent,
        LiteComponent,  # Union type

        # Full models (for runtime/rendering)
        FigureComponent,
        CardComponent,
        InteractiveComponent,
        TableComponent,
        ComponentMetadata,  # Union type
    )
"""

from depictio.models.components.base import BaseComponent
from depictio.models.components.card import CardComponent
from depictio.models.components.figure import FigureComponent
from depictio.models.components.interactive import InteractiveComponent
from depictio.models.components.lite import (
    BaseLiteComponent,
    CardLiteComponent,
    FigureLiteComponent,
    InteractiveLiteComponent,
    LiteComponent,
    MapLiteComponent,
    TableLiteComponent,
)
from depictio.models.components.map import MapComponent
from depictio.models.components.table import TableComponent
from depictio.models.components.types import (
    AggregationFunction,
    ChartType,
    ColumnType,
    ComponentType,
    InteractiveType,
    MapType,
)
from depictio.models.components.union import ComponentMetadata

__all__ = [
    # Types
    "ComponentType",
    "ChartType",
    "AggregationFunction",
    "InteractiveType",
    "ColumnType",
    "MapType",
    # Lite models (for YAML/user definition)
    "BaseLiteComponent",
    "FigureLiteComponent",
    "CardLiteComponent",
    "InteractiveLiteComponent",
    "TableLiteComponent",
    "MapLiteComponent",
    "LiteComponent",
    # Full models (for runtime/rendering)
    "BaseComponent",
    "CardComponent",
    "FigureComponent",
    "InteractiveComponent",
    "TableComponent",
    "MapComponent",
    # Union
    "ComponentMetadata",
]
