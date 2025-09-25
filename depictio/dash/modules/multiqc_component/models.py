"""
Pydantic models for MultiQC component parameter handling and state management.

This module provides type-safe parameter definitions for MultiQC visualization
components, enabling proper state serialization and restoration.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MultiQCComponentState(BaseModel):
    """State management for MultiQC components."""

    component_id: str = Field(..., description="Unique component identifier")
    component_type: str = Field(default="multiqc", description="Component type")
    workflow_id: str = Field(..., description="Workflow ID")
    data_collection_id: str = Field(..., description="Data collection ID")

    # MultiQC-specific visualization state
    selected_module: Optional[str] = Field(None, description="Selected MultiQC module")
    selected_plot: Optional[str] = Field(None, description="Selected plot within module")
    selected_dataset: Optional[str] = Field(None, description="Selected dataset ID (if applicable)")

    # S3 data locations
    s3_locations: List[str] = Field(
        default_factory=list, description="S3 locations of MultiQC data"
    )

    # Available options (for dropdowns)
    available_modules: List[str] = Field(default_factory=list, description="Available modules")
    available_plots: Dict[str, List[str]] = Field(
        default_factory=dict, description="Available plots per module"
    )
    available_datasets: Dict[str, List[str]] = Field(
        default_factory=dict, description="Available datasets per plot"
    )

    # Metadata from MultiQC reports
    metadata: Dict[str, Any] = Field(default_factory=dict, description="MultiQC metadata")

    # UI state
    is_loaded: bool = Field(False, description="Whether data has been loaded")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")

    def get_visualization_key(self) -> str:
        """Get unique key for current visualization selection."""
        parts = [self.selected_module or "none", self.selected_plot or "none"]
        if self.selected_dataset:
            parts.append(self.selected_dataset)
        return "/".join(parts)

    def has_complete_selection(self) -> bool:
        """Check if component has enough information to render a plot."""
        return bool(self.selected_module and self.selected_plot and self.s3_locations)

    def reset_selection(self) -> None:
        """Reset visualization selection."""
        self.selected_module = None
        self.selected_plot = None
        self.selected_dataset = None

    def update_from_metadata(self, metadata: Dict[str, Any]) -> None:
        """Update state from MultiQC metadata."""
        self.metadata = metadata
        self.available_modules = metadata.get("modules", [])
        self.available_plots = metadata.get("plots", {})

        # Auto-select first module if none selected
        if not self.selected_module and self.available_modules:
            self.selected_module = self.available_modules[0]

        # Auto-select first plot if none selected and module is available
        if (
            self.selected_module
            and not self.selected_plot
            and self.selected_module in self.available_plots
        ):
            module_plots = self.available_plots[self.selected_module]
            if module_plots:
                # Handle both simple plot names and dict structures
                first_plot = module_plots[0]
                if isinstance(first_plot, dict):
                    self.selected_plot = list(first_plot.keys())[0]
                else:
                    self.selected_plot = first_plot


class MultiQCMetadata(BaseModel):
    """Metadata structure for MultiQC reports."""

    modules: List[str] = Field(default_factory=list, description="Available MultiQC modules")
    plots: Dict[str, List[Any]] = Field(
        default_factory=dict, description="Available plots per module"
    )
    samples: List[str] = Field(default_factory=list, description="Sample names in the report")
    report_id: Optional[str] = Field(None, description="MultiQC report ID")
    s3_location: Optional[str] = Field(None, description="S3 location of the report")

    def get_plot_datasets(self, module: str, plot: str) -> List[str]:
        """Get available datasets for a specific plot."""
        if module not in self.plots:
            return []

        module_plots = self.plots[module]
        for plot_item in module_plots:
            if isinstance(plot_item, dict) and plot in plot_item:
                datasets = plot_item[plot]
                return datasets if isinstance(datasets, list) else []

        return []

    def get_module_plots(self, module: str) -> List[str]:
        """Get available plots for a module."""
        if module not in self.plots:
            return []

        module_plots = self.plots[module]
        plot_names = []

        for plot_item in module_plots:
            if isinstance(plot_item, str):
                plot_names.append(plot_item)
            elif isinstance(plot_item, dict):
                plot_names.extend(plot_item.keys())

        return plot_names


class MultiQCDashboardComponent(BaseModel):
    """Complete MultiQC dashboard component configuration."""

    # Base component info
    index: str = Field(..., description="Component index/ID")
    component_type: str = Field(default="multiqc", description="Component type")

    # Data source
    workflow_id: str = Field(..., description="Workflow ID")
    data_collection_id: str = Field(..., description="Data collection ID")

    # Current visualization state
    state: MultiQCComponentState = Field(..., description="Component state")

    # Build parameters (for compatibility with existing build system)
    build_frame: bool = Field(default=True, description="Whether to build frame")
    access_token: Optional[str] = Field(None, description="Access token for API calls")
    theme: str = Field(default="light", description="UI theme")

    @classmethod
    def from_stored_metadata(cls, stored_data: Dict[str, Any]) -> "MultiQCDashboardComponent":
        """Create component from stored dashboard metadata with backward compatibility."""
        # Extract IDs, handling both string and ObjectId formats and legacy duplicate fields
        workflow_id = stored_data.get("workflow_id") or stored_data.get("wf_id")
        data_collection_id = stored_data.get("data_collection_id") or stored_data.get("dc_id")

        # Convert ObjectId to string if needed
        if isinstance(workflow_id, dict) and "$oid" in workflow_id:
            workflow_id = workflow_id["$oid"]
        if isinstance(data_collection_id, dict) and "$oid" in data_collection_id:
            data_collection_id = data_collection_id["$oid"]

        # Ensure we have string IDs
        workflow_id = str(workflow_id) if workflow_id else ""
        data_collection_id = str(data_collection_id) if data_collection_id else ""

        # Create state from stored data
        state_data = {
            "component_id": stored_data.get("index", ""),
            "workflow_id": workflow_id,
            "data_collection_id": data_collection_id,
            "selected_module": stored_data.get("selected_module"),
            "selected_plot": stored_data.get("selected_plot"),
            "selected_dataset": stored_data.get("selected_dataset"),
            "s3_locations": stored_data.get("s3_locations", []),
            "metadata": stored_data.get("metadata", {}),
        }

        return cls(
            index=stored_data.get("index", ""),
            workflow_id=workflow_id,
            data_collection_id=data_collection_id,
            state=MultiQCComponentState(**state_data),
            access_token=stored_data.get("access_token"),
            theme=stored_data.get("theme", "light"),
        )

    def to_stored_metadata(self) -> Dict[str, Any]:
        """Convert component to storable metadata format with essential info only."""
        # Only store essential visualization state - no duplication
        essential_metadata = {
            "index": self.index.replace("-tmp", "")
            if self.index
            else "unknown",  # Clean index for btn-done matching
            "component_type": self.component_type,
            "workflow_id": self.workflow_id,
            "data_collection_id": self.data_collection_id,
        }

        # Add visualization state only if user has made selections
        if self.state.selected_module:
            essential_metadata["selected_module"] = self.state.selected_module
        if self.state.selected_plot:
            essential_metadata["selected_plot"] = self.state.selected_plot
        if self.state.selected_dataset:
            essential_metadata["selected_dataset"] = self.state.selected_dataset

        # Add s3_locations only if they exist
        if self.state.s3_locations:
            essential_metadata["s3_locations"] = self.state.s3_locations

        # Only store minimal metadata - modules and plots structure for dropdown restoration
        if self.state.metadata:
            minimal_metadata = {}
            if "modules" in self.state.metadata:
                minimal_metadata["modules"] = self.state.metadata["modules"]
            if "plots" in self.state.metadata:
                minimal_metadata["plots"] = self.state.metadata["plots"]
            if minimal_metadata:
                essential_metadata["metadata"] = minimal_metadata

        return essential_metadata
