"""
Cross-module communication stores.

Every bioinformatics module reads/writes to these shared dcc.Store components.
The demo app (app.py) instantiates them once; individual modules reference them
by ID in their callbacks.

Communication graph:
    Progressive Filter  ──selected_features──►  Feature Explorer
    Feature Explorer    ──active_feature────►  Progressive Filter (highlight)
    Progressive Filter  ──filtered_feature_ids──► Contrast Manager
    Contrast Manager    ──active_contrast───►  Enrichment Explorer
    Contrast Manager    ──highlighted_samples──► DimRed Explorer
"""

from dash import dcc

# Store IDs — importable constants so modules don't hardcode strings
SELECTED_FEATURES = "selected-features-store"
ACTIVE_FEATURE = "active-feature-store"
FILTERED_FEATURE_IDS = "filtered-feature-ids-store"
ACTIVE_CONTRAST = "active-contrast-store"
HIGHLIGHTED_SAMPLES = "highlighted-samples-store"
FILTER_STATE = "filter-state-store"


def create_shared_stores() -> list:
    """Create all shared dcc.Store components for cross-module communication."""
    return [
        # Progressive Filter writes: list of feature IDs passing all filters
        dcc.Store(id=FILTERED_FEATURE_IDS, data=[], storage_type="memory"),
        # Progressive Filter / Feature Explorer writes: list of user-selected features
        dcc.Store(id=SELECTED_FEATURES, data=[], storage_type="memory"),
        # Feature Explorer writes: single feature being explored
        dcc.Store(id=ACTIVE_FEATURE, data=None, storage_type="memory"),
        # Contrast Manager writes: name of the active contrast
        dcc.Store(id=ACTIVE_CONTRAST, data=None, storage_type="memory"),
        # Contrast Manager writes: sample IDs in active numerator/denominator
        dcc.Store(id=HIGHLIGHTED_SAMPLES, data=[], storage_type="memory"),
        # Progressive Filter writes: full filter configuration (for persistence)
        dcc.Store(id=FILTER_STATE, data={}, storage_type="memory"),
    ]
