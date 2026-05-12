"""Per-viz_kind Pydantic configs for advanced visualisation components.

Each config owns the role→column mapping (e.g. role ``effect_size`` →
column ``lfc``) plus per-kind display defaults (thresholds, top-N, sort
order). The union below is what the AdvancedViz component stores under
its ``config`` field; Pydantic discriminates by ``viz_kind``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseVizConfig(BaseModel):
    """Common base for all viz-kind configs."""

    model_config = ConfigDict(extra="forbid")


class VolcanoConfig(_BaseVizConfig):
    """Volcano plot: effect size (x) vs significance (y, usually -log10)."""

    viz_kind: Literal["volcano"] = "volcano"

    # Column bindings (role -> column name in the bound DC).
    feature_id_col: str = Field(..., description="Column with the feature identifier")
    effect_size_col: str = Field(..., description="Column with effect size (e.g. log2FC, lfc)")
    significance_col: str = Field(..., description="Column with p-value or padj/q-value")
    label_col: str | None = Field(default=None, description="Optional column for hover labels")
    category_col: str | None = Field(
        default=None, description="Optional column for point colour/category"
    )

    # Display defaults — editable from the viz UI as Tier-2 (intra-viz) controls.
    significance_is_neg_log10: bool = Field(
        default=False,
        description="True if significance_col already contains -log10(p); else applied client-side",
    )
    significance_threshold: float = Field(default=0.05, description="Default p/padj cutoff")
    effect_threshold: float = Field(default=1.0, description="Default |effect_size| cutoff")
    top_n_labels: int = Field(default=20, ge=0, description="How many top features to label")


class EmbeddingConfig(_BaseVizConfig):
    """2D/3D embedding scatter (PCA / UMAP / t-SNE / PCoA output)."""

    viz_kind: Literal["embedding"] = "embedding"

    sample_id_col: str = Field(..., description="Column with the sample identifier")
    dim_1_col: str = Field(..., description="Column with first embedding dim")
    dim_2_col: str = Field(..., description="Column with second embedding dim")
    dim_3_col: str | None = Field(default=None, description="Optional third dim (enables 3D)")
    cluster_col: str | None = Field(default=None, description="Optional cluster assignment column")
    color_col: str | None = Field(
        default=None, description="Optional column for point colouring (metadata or expression)"
    )

    show_density: bool = Field(default=False, description="Overlay density contours")
    point_size: int = Field(default=6, ge=1, le=30)


class ManhattanConfig(_BaseVizConfig):
    """Generic chr/pos/score plot.

    Covers true GWAS (variants), peak significance (ATAC/ChIP narrowPeak),
    and viral variant tracks. ``score_kind`` labels the y-axis honestly.
    """

    viz_kind: Literal["manhattan"] = "manhattan"

    chr_col: str = Field(..., description="Column with chromosome label")
    pos_col: str = Field(..., description="Column with genomic position (1-based)")
    score_col: str = Field(..., description="Column with the y-axis score")
    feature_col: str | None = Field(
        default=None, description="Optional column with feature/locus id (gene, SNP, peak)"
    )
    effect_col: str | None = Field(
        default=None, description="Optional column with signed effect for point colouring"
    )

    score_kind: str = Field(
        default="-log10(padj)",
        description="Y-axis label, e.g. '-log10(padj)', 'peak qvalue', 'variant AF'",
    )
    score_threshold: float | None = Field(
        default=None, description="Horizontal threshold line; None hides it"
    )


class StackedTaxonomyConfig(_BaseVizConfig):
    """Stacked composition bar (per-sample relative abundance by taxon)."""

    viz_kind: Literal["stacked_taxonomy"] = "stacked_taxonomy"

    sample_id_col: str = Field(..., description="Column with the sample identifier")
    taxon_col: str = Field(..., description="Column with taxon name")
    rank_col: str = Field(..., description="Column with taxonomic rank label")
    abundance_col: str = Field(..., description="Column with relative or absolute abundance")

    default_rank: str | None = Field(
        default=None,
        description="If rank_col carries multiple ranks, default-filter to this one",
    )
    top_n: int = Field(default=20, ge=1, description="Show top-N taxa, lump rest into 'Other'")
    sort_by: Literal["abundance", "alphabetical"] = Field(default="abundance")
    normalise_to_one: bool = Field(
        default=True, description="Force each sample's bars to sum to 1 (true % composition)"
    )


# Discriminated union — the AdvancedViz component stores one of these.
VizConfig = Annotated[
    VolcanoConfig | EmbeddingConfig | ManhattanConfig | StackedTaxonomyConfig,
    Field(discriminator="viz_kind"),
]
