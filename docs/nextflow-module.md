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
environment installs `depictio[local]` from PyPI: MultiQC for the templates, and the local server for `server 'local'`.

## Inputs

| Input | What to pass |
| --- | --- |
| `tuple val(meta), path(files), val(relpaths)` | The files the template reads, and where each is published, relative to the results directory. `meta.id` names the result file |
| `val template` | A template id (`nf-core/rnaseq/3.26.0`, `nf-core/rnaseq/latest`), or `''` to let the CLI detect the pipeline from the run's `pipeline_info/` and pick the closest bundled version |
| `path project_config` | A project YAML for a pipeline with no bundled template, else `[]`. Its `locations` must read `{DEPICTIO_DATA_ROOT}`, which the module sets to the rebuilt results directory |
| `path dashboards` | Dashboard YAMLs to import with the project, else `[]`. Templates bring their own |
| `path cli_config` | A `CLI.yaml`, else `[]` to read `$DEPICTIO_CLI_CONFIG_PATH` or `~/.depictio/CLI.yaml` (see [Choosing the server](#choosing-the-server)) |
| `val server` | `''` for the instance `cli_config` names, or `'local'` for the single-user server `depictio local up` runs on the launching machine, started when it does not run yet |

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
        params.depictio_cli_config ? file(params.depictio_cli_config, checkIfExists: true) : [],
        params.depictio_server,   // '' or 'local'
    )
}
```

In its `nextflow.config`:

```groovy
params {
    depictio            = true
    depictio_cli_config = null
    depictio_server     = ''    // 'local': the depictio local up server
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

Declare the `depictio*` parameters in `nextflow_schema.json` too, or
nf-schema rejects them.

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

## Choosing the server

Four set-ups, one module. Each was run end to end against the nf-core/rnaseq
3.26.0 results: project created, 12 data collections, template dashboard.

| Set-up | `cli_config` | `server` | Secrets | `ext.args` |
| --- | --- | --- | --- | --- |
| No server yet, single user | `[]` | `'local'` | none | |
| A `depictio local up` server already runs | `[]` | `'local'` | none | |
| A remote instance | its `CLI.yaml` | `''` | `DEPICTIO_CLI_TOKEN` | |
| A remote multi-user instance, as a given user | its `CLI.yaml` | `''` | `DEPICTIO_AUTH_PROVISIONING_API_KEY` | `--user alice@lab.org` |

### A local server: `server 'local'`

The task runs `depictio local up`, which reuses the server when it runs and
starts it otherwise (the first start downloads MongoDB, Redis and SeaweedFS,
about 700 MB, into `~/.depictio/local`), then ingests with `--server local`.
The server's processes run in their own sessions, so they outlive the task and
the pipeline: open the link the result JSON gives, and stop it with
`depictio local down`. `DEPICTIO_LOCAL_HOME` picks another home, as for the CLI.

That only holds where the task shares the machine and its lifetime with you:

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        executor = 'local'
    }
}
```

The module refuses `server 'local'` on any other executor, and inside a Docker,
Podman, Singularity or Apptainer container, which stops with the task, with a
message saying so. Run it with `-profile conda`, whose environment brings
`depictio[local]`, or with depictio installed on the launching machine.

### A remote instance

The CLI always reads a `CLI.yaml`: the one passed as `cli_config`, else
`$DEPICTIO_CLI_CONFIG_PATH`, else `~/.depictio/CLI.yaml`, which a container
does not have. `DEPICTIO_CLI_TOKEN` and `DEPICTIO_CLI_API_BASE_URL` only
override the token and URL of the file that was read; they do not replace it,
since it also carries the storage settings. So pass a `CLI.yaml` as
`cli_config`, and keep its token out of it in a Nextflow secret:

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

### A multi-user instance, as a given user

On an instance where each run belongs to the person who launched it, the CLI
provisions that person: `--user` names them, and the instance's provisioning
key, which the server must have too, comes from a secret. The account is
created on its first run and reused afterwards, whether provisioning or a
registration made it; the project and its dashboards are owned by that user,
and the task log ends with a one-time login link for them (see
[Pipeline provisioning](pipeline-provisioning-magic-link.md)).

```bash
nextflow secrets set DEPICTIO_AUTH_PROVISIONING_API_KEY <the instance's key>
```

```groovy
process {
    withName: 'DEPICTIO_INGEST' {
        secret   = ['DEPICTIO_AUTH_PROVISIONING_API_KEY']
        ext.args = { "--user ${params.depictio_user}" }
    }
}
```

`cli_config` still names the instance and its storage; its own token is not
used, the run acting with the provisioned user's.

### Network

The task talks to the Depictio API, so the node it runs on needs network
access to it. On a cluster whose compute nodes have none, run it on the head
node with `executor = 'local'`.

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

## Containers

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
