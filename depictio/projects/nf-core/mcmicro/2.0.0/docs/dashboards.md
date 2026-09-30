# nf-core/mcmicro 2.0.0: Depictio dashboards

This template turns the output of [nf-core/mcmicro](https://nf-co.re/mcmicro) 2.0.0 into a
five-tab Depictio dashboard. mcmicro takes multi-cycle, multi-tile immunofluorescence images
(CyCIF, CODEX, mIHC), optionally corrects their illumination with BaSiCPy, stitches and
registers the cycles into one mosaic with ASHLAR, optionally subtracts autofluorescence with
Backsub, segments cells with one or more modules (Mesmer, Cellpose, MCCellpose) and measures
every marker in every cell with MCQUANT. The dashboard is a paper companion: each sample's
image next to its mask, its cells and their marker intensities, with QC and filters around
them. It is not an image analysis suite and reads only what the run published.

Data comes from the AWS megatest run `results-f4400001578642e370a72668966c6602fe172ef6`
(the 2.0.0 release tag, `test_full` profile): two samples of two cycles each, BaSiCPy,
Backsub, and Mesmer plus Cellpose segmentation.

---

## How the dashboard is built

- **Images are bioimage collections.** `registration/ashlar/<sample>.ome.tif` (pyramidal
  OME-TIFF) is the image the viewer reads tile by tile. The segmentation masks
  (`segmentation/<module>/...tif`, plain integer TIFFs) are `kind: labels` collections whose
  `sample_pattern` maps the decorated file name (`<sample>_mask.tif`,
  `<sample>_backsub.ome_cp_masks.tif`) back to the sample. The viewer draws the mask of the
  sample it shows; a label value is the MCQUANT `CellID`, so the cell table's colour column,
  filters and lasso reach the labels.
- **One segmenter drives the Image and Markers tabs.** mcmicro can run several segmentation
  modules at once and a label value is only a cell id within its own mask, so the template
  variable `SEGMENTER` (default `mesmer`) picks the module whose mask and cells those tabs
  read, and `COMPARE_SEGMENTER` (default `cellpose`) the one shown in the Segmentation QC
  tab's second viewer. mcmicro's own default is `mccellpose`: pass
  `--var SEGMENTER=mccellpose` for such a run. The compare collections are optional, so a
  single-module run ingests and that viewer stays empty.
- **The cell table.** `mcquant/cells.py` reads every MCQUANT CSV
  (`quantification/mcquant/<module>/<sample>.csv`), takes the module from the directory and
  the sample from the file name (mcmicro keeps MCQUANT's `<image>_<mask>.csv` name when the
  two do not line up, e.g. `<sample>_backsub_<sample>_backsub.csv`), and keeps every marker
  column under the marker sheet's name. Two derived columns make it readable without knowing
  the panel: `dominant_marker` (per cell, the non-nuclear marker whose log1p intensity sits
  highest above that marker's median in the same sample, as a robust z-score; nuclear stains
  are recognised by the `DNA`, `DAPI` and `Hoechst` name prefixes) and `pc_1` / `pc_2` (the
  first two principal components of the standardised log1p intensities, fitted per module
  over every sample).
- **The long marker table is capped.** `mcquant/marker_long.py` melts at most 5000 cells per
  sample and module (every k-th cell in `CellID` order, a deterministic stride), so a
  whole-slide run with hundreds of thousands of cells per sample keeps a distribution table
  of a readable size. The per-cell table keeps every cell.
- **Design.** The optional design table (`METADATA_FILE`, sample id in `METADATA_ID_COL`,
  factor in `GROUP_COL`) becomes the `condition` column of the `samples` hub. Without it
  `condition` is `all`. The bundled reference run uses `input/metadata.tsv`, whose
  `acquisition` column records which two cycles each sample was built from.
- **Filters on two levels.** The pinned persistent `Sample filters` section (sample,
  condition) reaches every table through the project links; every tab adds an open section
  on its own columns (cycles imaged on MultiQC, module and marker on Slide overview, dominant
  marker, area and eccentricity on Image and cells, marker, stain type and dominant marker on
  Markers, module, area and solidity on Segmentation QC).
- **A glance strip on every tab.** `Run at a glance` is a pinned persistent four-card strip:
  samples by condition, cells segmented by `SEGMENTER` (top 3 samples), markers quantified
  (markers against nuclear stains) and the cell area spread.
- **Viewer tiles spell their config out.** The two `bioimage_viewer` tiles carry the explicit
  image, labels, sample and points bindings. The catalog also ships the same binding as the
  render `ashlar/cell_overlay` (image, Mesmer labels, MCQUANT cells); a later pass can switch
  the tiles to `use:` it once catalog image outputs are live.

## MultiQC

mcmicro's MultiQC report carries the pipeline's own input checks: before stitching it reads
every raw cycle image's OME-XML and the samplesheet and checks tile size, pixel size, channel
count, data type and exposure times for consistency. The tab shows that pass / warn / fail
matrix (`multiqc/matrix_summary`), one column per sample. The acquisition parameters behind
it (pixel size, channels, tiles per cycle) are the pinned `Reference tables` at the bottom of
every tab, parsed from the per-cycle `*_samplesheet_mqc.tsv` checks.

## Slide overview

What each slide yielded: the number of segmentation modules, the cells of every module, the
dominant-marker diversity and the marker intensity spread as cards; cells per sample and
module as grouped bars; the log1p intensity per sample for the markers picked on the left;
and cells per dominant marker per sample. When Backsub ran, the channel sheet of the corrected
image (marker, cycle, exposure, background channel removed) is a collapsed table.

## Image and cells

The registered image of the first sample picked in `Sample filters`, with the `SEGMENTER`
mask drawn over it (40 % fill, outlines on) and one point per cell coloured by its dominant
marker. The cell filters (dominant marker, area, eccentricity) narrow the points, the table
and the cards together. A lasso on the points narrows the full-width cell table below; a row
picked there opens the `Cell record` in the `Cell detail` section (position, shape, place on
the marker PCA).

## Markers

The panel read across cells: one box per marker of log1p intensity (nuclear stains coloured
apart), the marker by sample heatmap of median log1p intensity, the cells on their first two
marker components (lasso-enabled, colour by any column from the header) and a group
comparison (`group_compare`, Wilcoxon on log1p intensity) that opens on two levels of the
design condition and switches to two saved cell selections once they exist.

## Segmentation QC

How the modules differ on the same image: cells per module and the median area,
eccentricity and solidity as cards; area and eccentricity per module as boxes; a
parallel-coordinates view with one line per sample and module across cell count and median
shape; the `COMPARE_SEGMENTER` mask and cells over the same registered image, coloured by
area; and the per-sample roll-up table with its record card.

## Catalog outputs

| Tool | Output | Kind |
|---|---|---|
| ashlar | `registered_image` | bioimage, OME-TIFF image (+ render `cell_overlay`) |
| backsub | `image`, `markers` | bioimage OME-TIFF; channel sheet table |
| basicpy | `flatfield`, `darkfield` | bioimage, OME-TIFF image |
| deepcell | `mesmer_mask` | bioimage, TIFF labels |
| cellpose | `mask`, `mccellpose_mask` | bioimage, TIFF labels |
| coreograph | `core_centroids`, `core_masks` | table; bioimage TIFF labels |
| mcquant | `cells`, `marker_long`, `marker_matrix`, `sample_summary` | tables |
| multiqc | `matrix_summary` | MultiQC custom content |

## Reproducing

```bash
# 1. Fetch the megatest (53 files, about 44 MB)
bash depictio/projects/nf-core/mcmicro/2.0.0/download_test_data.sh

# 2. Copy the vendored samplesheet, marker sheet and design table
mkdir -p ~/Data/depictio-nfcore/mcmicro/2.0.0/megatest/input
cp depictio/projects/nf-core/mcmicro/2.0.0/input/* ~/Data/depictio-nfcore/mcmicro/2.0.0/megatest/input/

# 3. Dry run, then ingest
depictio-cli run --template nf-core/mcmicro/2.0.0 \
  --data-root ~/Data/depictio-nfcore/mcmicro/2.0.0/megatest \
  --var METADATA_FILE=$HOME/Data/depictio-nfcore/mcmicro/2.0.0/megatest/input/metadata.tsv --dry-run
```
