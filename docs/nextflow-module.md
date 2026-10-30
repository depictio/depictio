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

By default the module builds an **artifact**, like `shinyngs/app` builds a
Shiny app rather than serving one: the task starts a single-user depictio of its
own, ingests the run into it with the pipeline's bundled template (which brings
the template's dashboards), stops it, and emits its data directory. The
pipeline publishes that directory; anyone reopens it later with one command.
Nothing outlives the task, so the module runs the same on any executor.

Its conda environment installs `depictio[local]` from PyPI: MultiQC for the
templates, and MongoDB, Redis and SeaweedFS (fetched by `depictio local up`)
for the stack. The container is the `ghcr.io/depictio/depictio-cli` image of
the same release, which has only the `multiqc` extra, not `local`: the artifact
needs the conda environment (or a local install) until an image carries the
stack.

## Inputs

| Input | What to pass |
| --- | --- |
| `tuple val(meta), path(files), val(relpaths)` | The files the template reads, and where each is published, relative to the results directory. `meta.id` names the result file |
| `val template` | A template id (`nf-core/rnaseq/3.26.0`, `nf-core/rnaseq/latest`), or `''` to let the CLI detect the pipeline from the run's `pipeline_info/` and pick the closest bundled version |
| `path project_config` | A project YAML for a pipeline with no bundled template, else `[]`. Its `locations` must read `{DEPICTIO_DATA_ROOT}`, which the module sets to the rebuilt results directory |
| `path dashboards` | Dashboard YAMLs to import with the project, else `[]`. Templates bring their own |
| `path cli_config` | `[]` (the default) to build an artifact, or the `CLI.yaml` of an existing instance to send the run there instead (see [Sending to an existing instance](#sending-to-an-existing-instance), not the default, may change) |

`task.ext.args` is appended to the command, for `--attach-run`, `--project NAME`,
`--update-config`, `--var NAME=VALUE` and the other `ingest` options. It is
written into the task's `.command.sh`, so never put a token there.

Leaving `template` empty is the safer default for a pipeline: an explicit id
must match a bundled version exactly, whereas detection from `pipeline_info/`
falls back to the closest one with a warning, so a pipeline release newer than
the installed depictio still ingests.

### Why `relpaths`

A template finds its files by their path under the results directory, for
example `star_salmon/deseq2_qc/*pca.vals.txt`. A process never sees that
directory: it only sees the files staged into its work directory. `relpaths`
gives each file back its published path, and the module rebuilds that layout
before calling the CLI. A directory is rebuilt as a real tree of links, because
the scan does not descend into a symlinked directory.

```groovy
// One item each. combine keeps the order; mix().collect() would not.
ch_depictio = ch_multiqc_data
    .combine(ch_gene_counts)
    .map { mqc_data, gene_counts -> [
        [id: 'run'],
        [ mqc_data, gene_counts ],
        [ 'multiqc/multiqc_data', 'star_salmon/salmon.merged.gene_counts.tsv' ],
    ] }

DEPICTIO_INGEST(ch_depictio, 'nf-core/rnaseq/3.26.0', [], [], [], '')
```

The two lists pair up by position, and a size mismatch stops the task, as does
a relpath that is absolute or contains `..`. When two entries land on the same
path, the later one wins and the rest of the earlier one is kept, so a fresh
copy of some files can be laid over a whole results directory. Two shortcuts
leave `relpaths` empty:

- **One directory** is used as the results directory itself. This is the
  simplest way to run the module on the results of a run that already finished:

  ```groovy
  DEPICTIO_INGEST(
      Channel.of([ [id: 'run'], file(params.results, type: 'dir'), [] ]),
      '', [], [], [], '',
  )
  ```

- **Several files** are laid out flat, which suits a project YAML whose scan
  patterns match file names only. Two inputs with the same name collide, the
  later one winning.

The rebuilt directory lives in the task's work directory, and that is the run
location the project records. A later `--update-config` or `--attach-run`
rescan of that location finds nothing once the work directory is cleaned.

## In an nf-core pipeline

An nf-core template reads files from all over the results directory (the
rnaseq one reads about thirty globs), so wiring each of them through `relpaths`
is not worth it. Hand over the results directory once the run's last process,
MultiQC, is done, plus the samplesheet, which nf-core does not publish but the
templates read from `input/`. The CLI finds it there only when its name
contains `samplesheet`, hence the fixed name below. This was run end to end on nf-core/rnaseq 3.26.0
(`-profile test,conda`): the pipeline finished, the module ingested 10 data
collections and created the template's dashboard.

In the pipeline's `main.nf`, after the main workflow:

```groovy
include { DEPICTIO_INGEST } from './modules/local/depictio/ingest/main'

if (params.depictio) {
    DEPICTIO_INGEST(
        NFCORE_RNASEQ.out.multiqc_report
            .collect()
            .map { _reports -> [
                [ id: workflow.runName ],
                [ file(params.outdir, type: 'dir'), file(params.input) ],
                [ '.', 'input/samplesheet.csv' ],
            ] },
        '',     // template: detected from pipeline_info/
        [], [],
        [],     // no cli_config: build an artifact
    )
}
```

In its `nextflow.config`:

```groovy
params {
    depictio = true
}

process {
    withName: 'DEPICTIO_INGEST' {
        errorStrategy = 'ignore'
        publishDir    = [
            path: { "${params.outdir}/depictio" },
            mode: params.publish_dir_mode,
            saveAs: { filename -> filename.equals('versions.yml') ? null : filename },
        ]
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

Declare `depictio` in `nextflow_schema.json` too, or nf-schema rejects it.

The route flags are the per-template part: each template documents its
variables in its `template.yaml`, and the pipeline is the one place that knows
its own parameters. The CLI reads the run's `params.json`, but derives route
flags from it for a few pipelines only (ampliseq, viralrecon, demultiplex), not
rnaseq: without them a `--skip_alignment` rnaseq run looks for `star_salmon/`
and fails.

The results directory is read as published, so it relies on MultiQC's own
outputs having been copied by the time the module starts. Publishing is
asynchronous; in the tested run it had finished, but a slow file system can
lag. When that matters, add MultiQC's `data` output as a further `files`
entry at its published path, which depends on the pipeline and the MultiQC
version (the tested `--skip_alignment` run wrote `multiqc/multiqc_report_data`):
it comes from the task, not from the copy, and wins over whatever the copy
holds.

## The artifact

The task gives its stack a home in its own work directory
(`DEPICTIO_LOCAL_HOME="$PWD/stack"`), so it never touches `~/.depictio/local`,
and `depictio local up` picks free ports, so it runs beside any other stack on
the machine. A `trap` stops the stack on every exit, failed or not. After the
ingestion, the stack is stopped first, so MongoDB and SeaweedFS flush, and only
what reopening reads is kept: no binaries, logs, caches or Redis queue, and not
MongoDB's 100 MB preallocated journal file.

```
results/depictio/
├── <run>.depictio.json        how the ingestion ended, project and dashboard ids
└── <run>_depictio/            the artifact
    ├── .depictio-local-home
    ├── secrets.json  ports.json
    ├── keys/  cli/              token-signing keys, the admin CLI configuration
    ├── mongo/                   MongoDB data
    └── s3/                      SeaweedFS data (the ingested tables, MultiQC reports)
```

For the nf-core/rnaseq 3.26.0 test profile it weighs about 100 MB.

Reopen it, on any machine with `depictio[local]` installed:

```bash
DEPICTIO_LOCAL_HOME=results/depictio/<run>_depictio depictio local up
```

The first start fetches MongoDB, Redis and SeaweedFS into the artifact's `env/`
(about 700 MB, seconds from a warm conda-forge cache). The dashboard link in the
result JSON holds the dashboard id; its port is the one the task used, which
`up` reuses when free. `depictio local down` with the same `DEPICTIO_LOCAL_HOME`
stops it.

The artifact holds the stack's keys, admin token and storage password, like any
local home: share it as you would the data itself. A stack runs a single user,
so the artifact does too.

Inside the task, `depictio local up` fetches the same binaries into the work
directory. Under conda they come from the conda-forge package cache after the
first run; without that cache, every task downloads them, so the node needs
network access to conda-forge.

## Sending to an existing instance

*Not the default, may change.* Given the `CLI.yaml` of an existing instance as
`cli_config`, the task sends the run there and builds no artifact.

The CLI always reads a `CLI.yaml`. `DEPICTIO_CLI_TOKEN` and
`DEPICTIO_CLI_API_BASE_URL` only override the token and URL of the file that
was read; they do not replace it, since it also carries the storage settings.
Keep the token out of the file, in a Nextflow secret:

```bash
nextflow secrets set DEPICTIO_CLI_TOKEN <long-lived CLI token>
```

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        secret = ['DEPICTIO_CLI_TOKEN']
    }
}
```

The secret reaches the task's environment without being written into its
`.command.*` files. A `cli_config` that holds the token is staged like any
input, so on a cloud executor it is uploaded to the work directory's bucket.

On a multi-user instance, `--user` in `ext.args` names the person the run
belongs to, and the instance's provisioning key comes from a
`DEPICTIO_AUTH_PROVISIONING_API_KEY` secret: the account is created on its
first run and reused afterwards, and the task log ends with a one-time login
link (see [Pipeline provisioning](pipeline-provisioning-magic-link.md)).

The task then talks to that instance, so the node it runs on needs network
access to it.

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

`<meta.id>_depictio/` is the artifact (see [The artifact](#the-artifact)),
absent when the run is sent to an instance. `<meta.id>.depictio.json` is the
CLI's `--result-json`: how the ingestion ended, with the project and dashboard
ids and links. `versions.yml` carries the depictio version, as in any nf-core
module.

## Containers

The `depictio-cli` image lacks the `local` extra, so today it can only send a
run to an existing instance; building the artifact in a container needs an
image that carries the stack.

The CLI image's `ENTRYPOINT` is `depictio-cli`, so that `docker run <image>
ingest …` works on its own. Nextflow does not override an entrypoint, which
would hand the task's bash to the CLI as a subcommand, so under Docker and Podman
the module clears it with `--entrypoint ""`. Singularity and Apptainer run the
task with `exec`, which ignores it. Two limits follow:

- A `containerOptions` set for this process in a config replaces the module's,
  and with it the override: add `--entrypoint ""` to yours.
- Executors that do not start the container with `docker run`, such as AWS
  Batch, keep the entrypoint. Use the conda environment there.

The image runs as its own user, `depictio`. Run Docker with the host's user,
as nf-core pipelines already do, so the task can write its work directory:

```groovy
docker.runOptions = '-u $(id -u):$(id -g)'
```

The staging uses GNU `cp -s`, which the image and Linux hosts have. macOS's
`cp` has no `-s`, so on a Mac run the module in the container, not under conda.
