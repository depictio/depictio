#!/usr/bin/env python
"""
Quick test script for the Plotly figure customization system.

Run with: uv run python dev/test_customizations.py
"""

import pandas as pd
import plotly.express as px
import plotly.io as pio

from depictio.dash.modules.figure_component.customizations import (
    FigureCustomizations,
    AxesConfig,
    AxisConfig,
    AxisScale,
    ReferenceLineConfig,
    ReferenceLineType,
    LineStyle,
    HighlightConfig,
    HighlightCondition,
    HighlightConditionOperator,
    HighlightStyle,
    apply_customizations,
    volcano_plot_customizations,
    threshold_customizations,
)

# =============================================================================
# Test 1: Basic scatter with axis customizations and reference lines
# =============================================================================
print("=" * 60)
print("Test 1: Basic scatter with customizations")
print("=" * 60)

df1 = pd.DataFrame({
    "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "y": [10, 25, 15, 30, 20, 45, 35, 50, 40, 60],
    "category": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"],
})

fig1 = px.scatter(df1, x="x", y="y", color="category", template="plotly_white")

custom1 = FigureCustomizations(
    axes=AxesConfig(
        x=AxisConfig(title="Time (hours)", gridlines=True),
        y=AxisConfig(title="Value", range=[0, 70]),
    ),
    reference_lines=[
        ReferenceLineConfig(
            type=ReferenceLineType.HLINE,
            y=30,
            line_color="red",
            line_dash=LineStyle.DASH,
            annotation_text="Threshold",
        ),
        ReferenceLineConfig(
            type=ReferenceLineType.VLINE,
            x=5,
            line_color="blue",
            line_dash=LineStyle.DOT,
            annotation_text="Midpoint",
        ),
    ],
)

fig1 = apply_customizations(fig1, custom1, df=df1)
fig1.write_html("dev/test_output_basic.html")
print("✓ Saved: dev/test_output_basic.html")

# =============================================================================
# Test 2: Volcano plot preset
# =============================================================================
print("\n" + "=" * 60)
print("Test 2: Volcano plot with preset customizations")
print("=" * 60)

import numpy as np
np.random.seed(42)

n_genes = 200
df2 = pd.DataFrame({
    "log2FoldChange": np.random.normal(0, 2, n_genes),
    "pvalue": np.random.uniform(0.0001, 1, n_genes),
    "gene": [f"Gene_{i}" for i in range(n_genes)],
})
df2["neg_log10_pvalue"] = -np.log10(df2["pvalue"])
# Make some genes significant
significant_mask = (abs(df2["log2FoldChange"]) > 1) & (df2["pvalue"] < 0.05)
df2["significant"] = significant_mask

fig2 = px.scatter(
    df2,
    x="log2FoldChange",
    y="neg_log10_pvalue",
    hover_name="gene",
    template="plotly_white",
)

volcano_custom = volcano_plot_customizations(
    significance_threshold=0.05,
    fold_change_threshold=1.0,
)

fig2 = apply_customizations(fig2, volcano_custom, df=df2)
fig2.write_html("dev/test_output_volcano.html")
print("✓ Saved: dev/test_output_volcano.html")

# =============================================================================
# Test 3: Point highlighting
# =============================================================================
print("\n" + "=" * 60)
print("Test 3: Point highlighting")
print("=" * 60)

df3 = pd.DataFrame({
    "x": range(20),
    "y": [i ** 1.5 + np.random.normal(0, 2) for i in range(20)],
    "important": [i in [5, 10, 15] for i in range(20)],
    "label": [f"Point {i}" for i in range(20)],
})

fig3 = px.scatter(df3, x="x", y="y", template="plotly_white")

highlight_custom = FigureCustomizations(
    highlights=[
        HighlightConfig(
            conditions=[
                HighlightCondition(
                    column="important",
                    operator=HighlightConditionOperator.EQ,
                    value=True,
                ),
            ],
            style=HighlightStyle(
                marker_color="red",
                marker_size=15,
                marker_line_color="darkred",
                marker_line_width=2,
                dim_opacity=0.3,
            ),
            show_labels=True,
            label_column="label",
        ),
    ],
)

fig3 = apply_customizations(fig3, highlight_custom, df=df3)
fig3.write_html("dev/test_output_highlight.html")
print("✓ Saved: dev/test_output_highlight.html")

# =============================================================================
# Test 4: Log scale axes
# =============================================================================
print("\n" + "=" * 60)
print("Test 4: Log scale axes")
print("=" * 60)

df4 = pd.DataFrame({
    "x": [1, 10, 100, 1000, 10000],
    "y": [1, 5, 25, 125, 625],
})

fig4 = px.scatter(df4, x="x", y="y", template="plotly_white")

log_custom = FigureCustomizations(
    axes=AxesConfig(
        x=AxisConfig(scale=AxisScale.LOG, title="X (log scale)"),
        y=AxisConfig(scale=AxisScale.LOG, title="Y (log scale)"),
    ),
)

fig4 = apply_customizations(fig4, log_custom, df=df4)
fig4.write_html("dev/test_output_log.html")
print("✓ Saved: dev/test_output_log.html")

# =============================================================================
# Test 5: YAML dict input (simulating dashboard YAML)
# =============================================================================
print("\n" + "=" * 60)
print("Test 5: YAML dict input")
print("=" * 60)

yaml_customizations = {
    "axes": {
        "x": {"title": "From YAML", "gridlines": True},
        "y": {"range": [0, 100]},
    },
    "reference_lines": [
        {
            "type": "hline",
            "y": 50,
            "line_color": "green",
            "line_dash": "dash",
            "annotation_text": "50% mark",
        }
    ],
}

df5 = pd.DataFrame({"x": range(10), "y": [i * 10 for i in range(10)]})
fig5 = px.scatter(df5, x="x", y="y", template="plotly_white")

fig5 = apply_customizations(fig5, yaml_customizations, df=df5)
fig5.write_html("dev/test_output_yaml.html")
print("✓ Saved: dev/test_output_yaml.html")

# =============================================================================
# Summary
# =============================================================================
print("\n" + "=" * 60)
print("All tests completed!")
print("=" * 60)
print("\nOpen these files in your browser to see the results:")
print("  - dev/test_output_basic.html")
print("  - dev/test_output_volcano.html")
print("  - dev/test_output_highlight.html")
print("  - dev/test_output_log.html")
print("  - dev/test_output_yaml.html")
