#!/usr/bin/env python
"""Split heatmap — rows grouped by pathway, clustered within each group."""

import numpy as np
import pandas as pd

from plotly_complexheatmap import ComplexHeatmap, HeatmapAnnotation

rng = np.random.default_rng(99)
n_genes, n_samples = 45, 10

data = rng.standard_normal((n_genes, n_samples))
data[:15, :5] += 3.0
data[15:30, 5:] += 2.0

df = pd.DataFrame(
    data,
    index=[f"gene_{i:02d}" for i in range(n_genes)],
    columns=[f"sample_{j:02d}" for j in range(n_samples)],
)

# Define row groups for the split
gene_groups = (["Apoptosis"] * 15) + (["Cell_Cycle"] * 15) + (["Metabolism"] * 15)

right_ha = HeatmapAnnotation(
    pathway=gene_groups,
    which="row",
)

sample_type = (["Normal"] * 5) + (["Tumor"] * 5)
top_ha = HeatmapAnnotation(
    type=sample_type,
)

hm = ComplexHeatmap(
    df,
    cluster_rows=True,
    cluster_cols=True,
    top_annotation=top_ha,
    right_annotation=right_ha,
    split_rows_by="pathway",
    colorscale="RdBu_r",
    normalize="row",
    name="z-score",
    width=900,
    height=900,
)

fig = hm.to_plotly()
fig.show()
