# Bioinformatics Visualization Modules — Design Document

## 1. Vision

Depictio bioinformatics modules are **generic, reusable visualization building blocks** that can be composed into pipeline-specific dashboards. Each module encapsulates a single analytical concept (e.g., "filter a table progressively", "explore a single feature across conditions", "visualize enrichment results") and works across different data types, organisms, and technologies.

**Key principle**: Modules are NOT pipeline-specific. A "Progressive Filter" module works equally well on:
- DE results from RNA-seq (log2FC, padj, baseMean)
- Differential binding results from ChIP-seq (log2FC, padj, FRiP)
- Differential accessibility results from ATAC-seq (log2FC, padj)
- Differential abundance results from 16S amplicon (W-statistic, CLR)
- Variant calls from viralrecon (frequency, depth, quality)
- Methylation differences from methylseq (delta_beta, padj)
- Any tabular data with numeric and categorical columns

Pipeline dashboards are then **compositions of modules**, each wired to the appropriate data source.

---

## 2. Pipeline Landscape Analysis

### 2.1 Pipelines Analyzed (sorted by GitHub stars)

| Pipeline | Stars | Category | Primary Outputs | Diff. Analysis? |
|----------|-------|----------|----------------|-----------------|
| **rnaseq** | 1221 | Transcriptomics | Count matrices (gene/transcript), TPM/FPKM | DESeq2 QC only (no DE results) |
| **sarek** | 553 | Genomics (WGS/WES) | VCF (Strelka/Mutect2/FreeBayes), annotated variants | N/A |
| **scrnaseq** | 316 | Single-cell | Count matrices (AnnData/Seurat), cell QC | N/A |
| **mag** | 277 | Metagenome assembly | MAGs, bins, taxonomy, abundance tables | N/A |
| **ampliseq** | 236 | Metagenomics (16S) | ASV tables, taxonomy, abundance | ANCOM + ANCOMBC |
| **chipseq** | 232 | Epigenomics | Peaks (narrow/broad), bigWig, consensus | Full DESeq2 differential binding |
| **atacseq** | 220 | Epigenomics | Peaks (broad), bigWig, consensus | Full DESeq2 differential accessibility |
| **nanoseq** | 219 | Long-read sequencing | Aligned reads, QC metrics | N/A |
| **methylseq** | 189 | Epigenomics | Methylation calls (CpG coverage/ratios) | N/A |
| **fetchngs** | 188 | Data retrieval | FASTQ + metadata (not analysis) | N/A |
| **taxprofiler** | 179 | Metagenomics | Taxonomic profiles (multiple tools) | N/A |
| **rnafusion** | 171 | Transcriptomics | Fusion gene calls | N/A |
| **viralrecon** | 158 | Virology | Variants (iVar TSV), assemblies, consensus | N/A |
| **raredisease** | 114 | Clinical genomics | VCF, SV calls, clinical reports | N/A |
| **cutandrun** | 109 | Epigenomics | Peaks (SEACR), bigWig, consensus | None (no DiffBind) |
| **hic** | 108 | 3D Genomics | Contact matrices, TADs, compartments | N/A |
| **proteinfold** | 99 | Structural biology | PDB structures, confidence scores | N/A |
| **smrnaseq** | 98 | Small RNA | miRNA counts, mature/hairpin quantification | edgeR (optional) |
| **differentialabundance** | 90 | Multi-omics downstream | DE/DA tables, volcano, heatmaps, PCA, GSEA | Full (DESeq2, limma, edgeR, GSEA) |

### 2.2 Universal Outputs (ALL pipelines)

Every nf-core pipeline produces:
- **MultiQC**: `multiqc_report.html` + `multiqc_data/` (JSON, TSV, YAML)
- **FastQC**: per-sample HTML + ZIP (raw and/or trimmed)
- **Trimming stats**: tool-dependent (Trim Galore, fastp, Cutadapt)
- **pipeline_info/**: execution reports, traces, DAGs, params JSON, software versions YAML

### 2.3 Shared Data Shapes

Despite the diversity, pipeline outputs collapse into a small number of **data shapes**:

| Shape | Description | Found In |
|-------|-------------|----------|
| **Feature × Sample matrix** | Rows = features (genes/peaks/taxa/CpGs), Cols = samples, Values = counts/expression/methylation | rnaseq, chipseq, atacseq, cutandrun, ampliseq, scrnaseq, methylseq, smrnaseq |
| **Feature-level statistics table** | One row per feature with columns like log2FC, pvalue, padj, baseMean | differentialabundance, chipseq, atacseq, ampliseq (ANCOM), viralrecon (variants) |
| **Sample metadata table** | One row per sample with condition, batch, covariates | ALL (samplesheet.csv is universal) |
| **Enrichment results table** | pathway, NES/ES, pvalue, padj, gene_set, leading_edge | differentialabundance (GSEA), any downstream analysis |
| **QC metrics table** | Sample-level QC metrics (read counts, mapping rate, duplication, etc.) | ALL (via MultiQC general_stats) |
| **Genomic intervals** | BED/narrowPeak/broadPeak with chr, start, end, score, annotation | chipseq, atacseq, cutandrun, sarek (VCF) |
| **Pairwise distances** | Sample × Sample distance/correlation matrix | rnaseq (DESeq2), ampliseq (beta diversity), any PCA input |

### 2.4 Module Coverage Matrix (Top 19 pipelines)

Which modules apply to which pipelines:

```
                        ProgFilt  CondHigh  Contrast  Feature  Enrich  DimRed  QCSumm  PeakExp  TaxBrow  VarInsp
rnaseq (1221★)             ✓         ✓         ✓        ✓        ✓       ✓       ✓
sarek (553★)               ✓         ✓                                           ✓                         ✓
scrnaseq (316★)                                          ✓                ✓       ✓
mag (277★)                 ✓                                             ✓       ✓                ✓
ampliseq (236★)            ✓         ✓         ✓        ✓        ✓       ✓       ✓                ✓
chipseq (232★)             ✓         ✓         ✓        ✓        ✓       ✓       ✓        ✓
atacseq (220★)             ✓         ✓         ✓        ✓        ✓       ✓       ✓        ✓
nanoseq (219★)                                                           ✓       ✓
methylseq (189★)           ✓         ✓         ✓        ✓                ✓       ✓
taxprofiler (179★)         ✓                                             ✓       ✓                ✓
rnafusion (171★)           ✓                                                     ✓
viralrecon (158★)          ✓         ✓                                           ✓                         ✓
raredisease (114★)         ✓                                                     ✓                         ✓
cutandrun (109★)           ✓         ✓         ✓        ✓                ✓       ✓        ✓
hic (108★)                                                              ✓       ✓
proteinfold (99★)                                                                ✓
smrnaseq (98★)             ✓         ✓         ✓        ✓                ✓       ✓
diffabundance (90★)        ✓         ✓         ✓        ✓        ✓       ✓       ✓
────────────────────────────────────────────────────────────────────────────────────────
Pipeline coverage:         15        10        10       10        6      15      18        3        3        3
```

**Key insight**: The 7 core modules cover ALL 19 top pipelines. The 3 domain-specific modules each cover 3 pipelines. `QC Summary` alone covers 18/19 pipelines.

---

## 3. Module Architecture

### 3.1 Module Taxonomy

Based on the cross-pipeline analysis and existing prototypes, we define **7 core modules** and **3 domain-specific modules**:

#### Core Modules (work with ANY tabular data)

| Module | Input Shape | Key Visualizations | Existing Prototype |
|--------|------------|-------------------|-------------------|
| **Progressive Filter** | Feature-level stats table | Volcano/scatter, funnel chart, filtered AG Grid | `dev/progressive-filter/` |
| **Conditional Highlighting** | Feature-level stats table | Scatter with dynamic threshold overlays, summary badges | `dev/conditional-highlighting/` |
| **Contrast Manager** | Expression matrix + metadata + DE results per contrast | Contrast table, MA plot, PCA mini-view, contrast-vs-contrast | `dev/contrast-manager/` |
| **Feature Explorer** | Expression matrix + metadata + DE results | Violin/strip plot, heatmap row, rank badges, co-expression | `dev/gene-explorer/` |
| **Enrichment Explorer** | Enrichment table + ranked gene list + expression matrix | Running ES, dot plot, leading edge heatmap, enrichment table | `dev/gsea-explorer/` |
| **DimRed Explorer** | Feature × Sample matrix + metadata | PCA/UMAP/t-SNE scatter, variance bar, loadings, sample table | `dev/dimred-explorer/` |
| **QC Summary** | QC metrics table (from MultiQC) | Summary cards, bar charts, violin distributions, pass/fail badges | NEW |

#### Domain-Specific Modules (need specialized data)

| Module | Input Shape | Key Visualizations | Applicable Pipelines |
|--------|------------|-------------------|---------------------|
| **Peak Explorer** | Genomic intervals + annotation + signal tracks | Peak annotation pie/bar, FRiP distribution, consensus heatmap | chipseq, atacseq, cutandrun |
| **Taxonomy Browser** | Hierarchical abundance table (kingdom→species) | Stacked bar (relative abundance), krona-style sunburst, alpha/beta diversity | ampliseq, taxprofiler |
| **Variant Inspector** | Variant table + coverage + lineage assignments | Variant table with AF filter, coverage track, lineage timeline/bar | viralrecon, sarek |

### 3.2 Module Interface Contract

Every module follows the same interface contract, making them composable and pipeline-agnostic:

```python
from dataclasses import dataclass
from typing import Any
import pandas as pd


@dataclass
class ModuleDataContract:
    """Defines what data a module needs."""

    # Required inputs (module won't render without these)
    required: dict[str, str]
    # Optional inputs (module renders with reduced functionality)
    optional: dict[str, str]

    # Example for Progressive Filter:
    # required = {
    #     "features_table": "DataFrame with rows=features, must have >=1 numeric column"
    # }
    # optional = {
    #     "feature_id_col": "str, column name for feature IDs (default: first string column)",
    #     "presets": "dict of {preset_name: list[FilterSpec]} for quick filter templates",
    # }


@dataclass
class ColumnMapping:
    """Maps abstract column roles to actual column names in the data.

    This is the key to making modules pipeline-agnostic.
    The module defines abstract roles (e.g., "effect_size", "significance"),
    and the pipeline config maps these to actual column names.
    """

    mapping: dict[str, str]

    # Example for RNA-seq DE results → Progressive Filter:
    # mapping = {
    #     "feature_id": "gene_name",
    #     "effect_size": "log2FoldChange",
    #     "significance": "padj",
    #     "mean_abundance": "baseMean",
    # }
    #
    # Example for ChIP-seq differential binding → Progressive Filter:
    # mapping = {
    #     "feature_id": "peak_id",
    #     "effect_size": "Fold",
    #     "significance": "FDR",
    #     "mean_abundance": "Conc",
    # }
    #
    # Example for viralrecon variants → Progressive Filter:
    # mapping = {
    #     "feature_id": "POS",
    #     "effect_size": "ALT_FREQ",
    #     "significance": "ALT_QUAL",
    #     "mean_abundance": "ALT_DP",
    # }
```

### 3.3 Module Lifecycle

```
┌─────────────────────────────────────────────────────┐
│  1. DATA BINDING                                     │
│     Pipeline config provides:                        │
│     - Data source (Delta table / S3 path / API)      │
│     - ColumnMapping (abstract roles → actual cols)   │
│     - Module-specific presets                        │
├─────────────────────────────────────────────────────┤
│  2. INITIALIZATION                                   │
│     Module reads data, validates ColumnMapping,      │
│     auto-detects column types (numeric/categorical), │
│     sets up default controls                         │
├─────────────────────────────────────────────────────┤
│  3. RENDERING                                        │
│     Module creates Dash layout (sidebar + main area) │
│     using DMC 2.0 components                         │
├─────────────────────────────────────────────────────┤
│  4. INTERACTION                                      │
│     Callbacks handle user input, update viz in place  │
│     Cross-module communication via shared stores     │
└─────────────────────────────────────────────────────┘
```

---

## 4. Module Specifications

### 4.1 Progressive Filter

**Purpose**: Iteratively narrow down a feature table through a chain of composable filters, visualizing each reduction step.

**Works for**:
- DE results → filter significant genes (|log2FC| > 1.5 AND padj < 0.05)
- Peak calls → filter high-confidence peaks (score > 100 AND FRiP > 0.1)
- Variant calls → filter variants (AF > 0.05 AND QUAL > 30 AND DP > 10)
- Taxonomy → filter abundant taxa (relative_abundance > 0.01)
- Methylation → filter DMRs (|delta_beta| > 0.2 AND qvalue < 0.01)
- **ANY** tabular data with numeric/categorical columns

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `features_table` | DataFrame | Rows = features, columns = properties |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `feature_id_col` | str | auto-detect first string col | Column to use as feature identifier |
| `default_filters` | list[FilterSpec] | [] | Pre-configured filter chain |
| `scatter_x` | str | auto-detect | Default x-axis column for scatter |
| `scatter_y` | str | auto-detect | Default y-axis column for scatter |
| `scatter_preset` | str | "volcano" | One of "volcano", "ma", "generic" |

**Column role auto-detection heuristics**:
- `effect_size`: column named `*log2*fc*`, `*fold*change*`, `*lfc*`, `*delta*`
- `significance`: column named `*padj*`, `*fdr*`, `*qvalue*`, `*adj*pval*`
- `raw_pvalue`: column named `*pvalue*`, `*pval*` (not adj/fdr)
- `mean_abundance`: column named `*basemean*`, `*mean*`, `*conc*`, `*avg*`

**Scatter presets**:
- `volcano`: x = effect_size, y = -log10(significance)
- `ma`: x = mean_abundance, y = effect_size
- `generic`: x = first numeric, y = second numeric

**Visualizations**:
1. **Filter chain sidebar**: Add/remove/enable/disable filters with column, operator, threshold
2. **Summary badges**: Total → Filter 1 (N remaining) → Filter 2 (N remaining) → ... → Final
3. **Funnel chart**: Visual representation of filter reduction
4. **Scatter plot**: Volcano/MA/generic with highlighted passing points
5. **AG Grid table**: Filtered results with sort, search, export

---

### 4.2 Conditional Highlighting

**Purpose**: Overlay dynamic threshold lines on a scatter plot and highlight points meeting compound conditions.

**Works for**:
- Volcano plots with adjustable FC and p-value thresholds
- QC plots with pass/fail thresholds (mapping rate > 80%, duplication < 30%)
- Any x-y scatter where visual thresholding adds insight

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `features_table` | DataFrame | Same as Progressive Filter |

**Key difference from Progressive Filter**: This module focuses on visual exploration (threshold lines rendered on scatter, points dim/highlight in real-time) vs. Progressive Filter which focuses on data reduction (funnel, badge counts).

---

### 4.3 Contrast Manager

**Purpose**: Define, compare, and navigate between experimental contrasts (treatment vs. control comparisons).

**Works for**:
- RNA-seq: multiple treatment-vs-control DE comparisons
- ChIP-seq/ATAC-seq: multiple differential binding comparisons
- Proteomics: differential protein abundance across conditions
- **Any** experiment with a condition column in sample metadata

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `expression_matrix` | DataFrame | Features × Samples |
| `sample_metadata` | DataFrame | Samples × covariates (must include condition column) |
| `condition_col` | str | Column in metadata defining groups |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `de_results` | dict[str, DataFrame] | {} | Pre-computed DE results per contrast |
| `reference_group` | str | None | Default denominator group |

**Visualizations**:
1. **Contrast builder sidebar**: Select numerator/denominator groups
2. **Contrast summary table**: All contrasts with sample counts, sig. feature counts, balance warnings
3. **MA plot**: For active contrast
4. **PCA mini-view**: Samples colored by active contrast groups
5. **Contrast-vs-contrast scatter**: Compare effect sizes between two contrasts

---

### 4.4 Feature Explorer (generalized from Gene Explorer)

**Purpose**: Deep-dive into a single feature — its distribution across conditions, rank among all features, and co-expressed/co-occurring features.

**Works for**:
- RNA-seq: single gene expression across conditions + co-expression
- ChIP-seq: single peak signal across conditions + co-bound peaks
- Ampliseq: single taxon abundance across samples + co-occurring taxa
- Proteomics: single protein across conditions
- Methylseq: single CpG/region methylation across groups

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `expression_matrix` | DataFrame | Features × Samples (or Samples × Features) |
| `sample_metadata` | DataFrame | Sample metadata with grouping columns |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `de_results` | DataFrame | None | Feature-level stats for rank display |
| `feature_type_label` | str | "Gene" | UI label ("Gene", "Peak", "Taxon", "CpG") |
| `external_links` | dict[str, str] | auto | URL templates for external databases |
| `correlation_method` | str | "pearson" | "pearson", "spearman", or "kendall" |

**External link templates by feature type**:
- Gene: GeneCards, NCBI Gene, Ensembl, UniProt
- Peak: UCSC Genome Browser, Ensembl
- Taxon: NCBI Taxonomy, Silva, GTDB
- Variant: dbSNP, ClinVar, gnomAD

**Visualizations**:
1. **Feature search**: Searchable dropdown with type-ahead
2. **Distribution plot**: Violin/strip/box by condition (or numeric metadata)
3. **Heatmap row**: Single-feature expression across all samples, sorted by metadata
4. **Rank badges**: Where this feature ranks in DE results (log2FC, padj)
5. **Co-expression table**: Top N correlated features with Pearson r and p-value

---

### 4.5 Enrichment Explorer (generalized from GSEA Explorer)

**Purpose**: Explore pathway/gene set enrichment results across contrasts.

**Works for**:
- GSEA results from differentialabundance pipeline
- GO/KEGG enrichment from any tool (clusterProfiler, g:Profiler, Enrichr)
- Custom gene set analysis results

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `enrichment_table` | DataFrame | Must have: pathway_name, NES (or ES), pvalue/padj, gene_set_size |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `ranked_genes` | dict[str, DataFrame] | None | Ranked gene list per contrast (for running ES plot) |
| `expression_matrix` | DataFrame | None | For leading edge heatmap |
| `source_col` | str | "source" | Column for pathway database filter (GO, KEGG, Reactome) |
| `contrast_col` | str | "contrast" | Column for contrast selection |

**Column role auto-detection**:
- `enrichment_score`: column named `*NES*`, `*ES*`, `*enrichment*score*`
- `pathway_name`: column named `*pathway*`, `*term*`, `*gene_set*`, `*description*`
- `gene_set_size`: column named `*size*`, `*count*`, `*n_genes*`

**Visualizations**:
1. **Enrichment table**: AG Grid with pathway, NES, padj, source, leading edge size
2. **Running ES plot**: Click a pathway → see enrichment score curve
3. **Dot plot**: Top N pathways by |NES|, dot size = gene set size, color = NES, x = padj
4. **Leading edge heatmap**: Expression of leading edge genes for selected pathway

---

### 4.6 DimRed Explorer

**Purpose**: Interactive dimensionality reduction with multiple algorithms, colored by metadata.

**Works for**:
- RNA-seq: PCA/UMAP/t-SNE on expression matrix
- ChIP-seq/ATAC-seq: PCA on peak count matrix
- Ampliseq: PCoA on beta diversity (Bray-Curtis, UniFrac)
- Single-cell: UMAP/t-SNE on cell embeddings
- Methylseq: PCA on methylation beta values

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `feature_matrix` | DataFrame | Features × Samples (or Samples × Features) |
| `sample_metadata` | DataFrame | Sample metadata with grouping columns |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `precomputed_coords` | DataFrame | None | Pre-computed embeddings (skip computation) |
| `distance_matrix` | DataFrame | None | For PCoA (ampliseq beta diversity) |
| `methods` | list[str] | ["pca","umap","tsne"] | Available methods |

**Visualizations**:
1. **Method selector**: Segmented control (PCA / UMAP / t-SNE / PCoA)
2. **Main scatter**: 2D embedding, colored by metadata, optional symbol by second metadata
3. **Variance explained bar**: Component contributions (PCA/PCoA only)
4. **Loadings bar**: Top contributing features per component (PCA only)
5. **Sample table**: AG Grid with metadata + coordinates
6. **Algorithm parameters**: n_neighbors, min_dist (UMAP), perplexity (t-SNE), metric (PCoA)

---

### 4.7 QC Summary (NEW)

**Purpose**: Parse MultiQC data and present sample-level QC metrics with pass/fail thresholds.

**Works for**: ALL nf-core pipelines (MultiQC is universal).

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `qc_metrics` | DataFrame | Samples × QC metrics (from MultiQC general_stats or custom) |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `thresholds` | dict[str, tuple] | auto | {metric: (min, max)} for pass/fail |
| `sample_metadata` | DataFrame | None | For grouping QC by condition/batch |
| `tool_sections` | list[str] | all | Filter to specific tool sections |

**Visualizations**:
1. **Summary cards**: Total samples, samples passing all QC, samples failing
2. **Metric distribution**: Violin/histogram per QC metric, colored by pass/fail
3. **QC heatmap**: Samples × metrics, color = z-score, cells flagged if outside threshold
4. **Per-sample detail**: Click a sample → see all its metrics vs. thresholds

**Common QC metrics by pipeline**:
| Metric | Source | Pipelines |
|--------|--------|-----------|
| Total reads | FastQC/fastp | ALL |
| % Mapped | Samtools flagstat | rnaseq, chipseq, atacseq, cutandrun, viralrecon, sarek |
| % Duplicates | Picard/fastp | rnaseq, chipseq, atacseq, cutandrun |
| % GC | FastQC | ALL |
| Insert size | Picard | rnaseq, chipseq, atacseq |
| FRiP | Custom/Homer | chipseq, atacseq, cutandrun |
| % rRNA | Bowtie2/STAR | rnaseq |
| TSS enrichment | ATAQV | atacseq |
| Median coverage | mosdepth | viralrecon, sarek, methylseq |

---

### 4.8 Peak Explorer (Domain-Specific)

**Purpose**: Explore ChIP-seq/ATAC-seq/CUT&RUN peak calls with annotation and signal.

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `peak_table` | DataFrame | Peaks with chr, start, end, score/pvalue |
| `annotation` | DataFrame | Peak annotation (promoter/intron/intergenic from HOMER/ChIPseeker) |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `consensus_matrix` | DataFrame | None | Peaks × Samples binary/count matrix |
| `frip_scores` | DataFrame | None | Per-sample FRiP scores |

**Visualizations**:
1. **Peak annotation distribution**: Pie/bar chart (promoter, UTR, intron, intergenic, etc.)
2. **Peak width distribution**: Histogram of peak widths
3. **FRiP distribution**: Bar chart per sample
4. **Consensus heatmap**: Which peaks are found in which samples
5. **Peak table**: AG Grid with annotation, sortable by score/pvalue

**Applicable to**: chipseq, atacseq, cutandrun

---

### 4.9 Taxonomy Browser (Domain-Specific)

**Purpose**: Explore taxonomic composition across samples at multiple ranks.

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `abundance_table` | DataFrame | Taxa × Samples (counts or relative abundance) |
| `taxonomy` | DataFrame | Taxa with rank columns (kingdom, phylum, ..., species) |
| `sample_metadata` | DataFrame | Sample grouping info |

**Visualizations**:
1. **Rank selector**: Toggle between phylum/class/order/family/genus/species
2. **Stacked bar plot**: Relative abundance per sample, grouped by condition
3. **Alpha diversity**: Shannon, Simpson, Chao1 per sample, grouped
4. **Beta diversity ordination**: PCoA on Bray-Curtis/UniFrac (→ delegates to DimRed Explorer)
5. **Differential abundance table**: ANCOM/ANCOMBC results with W-statistic, CLR

**Applicable to**: ampliseq, taxprofiler

---

### 4.10 Variant Inspector (Domain-Specific)

**Purpose**: Explore variant calls with allele frequency filtering and lineage context.

**Required inputs**:
| Input | Type | Description |
|-------|------|-------------|
| `variant_table` | DataFrame | Variants with position, ref, alt, frequency, quality |

**Optional inputs**:
| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `coverage_table` | DataFrame | None | Per-position depth |
| `lineage_results` | DataFrame | None | Freyja/Pangolin lineage assignments |
| `annotation_table` | DataFrame | None | SnpEff/VEP functional annotations |

**Visualizations**:
1. **Variant table**: AG Grid with position, ref, alt, AF, quality, annotation
2. **AF distribution**: Histogram of allele frequencies
3. **Coverage track**: Per-position depth (mini genome browser feel)
4. **Lineage bar**: Freyja/Pangolin lineage composition per sample
5. **Variant-vs-variant scatter**: Compare AF between samples

**Applicable to**: viralrecon, sarek

---

## 5. Cross-Module Communication

Modules communicate through **shared Dash stores** (dcc.Store), enabling linked interactions:

```
┌──────────────┐     selected_features     ┌──────────────────┐
│  Progressive │ ──────────────────────────▶│  Feature Explorer│
│  Filter      │                            │  (deep-dive on   │
│              │◀──────────────────────────│   selected gene)  │
│              │     click_feature          └──────────────────┘
└──────────────┘
       │
       │ filtered_feature_ids
       ▼
┌──────────────┐     active_contrast       ┌──────────────────┐
│  Contrast    │ ──────────────────────────▶│  Enrichment      │
│  Manager     │                            │  Explorer        │
│              │                            │  (GSEA for       │
│              │                            │   active contrast)│
└──────────────┘                            └──────────────────┘
       │
       │ highlighted_samples
       ▼
┌──────────────┐
│  DimRed      │
│  Explorer    │
│  (highlight  │
│   selected   │
│   samples)   │
└──────────────┘
```

**Shared store protocol**:
```python
# Every module reads/writes to these shared stores:
SHARED_STORES = {
    "selected-features-store": [],      # list of feature IDs currently selected
    "active-contrast-store": "",         # name of the active contrast
    "highlighted-samples-store": [],     # list of sample IDs to highlight
    "active-feature-store": "",          # single feature being explored
    "filter-state-store": {},            # current filter configuration
}
```

---

## 6. Data Binding: Connecting Modules to Pipeline Outputs

### 6.1 Column Mapping Configuration

Each pipeline dashboard defines how its outputs map to module inputs:

```yaml
# Example: rnaseq_dashboard.yaml
pipeline: rnaseq
modules:
  - module: progressive_filter
    data_source: "differentialabundance/deseq2_results.tsv"
    column_mapping:
      feature_id: gene_id
      effect_size: log2FoldChange
      significance: padj
      mean_abundance: baseMean
    presets:
      significant_up:
        - {column: log2FoldChange, operator: ">", threshold: 1.0}
        - {column: padj, operator: "<", threshold: 0.05}
      significant_down:
        - {column: log2FoldChange, operator: "<", threshold: -1.0}
        - {column: padj, operator: "<", threshold: 0.05}

  - module: dimred_explorer
    data_source: "salmon/salmon.merged.gene_counts.tsv"
    metadata_source: "samplesheet.csv"
    column_mapping:
      condition: condition
      batch: batch

  - module: feature_explorer
    data_source: "salmon/salmon.merged.gene_tpm.tsv"
    metadata_source: "samplesheet.csv"
    de_results_source: "differentialabundance/deseq2_results.tsv"
    column_mapping:
      feature_id: gene_id
    config:
      feature_type_label: Gene
      external_links:
        GeneCards: "https://www.genecards.org/cgi-bin/carddisp.pl?gene={feature_id}"
        Ensembl: "https://ensembl.org/Human/Gene/Summary?g={feature_id}"

  - module: qc_summary
    data_source: "multiqc/multiqc_data/multiqc_general_stats.txt"
    thresholds:
      total_reads: [1000000, null]
      percent_mapped: [80, null]
      percent_duplicates: [null, 50]
```

```yaml
# Example: chipseq_dashboard.yaml
pipeline: chipseq
modules:
  - module: progressive_filter
    data_source: "macs2/consensus/deseq2/{contrast}.results.txt"
    column_mapping:
      feature_id: peak_id
      effect_size: log2FoldChange
      significance: padj
      mean_abundance: baseMean

  - module: peak_explorer
    data_source: "macs2/consensus/{contrast}.peaks.bed"
    annotation_source: "homer/annotatepeaks/{contrast}.annotatePeaks.txt"

  - module: dimred_explorer
    data_source: "macs2/consensus/featureCounts.txt"
    metadata_source: "samplesheet.csv"
```

```yaml
# Example: ampliseq_dashboard.yaml
pipeline: ampliseq
modules:
  - module: taxonomy_browser
    data_source: "qiime2/abundance_tables/rel-table-{rank}.tsv"
    taxonomy_source: "qiime2/taxonomy/taxonomy.tsv"
    metadata_source: "samplesheet.csv"

  - module: dimred_explorer
    data_source: "qiime2/diversity/beta_diversity/bray_curtis_pcoa.tsv"
    metadata_source: "samplesheet.csv"
    config:
      methods: [pcoa]
      precomputed: true

  - module: progressive_filter
    data_source: "qiime2/ancombc/ancombc.tsv"
    column_mapping:
      feature_id: taxon
      effect_size: lfc
      significance: q_val
```

### 6.2 Auto-Detection Strategy

When pointing depictio at an nf-core output folder:

1. **Pipeline identification**: Read `pipeline_info/params_*.json` → extract pipeline name
2. **Version detection**: Read `pipeline_info/software_versions.yml`
3. **File discovery**: Glob for expected output patterns per pipeline
4. **Column mapping**: Apply pipeline-specific defaults with auto-detection fallback
5. **Dashboard assembly**: Load the pipeline's module configuration

---

## 7. Generalization Summary

### How each prototype generalizes:

| Prototype | Generalizes To | Key Abstraction |
|-----------|---------------|-----------------|
| `progressive-filter` | **Any tabular data with numeric/categorical columns** | `ColumnMapping` maps abstract roles (effect_size, significance) to actual column names |
| `conditional-highlighting` | **Any scatter plot needing dynamic thresholds** | Threshold conditions are column-agnostic (pick any numeric column + operator + value) |
| `contrast-manager` | **Any experiment with grouped samples** | `condition_col` in metadata defines groups; DE computation is optional (can use pre-computed) |
| `gene-explorer` → `feature-explorer` | **Any feature × sample matrix** | `feature_type_label` changes UI text; external links are templated per feature type |
| `gsea-explorer` → `enrichment-explorer` | **Any enrichment results table** | NES/ES column auto-detected; pathway sources are dynamic (not hardcoded GO/KEGG/Reactome) |
| `dimred-explorer` | **Any high-dimensional data needing embedding** | Methods list is configurable; PCoA added for ecology; pre-computed embeddings supported |

### What's truly RNA-seq specific vs. generic:

| Concept | RNA-seq Term | Generic Term | Also Used By |
|---------|-------------|-------------|-------------|
| Gene | Gene | Feature | Peak, Taxon, CpG, Protein, miRNA |
| Expression | log2(TPM) | Abundance/Signal | Peak count, Relative abundance, Beta value |
| DE result | DESeq2 output | Feature-level statistics | DiffBind, ANCOMBC, DMR caller |
| log2FC | log2FoldChange | Effect size | Fold, lfc, delta_beta |
| padj | Adjusted p-value | Significance | FDR, q_val, qvalue |
| baseMean | baseMean | Mean abundance | Conc, mean_count, avg_depth |
| GSEA | Gene Set Enrichment | Set Enrichment | Pathway enrichment, GO enrichment |
| PCA on expression | DESeq2 PCA | Dimensionality reduction | PCoA (ecology), UMAP (single-cell) |

---

## 8. Implementation Priority

### Phase 1: Core Modules (pipeline-agnostic)
1. **Progressive Filter** — most universally useful, already prototyped
2. **DimRed Explorer** — universal QC/exploration tool, already prototyped
3. **QC Summary** — universal (MultiQC parsing), high immediate value

### Phase 2: Analysis Modules
4. **Feature Explorer** — requires matrix + metadata, broadly useful
5. **Contrast Manager** — requires DE results or ability to compute them
6. **Enrichment Explorer** — requires GSEA results (often from differentialabundance)

### Phase 3: Domain-Specific
7. **Peak Explorer** — chipseq/atacseq/cutandrun
8. **Taxonomy Browser** — ampliseq/taxprofiler
9. **Variant Inspector** — viralrecon/sarek

### Phase 4: Cross-Module Integration
10. Shared stores and linked interactions
11. Pipeline auto-detection and dashboard assembly
12. Pre-built pipeline dashboard templates

---

## 9. Appendix: Pipeline Output File Patterns

### Files to parse per pipeline (for data binding)

```
# RNA-seq
salmon/salmon.merged.gene_counts.tsv          → expression_matrix
salmon/salmon.merged.gene_tpm.tsv             → expression_matrix (normalized)
star_salmon/deseq2_qc/deseq2.pca.vals.txt    → precomputed PCA
star_salmon/deseq2_qc/deseq2.dists.txt       → sample distances

# ChIP-seq / ATAC-seq
macs2/consensus/featureCounts.txt             → peak_count_matrix
macs2/consensus/deseq2/*.results.txt          → de_results
macs2/consensus/*.boolean.annotatePeaks.txt   → peak_annotation
bwa/mergedLibrary/bigwig/*.bigWig             → signal_tracks
bwa/mergedLibrary/picard_metrics/*            → qc_metrics

# Ampliseq
qiime2/abundance_tables/feature-table.biom    → count_matrix
qiime2/abundance_tables/rel-table-*.tsv       → relative_abundance
qiime2/taxonomy/taxonomy.tsv                  → taxonomy
qiime2/diversity/alpha_diversity/*.tsv        → alpha_diversity
qiime2/diversity/beta_diversity/*.tsv         → beta_diversity
qiime2/ancombc/ancombc.tsv                    → differential_abundance

# Viralrecon
variants/ivar/*.tsv                           → variant_table
variants/freyja/demix/*.tsv                   → lineage_results
variants/freyja/variants/*.depth.tsv          → coverage_table
variants/bowtie2/samtools_stats/*             → qc_metrics

# CUT&RUN
seacr/consensus/featureCounts.txt             → peak_count_matrix
deeptools/plotFingerprint.raw.txt             → signal_qc
bowtie2/mergedLibrary/bigwig/*.bigWig         → signal_tracks

# Differentialabundance (confirmed from S3 megatests)
tables/processed_counts/*.normalised_counts.tsv  → count_matrix (normalized)
tables/processed_counts/*.vst.tsv                → count_matrix (variance-stabilized)
tables/differential/*.deseq2.results.tsv         → de_results (full DE table)
tables/deseq2_other/*.deseq2.sizefactors.tsv     → size_factors
tables/deseq2_other/*.dds.rld.rds                → R objects (rlog-transformed)
tables/gsea/{contrast}/*.gsea_report_for_*.tsv   → enrichment_results (per group)
plots/differential/{contrast}/png/volcano.png    → static_volcano
plots/exploratory/{variable}/png/pca2d.png       → static_pca
plots/exploratory/{variable}/png/boxplot.png     → static_boxplot
plots/exploratory/{variable}/png/density.png     → static_density
plots/exploratory/{variable}/png/sample_dendrogram.png → static_dendrogram
plots/exploratory/{variable}/png/mad_correlation.png   → static_correlation
plots/gsea/{contrast}/*.HALLMARK_*.png           → static_gsea_enrichment_plots
plots/gsea/{contrast}/*.butterfly_plot.png       → static_gsea_butterfly
plots/gsea/{contrast}/*.enplot_*.png             → static_gsea_enrichment_score

# Sarek (WGS/WES variant calling, confirmed from S3)
variant_calling/strelka/{sample}/*.strelka.variants.vcf.gz     → variant_calls
variant_calling/strelka/{sample}/*.strelka.genome.vcf.gz       → genome_variants
preprocessing/{sample}/*.recal.cram                             → aligned_reads
reports/mosdepth/{sample}/*                                     → coverage
reports/bcftools/{sample}/*                                     → variant_stats
csv/recalibrated.csv                                            → sample_tracking

# Taxprofiler (metagenomics taxonomic profiling, confirmed from S3)
kraken2/{db}/{sample}/*.kraken2.report.txt    → taxonomy_report
bracken/{db}/{sample}/*.bracken.report.txt    → abundance_estimation
metaphlan/{version}/{sample}/*.txt            → taxonomy_profile
kaiju/{db}/{sample}/*.kaiju.summary.tsv       → taxonomy_summary
centrifuge/{db}/{sample}/*                    → taxonomy_classification
krona/{tool}/{sample}/*.html                  → interactive_taxonomy_viz
diamond/{db}/{sample}/*                       → protein_alignment
nonpareil/{sample}/*                          → metagenome_coverage

# Universal (all pipelines)
multiqc/multiqc_data/multiqc_general_stats.txt  → qc_metrics
multiqc/multiqc_data/multiqc_*.txt              → tool_specific_qc
pipeline_info/params_*.json                     → pipeline_config
pipeline_info/*software*versions*.yml           → software_versions
```
