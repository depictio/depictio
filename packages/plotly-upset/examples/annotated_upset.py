"""Annotated UpSet plot example — box, violin, and bar tracks."""

import numpy as np
import pandas as pd

from plotly_upset import UpSetAnnotation, UpSetPlot

# Create synthetic data with binary sets and numeric annotations
np.random.seed(42)
n_elements = 150
df = pd.DataFrame(
    {
        "Pathway A": np.random.choice([0, 1], n_elements, p=[0.6, 0.4]),
        "Pathway B": np.random.choice([0, 1], n_elements, p=[0.5, 0.5]),
        "Pathway C": np.random.choice([0, 1], n_elements, p=[0.7, 0.3]),
        "Pathway D": np.random.choice([0, 1], n_elements, p=[0.65, 0.35]),
        "expression": np.random.randn(n_elements) * 2 + 5,
        "p_value": np.random.uniform(0, 0.1, n_elements),
        "fold_change": np.random.lognormal(0, 0.5, n_elements),
    }
)

# Define annotation tracks
anno = UpSetAnnotation(
    data=df,
    expression="expression",  # auto-detected as box
    p_value={"column": "p_value", "type": "violin", "color": "#E45756"},
    fold_change={"column": "fold_change", "type": "bar", "agg": "median", "color": "#54A24B"},
)

# Create the plot
plot = UpSetPlot(
    df,
    set_columns=["Pathway A", "Pathway B", "Pathway C", "Pathway D"],
    annotation=anno,
    title="Pathway Intersection Analysis",
    subtitle="With expression, p-value, and fold-change annotations",
    sort_by="cardinality",
    min_size=2,
)
fig = plot.to_plotly()
fig.show()
