# nf-core/cellpainting 1.0.0dev template validation report

nf-core/cellpainting is unreleased: validated offline against the AWS megatest
`results-40423f0d1da0dde52bd5f1fd812ee6a1549cdfb3` (dev commit of 2026-04-29, test_full
profile: one JUMP Cell Painting plate, 4 wells x 9 sites x 8 channels). Local subset: 323 MB
(`bash download_test_data.sh`).

## Checks

| Check | Result |
| --- | --- |
| Every recipe on the megatest (`execute_recipe`, dependency order) | pass, 10 collections |
| `test_catalog.py` (other agents' in-progress catalog dirs skipped) | pass, cytotable and cellprofiler entries included |
| `test_shipped_dashboard_yamls.py -k cellpainting` | 10 passed |
| `test_template_conventions.py -k cellpainting` | 8 passed, no warning |
| `resolve_template` | GROUP_COL, IMAGES_S3_BASE, METADATA_FILE and the recipe params resolve from the variable defaults |
| `python -m depictio.cli run --template nf-core/cellpainting/1.0.0dev --dry-run` | 8/8 steps |
| Ingest, image push, rendering | not run (main session) |

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| cp-cells | 3595 (37 columns) |
| cp-sites | 36 |
| samples | 4 |
| cp-wells | 4 (57 columns) |
| cp-plate-layout | 2 |
| cp-cell-profiles | 3595 |
| cp-cell-embedding | 3595 |
| cp-image-qc | 8 (one site, flat analysis publish) |
| cp-illumination | 400 (8 functions x 50 rings) |
| cp-overlays | 6 (4 object overlays, 2 outlines) |

## Open

- The analysis step is published flat on this commit, so `cp-image-qc` and the outline images
  cover one site (see docs/dashboards.md, layout notes).
- The gallery needs the PNGs pushed under `IMAGES_S3_BASE` before it shows anything.
- `latest` does not resolve to this template: the version directory `1.0.0dev` is not numeric.
