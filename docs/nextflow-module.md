# The `depictio/ingest` Nextflow module

[The onComplete trigger](nextflow-trigger.md) pushes a run's results to Depictio
from outside the pipeline, and needs nothing from the pipeline itself. The
`depictio/ingest` module does the same thing from inside a pipeline, as an
ordinary process: the pipeline decides when it runs, which outputs it receives,
and it can be shipped with the pipeline like any other nf-core module.

It follows the nf-core module layout (`main.nf`, `meta.yml`, `environment.yml`,
`tests/main.nf.test`) and lives in the depictio package, next to the trigger
snippet:

```
depictio/cli/configs/nextflow/modules/depictio/ingest/
```

## Adding it to a pipeline

Copy the directory into the pipeline. With depictio installed, the snippet's
path gives the way to it:

```bash
cp -r "$(dirname "$(depictio config nextflow)")/modules/depictio" modules/local/
```

```groovy
include { DEPICTIO_INGEST } from './modules/local/depictio/ingest/main'
```

The process runs `depictio ingest` with the pipeline's bundled template, which
brings the template's dashboards with it. Its container is the
`ghcr.io/depictio/depictio-cli` image of the same release, and its conda
environment installs `depictio[multiqc]` from PyPI.

## Inputs

| Input | What to pass |
| --- | --- |
| `tuple val(meta), path(files), val(relpaths)` | The files the template reads, and where each is published, relative to the results directory. `meta.id` names the result file |
| `val template` | A template id (`nf-core/rnaseq/3.26.0`, `nf-core/rnaseq/latest`), or `''` to derive it from `workflow.manifest` as `<name>/<version>` |
| `path project_config` | A project YAML for a pipeline with no bundled template, else `[]` |
| `path dashboards` | Dashboard YAMLs to import with the project, else `[]`. Templates bring their own |
| `path cli_config` | A `CLI.yaml`, else `[]` to authenticate through the environment (below) |

`task.ext.args` is appended to the command, for `--attach-run`, `--project NAME`,
`--update-config` and the other `ingest` options.

### Why `relpaths`

A template finds its files by their path under the results directory, for
example `star_salmon/deseq2_qc/*pca.vals.txt`. A process never sees that
directory: it only sees the files staged into its work directory. `relpaths`
gives each file back its published path, and the module rebuilds that layout
before calling the CLI. A directory is rebuilt as a real tree of links, because
the scan does not descend into a symlinked directory.

```groovy
ch_depictio = ch_multiqc_data                       // multiqc/multiqc_data
    .mix(ch_gene_counts)                            // star_salmon/salmon.merged.gene_counts.tsv
    .collect()
    .map { files -> [ [id: 'run'], files, [
        'multiqc/multiqc_data',
        'star_salmon/salmon.merged.gene_counts.tsv',
    ] ] }

DEPICTIO_INGEST(ch_depictio, '', [], [], [])
```

The two lists pair up by position, and a size mismatch stops the task. When
two entries land on the same path, the later one wins and the rest of the
earlier one is kept, so a fresh copy of some files can be laid over a whole
results directory. Two shortcuts leave `relpaths` empty:

- **One directory** is used as the results directory itself. This is the
  simplest way to run the module on the results of a run that already finished:

  ```groovy
  DEPICTIO_INGEST(
      Channel.of([ [id: 'run'], file(params.results, type: 'dir'), [] ]),
      'nf-core/rnaseq/3.26.0', [], [], [],
  )
  ```

- **Several files** are laid out flat, which suits a project YAML whose scan
  patterns match file names only.

## In an nf-core pipeline

An nf-core template reads files from all over the results directory (the
rnaseq one reads about thirty globs), so wiring each of them through `relpaths`
is not worth it. Hand over the results directory once the run's last process,
MultiQC, is done, plus the samplesheet, which nf-core does not publish but the
templates read from `input/`. This was run end to end on nf-core/rnaseq 3.26.0
(`-profile test,conda`): the pipeline finished, the module ingested 10 data
collections and created the template's dashboard.

In the pipeline's `main.nf`, after the main workflow:

```groovy
include { DEPICTIO_INGEST } from './modules/local/depictio/ingest/main'

if (params.depictio) {
    def samplesheet = file(params.input)
    DEPICTIO_INGEST(
        NFCORE_RNASEQ.out.multiqc_report
            .collect()
            .map { _reports -> [
                [ id: workflow.runName ],
                [ file(params.outdir, type: 'dir'), samplesheet ],
                [ '.', "input/${samplesheet.name}" ],
            ] },
        '',     // template: from the manifest, nf-core/rnaseq/<version>
        [], [],
        params.depictio_cli_config ? file(params.depictio_cli_config, checkIfExists: true) : [],
    )
}
```

In its `nextflow.config`:

```groovy
params {
    depictio            = true
    depictio_cli_config = null
}

process {
    withName: 'DEPICTIO_INGEST' {
        executor      = 'local'
        errorStrategy = 'ignore'
        ext.args      = { [
            // One project per run. A '/' in a project name breaks the CLI's
            // lookup by name, hence the last part of the manifest name only.
            "--project '${workflow.manifest.name.tokenize('/').last()} ${workflow.runName}'",
            // The template's route flags, from the run's own parameters.
            params.skip_alignment                   ? '--var PSEUDOALIGNER_ONLY=true'        : '',
            (params.skip_multiqc || params.skip_qc) ? '--var SKIP_MULTIQC=true'              : '',
            params.skip_quantification_merge        ? '--var SKIP_QUANTIFICATION_MERGE=true' : '',
        ].findAll { a -> a }.join(' ') }
    }
}
```

Declare `depictio` and `depictio_cli_config` in `nextflow_schema.json` too, or
nf-schema rejects them.

The route flags are the per-template part: each template documents its
variables in its `template.yaml`, and the pipeline is the one place that knows
its own parameters. The CLI reads a run's `params.json` for ampliseq only, so
without them a `--skip_alignment` rnaseq run looks for `star_salmon/` and
fails.

The results directory is read as published, so it relies on MultiQC's own
outputs having been copied by the time the module starts. Publishing is
asynchronous; in the tested run it had finished, but a slow file system can
lag. When that matters, add MultiQC's `data` output as a further `files`
entry at its published path (`multiqc/multiqc_report_data` for a
`--skip_alignment` run, `multiqc/<aligner>/multiqc_report_data` otherwise): it
comes from the task, not from the copy, and wins over whatever the copy holds.

## Authentication and network

The task talks to the Depictio API, so the node it runs on needs network access
to it. On a cluster whose compute nodes have none, run it on the head node:

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        executor = 'local'
    }
}
```

Without a `cli_config` file, the CLI reads `DEPICTIO_CLI_TOKEN` and
`DEPICTIO_CLI_API_BASE_URL`. Keep the token in a Nextflow secret rather than in
a file:

```bash
nextflow secrets set DEPICTIO_CLI_TOKEN <long-lived CLI token>
```

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        secret = ['DEPICTIO_CLI_TOKEN']
    }
}
env.DEPICTIO_CLI_API_BASE_URL = 'https://depictio.example.org'
```

The secret reaches the task's environment without being written into its
`.command.*` files.

## Failure

Unlike the trigger, the module is part of the pipeline: a failed ingestion
fails the task, and so the run. When Depictio is optional, say so:

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        errorStrategy = 'ignore'
    }
}
```

## Output

`<meta.id>.depictio.json` is the CLI's `--result-json`: how the ingestion ended,
with the project and dashboard ids and links. `versions.yml` carries the depictio
version, as in any nf-core module.

## The container entrypoint

The CLI image's `ENTRYPOINT` is `depictio-cli`, so that `docker run <image>
ingest …` works on its own. Nextflow does not override an entrypoint, which
would hand the task's bash to the CLI as a subcommand, so under Docker and Podman
the module clears it with `--entrypoint ""`. Singularity and Apptainer run the
task with `exec`, which ignores it.
