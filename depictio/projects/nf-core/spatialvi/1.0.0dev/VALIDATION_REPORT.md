# nf-core/spatialvi 1.0.0dev: validation report

Status: **offline only, unreleased pipeline**. spatialvi has no release and no AWS megatest.
The template follows `dev` at `441ded53109f57ecf70555fb0b060546b34b4a2c` (2026-09-15,
manifest `1.0dev`, Nextflow `!>=25.10.4`). It was authored from the dev `docs/output.md`,
the `publishDir` declarations in `conf/modules.config`, and the module templates
(`read_data`, `quality_controls`, `clustering`, `svg`, `integration`). Every item marked HPC
below waits for the `test` profile run (`scripts/nfcore_validation_hpc.py`, key `spatialvi`).

## Offline checks

| Check | Result |
| --- | --- |
| `test_catalog.py` (including `catalog dev validate`) | pass |
| `test_shipped_dashboard_yamls.py`, `test_template_conventions.py`, `tests/catalog` (`-k spatialvi`) | pass |
| every recipe through the real SpatialData reader and scan on the synthetic run | schemas match |
| `depictio.cli run --template nf-core/spatialvi/1.0.0dev --dry-run`, with and without `GENES` / `METADATA_FILE` | 8/8 steps |

Synthetic run: the test-dataset Space Ranger outputs (CytAssist 11 mm FFPE, probe set)
copied into two samples, one of them with a dotted id. The pipeline's own module templates
ran outside Nextflow (spatialdata-io, scanpy, squidpy, harmonypy) to produce
`<sample>/data/*_svg.csv` and `integration/data/{merged,harmony}.zarr`. MultiQC 1.35 ran on
the Space Ranger outputs and the spot-filter custom content. There is no FastQC because the
synthetic run has no FASTQ files. Recipe output: 2 metric rows, 28,672 capture spots,
4,032 sample and gene rows, 834 kept spots on the image sample (all with an integrated
cluster) and 26 composition rows.

## Findings on the dev pipeline

- **Coordinates.** `obsm["spatial"]` is already in hires pixels, so the reader's `auto`
  mode scales it twice. The template reads `coordinates: region` (the spot shapes).
- **Gene ids.** The var names are Ensembl ids. The pipeline's `MT-` test finds no genes,
  so `pct_counts_mt` is 0 and the mitochondrial filter does nothing. `GENES` takes ids.
- **Dotted sample ids.** Element names drop the dot, directories keep it. The integration
  step then fails to map the integrated clusters back onto that sample's table.
- **No per-sample store published.** Only `integration/data/*.zarr` holds SpatialData.
- **`test_full`** points at a sample sheet that returns 404.

## Needs the HPC run

- Real published names and layout, and whether `--publish_dir_mode copy` covers every
  process.
- Whether MultiQC 1.29 (pinned by the module) writes `multiqc.parquet`, and the exact
  Space Ranger and FastQC plot names in it.
- `pipeline_info/*software*versions*.yml`, which was absent offline, so provenance was
  checked on params only.
- The single-sample `test` run leaves the integration step with one batch. Check that
  `harmony.zarr` is still written.
- Tile performance of the hires image through the bioimage viewer.

## Reproducing

```bash
python scripts/nfcore_validation_hpc.py run --key spatialvi
# fetch, copy the --input samplesheet into <DATA_ROOT>/input/
python -m depictio.cli run --template nf-core/spatialvi/1.0.0dev --data-root <DATA_ROOT> \
  --var IMAGE_SAMPLE=<sample, as the store spells it> \
  --var METADATA_FILE=<DATA_ROOT>/input/samplesheet.csv
```
