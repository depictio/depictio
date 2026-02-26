#!/usr/bin/env python
"""Comprehensive Depictio integration showcase.

Generates synthetic gene-expression data with rich annotations and produces
four heatmaps of increasing complexity:

1. **Minimal** — from_dataframe with auto-detected annotations
2. **Multi-layer annotations** — categorical + bar + scatter tracks on both axes
3. **Split heatmap** — row groups with independent clustering
4. **Full feature** — all track types including box and violin

Each example mirrors a realistic Depictio YAML configuration; the
corresponding dict_kwargs are printed so you can copy them into a dashboard
YAML file.

Usage::

    python examples/depictio_showcase.py          # opens all 4 in browser
    python examples/depictio_showcase.py --save   # writes PNG + HTML
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from plotly_complexheatmap import ComplexHeatmap, HeatmapAnnotation

# ---------------------------------------------------------------------------
# Reproducible synthetic data
# ---------------------------------------------------------------------------

rng = np.random.default_rng(42)

N_GENES = 60
N_SAMPLES = 20

# Expression matrix with embedded clusters
expression = rng.standard_normal((N_GENES, N_SAMPLES))
expression[:20, :7] += 3.0  # Cluster 1: first 20 genes upregulated in samples 0-6
expression[20:40, 7:14] += 2.5  # Cluster 2: genes 20-39 up in samples 7-13
expression[40:, 14:] -= 1.5  # Cluster 3: genes 40-59 down in samples 14-19

gene_names = [f"gene_{i:03d}" for i in range(N_GENES)]
sample_names = [f"sample_{j:02d}" for j in range(N_SAMPLES)]

# -- Row metadata (per gene) -----------------------------------------------
pathways = ["Apoptosis"] * 15 + ["Cell_Cycle"] * 15 + ["Metabolism"] * 10 + ["Signaling"] * 10 + ["Immune"] * 10
gene_length_kb = rng.uniform(0.5, 15.0, size=N_GENES)
gc_content = rng.uniform(0.35, 0.65, size=N_GENES)
mutation_score = rng.exponential(scale=2.0, size=N_GENES)

# -- Column metadata (per sample) ------------------------------------------
sample_group = (["Control"] * 7) + (["Treatment_A"] * 7) + (["Treatment_B"] * 6)
batch = (["Batch_1"] * 5) + (["Batch_2"] * 5) + (["Batch_3"] * 5) + (["Batch_1"] * 5)
quality_score = rng.uniform(0.7, 1.0, size=N_SAMPLES)
library_size = rng.uniform(20, 80, size=N_SAMPLES)  # millions of reads

# Build the main DataFrame (as Depictio would load from a data collection)
# "gene" is a regular column, not the index — matches how Depictio loads CSV/Delta data
df = pd.DataFrame(expression, columns=sample_names)
df.insert(0, "gene", gene_names)
df.insert(1, "pathway", pathways)
df.insert(2, "gene_length_kb", gene_length_kb)
df.insert(3, "gc_content", gc_content)
df.insert(4, "mutation_score", mutation_score)


def save_test_csv(path: Path) -> None:
    """Write the DataFrame to CSV for use as Depictio test data."""
    df.to_csv(path, index=False)
    print(f"  Saved test CSV: {path} ({df.shape[0]} genes × {df.shape[1]} columns)")


# ---------------------------------------------------------------------------
# Helper to print dict_kwargs as Depictio YAML
# ---------------------------------------------------------------------------


def print_yaml_config(title: str, kwargs: dict) -> None:
    """Print a dict_kwargs as a YAML-ready config block."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")
    print("dict_kwargs:")
    for k, v in kwargs.items():
        if isinstance(v, (dict, list)):
            print(f"  {k}: '{json.dumps(v)}'")
        elif isinstance(v, bool):
            print(f"  {k}: {str(v).lower()}")
        else:
            print(f"  {k}: {v}")
    print()


# ===========================================================================
# Example 1: Minimal — auto-detected annotations from DataFrame columns
# ===========================================================================


def example_minimal() -> tuple:
    kwargs = {
        "index_column": "gene",
        "row_annotations": ["pathway"],
        "cluster_rows": True,
        "cluster_cols": True,
        "normalize": "row",
        "name": "z-score",
        "width": 900,
        "height": 700,
    }
    print_yaml_config("Example 1: Minimal Heatmap", kwargs)

    # Using from_dataframe (same path as Depictio)
    hm = ComplexHeatmap.from_dataframe(
        df,
        index_column="gene",
        row_annotations=["pathway"],
        cluster_rows=True,
        cluster_cols=True,
        normalize="row",
        name="z-score",
        width=900,
        height=700,
    )
    return hm.to_plotly(), kwargs


# ===========================================================================
# Example 2: Multi-layer annotations — bar + scatter + categorical
# ===========================================================================


def example_multi_annotation() -> tuple:
    kwargs = {
        "index_column": "gene",
        "row_annotations": {
            "pathway": {},
            "gene_length_kb": {"type": "bar", "color": "#4C78A8"},
            "gc_content": {"type": "scatter", "color": "#E45756"},
            "mutation_score": {"type": "bar", "color": "#72B7B2"},
        },
        "cluster_rows": True,
        "cluster_cols": True,
        "normalize": "row",
        "colorscale": "Viridis",
        "name": "expression",
        "width": 1100,
        "height": 800,
    }
    print_yaml_config("Example 2: Multi-Layer Annotations", kwargs)

    # Column annotations (not in the DataFrame — external metadata)
    top_ha = HeatmapAnnotation(
        group=sample_group,
        batch=batch,
        quality=quality_score,
        library_size={"values": library_size.tolist(), "type": "bar", "color": "#B07AA1"},
    )

    hm = ComplexHeatmap.from_dataframe(
        df,
        index_column="gene",
        row_annotations={
            "pathway": {},
            "gene_length_kb": {"type": "bar", "color": "#4C78A8"},
            "gc_content": {"type": "scatter", "color": "#E45756"},
            "mutation_score": {"type": "bar", "color": "#72B7B2"},
        },
        cluster_rows=True,
        cluster_cols=True,
        normalize="row",
        colorscale="Viridis",
        name="expression",
        width=1100,
        height=800,
        top_annotation=top_ha,
    )
    return hm.to_plotly(), kwargs


# ===========================================================================
# Example 3: Split heatmap — rows grouped by pathway
# ===========================================================================


def example_split() -> tuple:
    kwargs = {
        "index_column": "gene",
        "value_columns": sample_names,
        "row_annotations": ["pathway", "mutation_score"],
        "split_rows_by": "pathway",
        "cluster_rows": True,
        "cluster_cols": True,
        "normalize": "row",
        "colorscale": "RdBu_r",
        "name": "z-score",
        "width": 1000,
        "height": 900,
    }
    print_yaml_config("Example 3: Split Heatmap by Pathway", kwargs)

    top_ha = HeatmapAnnotation(group=sample_group)

    hm = ComplexHeatmap.from_dataframe(
        df,
        index_column="gene",
        value_columns=sample_names,
        row_annotations=["pathway", "mutation_score"],
        split_rows_by="pathway",
        cluster_rows=True,
        cluster_cols=True,
        normalize="row",
        colorscale="RdBu_r",
        name="z-score",
        width=1000,
        height=900,
        top_annotation=top_ha,
    )
    return hm.to_plotly(), kwargs


# ===========================================================================
# Example 4: Full feature — box/violin annotations + all options
# ===========================================================================


def example_full_feature() -> tuple:
    # Box and violin tracks need 2D data (n_genes × n_observations)
    # Simulate replicate measurements for each gene
    box_data = rng.standard_normal((N_GENES, 8))
    box_data[:20] += 2.0
    violin_data = rng.standard_normal((N_GENES, 12))
    violin_data[20:40] += 1.5

    # Build row annotations with explicit type configs
    right_ha = HeatmapAnnotation(
        which="row",
        pathway=pathways,
        length={"values": gene_length_kb.tolist(), "type": "bar", "color": "#4C78A8"},
        GC={"values": gc_content.tolist(), "type": "scatter", "color": "#E45756"},
    )

    left_ha = HeatmapAnnotation(
        which="row",
        replicate_dist={"values": box_data.tolist(), "type": "box", "color": "#72B7B2"},
        expression_dist={"values": violin_data.tolist(), "type": "violin", "color": "#FF9DA7"},
    )

    top_ha = HeatmapAnnotation(
        group=sample_group,
        batch=batch,
        quality={"values": quality_score.tolist(), "type": "bar", "color": "#EECA3B"},
        reads={"values": library_size.tolist(), "type": "scatter", "color": "#F58518"},
    )

    # Build expression-only DataFrame (no annotation columns)
    expr_df = pd.DataFrame(expression, index=gene_names, columns=sample_names)

    hm = ComplexHeatmap(
        expr_df,
        cluster_rows=True,
        cluster_cols=True,
        right_annotation=right_ha,
        left_annotation=left_ha,
        top_annotation=top_ha,
        normalize="row",
        colorscale="RdBu_r",
        cluster_method="average",
        cluster_metric="correlation",
        name="z-score",
        width=1200,
        height=900,
    )

    kwargs_info = {
        "note": "Full-feature example uses the direct ComplexHeatmap API",
        "annotations": "right: pathway + bar + scatter; left: box + violin; top: group + batch + bar + scatter",
        "cluster_method": "average",
        "cluster_metric": "correlation",
        "normalize": "row",
    }
    print_yaml_config("Example 4: Full Feature (Direct API)", kwargs_info)

    return hm.to_plotly(), kwargs_info


# ===========================================================================
# Main
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="plotly-complexheatmap Depictio showcase")
    parser.add_argument("--save", action="store_true", help="Save HTML + PNG instead of opening browser")
    parser.add_argument("--csv", action="store_true", help="Also save test CSV data")
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "output"

    examples = [
        ("01_minimal", example_minimal),
        ("02_multi_annotation", example_multi_annotation),
        ("03_split", example_split),
        ("04_full_feature", example_full_feature),
    ]

    if args.csv:
        out_dir.mkdir(exist_ok=True)
        save_test_csv(out_dir / "heatmap_test_data.csv")

    for name, func in examples:
        fig, _ = func()

        if args.save:
            out_dir.mkdir(exist_ok=True)
            html_path = out_dir / f"{name}.html"
            fig.write_html(str(html_path))
            print(f"  Saved: {html_path}")
        else:
            fig.show()


if __name__ == "__main__":
    main()
