#!/usr/bin/env python
"""Heatmap with categorical and numeric annotation tracks."""

import numpy as np
import pandas as pd

from plotly_complexheatmap import ComplexHeatmap, HeatmapAnnotation

rng = np.random.default_rng(123)
n_genes, n_samples = 40, 15

data = rng.standard_normal((n_genes, n_samples))
data[:15, :5] += 2.5
data[15:30, 5:10] += 2.0

df = pd.DataFrame(
    data,
    index=[f"gene_{i:02d}" for i in range(n_genes)],
    columns=[f"sample_{j:02d}" for j in range(n_samples)],
)

# Column annotations: sample group + a numeric quality metric
sample_group = (["Control"] * 5) + (["Treatment_A"] * 5) + (["Treatment_B"] * 5)
quality_score = rng.uniform(0.7, 1.0, size=n_samples)

top_ha = HeatmapAnnotation(
    group=sample_group,
    quality=quality_score,
)

# Row annotations: gene pathway category
pathways = (["Metabolism"] * 15) + (["Signaling"] * 15) + (["Other"] * 10)
right_ha = HeatmapAnnotation(
    pathway=pathways,
    which="row",
)

hm = ComplexHeatmap(
    df,
    cluster_rows=True,
    cluster_cols=True,
    top_annotation=top_ha,
    right_annotation=right_ha,
    colorscale="Viridis",
    normalize="row",
    name="expression",
    width=1000,
    height=800,
)

fig = hm.to_plotly()
fig.show()
