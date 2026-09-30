# nf-core/mcmicro 2.0.0: template validation report

## Goal

A deployable paper-companion dashboard for any nf-core/mcmicro 2.0.0 run: each sample's
registered image with its segmentation mask and MCQUANT cells, the marker panel read across
cells and samples, and a comparison of the segmentation modules, on top of the MultiQC input
checks.

## Data used

AWS megatest `s3://nf-core-awsmegatests/mcmicro/results-f4400001578642e370a72668966c6602fe172ef6`
(2.0.0 release, `test_full` profile), 53 files, about 44 MB, at
`~/Data/depictio-nfcore/mcmicro/2.0.0/megatest/`. Two samples of two cycles each, BaSiCPy,
Backsub, Mesmer and Cellpose. The samplesheet, marker sheet and a design table are vendored
in `input/` (the run publishes none of them).

## Offline validation (no server, no ingestion)

| Check | Result |
|---|---|
| `pytest test_shipped_dashboard_yamls.py test_template_conventions.py -k mcmicro` | 18 passed |
| catalog tool dirs loaded in isolation (`_load_tool_dir`), bioimage render partners | OK |
| every recipe on the megatest (`depictio.recipes.execute_recipe`) | OK, schemas as declared |
| `python -m depictio.cli run --template nf-core/mcmicro/2.0.0 ... --dry-run` | 8/8 steps, with and without METADATA_FILE |
| scan regexes and `sample_pattern` against the megatest paths | every image and mask matched, samples recovered |

Recipe outputs on the megatest: `mc-cells` 4303 cells (Mesmer 2114 + 2085, Cellpose 72 + 32),
`mc-cells-primary` 4199, `mc-markers-long` 30121 rows (all cells, under the 5000 cap),
`mc-marker-matrix` 7 markers by 2 samples, `mc-sample-summary` 4 rows, `mc-acquisition` 4
rows, `mc-backsub-markers` 14 rows. Mask label counts equal MCQUANT row counts (Mesmer
2114 labels, Cellpose 72 for the first sample).

## Not verified here

- Labels ingest (`format: tiff`, `kind: labels`, `sample_pattern`) and the labels overlay:
  depends on the platform labels work landing; not run.
- `mccellpose` masks: no run with them; its `.ome.tif` mask is declared `format: tiff`.
- Coreograph outputs: no TMA run; the centroid recipe was tested on a file written with the
  tool's own `numpy.savetxt(fmt="%10.5f")` call.
- The MultiQC `matrix_summary` panel against the conformance parquet (needs a stub).
- Full ingestion, rendering and the group comparison job (no stack).

## Discrepancies

### MC-D1: the mcquant table name is not always `<sample>.csv`
mcmicro renames MCQUANT's output to `<sample>.csv` only when the image and mask names line
up; the Cellpose run keeps `<sample>_backsub_<sample>_backsub.csv`. The recipe strips the
repeated tail and the stage words, verified on both.

### MC-D2: the Cellpose mask keeps Cellpose's own name
`modules.config` renames `<id>.ome_cp_masks.tif` to `<id>_mask.tif`, but on this run the
file is `<sample>_backsub.ome_cp_masks.tif`. The `sample_pattern` accepts both.

### MC-D3: the pipeline default segmenter is not the megatest's
mcmicro defaults to `mccellpose`; the megatest ran `mesmer,cellpose`. `SEGMENTER` defaults
to `mesmer` so the reference run works as shipped; a default run needs
`--var SEGMENTER=mccellpose`.

### MC-D4: MultiQC holds only the input checks
The run's parquet carries one custom-content section (`matrix_summary`), so the MultiQC tab
is one panel. The acquisition checks behind it are parsed into the pinned reference table.
