# nf-core/molkart 1.2.0: validation report

Status: **offline only**. The AWS megatest of 1.2.0 published `pipeline_info/` and nothing
else, so the template was authored from the pipeline's `docs/output.md`, its module
`publishDir` declarations, `bin/spot2cell.py`, `bin/collect_QC.py`, `conf/test*.config` and
the test-datasets `molkart` branch. Every item marked HPC below waits for the test_full run
(`scripts/nfcore_validation_hpc.py`, key `molkart`).

## Offline checks

| Check | Result |
| --- | --- |
| `catalog validate --path` on spot2cell, molkartqc, mindagap, stardist, ilastik | OK |
| `test_catalog.py`, `test_catalog_source_from_use.py` | pass |
| `test_shipped_dashboard_yamls.py`, `test_template_conventions.py`, `test_nfcore_megatest.py` (`-k molkart`) | pass |
| every recipe through `execute_recipe` on the synthetic tree | schemas match |
| `depictio-cli run --template nf-core/molkart/1.2.0 --dry-run` on the synthetic tree | 8/8 steps |

Synthetic tree: 3 samples (two named like the test_full samples' layout, one like the
`-profile test` sample), 3 methods (mesmer, cellpose, stardist) with a seeded Voronoi
stand-in for segmentation, pyramidal OME-TIFF CLAHE images, raw and filtered masks, and
spot2cell / molkartqc outputs computed with the pipeline's own algorithms on the
test-datasets spot table. Recipe output: 468 cells (156 primary), 415 cell-gene rows, 432
gene-summary rows, a 40 x 4 heatmap, 9 QC rows, 146 marked-spot rows.

## Needs the HPC run

- Real file names: the `IMAGE_SAMPLE_PATTERN` default and the label `sample_pattern`
  were tested on names derived from `conf/modules.config`, not on published files.
- CLAHE location: the 1.2.0 megatest trace suggests the images land at the outdir root;
  the scan is recursive, so either location matches.
- Symlinked publishes (MOLKARTQC, MINDAGAP, STARDIST, DEEPCELL_MESMER, CELLPOSE, ILASTIK):
  the fetch must use `rsync -L`.
- Viewer: the CLAHE image is a pyramidal OME-TIFF named `.tiff`, which the bioimage scan
  (`.ome.tif` / `.ome.tiff` only) does not accept yet. Until it does, the `mk-img` DC
  finds no store and both viewers show labels and points only.
- Cell counts, label id alignment between filtered masks and spot2cell `CellID`, and
  tile performance on full-size images.
