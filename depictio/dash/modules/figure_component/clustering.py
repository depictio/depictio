"""
Clustering and dimensionality reduction visualizations.

This module provides implementations for clustering algorithms like UMAP
that are not available in Plotly Express by default.
"""

import logging
import os
from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

from depictio.api.v1.configs.config import settings

# Configure Numba environment to avoid Docker/container caching issues
os.environ["NUMBA_CACHE_DIR"] = "/tmp"
os.environ["NUMBA_DISABLE_JIT"] = "0"

logger = logging.getLogger(__name__)


def create_umap_plot(
    df: pd.DataFrame,
    features: Optional[list] = None,
    color: Optional[str] = None,
    hover_name: Optional[str] = None,
    hover_data: Optional[list] = None,
    title: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    template: str = "plotly",
    opacity: float = 0.7,
    # UMAP-specific parameters
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    n_components: int = 2,
    metric: str = "euclidean",
    random_state: int = 42,
    **kwargs,
) -> Figure:
    """
    Create a UMAP (Uniform Manifold Approximation and Projection) visualization.

    Args:
        df: Input DataFrame
        features: List of column names to use for UMAP computation. If None, uses all numeric columns
        color: Column name for color encoding
        hover_name: Column for hover tooltip names
        hover_data: List of columns to show on hover
        title: Plot title
        width: Figure width
        height: Figure height
        template: Plotly template
        opacity: Marker opacity
        n_neighbors: Number of nearest neighbors for UMAP
        min_dist: Minimum distance parameter for UMAP
        n_components: Number of dimensions for UMAP output (2 or 3)
        metric: Distance metric for UMAP
        random_state: Random state for reproducibility
        **kwargs: Additional keyword arguments

    Returns:
        Plotly Figure object
    """
    try:
        from umap import UMAP  # type: ignore
    except ImportError:
        raise ImportError(
            "UMAP is required for clustering visualizations. "
            "Please install it with: pip install umap-learn"
        )

    # Prepare data for UMAP
    if features is None:
        # Use all numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) < 2:
            raise ValueError("Need at least 2 numeric columns for UMAP")
        features = numeric_cols

    # Extract feature matrix
    feature_matrix = df[features].values

    # Handle missing values
    if np.isnan(feature_matrix).any():
        logger.warning("Found NaN values in feature matrix, filling with column means")
        feature_matrix = (
            pd.DataFrame(feature_matrix).fillna(pd.DataFrame(feature_matrix).mean()).values
        )

    # Apply UMAP
    # Get the number of workers from Dash configuration for optimal performance
    n_workers = settings.dash.workers
    logger.info(
        f"Running UMAP with n_neighbors={n_neighbors}, min_dist={min_dist}, "
        f"n_components={n_components}, metric={metric}, n_jobs={n_workers}"
    )

    try:
        umap_model = UMAP(
            n_neighbors=n_neighbors,
            min_dist=min_dist,
            n_components=n_components,
            metric=metric,
            random_state=random_state,
            n_jobs=n_workers,  # Use configured number of workers
            low_memory=True,  # Enable low memory mode for better performance
        )

        embedding = umap_model.fit_transform(feature_matrix)

    except Exception as e:
        # Handle common UMAP issues in containerized environments
        if "cache" in str(e).lower() or "locator" in str(e).lower():
            logger.warning(f"UMAP caching issue detected: {e}")
            logger.info("Retrying UMAP with modified parameters for container environment")

            # Try with simpler parameters that are less likely to cause caching issues
            try:
                # Set environment variables again as a last resort
                os.environ["NUMBA_DISABLE_JIT"] = "1"  # Disable JIT compilation entirely

                umap_model = UMAP(
                    n_neighbors=min(n_neighbors, 10),  # Reduce complexity
                    min_dist=min_dist,
                    n_components=n_components,
                    metric="euclidean",  # Use simpler metric
                    random_state=random_state,
                    n_jobs=1,  # Use single worker for fallback to avoid issues
                    low_memory=True,  # Enable low memory mode
                )

                embedding = umap_model.fit_transform(feature_matrix)
                logger.info("UMAP succeeded with fallback parameters")

            except Exception as fallback_error:
                logger.error(f"UMAP fallback also failed: {fallback_error}")
                raise ValueError(
                    f"UMAP failed due to container environment issues. "
                    f"Original error: {e}. Fallback error: {fallback_error}"
                )
        else:
            # Re-raise other types of errors
            raise

    # Create DataFrame with UMAP coordinates
    umap_df = df.copy()
    if n_components == 2:
        umap_df["UMAP_1"] = embedding[:, 0]
        umap_df["UMAP_2"] = embedding[:, 1]

        # Create 2D scatter plot
        fig = px.scatter(
            umap_df,
            x="UMAP_1",
            y="UMAP_2",
            color=color,
            hover_name=hover_name,
            hover_data=hover_data,
            title=title or "UMAP Projection",
            width=width,
            height=height,
            template=template,
            opacity=opacity,
            **kwargs,
        )

        fig.update_layout(xaxis_title="UMAP Dimension 1", yaxis_title="UMAP Dimension 2")

    elif n_components == 3:
        umap_df["UMAP_1"] = embedding[:, 0]
        umap_df["UMAP_2"] = embedding[:, 1]
        umap_df["UMAP_3"] = embedding[:, 2]

        # Create 3D scatter plot
        fig = px.scatter_3d(
            umap_df,
            x="UMAP_1",
            y="UMAP_2",
            z="UMAP_3",
            color=color,
            hover_name=hover_name,
            hover_data=hover_data,
            title=title or "UMAP 3D Projection",
            width=width,
            height=height,
            template=template,
            opacity=opacity,
            **kwargs,
        )

        fig.update_layout(
            scene=dict(
                xaxis_title="UMAP Dimension 1",
                yaxis_title="UMAP Dimension 2",
                zaxis_title="UMAP Dimension 3",
            )
        )
    else:
        raise ValueError("n_components must be 2 or 3 for visualization")

    # Add hover information about UMAP parameters
    fig.update_traces(
        hovertemplate=fig.data[0].hovertemplate
        + f"<br>UMAP Parameters:<br>n_neighbors: {n_neighbors}<br>min_dist: {min_dist}<extra></extra>"
    )

    return fig


# Registry of clustering functions
CLUSTERING_FUNCTIONS = {
    "umap": create_umap_plot,
}


def get_clustering_function(name: str):
    """Get clustering function by name."""
    if name not in CLUSTERING_FUNCTIONS:
        raise ValueError(f"Unknown clustering function: {name}")
    return CLUSTERING_FUNCTIONS[name]
