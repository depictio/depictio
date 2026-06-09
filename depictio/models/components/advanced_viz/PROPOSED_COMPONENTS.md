# Proposed advanced-viz components

Design specs for new `advanced_viz` `viz_kind`s surfaced by the
[nf-core pipeline gap analysis](../../../projects/nf-core/CANDIDATE_PIPELINES.md).

Each spec is shaped to drop cleanly into the existing pattern in
[`configs.py`](./configs.py) / [`schemas.py`](./schemas.py) /
[`types.py`](../types.py), plus a React renderer alongside the existing
ones at `packages/depictio-react-core/src/components/advanced_viz/*Renderer.tsx`.

Ranked by reuse — top of list = highest-leverage build.

---

## 1. `signal_profile` — feature-anchored meta-profile + heatmap

**Pipelines unlocked:** `atacseq`, `chipseq`, `methylseq` (3 direct) — plus future
`cutandrun` and `rnafusion` meta-profiles.

**What it renders.** Two stacked panels sharing an x-axis (`-N` … `+N` bp around feature
center, typically a TSS or peak summit):
- Top: aggregate profile — mean signal across rows, one line per sample/group, optional
  ±SE ribbon. Same primitive as deepTools `plotProfile`.
- Bottom: heatmap — one row per feature (peak/TSS), one column per bin, colour = signal.
  Optional row-sort by max intensity. Same primitive as deepTools `plotHeatmap`.

**Input shape.** Long-format DC, one row per (sample, feature, bin):

| role           | dtype     | notes |
|----------------|-----------|-------|
| `sample_id`    | `_STRING` | sample / group identifier |
| `feature_id`   | `_STRING` | peak / TSS / region identifier |
| `bin`          | `_INT`    | bin offset from feature center (negative = upstream) |
| `signal`       | `_FLOAT`  | mean signal in bin (counts, fold-enrichment, %methylation) |
| `category`     | `_STRING` | *optional* — group rows (e.g. peak class, methylation context) |

### `configs.py` snippet

```python
class SignalProfileConfig(_BaseVizConfig):
    """Feature-anchored signal meta-profile + heatmap.

    Long-format input: one row per (sample, feature, bin). Bin is offset
    (bp) from feature center — typically a TSS or peak summit. Top panel
    is the per-sample mean across features; bottom panel is the
    feature × bin heatmap. Universal across ATAC / ChIP / methyl /
    CUT&RUN protocols.
    """

    viz_kind: Literal["signal_profile"] = "signal_profile"

    sample_id_col: str = Field(..., description="Sample / group identifier")
    feature_id_col: str = Field(..., description="Feature (peak/TSS/region) identifier")
    bin_col: str = Field(..., description="Bin offset (bp) from feature center")
    signal_col: str = Field(..., description="Signal value (counts / FE / %methylation)")
    category_col: str | None = Field(
        default=None, description="Optional row-grouping (peak class, methylation context)"
    )

    # Display defaults — editable from the viz Settings popover.
    flank_bp: int = Field(default=2000, ge=100, le=20000, description="±bp window")
    bin_size_bp: int = Field(default=50, ge=10, le=500)
    row_sort: Literal["max_intensity", "category", "none"] = Field(default="max_intensity")
    color_scale: Literal["viridis", "Blues", "Reds", "RdBu_r"] = Field(default="viridis")
    show_ci: bool = Field(default=True, description="±SE band on the top profile")
    log_signal: bool = Field(default=False)
```

### `schemas.py` snippet

```python
# CANONICAL_SCHEMAS
"signal_profile": {
    "sample_id": _STRING,
    "feature_id": _STRING,
    "bin": _INT,
    "signal": _FLOAT,
},

# ROLE_NAMES
"signal_profile": {
    "sample_id": frozenset({"sample_id", "sample", "group"}),
    "feature_id": frozenset({"feature_id", "peak_id", "tss_id", "region_id"}),
    "bin": frozenset({"bin", "offset", "bp_offset", "position"}),
    "signal": frozenset({"signal", "value", "coverage", "methylation", "fe"}),
},

# _OPTIONAL_ROLES
"signal_profile": {
    "category": _STRING,
},
```

### `types.py` change

Add `"signal_profile"` to `AdvancedVizKind`. Add `SignalProfileConfig` to the
`VizConfig` discriminated union in `configs.py`.

### React renderer

`packages/depictio-react-core/src/components/advanced_viz/SignalProfileRenderer.tsx` —
register in `AdvancedVizFrame.tsx` dispatcher. Heavy aggregation runs server-side
(Celery task with binning + per-sample mean/SE); the renderer plots the returned
profile + heatmap Plotly dict.

### Estimated effort
~3-4 days backend (config + Celery aggregation + binding tests), ~3 days renderer.

---

## 2. `cnv_ideogram` — chromosome ideogram with CNV gains/losses + ROH bands

**Pipelines unlocked:** `raredisease` (1 direct) — plus latent `sarek` somatic CNV,
`oncoanalyser`, `hgtseq`.

**What it renders.** Karyogram-style chromosome ideogram (24 chromosomes by default for
human). Each chromosome a horizontal bar with cytoband shading; CNV calls drawn as
coloured rectangles above (gains = blue, losses = red, height ∝ |log2 ratio|); ROH
intervals drawn as a thin grey band below. Hover surfaces gene overlaps.

**Input shape.** Long-format DC, one row per CNV / ROH interval:

| role          | dtype     | notes |
|---------------|-----------|-------|
| `sample_id`   | `_STRING` | sample identifier (for sample picker) |
| `chr`         | `_STRING` | chromosome label (1..22, X, Y, MT) |
| `start`       | `_INT`    | interval start (bp) |
| `end`         | `_INT`    | interval end (bp) |
| `event_type`  | `_STRING` | `gain` / `loss` / `roh` / `neutral` |
| `effect`      | `_FLOAT`  | *optional* — log2 ratio / copy number / depth |

### `configs.py` snippet

```python
class CnvIdeogramConfig(_BaseVizConfig):
    """Chromosome ideogram with CNV gains/losses + ROH bands.

    Renders all chromosomes for one sample at a time (sample picker
    surfaced in the viz controls). CNV gains/losses appear as coloured
    rectangles above each chromosome; ROH intervals as a thin band
    below. Cytobands shaded by Giemsa stain when assembly is provided.
    """

    viz_kind: Literal["cnv_ideogram"] = "cnv_ideogram"

    sample_id_col: str = Field(..., description="Sample identifier")
    chr_col: str = Field(..., description="Chromosome label")
    start_col: str = Field(..., description="Interval start (bp)")
    end_col: str = Field(..., description="Interval end (bp)")
    event_type_col: str = Field(..., description="Event type: gain/loss/roh/neutral")
    effect_col: str | None = Field(
        default=None, description="Optional |log2 ratio| or copy number for bar height"
    )

    assembly: Literal["GRCh37", "GRCh38", "T2T-CHM13"] = Field(default="GRCh38")
    show_cytobands: bool = Field(default=True)
    chromosomes_filter: list[str] | None = Field(
        default=None, description="Whitelist; null = all autosomes + X/Y"
    )
    min_event_bp: int = Field(default=10_000, ge=0)
```

### `schemas.py` snippet

```python
# CANONICAL_SCHEMAS
"cnv_ideogram": {
    "sample_id": _STRING,
    "chr": _STRING,
    "start": _INT,
    "end": _INT,
    "event_type": _STRING,
},

# ROLE_NAMES
"cnv_ideogram": {
    "sample_id": frozenset({"sample_id", "sample"}),
    "chr": frozenset({"chr", "chrom", "chromosome", "#chrom"}),
    "start": frozenset({"start", "pos", "begin"}),
    "end": frozenset({"end", "stop"}),
    "event_type": frozenset({"event_type", "type", "call", "cnv_type"}),
},

# _OPTIONAL_ROLES
"cnv_ideogram": {
    "effect": _FLOAT,
},
```

### React renderer

`CnvIdeogramRenderer.tsx`. Bundled cytoband tracks for GRCh37/38 + T2T live alongside
the existing `genome_annotations/` registry used by `CoverageTrackRenderer`.

### Estimated effort
~3 days backend (config + assembly bundling), ~5 days renderer (ideogram + cytobands +
interaction).

---

## 3. `knee_qc` — barcode-rank knee + per-cell QC scatter

**Pipelines unlocked:** `scrnaseq` (1 direct) — plus latent any droplet-based protocol
(spatial-transcriptomics, CITE-seq, multiome).

**What it renders.** Two side-by-side panels:
- Left: barcode-rank knee — log10(rank) vs log10(total UMI), one trace per sample,
  inflection point marked, empty-droplet threshold line.
- Right: per-cell QC scatter — `total_counts` (x) vs `n_genes_detected` (y), point colour
  = `pct_mito`, threshold guidelines for typical filters.

**Input shape.** One row per barcode/cell:

| role               | dtype     |
|--------------------|-----------|
| `sample_id`        | `_STRING` |
| `barcode`          | `_STRING` |
| `total_counts`     | `_INT`    |
| `n_genes_detected` | `_INT`    |
| `pct_mito`         | `_FLOAT`  |

### `configs.py` snippet

```python
class KneeQcConfig(_BaseVizConfig):
    """Single-cell knee + per-cell QC diagnostic.

    Standard pre-clustering QC view for droplet protocols (10x, drop-seq).
    Left panel: barcode-rank knee per sample. Right panel: counts vs
    n_genes scatter, coloured by %mito.
    """

    viz_kind: Literal["knee_qc"] = "knee_qc"

    sample_id_col: str = Field(..., description="Sample identifier")
    barcode_col: str = Field(..., description="Cell barcode")
    total_counts_col: str = Field(..., description="Total UMI counts per barcode")
    n_genes_col: str = Field(..., description="Genes detected per barcode")
    pct_mito_col: str | None = Field(
        default=None, description="% mitochondrial reads (point colour on QC scatter)"
    )

    knee_log_axes: bool = Field(default=True)
    min_counts_default: int = Field(default=500, ge=0)
    min_genes_default: int = Field(default=200, ge=0)
    max_pct_mito_default: float = Field(default=20.0, ge=0.0, le=100.0)
```

### `schemas.py` snippet

```python
# CANONICAL_SCHEMAS
"knee_qc": {
    "sample_id": _STRING,
    "barcode": _STRING,
    "total_counts": _INT,
    "n_genes": _INT,
},

# ROLE_NAMES
"knee_qc": {
    "sample_id": frozenset({"sample_id", "sample"}),
    "barcode": frozenset({"barcode", "cell_barcode", "cb"}),
    "total_counts": frozenset({"total_counts", "n_counts", "total_umi", "nCount_RNA"}),
    "n_genes": frozenset({"n_genes", "n_genes_detected", "nFeature_RNA"}),
},

# _OPTIONAL_ROLES
"knee_qc": {
    "pct_mito": _FLOAT,
},
```

### Estimated effort
~2 days backend, ~3 days renderer.

---

## 4. `bin_qc_scatter` — assembly bin completeness vs contamination

**Pipelines unlocked:** `mag` (1 direct) — plus latent `bacass` + any assembly-QC dashboard.

**What it renders.** Scatter plot, one point per bin: x = completeness (%), y =
contamination (%). Point size = bin size (Mb), colour = N50 or refinement tool. Reference
quality thresholds drawn as guidelines (high-quality ≥ 90/≤ 5, medium ≥ 50/≤ 10).

**Input shape.** One row per bin:

| role            | dtype     |
|-----------------|-----------|
| `sample_id`     | `_STRING` |
| `bin_id`        | `_STRING` |
| `completeness`  | `_FLOAT`  |
| `contamination` | `_FLOAT`  |
| `bin_size_bp`   | `_INT`    (optional) |
| `n50`           | `_INT`    (optional) |
| `tool`          | `_STRING` (optional) |

### `configs.py` snippet

```python
class BinQcScatterConfig(_BaseVizConfig):
    """Bin-level assembly QC (completeness vs contamination).

    Canonical CheckM / QUAST output view. One point per bin, with the
    MIMAG quality thresholds drawn as reference lines.
    """

    viz_kind: Literal["bin_qc_scatter"] = "bin_qc_scatter"

    sample_id_col: str = Field(..., description="Sample / assembly identifier")
    bin_id_col: str = Field(..., description="Bin identifier")
    completeness_col: str = Field(..., description="Completeness (%)")
    contamination_col: str = Field(..., description="Contamination (%)")
    bin_size_col: str | None = Field(default=None, description="Bin size (bp) — point size")
    n50_col: str | None = Field(default=None, description="N50 (bp) — point colour")
    tool_col: str | None = Field(default=None, description="Binning tool (point shape)")

    show_mimag_thresholds: bool = Field(default=True)
```

### `schemas.py` snippet

```python
# CANONICAL_SCHEMAS
"bin_qc_scatter": {
    "sample_id": _STRING,
    "bin_id": _STRING,
    "completeness": _FLOAT,
    "contamination": _FLOAT,
},
```

### Estimated effort
~1 day backend, ~1 day renderer (mostly a thin Plotly scatter wrapper).

---

## 5. `gene_context_map` — linear contig gene-hit map

**Pipelines unlocked:** `funcscan` (1 direct) — narrow; distinct from `lollipop` and
`coverage_track`.

**What it renders.** One horizontal contig per row, with gene hits drawn as coloured
arrows (direction = strand, colour = category — AMR class, BGC type). Hover surfaces the
gene name + tool that called it. Optionally faceted per-sample.

**Input shape.** One row per gene hit:

| role         | dtype     |
|--------------|-----------|
| `contig_id`  | `_STRING` |
| `gene_id`    | `_STRING` |
| `start`      | `_INT`    |
| `end`        | `_INT`    |
| `strand`     | `_STRING` |
| `category`   | `_STRING` |

### `configs.py` snippet

```python
class GeneContextMapConfig(_BaseVizConfig):
    """Linear contig map of gene hits (AMR / BGC / virulence).

    One contig per subplot row; each gene is a coloured arrow with
    strand direction. Designed for funcscan's hAMRonization /
    antiSMASH output but generalises to any contig-anchored feature
    table.
    """

    viz_kind: Literal["gene_context_map"] = "gene_context_map"

    contig_id_col: str = Field(..., description="Contig identifier (subplot row)")
    gene_id_col: str = Field(..., description="Gene identifier")
    start_col: str = Field(..., description="Gene start (bp on contig)")
    end_col: str = Field(..., description="Gene end (bp on contig)")
    strand_col: str = Field(..., description="Strand: + / -")
    category_col: str = Field(..., description="Hit category (AMR class, BGC type, ...)")

    sample_col: str | None = Field(default=None, description="Optional sample for faceting")
    max_contigs_per_view: int = Field(default=8, ge=1, le=50)
```

### `schemas.py` snippet

```python
# CANONICAL_SCHEMAS
"gene_context_map": {
    "contig_id": _STRING,
    "gene_id": _STRING,
    "start": _INT,
    "end": _INT,
    "strand": _STRING,
    "category": _STRING,
},
```

### Estimated effort
~1 day backend, ~2 days renderer.

---

## Implementation checklist (per kind)

For each `viz_kind` above, the wiring is mechanical:

1. **`depictio/models/components/advanced_viz/configs.py`** — add the `Config` class +
   include in the `VizConfig` discriminated union.
2. **`depictio/models/components/advanced_viz/schemas.py`** — add `CANONICAL_SCHEMAS`,
   `ROLE_NAMES`, and `_OPTIONAL_ROLES` entries.
3. **`depictio/models/components/types.py`** — add the literal to `AdvancedVizKind`.
4. **`packages/depictio-react-core/src/components/advanced_viz/<Name>Renderer.tsx`** —
   author the React renderer (data fetch + Plotly figure).
5. **`packages/depictio-react-core/src/components/advanced_viz/AdvancedVizFrame.tsx`** —
   register the renderer in the dispatcher.
6. **Server-side compute (Celery)** for any heavy aggregation (`signal_profile` only).
7. **Tests** — extend `depictio/tests/models/test_advanced_viz_schemas.py` and add a
   binding test.
8. **Reference data** — one pipeline scaffold (e.g. `chipseq` for `signal_profile`) wired
   up end-to-end, with `STATIC_IDS` entry + reseed.

## Out of scope here

These specs are documentation. The actual `configs.py` / `schemas.py` / `types.py` /
TSX renderer files are not modified by the scaffolds shipping alongside this doc —
wiring them requires a TSX renderer + binding tests + a reseed (none runnable in a
remote web session without Docker + megatest data).
