# nf-core/mcmicro 2.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the input
images and their segmentation to the cells: where they sit, what they express and their shape.
The template follows the family rules in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0
is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Do the input tiles carry consistent image metadata? |
| Data & QC | Previews | What do the registered images and their masks look like? |
| Data & QC | Segmentation | How many cells does each method find, and do they agree? |
| Cells | Spatial | Where do the cells sit, and what do they express? |
| Cells | Markers | How bright is each marker, and which markers go together? |
| Cells | Morphology | What size and shape are the cells? |

mcmicro processes multiplexed tissue images (CyCIF, CODEX and similar). A sample is one tissue
image, imaged in several cycles of a few channels each. The pipeline checks the metadata of every
tile (the prelude), corrects the illumination of each tile (BaSiCPy), stitches and registers the
cycles into one OME-TIFF (ASHLAR), subtracts autofluorescence channel by channel (Backsub),
segments the cells with each method of `--segmentation` (Mesmer, Cellpose, MCCellpose) and
measures every cell in every channel (MCQUANT). MCQUANT writes one table per image and method,
`quantification/mcquant/<segmenter>/<sample>.csv`: one row per cell with its mean intensity in
each channel of the panel, its centroid in pixels of the registered image and its regionprops
morphology. Every cell-level collection is built from those tables by the `mcquant` catalog
module.

The design comes from the samplesheet (`samples`): one row per image with its cycle count.
`cycles` (the cycle count as a label, derived by the hub recipe) is the default `GROUP_COL`; a
design column added to the sheet (tissue, patient, condition) can replace it. Every sample filter
starts there and reaches every per-image collection by `sample`. The panel comes from the marker
sheet (`markers`).

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | image |
| `markers` | the marker sheet (`MARKER_SHEET`, default `input/markers.csv`) | channel |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | check (custom content) |
| `mcquant_cells` | `quantification/mcquant/<segmenter>/<file>.csv` | image, method and cell (one column per marker) |
| `mcquant_cell_markers` | the same | image, method, cell and marker |
| `mcquant_segmentation_summary` | the same | image and method |
| `mcquant_marker_summary` | the same | image, method and marker |
| `mcquant_marker_correlation` | the same | method and marker (one column per marker) |
| `mcquant_segmenter_agreement` | the same (optional) | image and pair of methods |
| `mcmicro_previews` | `previews/previews.tsv` and its PNGs, written at fetch time (optional, Image) | preview |

mcmicro publishes neither its samplesheet nor its marker sheet, so the template ships the
megatest's (the pipeline's own `assets/samplesheet-test_full.csv` and
`assets/markers-test_full.csv`) under `input/` and reads them by default; point `METADATA_FILE`
and `MARKER_SHEET` at the sheets of another run.

### Images (PNG previews, a stand-in)

Depictio has no OME-TIFF, zarr or pyramid viewer yet. The images reach the dashboard as PNG
previews written when the run is fetched: `scripts/make_previews.py` (run by
`download_test_data.sh`; needs numpy, tifffile and Pillow) reads each registered image and each
segmentation mask and writes, at most 1024 pixels on the long side:

- one grey preview per channel of the registered image, stretched to the 0.5th and 99.5th
  percentiles of the channel's signal and named from the marker sheet;
- a composite: the nuclear stain in blue, the first two other markers in green and red;
- one outline preview per mask: the mask boundaries in yellow over the nuclear stain.

`previews/previews.tsv` lists them with their size, the full-resolution size and the scale
between the two. It is the manifest of the optional `mcmicro_previews` Image collection, which
`depictio ingest` uploads to `PREVIEW_S3_FOLDER` (a folder in the server's own bucket, one per
run). The first channel of each image (its nuclear stain) carries `underlay_sample`, the column
the cell map reads its underlay by. The illumination profiles are not previewed: BaSiCPy writes
them with a floating-point predictor that tifffile reads only with `imagecodecs`.
`TODO(bioimage)`: replace the PNG previews with an OME-TIFF / zarr pyramid viewer (viv,
deck.gl) once bioimage lands.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `cycles`, `Cycles` | group filters, the Images card and the group colours |
| `MARKER_SHEET` | `{DATA_ROOT}/input/markers.csv` | marker sheet read by `markers` |
| `PREVIEW_S3_FOLDER` | `s3://depictio-bucket/nf-core-mcmicro/previews/` | where the previews are uploaded and served from; must be in the server's bucket, one folder per run |
| `SINGLE_SEGMENTER` | unset | set for a run with one method in `--segmentation`: drops the segmenter agreement |

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The second lists the images
  (from the samplesheet), the channels quantified (from the marker sheet), and the segmentation
  methods, illumination correction and background subtraction of the run (from its parameters).
- **Pipeline**: five steps (check, register, subtract, segment, quantify), each opening the
  parameters that drive it and the tab that shows its result; the quantify step cites the cells
  measured.
- **Key figures**: four headline cards, each opening the tab that explains it. Images (split by
  the group), cells (with the spread of cells per image and method), channels quantified (split
  into nuclear stains and markers) and the median cell area (with its distribution). A group and
  an image filter above them narrow these four only.
- **Findings**: the method that finds the most cells and its share, the brightest marker by
  median intensity (nuclear stains left out), the share of one method's cells that hold a cell
  of the other, and the median eccentricity, each with a link to its tab. Below them four
  figures: the cell map beside the cells per image, then the marker intensities beside area
  against eccentricity. The bar of this section filters by group and segmenter.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, image) sit in the collapsed left panel and narrow every
tab but MultiQC (see below). The `Sample sheet` section is pinned to the bottom of every child
tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro, then a strip of key numbers (four cards, or two on
Previews and Spatial), then at most three open sections; tables follow, collapsed.

**MultiQC.** MultiQC panels only: the prelude's input image check matrix (a row per check of
tile size, pixel size, channel count, data type and exposure, a column per image, pass or
warning). It is the report's only section and custom content: its rows are checks, not
samples, so the sample filters do not reach it (a sample link would empty it rather than narrow
it; allowlisted in `test_template_conventions.py`).

**Previews.** Strip: the previews (split by stage) and the channels they show (by stage). Then
the gallery of previews; collapsed, the preview table with sizes and scale. Filters: stage and
channel. The whole tab goes with the optional Image collection.

**Segmentation.** Strip: the cells (a ring by image), cells per image and method (with its
spread), the median cell area (with its spread) and the median solidity (with its distribution).
Then the cells per image per method (log scale) beside the cell areas per method (log scale),
and the agreement between methods: per image, the share of one method's cells whose area holds
the centroid of a cell of the other. Collapsed: the per-image table. Filter: segmenter.

**Spatial.** Strip: the cells in view (by image) and their area. Then the cell map
(`spatial_cells`): one point per cell at its centroid, in the frame of its image (origin
top-left, y down), one image at a time behind a picker, sized by its area, coloured by a marker
picked in the tile (asinh, cofactor 150, clipped to the 1st and 99th percentiles of the image
shown) or by the segmenter, over the image's nuclear-stain preview when the run has previews.
The markers are every numeric column of the cell table but the regionprops measures, named by
pattern, since the panel is only known at ingest. A lasso selects cells by their run-wide
`cell_key`; the box plot below then shows the marker intensities of those cells. Collapsed: the
cell table. Filters: segmenter and a cell-area range.

**Markers.** Strip: channels quantified (nuclear stains and markers), measurements (one per cell
and channel, by image), the median marker intensity with the brightest markers ranked, and the
coefficient of variation over the cells (its spread). Then one box per marker and method of the
asinh intensities, and the marker correlation heatmap (Pearson on the asinh intensities over
every cell of a method; a row per marker and method, a column per marker, clustered). Collapsed:
the per-image marker table and the marker sheet. Filters: marker, marker role and segmenter.

**Morphology.** Strip: the median cell area (its distribution), eccentricity (its spread),
solidity (its distribution) and aspect ratio (its spread). Then every cell by its area (log) and
eccentricity, coloured by segmenter, and the area histogram per method beside the solidity per
method. Filters: segmenter, area range and eccentricity range.

## Routes and pruning

| Route | What changes |
|---|---|
| One segmentation method (`SINGLE_SEGMENTER`, the pipeline's default `--segmentation mesmer`) | No segmenter agreement: the Agreement section of Segmentation and the agreement findings row go. The collection is also optional and its recipe fails with a named reason, so an ingest that finds one method skips it even without the variable. |
| No previews (`make_previews.py` not run) | The optional Image collection is pruned at template resolution: the Previews tab (left with its intro only) is dropped by the importer, and the cell map draws without an underlay (its `background_dc_tag` resolves to nothing). The How to read list keeps a bare `Previews` label. |

The Overview's Key figures read collections every route writes, so a route never leaves a gap in
the strip.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column is
coloured `auto`; the segmenters (Mesmer, Cellpose, MCCellpose, then `auto`), the marker roles,
the channel status and the preview stages are written out; the method pairs of the agreement are
`auto`.

## Cross-selection

- The sample sheet selects on `sample`, which the links carry to every per-image collection and
  to the previews.
- The cell map and the morphology scatter select on `cell_key` (`<sample>|<segmenter>|<CellID>`,
  unique over the run), which a link carries to the per-cell marker intensities.
- A marker pick on the per-cell intensities reaches the per-image marker summary.

## Methods and assumptions

- **Sample names.** MCQUANT tables are meant to be `<sample>.csv`, but 2.0.0's rename only fires
  for a mask named `<sample>_mask`, so the Cellpose tables are published as
  `<sample>_backsub_<sample>_backsub.csv`. The sample is read back from either shape.
- **Markers.** A marker column is a numeric column that is not `CellID` or a regionprops
  measure; a nuclear stain is a marker whose name starts with DNA, DAPI, Hoechst or a similar
  counterstain name.
- **asinh.** Summaries and the cell map read intensities through `asinh(x / 150)`.
- **Agreement.** Without the masks, a cell of one method holds a cell of the other when the
  other's centroid lies within the disc of its area. A whole-cell method against a nuclear one
  reads asymmetric by design: every whole cell holds a nucleus, few nuclei hold a whole-cell
  centroid.
- **Correlation.** Taken over every cell of a method on every image, so it is not narrowed by
  the image filter.
- **Units.** Areas and axes are in pixels of the registered image; the pixel size (0.65 µm in
  the megatest) is in the OME metadata and is not applied.
