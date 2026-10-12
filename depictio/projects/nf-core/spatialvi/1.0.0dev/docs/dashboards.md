# nf-core/spatialvi 1.0.0dev: Depictio dashboards

> **Unreleased pipeline.** [nf-core/spatialvi](https://nf-co.re/spatialvi) (formerly
> spatialtranscriptomics) has no release. This template follows the `dev` branch pinned at
> `441ded53109f57ecf70555fb0b060546b34b4a2c` (2026-09-15, manifest `1.0dev`, Nextflow
> `>=25.10.4`). Its outputs may change before the first release. There is no AWS megatest:
> the reference run is the `test` profile on the EMBL cluster
> (`scripts/nfcore_validation_hpc.py`, key `spatialvi`). See `megatest.yaml` and
> `VALIDATION_REPORT.md`.

spatialvi processes 10x Visium data. It runs Space Ranger count (or takes existing Space
Ranger outputs), reads each sample into a SpatialData store, and filters the spots and
genes. It clusters each sample with Leiden, ranks spatially variable genes with squidpy
(Moran's I by default), then concatenates the samples and integrates them (Harmony by
default) before clustering again.

## Dashboard funnel

1. **MultiQC.** The pinned glance strip (samples, spots under tissue, reads, spatially
   variable genes) and the sample sheet. Below them: Space Ranger's median genes,
   saturation and genomic DNA curves, FastQC, and the spots and genes removed by the QC
   filter.
2. **Space Ranger QC.** Genes, UMIs, saturation and tissue coverage per sample. Also depth
   against genes per spot, confident mapping, the capture array coloured by tissue call,
   the metrics table and a sample record linked to it.
3. **Tissue & spots.** The hires tissue image of `IMAGE_SAMPLE`, with one point per kept
   spot coloured by Leiden cluster. A lasso narrows the spot table, and a row opens the
   **Spot detail** record. Spot QC (UMIs against genes, UMIs by cluster) sits below.
4. **Spatially variable genes.** Spatial score against significance, the score per
   sample, the ranked gene table and a gene record linked to it.
5. **Integration.** Spots per cluster and per sample, for both clusterings. Also how the
   per-sample clusters split across the integrated ones, and the tissue coloured by
   integrated cluster.

Every tab carries the pinned Sample and `{GROUP_COL_DISPLAY}` filters and the four-card
glance strip. Each tab also has its own open filter section.

When `GENES` is set, a second dashboard, **Genes on tissue**, colours the spots by the
expression of one picked gene and shows expression by cluster.

## Data collections

| Tag | Source | One row per |
| --- | --- | --- |
| `samples` | union of the samples below, plus `METADATA_FILE` | sample |
| `metadata` | `METADATA_FILE`, optional | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC plot |
| `sv-qc-metrics` | `<sample>/spaceranger/outs/metrics_summary.csv` | sample |
| `sv-qc-spots` | `<sample>/spaceranger/outs/spatial/tissue_positions.csv` | capture spot |
| `sv-svg-genes` | `<sample>/data/<sample>_svg.csv` | sample and gene |
| `sv-img-tissue` | `integration/data/merged.zarr`, `images/<IMAGE_SAMPLE>_hires_image` | image |
| `spatialdata_visium_spots` | `tables/<IMAGE_SAMPLE>_table` in `merged.zarr`, plus the integrated store | kept spot |
| `sv-int-composition` | the spots table | sample, clustering and cluster |
| `sv-genes-expression` | `X` of the same table, `GENES` only | spot and gene |

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_ROOT` | | the run's `--outdir`, with the `--input` sheet copied to `input/` |
| `IMAGE_SAMPLE` | | sample read by the image and spot tabs, spelt as the store names it (letters, digits, `_` and `-` only) |
| `INTEGRATION_METHOD` | `harmony` | names the integrated store `<method>.zarr` |
| `GENES` | unset | comma-separated var names (gene ids of the reference) that add the Genes on tissue dashboard |
| `METADATA_FILE` | unset | design table, the pipeline sample sheet by default in the reference run |
| `METADATA_ID_COL` | `sample` | design-table sample column |
| `GROUP_COL` / `GROUP_COL_DISPLAY` | `slide` / `Slide` | design column of the pinned group filter |

## Limitations

- **One sample on the image.** The stores name their elements after the sample, and a
  collection reads one element path. The Tissue & spots, Integration and Genes tabs
  therefore show `IMAGE_SAMPLE` only. The Space Ranger and spatially variable gene tabs
  cover every sample.
- **Coordinates.** `obsm["spatial"]` in these stores is already in hires pixels, so the
  spot tables read x and y from the spot shapes (`coordinates: region`).
- **Gene ids.** The stores use the reference's gene ids (Ensembl ids on a Space Ranger
  reference) as var names. `GENES` takes those ids, not symbols. For the same reason,
  the pipeline's `MT-` prefix test finds no mitochondrial genes, so the mitochondrial
  share reads 0.
- **Sample ids with dots.** The store drops characters other than letters, digits, `_`
  and `-` from element names. Spots of such a sample get no integrated cluster.
- **AnnData outputs** (`<sample>/data/*.h5ad`) are not read.
- **MultiQC.** The Space Ranger count module and the spot-filter custom content are read
  from the parquet. Runs without FASTQ input (Space Ranger outputs given) have no FastQC
  panels.
