"""
Preset customization configurations for common use cases.

This module provides factory functions for creating common
customization configurations, similar to Vizro's approach of
providing sensible defaults with minimal configuration.
"""

from typing import Any, Dict, List, Optional, Union

from .models import (
    AnnotationPosition,
    AxesConfig,
    AxisConfig,
    AxisScale,
    FigureCustomizations,
    HighlightCondition,
    HighlightConditionOperator,
    HighlightConfig,
    HighlightStyle,
    LineStyle,
    ReferenceLineConfig,
    ReferenceLineType,
    ShapeConfig,
)

# =============================================================================
# Volcano Plot Presets
# =============================================================================


def volcano_plot_customizations(
    significance_threshold: float = 0.05,
    fold_change_threshold: float = 1.0,
    significance_column: str = "pvalue",
    fold_change_column: str = "log2FoldChange",
    highlight_color: str = "red",
    dim_color: str = "gray",
) -> FigureCustomizations:
    """
    Create customizations for a volcano plot.

    Adds:
    - Horizontal line at significance threshold
    - Vertical lines at fold change thresholds
    - Point highlighting for significant genes

    Args:
        significance_threshold: P-value threshold (horizontal line)
        fold_change_threshold: Log2 fold change threshold (vertical lines)
        significance_column: Column name for p-values
        fold_change_column: Column name for fold changes
        highlight_color: Color for significant points
        dim_color: Color for non-significant points

    Returns:
        FigureCustomizations configured for a volcano plot
    """
    # Convert p-value to -log10
    neg_log_threshold = -1 * (
        __import__("math").log10(significance_threshold) if significance_threshold > 0 else 0
    )

    return FigureCustomizations(
        axes=AxesConfig(
            x=AxisConfig(
                title="Log2 Fold Change",
                zeroline=True,
                zerolinecolor="rgba(0,0,0,0.3)",
            ),
            y=AxisConfig(
                title=f"-Log10({significance_column})",
            ),
        ),
        reference_lines=[
            # Significance threshold
            ReferenceLineConfig(
                type=ReferenceLineType.HLINE,
                y=neg_log_threshold,
                line_color="red",
                line_dash=LineStyle.DASH,
                line_width=1,
                opacity=0.7,
                annotation_text=f"p = {significance_threshold}",
                annotation_position=AnnotationPosition.TOP_RIGHT,
            ),
            # Left fold change threshold
            ReferenceLineConfig(
                type=ReferenceLineType.VLINE,
                x=-fold_change_threshold,
                line_color="blue",
                line_dash=LineStyle.DASH,
                line_width=1,
                opacity=0.7,
            ),
            # Right fold change threshold
            ReferenceLineConfig(
                type=ReferenceLineType.VLINE,
                x=fold_change_threshold,
                line_color="blue",
                line_dash=LineStyle.DASH,
                line_width=1,
                opacity=0.7,
            ),
        ],
        highlights=[
            # Highlight significantly upregulated
            HighlightConfig(
                conditions=[
                    HighlightCondition(
                        column=significance_column,
                        operator=HighlightConditionOperator.LT,
                        value=significance_threshold,
                    ),
                    HighlightCondition(
                        column=fold_change_column,
                        operator=HighlightConditionOperator.GT,
                        value=fold_change_threshold,
                    ),
                ],
                logic="and",
                style=HighlightStyle(
                    marker_color="red",
                    marker_size=8,
                    dim_opacity=0.3,
                    dim_color=dim_color,
                ),
                label="Upregulated",
            ),
            # Highlight significantly downregulated
            HighlightConfig(
                conditions=[
                    HighlightCondition(
                        column=significance_column,
                        operator=HighlightConditionOperator.LT,
                        value=significance_threshold,
                    ),
                    HighlightCondition(
                        column=fold_change_column,
                        operator=HighlightConditionOperator.LT,
                        value=-fold_change_threshold,
                    ),
                ],
                logic="and",
                style=HighlightStyle(
                    marker_color="blue",
                    marker_size=8,
                    dim_opacity=0.3,
                    dim_color=dim_color,
                ),
                label="Downregulated",
            ),
        ],
    )


# =============================================================================
# UMAP/Dimensionality Reduction Presets
# =============================================================================


def umap_highlight_customizations(
    highlight_column: str,
    highlight_values: List[Any],
    highlight_color: str = "red",
    highlight_size: float = 10,
    dim_opacity: float = 0.2,
    show_labels: bool = False,
    label_column: Optional[str] = None,
) -> FigureCustomizations:
    """
    Create customizations for highlighting points in UMAP/t-SNE plots.

    Args:
        highlight_column: Column to use for matching points
        highlight_values: List of values to highlight
        highlight_color: Color for highlighted points
        highlight_size: Size for highlighted points
        dim_opacity: Opacity for non-highlighted points
        show_labels: Whether to show labels on highlighted points
        label_column: Column to use for labels (defaults to highlight_column)

    Returns:
        FigureCustomizations configured for UMAP highlighting
    """
    return FigureCustomizations(
        axes=AxesConfig(
            x=AxisConfig(title="UMAP 1"),
            y=AxisConfig(title="UMAP 2"),
        ),
        highlights=[
            HighlightConfig(
                conditions=[
                    HighlightCondition(
                        column=highlight_column,
                        operator=HighlightConditionOperator.IN,
                        value=highlight_values,
                    ),
                ],
                style=HighlightStyle(
                    marker_color=highlight_color,
                    marker_size=highlight_size,
                    dim_opacity=dim_opacity,
                    marker_line_color="white",
                    marker_line_width=1,
                ),
                show_labels=show_labels,
                label_column=label_column or highlight_column,
            ),
        ],
    )


def umap_cluster_customizations(
    cluster_column: str = "cluster",
    show_centroids: bool = False,
) -> FigureCustomizations:
    """
    Create customizations for UMAP cluster visualization.

    Args:
        cluster_column: Column containing cluster assignments
        show_centroids: Whether to show cluster centroids (not yet implemented)

    Returns:
        FigureCustomizations for cluster visualization
    """
    return FigureCustomizations(
        axes=AxesConfig(
            x=AxisConfig(
                title="UMAP 1",
                showspikes=True,
                spikecolor="rgba(0,0,0,0.3)",
            ),
            y=AxisConfig(
                title="UMAP 2",
                showspikes=True,
                spikecolor="rgba(0,0,0,0.3)",
            ),
        ),
        hover={"mode": "closest"},
    )


# =============================================================================
# Statistical Plot Presets
# =============================================================================


def regression_plot_customizations(
    show_confidence_band: bool = True,
    show_prediction_band: bool = False,
    show_diagonal: bool = True,
    x_equals_y_line: bool = True,
) -> FigureCustomizations:
    """
    Create customizations for regression/correlation plots.

    Args:
        show_confidence_band: Show confidence interval band
        show_prediction_band: Show prediction interval band
        show_diagonal: Show y=x diagonal line
        x_equals_y_line: Same as show_diagonal (alias)

    Returns:
        FigureCustomizations for regression plots
    """
    ref_lines = []

    if show_diagonal or x_equals_y_line:
        ref_lines.append(
            ReferenceLineConfig(
                type=ReferenceLineType.DIAGONAL,
                line_color="gray",
                line_dash=LineStyle.DASH,
                line_width=1,
                opacity=0.5,
                annotation_text="y = x",
            )
        )

    return FigureCustomizations(
        reference_lines=ref_lines if ref_lines else None,
        hover={"mode": "closest"},
    )


def qq_plot_customizations() -> FigureCustomizations:
    """
    Create customizations for Q-Q plots.

    Returns:
        FigureCustomizations for Q-Q plots
    """
    return FigureCustomizations(
        axes=AxesConfig(
            x=AxisConfig(title="Theoretical Quantiles"),
            y=AxisConfig(title="Sample Quantiles"),
        ),
        reference_lines=[
            ReferenceLineConfig(
                type=ReferenceLineType.DIAGONAL,
                line_color="red",
                line_dash=LineStyle.SOLID,
                line_width=1,
                opacity=0.7,
            ),
        ],
    )


# =============================================================================
# Time Series Presets
# =============================================================================


def time_series_customizations(
    show_zero_line: bool = True,
    highlight_regions: Optional[List[Dict[str, Any]]] = None,
) -> FigureCustomizations:
    """
    Create customizations for time series plots.

    Args:
        show_zero_line: Show horizontal line at y=0
        highlight_regions: List of dicts with x0, x1, color for regions

    Returns:
        FigureCustomizations for time series
    """
    ref_lines = []
    shapes = []

    if show_zero_line:
        ref_lines.append(
            ReferenceLineConfig(
                type=ReferenceLineType.HLINE,
                y=0,
                line_color="gray",
                line_dash=LineStyle.SOLID,
                line_width=1,
                opacity=0.5,
            )
        )

    if highlight_regions:
        for region in highlight_regions:
            shapes.append(
                ShapeConfig(
                    type="rect",
                    x0=region.get("x0"),
                    x1=region.get("x1"),
                    y0=0,
                    y1=1,
                    yref="paper",
                    fillcolor=region.get("color", "rgba(255,0,0,0.1)"),
                    line_color="transparent",
                    opacity=region.get("opacity", 0.3),
                    layer="below",
                )
            )

    return FigureCustomizations(
        reference_lines=ref_lines if ref_lines else None,
        shapes=shapes if shapes else None,
        hover={"mode": "x unified"},
    )


# =============================================================================
# Threshold-based Presets
# =============================================================================


def threshold_customizations(
    threshold_value: Union[float, int],
    axis: str = "y",
    threshold_color: str = "red",
    threshold_label: Optional[str] = None,
    highlight_above: bool = False,
    highlight_below: bool = False,
    data_column: Optional[str] = None,
) -> FigureCustomizations:
    """
    Create customizations for threshold visualization.

    Args:
        threshold_value: The threshold value
        axis: Which axis the threshold applies to ('x' or 'y')
        threshold_color: Color for the threshold line
        threshold_label: Label for the threshold line
        highlight_above: Highlight points above threshold
        highlight_below: Highlight points below threshold
        data_column: Column to use for highlighting

    Returns:
        FigureCustomizations with threshold line and optional highlighting
    """
    ref_lines = []
    highlights = []

    if axis == "y":
        ref_lines.append(
            ReferenceLineConfig(
                type=ReferenceLineType.HLINE,
                y=threshold_value,
                line_color=threshold_color,
                line_dash=LineStyle.DASH,
                line_width=2,
                annotation_text=threshold_label or f"Threshold: {threshold_value}",
            )
        )
    else:
        ref_lines.append(
            ReferenceLineConfig(
                type=ReferenceLineType.VLINE,
                x=threshold_value,
                line_color=threshold_color,
                line_dash=LineStyle.DASH,
                line_width=2,
                annotation_text=threshold_label or f"Threshold: {threshold_value}",
            )
        )

    if (highlight_above or highlight_below) and data_column:
        if highlight_above:
            highlights.append(
                HighlightConfig(
                    conditions=[
                        HighlightCondition(
                            column=data_column,
                            operator=HighlightConditionOperator.GT,
                            value=threshold_value,
                        ),
                    ],
                    style=HighlightStyle(
                        marker_color="red",
                        marker_size=10,
                        dim_opacity=0.3,
                    ),
                    label="Above threshold",
                )
            )
        if highlight_below:
            highlights.append(
                HighlightConfig(
                    conditions=[
                        HighlightCondition(
                            column=data_column,
                            operator=HighlightConditionOperator.LT,
                            value=threshold_value,
                        ),
                    ],
                    style=HighlightStyle(
                        marker_color="blue",
                        marker_size=10,
                        dim_opacity=0.3,
                    ),
                    label="Below threshold",
                )
            )

    return FigureCustomizations(
        reference_lines=ref_lines,
        highlights=highlights if highlights else None,
    )


# =============================================================================
# Axis Scale Presets
# =============================================================================


def log_scale_customizations(
    x_log: bool = False,
    y_log: bool = False,
    x_title: Optional[str] = None,
    y_title: Optional[str] = None,
) -> FigureCustomizations:
    """
    Create customizations for log-scale axes.

    Args:
        x_log: Use log scale for x-axis
        y_log: Use log scale for y-axis
        x_title: Custom title for x-axis
        y_title: Custom title for y-axis

    Returns:
        FigureCustomizations with log scale settings
    """
    x_config = None
    y_config = None

    if x_log:
        x_config = AxisConfig(
            scale=AxisScale.LOG,
            title=x_title,
        )

    if y_log:
        y_config = AxisConfig(
            scale=AxisScale.LOG,
            title=y_title,
        )

    return FigureCustomizations(
        axes=AxesConfig(x=x_config, y=y_config) if (x_config or y_config) else None,
    )


# =============================================================================
# Combining Presets
# =============================================================================


def merge_customizations(
    *customizations: FigureCustomizations,
) -> FigureCustomizations:
    """
    Merge multiple FigureCustomizations into one.

    Later customizations override earlier ones for single-value fields.
    List fields (like reference_lines, highlights) are concatenated.

    Args:
        *customizations: Variable number of FigureCustomizations to merge

    Returns:
        Merged FigureCustomizations
    """
    result_dict: Dict[str, Any] = {}

    for custom in customizations:
        if not custom.has_customizations():
            continue

        custom_dict = custom.model_dump(exclude_none=True)

        for key, value in custom_dict.items():
            if key in result_dict and isinstance(value, list):
                # Concatenate lists
                result_dict[key] = result_dict[key] + value
            elif key in result_dict and isinstance(value, dict):
                # Deep merge dicts
                result_dict[key] = _deep_merge_dicts(result_dict[key], value)
            else:
                result_dict[key] = value

    return FigureCustomizations.model_validate(result_dict)


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result
