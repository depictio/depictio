# Nextflow trigger example

A runnable pipeline that ingests its own output into Depictio when it finishes.
Everything here is what a pipeline Depictio ships no template for needs: for an
nf-core pipeline, `-c $(depictio-cli config nextflow)` on the command you already
run is the whole setup, and none of these files are involved.

| File | What it is |
| --- | --- |
| `main.nf` | Fabricates the two output shapes a QC pipeline produces: per-sample metrics and windowed depth in mosdepth's column layout. No tool is involved, none of the numbers mean anything |
| `nextflow.config` | Includes the trigger and points it at the two files below |
| `depictio_project.yaml` | What to ingest: the metrics, the depth, and a third collection built from the depth by a catalog recipe rather than read from disk |
| `depictio_dashboard.yaml` | What to show: eight cards each on a different secondary layout, the coverage track the recipe makes possible, a figure and a table |
| `depictio_all_options.config` | Every `params.depictio_*` with its default and the option it drives. Reference, not something to include |

## Run it

```bash
pip install depictio-cli
# save the CLI config from the viewer's CLI agents page to ~/.depictio/CLI.yaml
depictio-cli config check

nextflow run main.nf --outdir results
```

The pipeline's own `nextflow.config` includes the trigger, so there is no `-c`.
On success the `onComplete` handler runs `depictio-cli run` against `results/`,
and the run summary at the end of the log links the project and the dashboard:

```
• 📘 Project: http://localhost:5600/projects/…
• 📘 Dashboard 'Nextflow trigger example': http://localhost:5600/dashboard/…
```

Run it a second time and the handler stops at step 4, because the project
exists. That is deliberate: refreshing rewrites the Delta tables, and the
handler runs unattended. Say which you mean:

```bash
nextflow run main.nf --outdir results --depictio_attach true   # add a run
nextflow run main.nf --outdir results --depictio_update true   # refresh in place
```

## What the files show

**`depictio_project.yaml`** declares three collections. Two are scanned from
disk. The third, `coverage_track_canonical`, has `source: transformed` and names
a recipe under `depictio/catalog/`: it is built from `mosdepth_genome_coverage`
by renaming that tool's columns to the roles the shared `coverage_track`
visualisation expects. Recipes are not reserved for bundled templates; any
project YAML can use one.

`{DEPICTIO_DATA_ROOT}` in `data_location.locations` is expanded from the
environment variable the handler exports, so the YAML never hardcodes an output
directory. Running the CLI by hand against this YAML needs that variable set.

**`depictio_dashboard.yaml`** is the part worth copying. Each card's
`secondary_layout` is chosen by the question its column asks: `attrition` for
the read stages, `threshold` for the quality cut-off, `box_plot` and `histogram`
on the same column because a five-number summary is blind to modality, `donut`,
`composition`, `completeness` and `top_n` for the rest. The `project_tag` must
match the project's `name`, and every `workflow_tag` / `data_collection_tag`
must match the project YAML, or the import fails naming the component.

## What it does not show

Authentication beyond the default config file, running the CLI from a container,
and multi-user provisioning are in `docs/nextflow-trigger.md`.
