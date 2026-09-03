# Depictio Nextflow trigger: minimal example

A four-file, runnable demonstration of `../depictio.config`: a pipeline that
produces one table, a project YAML that describes it, and the config that wires
the two together.

| File | Role |
| --- | --- |
| `main.nf` | Trivial DSL2 pipeline writing `measurements.tsv` into `params.outdir` |
| `nextflow.config` | Declares a manifest, sets `params.outdir`, points the trigger at the project YAML, includes `../depictio.config` |
| `depictio_project.yaml` | Depictio project config, one Table data collection, located at `{DEPICTIO_DATA_ROOT}` |

## Run it

```bash
cd depictio/cli/configs/nextflow/example
nextflow run main.nf
```

The pipeline writes `results/measurements.tsv`. On success the `onComplete`
handler runs:

```
depictio-cli run \
  --CLI-config-path ~/.depictio/CLI.yaml \
  --data-root <absolute path>/results \
  --project-config-path <absolute path>/depictio_project.yaml \
  --nextflow-manifest depictio/nextflow-trigger-example/0.1.0 \
  --project-name 'Nextflow trigger example'
```

`--nextflow-manifest` is forwarded from the manifest block but ignored by the
CLI here, because `--project-config-path` was given explicitly.

If `depictio-cli` is not installed or not configured, the pipeline still
finishes green and the handler logs a warning. That is the point of the
best-effort design, so this example is safe to run before setting up a server.

## What to look at

- **`{DEPICTIO_DATA_ROOT}`** in `depictio_project.yaml`. The handler exports that
  variable from the resolved data root, so the same YAML works for any output
  directory and does not need editing per run.
- **`scan.mode: "recursive"`** with the pattern `measurements\.tsv$`. The data
  collection finds its file anywhere under the data root, which is what makes
  the config survive a change of output layout.
- **Include order.** `params.depictio_project` is set in `nextflow.config`
  *before* `includeConfig '../depictio.config'`, and it survives. Every default
  in the snippet keeps a value that is already set.

## Adapting it

- Not an nf-core pipeline: keep `params.depictio_project_config` and edit the
  YAML to describe your outputs.
- An nf-core pipeline: drop `params.depictio_project_config` entirely. The
  manifest alone lets the CLI resolve a bundled template.
- Repeated executions that belong in one project: add
  `params.depictio_attach = true`.

Full documentation: `docs/nextflow-trigger.md`.
