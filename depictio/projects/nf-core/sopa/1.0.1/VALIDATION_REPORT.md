# nf-core/sopa 1.0.1: validation report

## Status: authored offline, awaiting the HPC runs

The AWS megatest cannot be used (dangling `<sample>.zarr` symlink, JPEG 2000 explorer TIFF), so
`megatest.yaml` has `results_sha: null`. Everything below was checked without a real run.

## Sources of the layout

- `docs/output.md`, `workflows/sopa.nf`, `modules/local/*` of nf-core/sopa 1.0.1.
- `tests/default.nf.test.snap`, `tests/baysor.nf.test.snap`, `tests/cellpose.nf.test.snap`: the
  full file list of `sample_name.zarr` on the `test` profile, including every `obs` column of
  `tables/table` (Proseg: `cell`, `original_cell_id`, `centroid_x/y/z`, `component`, `volume`,
  `surface_area`, `scale`; Baysor: `n_transcripts`, `density`, `elongation`, confidences, `x`,
  `y`, `cluster`), and the tool versions (sopa 2.2.9, proseg 3.1.1, spatialdata 0.8.0).
- A synthetic run under `~/Data/depictio-nfcore/sopa/1.0.1/synthetic/` (26 MB): sopa 2.2.11 on
  its toy dataset, 3 samples, the pipeline's `test` steps through the `sopa` CLI (aggregate with
  channels and min 5 transcripts, fluorescence annotation, scanpy preprocessing, explorer,
  report), Proseg replaced by the toy cells copied to `proseg_boundaries` and the obs columns
  Proseg writes added. Zarr v3 stores, NGFF 0.5 images.

## Checks run

- `read_spatialdata_table` on the three synthetic stores (with and without `image`, with genes):
  1200 cells, obs + `x`/`y` in image pixels + gene columns.
- `validate_spatialdata_store` on `images/image` and `images/he_image`: NGFF 0.5, valid.
- Every recipe (`sopa/cells`, `sopa/composition`, `sopa/gene_expression`, `sopa/gene_summary`,
  `proseg/cell_metadata`, `baysor/cell_metadata`, `nf-core/sopa/samples`) on the reader's output,
  schema-validated; composition with no cluster and no cell type gives `unassigned` rows;
  `proseg/cell_metadata` raises on a non-Proseg table (the DC is optional).
- Template resolution with and without `GENES` / `METADATA_FILE` (gene and metadata DCs and
  their links pruned); `depictio-cli run --dry-run` on the synthetic root, both ways.
- Dashboard lint (`test_shipped_dashboard_yamls`, `test_template_conventions`, `-k sopa`).

## Open (needs the HPC runs)

- Real `test` run: obs of Proseg 3.1.1 as snapshotted; `IMAGE_ELEMENT=image`; viewer overlay
  alignment on the real multiscale image.
- `test_full` (Visium HD): the image element name (`<dataset_id>_full_image`, dataset id
  inferred by spatialdata-io from the Space Ranger outputs), the table after StarDist + Proseg
  on bins, cell counts (hundreds of thousands: table and viewer load), store size.
- Whether `--publish_dir_mode copy` publishes a real `<sample>.zarr` directory (REPORT
  re-publishes its staged input).
- `pipeline_info/params.json` / `samplesheet.valid.csv` names.
