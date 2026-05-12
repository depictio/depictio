"""Advanced visualisation component family.

Five composite, analysis-grade viz kinds (volcano, embedding, manhattan,
stacked_taxonomy, phylogenetic), each bundling a chart with builtin
filters/controls. At the outer dashboard level these are a single
``component_type = "advanced_viz"``; per-kind config is a Pydantic
discriminated union by ``viz_kind`` (see configs.py).

Per-pipeline recipes (under depictio/projects/nf-core/<pipe>/recipes/) bring
each pipeline's outputs to the canonical column schemas defined in
schemas.py. The editor validates a chosen DC against the viz's canonical
schema via validate_binding().
"""

from depictio.models.components.advanced_viz.component import (
    AdvancedVizComponent,
    AdvancedVizLiteComponent,
)
from depictio.models.components.advanced_viz.configs import (
    ANCOMBCDifferentialsConfig,
    ComplexHeatmapConfig,
    DaBarplotConfig,
    EmbeddingConfig,
    EnrichmentConfig,
    ManhattanConfig,
    PhylogeneticConfig,
    RarefactionConfig,
    StackedTaxonomyConfig,
    VizConfig,
    VolcanoConfig,
)
from depictio.models.components.advanced_viz.schemas import (
    CANONICAL_SCHEMAS,
    BindingError,
    validate_binding,
)

__all__ = [
    "ANCOMBCDifferentialsConfig",
    "AdvancedVizComponent",
    "AdvancedVizLiteComponent",
    "BindingError",
    "CANONICAL_SCHEMAS",
    "ComplexHeatmapConfig",
    "DaBarplotConfig",
    "EmbeddingConfig",
    "EnrichmentConfig",
    "ManhattanConfig",
    "PhylogeneticConfig",
    "RarefactionConfig",
    "StackedTaxonomyConfig",
    "VizConfig",
    "VolcanoConfig",
    "validate_binding",
]
