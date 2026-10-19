# nf-core/mcmicro 2.0.0 template validation report

Validated offline against the AWS megatest `results-f4400001578642e370a72668966c6602fe172ef6`
(the 2.0.0 release tag, `Full test profile`, run 2026-07-02). Two samples, each registered from
two cycles of the CyCIF tonsil test images (four channels per cycle, nine 220 x 180 px tiles,
0.65 µm pixels), BaSiCPy illumination, background subtraction, Mesmer and Cellpose segmentation,
MCQUANT. Whole run: 59 objects, 48 MB; the fetched subset is 45 files, 44 MB, the images
included (`bash download_test_data.sh`), plus 22 PNG previews (4.7 MB) written by
`scripts/make_previews.py`.

No running stack was available for this build: the live check of RULES section 15 is listed
below as pending, item by item, with what remains to be checked for the Image collection.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k mcmicro` (plus the allowlist tests) | 59 passed |
| `test_advanced_viz_config_alignment.py`, `test_catalog.py` | 207 passed |
| `depictio dev catalog validate` | pass, 125 tools |
| `depictio/tests/recipes/test_mcmicro_recipes.py` (catalog recipes, file naming, agreement geometry, the preview helper) and `test_mcmicro_project_recipes.py` (the two hubs) | 24 passed |
| `depictio/tests/catalog/`, `depictio/tests/recipes/` | 543 passed, 4 failed: `test_conformance_project.py` wants the conformance project regenerated for the new `mcquant` module (and for the other wave 4 modules already on the branch; shared file, regenerated at integration) |
| Every recipe over the megatest (`execute_recipe`, input and output schemas) | pass, 9 recipe collections, under 1 s each |
| `depictio ingest --template nf-core/mcmicro/2.0.0 --dry-run` on the megatest | template resolved, 10 of 10 collections `ok` (the Image collection included), 0 empty, 0 missing sources; stops at step 1 (no server configured) |
| Resolved config validated as `Workflow` models in the CLI context (the Image collection's `local_images_path` + `s3_base_folder` rule) | pass |
| Resolution without `previews/` and with `SINGLE_SEGMENTER=true` | `mcmicro_previews` pruned as an optional single-file collection, `mcquant_segmenter_agreement` removed by the route; 8 collections, 6 links |
| `bash download_test_data.sh` end to end (fetch, vendored sheets, previews) | pass; previews checked by eye (composite and mask outlines) |

The text tiles, KPI strips and section styling are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
bundled section icons). The row budgets below are counted by hand from the stored heights.

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 2 (both `2 cycles`) |
| markers | 8 channels (7 quantified: 2 nuclear stains, 5 markers; 1 removed) |
| multiqc_data | 1 report (MultiQC 1.32): 1 custom-content section, the 16 x 2 input check matrix |
| mcquant_cells | 4,303 (Mesmer 2,114 + 2,085, Cellpose 72 + 32), 7 marker columns |
| mcquant_cell_markers | 30,121 (4,303 cells x 7 markers) |
| mcquant_segmentation_summary | 4 (2 images x 2 methods) |
| mcquant_marker_summary | 28 (2 images x 2 methods x 7 markers) |
| mcquant_marker_correlation | 14 (7 markers x 2 methods), 7 marker columns |
| mcquant_segmenter_agreement | 4 (2 images x 2 directions) |
| mcmicro_previews | 22 PNGs (per image: 1 composite, 8 channels, 2 outline sets), 591 x 470 and 591 x 468 px, scale 1.0 |

## Routes (RULES section 13)

| Route | Result |
| --- | --- |
| Full run (the megatest: two methods, previews written) | nothing dropped |
| `SINGLE_SEGMENTER` (one method, the pipeline's default `--segmentation mesmer`) | `mcquant_segmenter_agreement` goes: the Agreement section of Segmentation and the agreement findings row. Every Key figure and KPI strip reads always-written collections and breaks down by image, role or a distribution, never by segmenter alone, so no card is left with one bar. |
| No previews (`make_previews.py` not run) | `mcmicro_previews` is pruned at resolution (optional single-file scan): the Previews tab keeps only its intro and is dropped by the importer's minimum-tab gate; the cell map's `background_dc_tag` resolves to nothing and it draws without an underlay. The How to read list keeps a bare `Previews` label (RULES section 13, a `tab:` link alone). |
| One method and no previews | the two above together; the Overview, Spatial, Markers and Morphology are untouched |

`mcquant_segmenter_agreement` is also `optional: true` and its recipe raises a named error when
no image has two methods, so an ingest that meets a single-method run skips it even without the
variable.

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 21 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 10, how to read 2 |
| MultiQC | 6 | 1 (input image checks 4) |
| Previews | 10 | 2 (strip 2, gallery 6; table collapsed) |
| Segmentation | 12 | 3 (strip 2, cells and sizes 4, agreement 4; table collapsed) |
| Spatial | 15 | 3 (strip 2, cell map 7, selected cells 4; table collapsed) |
| Markers | 13 | 3 (strip 2, intensity 4, correlation 5; two tables collapsed) |
| Morphology | 14 | 3 (strip 2, size against shape 6, distributions 4) |

## Findings

- **Methods.** Mesmer finds 97.6% of the cells (4,199 of 4,303). Cellpose, run on the
  background-subtracted image with its default model, finds 72 and 32 cells where Mesmer finds
  2,114 and 2,085, and draws them larger (median 244 px against 96 px).
- **Agreement.** Every Cellpose cell holds at least one Mesmer centroid (100%, a median of 2 and
  3 per cell), and 1.7% to 3.8% of the Mesmer cells hold a Cellpose centroid: Cellpose cut the
  tissue into a few large objects, each over several nuclei.
- **Markers.** CD45 is the brightest marker by median intensity (nuclear stains left out). The
  test marker sheet subtracts the first cycle's nuclear stain from the second's as background,
  so the second nuclear stain reads near zero in most cells and anti-correlates with CD45
  (-0.79 under Mesmer): a property of the test configuration, which the correlation heatmap
  shows plainly.
- **Shape.** Median eccentricity 0.58, solidity 0.93, aspect ratio 1.23; the median coefficient
  of variation of a marker over an image's cells is 0.54.
- **Input checks.** Every tile check passes on both images but the exposure check, a warning
  (the test OME metadata carries no exposure time).

## Image collection: what remains for the live check

The Image collection (`mcmicro_previews`), the Previews gallery and the cell-map underlay are
validated offline as far as the models go: the collection resolves, validates as an Image DC in
the CLI context and is pruned when absent, and the dashboard validates. Not checked without a
stack:

1. ingest of the Image collection: the delta table built from `previews/previews.tsv` (a null
   `underlay_sample` on 20 of 22 rows), then the upload of `previews/` to `PREVIEW_S3_FOLDER`,
   which must be a folder in the server's bucket (`depictio-bucket` by default; the upload
   refuses another bucket) and one per run, or two runs' PNGs of the same sample overwrite each
   other;
2. the gallery serving the PNGs through the collection's `s3_base_folder` (the component names
   none, so it inherits the collection's);
3. the cell-map underlay: the import resolving `background_dc_tag` to `background_dc_id` /
   `background_wf_id`, the renderer fetching `underlay_sample`, `image_path`, `full_width`,
   `full_height` and drawing the nuclear-stain PNG under the picked image, placed on the
   full-resolution frame (so a downscaled preview of a large image lands on the centroids);
4. the `image` link from `samples` narrowing the gallery and the preview cards by image.

## Live check (RULES section 15): pending

None of these could be checked without a running stack; each is pending a live check.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check (cell map, correlation heatmap, size against shape) |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over tick labels | pending live check (the marker box names every marker of the panel on x) |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws | pending live check (cell map marker picker, colour by, image picker, underlay toggle) |
| The group has the same colour on figures, advanced viz and filter chips | pending live check (the segmenter colours especially) |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | simulated offline (above); pending live check |
| A sample picked in the left panel moves every card of a child tab | pending live check (MultiQC excepted by design: its rows are checks, not images) |
| The Locus tab opens on data | not applicable (no locus tab) |
| The MultiQC check matrix (a violin table of pass / warning strings) renders | pending live check |
| The Image collection, gallery and underlay | pending live check (the four items above) |

## Scenarios

**Megatest:** `s3://nf-core-awsmegatests/mcmicro/results-f4400001578642e370a72668966c6602fe172ef6/`
(tag 2.0.0, run_root `.`, manifest megatest.yaml, `Full test profile`)

**MultiQC:** run wrote 1.32 -> used as-is (custom content only: the prelude's input check matrix)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| MC1 | **Full test megatest (validated offline)** | `-profile test_full` | none | Every recipe runs on the real files, both methods; CLI dry run resolves 10 of 10 collections, previews included. |
| MC2 | **default segmentation** | `--segmentation mesmer` plus `--var SINGLE_SEGMENTER=1` | one MCQUANT table per image | Agreement section and findings row pruned; every strip still breaks down by image, role or a distribution. |
| MC3 | **TMA dearray** | `--tma_dearray` (Coreograph) | one image per core, cores as MCQUANT inputs | Core-level file names (`<sample>_<core>`) become `sample` values the hub does not list, so the sample filters miss them; the cell map frames each core. Highest-risk: untested. |
| MC4 | **sample-format sheet** | `--input_sample` (one row per sample, a tile directory) | no `cycle_number` | The hub reads it (recipe tests only): `cycle_count` 1, `cycles` `1 cycle`. |
| MC5 | **no background subtraction** | `--backsub false` | Cellpose on the registered image; `remove` channels quantified | MCQUANT names `<sample>.csv` for both methods; the marker panel still says `Removed` for a `remove` channel the run kept. |
| MC6 | **no previews** | fetch without tifffile / Pillow | no `previews/` | Image collection pruned: Previews tab dropped, no underlay. |
| MC7 | **whole-slide cohort** | real CyCIF / CODEX slides, 30 to 60 markers | 10^5 to 10^6 cells per image, images far over 1024 px | Previews downscaled (underlay on the full frame); `mcquant_cell_markers` grows to cells x markers rows; the cell map samples, Load-All lifts it; the correlation heatmap grows to markers x methods rows. |

**Ranking by template stress:** MC3 > MC7 > MC4 > MC5 > MC2 > MC6 > MC1

## Open issues

- Depictio has no OME-TIFF / zarr / pyramid viewer: the images are PNG previews written at fetch
  time, an optional Image collection (`TODO(bioimage)` beside the collection in `template.yaml`,
  the gallery and the cell-map underlay in `dashboards/base.yaml`, the helper and
  `download_test_data.sh`). The recipe layer cannot write images, so a run ingested without the
  helper has no Previews tab and no underlay.
- `make_previews.py` needs tifffile and Pillow, maintainer tools that are not depictio runtime
  dependencies (tifffile was installed into the maintainer venv for this build; nothing was added
  to `pyproject.toml`). The BaSiCPy illumination profiles are fetched but not previewed: tifffile
  needs `imagecodecs` for their floating-point predictor.
- Neither sheet is published: both are vendored under `input/` (the pipeline's own test assets,
  unchanged). `SINGLE_SEGMENTER` is not introspected from `params.json` (`segmentation`); the
  optional collection falls back to being skipped at ingest.
- 2.0.0 publishes the Cellpose tables as `<sample>_backsub_<sample>_backsub.csv` (the rename in
  `conf/modules.config` only matches a `_mask` stem); the sample is read back from either name.
- The MultiQC report holds custom content only, transposed (checks as rows, images as columns),
  so the pinned sample filters cannot reach it; `samples` is allowlisted in
  `PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL`.
- Areas and axes stay in pixels; the pixel size is in the OME metadata (`bftools/*.xml`) and is
  not applied.
- The marker correlation is pooled over every image of a method, so the image filter does not
  narrow it.
- The conformance project and the Tool Studio catalog snapshot are not regenerated here (shared
  files): `test_conformance_project.py` fails 4 tests until they are.
