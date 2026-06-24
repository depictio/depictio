# Depictio Nextflow trigger — minimal example

This directory shows how to make a Nextflow pipeline **automatically ingest its
outputs into Depictio** when it finishes, using the shared
[`depictio.config`](../depictio.config) snippet (`workflow.onComplete`).

Files:

| File | Purpose |
|------|---------|
| `main.nf` | Trivial pipeline that writes `measurements.tsv` to `--outdir`. |
| `nextflow.config` | Loads `../depictio.config` and points it at a generic project config. |
| `depictio_project.yaml` | Generic Depictio project config (uses `{DEPICTIO_DATA_ROOT}`). |

## Prerequisites

* `nextflow` and `depictio-cli` installed and on your `PATH`.
* A Depictio CLI config. Keep the token out of the file and inject it at runtime:

  ```bash
  export DEPICTIO_CLI_TOKEN="eyJhbGciOiJI...<JWT>"
  export DEPICTIO_CLI_API_BASE_URL="http://localhost:8058"   # optional override
  ```

## Run it

```bash
cd depictio/cli/configs/nextflow/example
nextflow run main.nf --outdir results/
```

On success you should see, after `Pipeline completed successfully`:

```
[depictio] triggering ingestion: depictio-cli run --data-root results/ ... --nextflow-manifest depictio/nextflow-trigger-example/0.1.0
[depictio] ✓ ...
[depictio] ingestion completed
```

If `depictio-cli` is not installed or ingestion fails, the pipeline still
finishes **green** — the trigger is best-effort and only logs a warning.

## Try it without a running Depictio server

To see the resolved `depictio-cli` invocation without performing any ingestion,
run the CLI directly in dry-run mode:

```bash
depictio-cli run --data-root results/ \
  --project-config-path depictio_project.yaml \
  --dry-run
```

## nf-core pipelines

For an nf-core pipeline you do **not** need `depictio_project.yaml`: drop the
`params.depictio_project_config` line and the trigger will forward the pipeline's
manifest (e.g. `nf-core/rnaseq/3.18.0`) so depictio-cli auto-resolves the bundled
template:

```bash
nextflow run nf-core/rnaseq -r 3.18.0 -profile docker --outdir results/ -c ../depictio.config
```
