"""
Pydantic models for card component configuration.

This module defines the data models used for configuring card components
in the add component stepper workflow.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AggregationType(str, Enum):
    """Available aggregation types for card components."""

    # Numeric aggregations
    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    RANGE = "range"
    VARIANCE = "variance"
    STD_DEV = "std_dev"
    SKEWNESS = "skewness"
    KURTOSIS = "kurtosis"
    PERCENTILE = "percentile"

    # Categorical aggregations
    MODE = "mode"
    NUNIQUE = "nunique"


class CardColorOption(str, Enum):
    """Available color options for card components."""

    BLUE = "blue"
    GREEN = "green"
    RED = "red"
    ORANGE = "orange"
    PURPLE = "purple"
    TEAL = "teal"
    GRAY = "gray"
    YELLOW = "yellow"
    PINK = "pink"
    VIOLET = "violet"


class CardIconOption(str, Enum):
    """Available icon options for card components."""

    # Numbers and metrics
    NUMBER = "formkit:number"
    CHART_BAR = "mdi:chart-bar"
    CHART_LINE = "mdi:chart-line"
    CHART_PIE = "mdi:chart-pie"

    # Business metrics
    CURRENCY = "mdi:currency-usd"
    USERS = "mdi:account-group"
    SESSIONS = "mdi:monitor-eye"
    TRENDING_UP = "mdi:trending-up"
    TRENDING_DOWN = "mdi:trending-down"

    # Generic
    INFO = "mdi:information"
    STAR = "mdi:star"
    HEART = "mdi:heart"
    LIGHTNING = "mdi:lightning-bolt"
    TARGET = "mdi:target"


class FontSizeOption(str, Enum):
    """Available font size options for card components."""

    SMALL = "sm"
    MEDIUM = "md"
    LARGE = "lg"
    EXTRA_LARGE = "xl"


class CardComponentConfig(BaseModel):
    """
    Configuration model for card components.

    This model defines all configurable properties for creating
    a card component through the stepper interface.
    """

    # Data source configuration
    workflow_id: str = Field(..., description="ID of the selected workflow")
    data_collection_id: str = Field(..., description="ID of the selected data collection")

    # Column and aggregation settings
    column_name: str = Field(..., description="Name of the column to aggregate")
    aggregation_type: AggregationType = Field(..., description="Type of aggregation to perform")

    # Card presentation settings
    title: str = Field(..., min_length=1, max_length=100, description="Display title for the card")

    # Visual customization
    color: CardColorOption = Field(
        default=CardColorOption.BLUE, description="Color theme for the card"
    )
    icon: CardIconOption = Field(
        default=CardIconOption.NUMBER, description="Icon to display on the card"
    )
    font_size: FontSizeOption = Field(
        default=FontSizeOption.LARGE, description="Font size for the card value"
    )

    # Optional metadata
    description: Optional[str] = Field(
        None, max_length=500, description="Optional description for the card"
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v):
        """Ensure title is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Title cannot be empty or only whitespace")
        return v.strip()

    @field_validator("column_name")
    @classmethod
    def column_name_must_be_valid(cls, v):
        """Ensure column name is valid."""
        if not v or not v.strip():
            raise ValueError("Column name cannot be empty")
        return v.strip()

    def to_build_card_kwargs(self, index: str, access_token: str) -> dict:
        """
        Convert configuration to kwargs for build_card function.

        Args:
            index: Component index for the card
            access_token: User access token for API calls

        Returns:
            Dictionary of kwargs for build_card function
        """
        return {
            "index": index,
            "title": self.title,
            "wf_id": self.workflow_id,
            "dc_id": self.data_collection_id,
            "column_name": self.column_name,
            "aggregation": self.aggregation_type.value,
            "color": self.color.value,
            "access_token": access_token,
            "build_frame": True,
            "refresh": True,
        }

    class Config:
        """Pydantic model configuration."""

        use_enum_values = True
        validate_assignment = True
        extra = "forbid"


class ComponentTypeSelection(BaseModel):
    """Model for component type selection in stepper."""

    component_type: str = Field(..., description="Type of component to create")

    @field_validator("component_type")
    @classmethod
    def valid_component_type(cls, v):
        """Ensure component type is valid."""
        valid_types = ["Card", "Figure", "Table", "Interactive", "Text"]
        if v not in valid_types:
            raise ValueError(f"Component type must be one of: {valid_types}")
        return v


class StepperState(BaseModel):
    """Model for tracking stepper state."""

    current_step: int = Field(default=0, ge=0, le=2, description="Current step index (0-2)")
    component_type: Optional[str] = Field(None, description="Selected component type")
    card_config: Optional[CardComponentConfig] = Field(
        None, description="Card configuration if applicable"
    )

    def is_step_complete(self, step: int) -> bool:
        """Check if a specific step is complete."""
        if step == 0:  # Component type selection
            return self.component_type is not None
        elif step == 1:  # Component configuration
            if self.component_type == "Card":
                return self.card_config is not None
            # Add other component types here
            return False
        elif step == 2:  # Final confirmation
            return self.is_step_complete(0) and self.is_step_complete(1)
        return False

    def can_proceed_to_step(self, step: int) -> bool:
        """Check if user can proceed to a specific step."""
        if step <= self.current_step:
            return True
        return self.is_step_complete(step - 1)
