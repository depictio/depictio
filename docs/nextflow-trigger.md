# Automatic triggering from Nextflow

A Nextflow pipeline can push its own results into a running Depictio instance
when it finishes. The mechanism is a `workflow.onComplete` handler shipped as a
drop-in config snippet, `depictio/cli/configs/nextflow/depictio.config`, which
runs `depictio-cli run` on the pipeline's output directory.

## What the handler does

On completion, in this order:

1. Returns immediately if `params.depictio_enabled` is false.
2. **Skips with a warning if `workflow.success` is false.** The output directory
   of a failed run is partial by definition, and a half-filled project is worse
   than no project.
3. Resolves the data root: `params.depictio_data_root`, else `params.outdir`.
   A relative path is made absolute against `workflow.launchDir`. If neither is
   set, it warns and returns.
4. Builds the `depictio-cli run` argument list.
5. Runs it as a child process with stderr merged into stdout, exporting
   `DEPICTIO_DATA_ROOT` into the child environment, and streams the CLI's output
   line by line into the Nextflow log.
6. Warns on a non-zero exit code.

The whole handler is wrapped in a `try`/`catch`. A missing `depictio-cli`, an
unreachable server, or any ingestion failure logs a warning and **never changes
the pipeline's own exit status**. The handler is also additive: it does not
replace a `workflow.onComplete` the pipeline defines for itself.

## Requirements

- `depictio-cli` installed and on the PATH of the **Nextflow head job**, that is
  the shell or scheduler job running `nextflow run`. The handler executes there,
  never on a compute node. On an HPC cluster this usually means the submit node
  or the job that launches Nextflow, and it is the machine that must have network
  access to the Depictio API. Install it with `pip install depictio-cli`, or run
  it from the published container (see
  [Running the CLI from the published container](#running-the-cli-from-the-published-container)).
- Credentials reachable from that job, either a CLI config file or environment
  variables (see [Authentication](#authentication)).

## Enabling it

For an nf-core pipeline, the whole setup is two steps.

**Once**, on the head job:

```bash
pip install depictio-cli
```

and put the CLI configuration Depictio generated for you at
`~/.depictio/CLI.yaml`. That is the path the CLI agents page in the viewer
already tells you to save it to, and the path the snippet falls back to, so
there is nothing to point at and nothing to export. Confirm it took, from that
same machine, before trusting a long pipeline to it:

```bash
depictio-cli config check
```

**Then** add one `-c` to the command you already run:

```bash
nextflow run nf-core/ampliseq -profile test,docker --outdir results \
  -c $(depictio-cli config nextflow)
```

That is all. `depictio-cli config nextflow` prints the path of the snippet
bundled with the CLI, so there is no file to download, copy or keep in sync, and
nothing to configure: the snippet reads the pipeline's own manifest and passes it
to the CLI as `--pipeline-id`, which resolves the matching bundled template.

To read the snippet, or to keep an editable copy of it:

```bash
depictio-cli config nextflow --print > depictio.config
```

Nothing was copied along the way. The snippet arrived with `pip install`, like
any other file in the package, and `-c` just points at where it landed.

### Turning it on for good

Adding `-c` to each run is the explicit form. To stop thinking about it, run this
once per machine:

```bash
depictio-cli config nextflow --install
```

```bash
# no -c, no flags, nothing added to the command
nextflow run nf-core/ampliseq -profile test,docker --outdir results
```

`--install` copies the handler to `~/.depictio/nextflow.config` and adds an
`includeConfig` for it to `$NXF_HOME/config` (`~/.nextflow/config` by default),
which Nextflow reads before every run. Whatever else that file holds is kept,
re-running it replaces the block instead of adding a second one, and
`--uninstall` takes it back out.

Do not write that include by hand pointing at `$(depictio-cli config nextflow)`.
That path is inside your Python environment, and Nextflow refuses to parse a
config whose `includeConfig` target has gone missing:

```
Error config:1:1: Invalid include source: '...'
ERROR ~ Config parsing failed
```

That is not a failed ingestion, it is a failed parse: **every** pipeline on the
machine stops starting, including the ones that never heard of Depictio, and
uninstalling the CLI or switching virtualenv is enough to cause it. `--install`
points at a copy under `~/.depictio` precisely so that cannot happen. If the CLI
later disappears, Nextflow still parses, the handler reports that it cannot find
`depictio-cli`, and the pipeline's own result is untouched.

`$NXF_HOME/config` covers all your pipelines at once. Set
`params.depictio_enabled = false` in a pipeline's own config to opt one of them
back out.

Having installed it globally and *also* passing `-c $(depictio-cli config
nextflow)`, or running a pipeline that includes the snippet itself, ingests
once, not twice: the snippet assigns `workflow.onComplete`, so a second include
replaces the first rather than adding to it. A handler the pipeline registers
for itself is a different matter and still runs, because nf-core registers it
from inside a workflow block, which appends. Both were checked against Nextflow
26.04.

Per pipeline rather than per machine, put the same line in that pipeline's
`nextflow.config`:

```groovy
includeConfig '/path/to/depictio.config'
```

### Which file goes where

Two files are involved and only one of them is ever copied.

| File | What it is | Copied? |
| --- | --- | --- |
| `~/.depictio/CLI.yaml` | Your credentials, generated by the viewer's CLI agents page | **Once**, when you set up the machine. It is a secret, so treat it as one |
| `depictio.config` | The onComplete snippet | **Never** by hand. With `-c $(depictio-cli config nextflow)` it is read in place, inside the installed CLI; with `--install` the command copies it to `~/.depictio/nextflow.config` for you and refreshes that copy every time you re-run it |

Copy the snippet yourself only when you genuinely cannot reach that one:

- the head job runs the CLI from a container and has no `depictio-cli` of its
  own, so there is nothing to substitute (the image can hand you the file, see
  [Running the CLI from the published container](#running-the-cli-from-the-published-container));
- you want it versioned alongside your pipeline;
- you want it pinned independently of the CLI version.

What you should **not** copy it for is to edit it. Your own settings go in your
`nextflow.config`, or in the file you pass with `-c`, as `params.depictio_*`
entries. The snippet reads them when the pipeline completes and has no defaults
of its own to be overridden, so nothing is lost by leaving it untouched, and an
edited copy silently stops receiving fixes.

Include order does not matter, and neither does where your own settings sit
relative to the include: the snippet writes nothing into `params` when it is
parsed and reads every setting when the pipeline completes, so it has nothing to
overwrite. A `--depictio_*` value on the `nextflow run` command line always
wins.

Put your settings in the **same file** that carries the `includeConfig`. A
second `-c` works, but Nextflow lets the last one win outright rather than
merging, so splitting them across files is a way to lose settings for no
benefit.

## Checking it will work before you run the pipeline

The handler runs in `workflow.onComplete`, so the first `[depictio]` line appears
when the pipeline is already over. There is no startup message and there cannot
be one: Nextflow's strict config parser (25.10 and later) rejects any statement
at the top level of a config file, only assignments and scope blocks are allowed,
and `workflow.onStart` is accepted as an assignment but never invoked. So a bad
token or a missing CLI would otherwise surface after however long the pipeline
takes. Two checks, both quick, catch that up front.

**Check the connection, on the machine that will run the pipeline.** This is the
whole point: the CLI usually works on a laptop and fails on the cluster, because
the head job is a different machine with a different home directory and a
different environment.

```bash
depictio-cli config check --CLI-config-path /path/to/CLI.yaml
```

It validates the configuration file, reaches the server with the token and names
the user it authenticated as, then checks the S3 storage:

```
• ✅ Depictio CLI configuration is model-compliant.
• ✅ Server accessible - User: you@example.org, Admin privileges: No
• ✅ S3 storage configuration is valid
```

Run it as the same user, with the same `--CLI-config-path` or the same
`DEPICTIO_CLI_*` environment variables the trigger will use. In a scheduler,
that means running it inside a job, not on the login node.

**Check the wiring, without running the pipeline.** `nextflow run -preview`
executes no process, but the completion handler still fires, so the trigger is
exercised end to end in a couple of seconds:

```bash
nextflow run <pipeline> -c depictio.config -preview --outdir ./preflight-does-not-exist
```

You get the exact command the handler will run, and then a clean stop:

```
[depictio] <executable> run --CLI-config-path ... --data-root ... --triggered-by nextflow --pipeline-id nf-core/ampliseq/2.16.0
[depictio] • ✅ Resolved pipeline 'nf-core/ampliseq/2.16.0' to a bundled template.
[depictio] • ❌ --data-root does not exist or is not a directory: ...
```

That single output proves the executable was found, the CLI config loaded, the
server answered and the template resolved. Point the preview at a data root that
does not exist yet, as above: the preview runs no process, but the handler is
real, so if the directory it would ingest already holds results the CLI carries
on and genuinely creates the project. That is `--outdir` here, or
`params.depictio_data_root` when you set it explicitly.

Note that `nextflow config` is not an alternative here. It has no `-c` option, so
it cannot see a snippet passed with `-c`; it shows the `depictio_*` parameters
only when the snippet is pulled in with `includeConfig` from the project's own
`nextflow.config`.

## nf-core pipelines

```bash
nextflow run nf-core/ampliseq \
  -profile docker \
  --outdir results \
  -c /path/to/depictio.config
```

The handler always forwards the pipeline's identity as
`--pipeline-id "<manifest.name>/<manifest.version>"` (falling back to `latest`
when the manifest declares no version). Only the name and the version travel,
not the manifest: the option is engine-neutral, because the CLI recognises
Snakemake runs too and a Snakemake trigger would have nothing to call a
manifest. The CLI resolves it against its bundled templates.

The pipeline id is forwarded even when a template or project config is given: the
CLI ignores it in that case, so an explicit choice is never overridden.

To pin a template explicitly instead of relying on manifest resolution:

```groovy
params.depictio_template = 'nf-core/ampliseq/2.16.0'
```

## Custom pipelines

For a pipeline Depictio ships no template for, point the trigger at a Depictio
project YAML:

```groovy
params.depictio_project_config = "${projectDir}/depictio_project.yaml"
```

`params.depictio_project_config` wins over `params.depictio_template` when both
are set.

Because the handler exports `DEPICTIO_DATA_ROOT` into the CLI's environment, the
YAML does not have to hardcode an output directory:

```yaml
name: "Nextflow trigger example"
workflows:
  - name: "nextflow-trigger-example"
    engine:
      name: "nextflow"
    data_location:
      structure: "flat"
      locations:
        - "{DEPICTIO_DATA_ROOT}"
    data_collections:
      - data_collection_tag: "measurements"
        config:
          type: "Table"
          metatype: "Aggregate"
          scan:
            mode: "recursive"
            scan_parameters:
              regex_config:
                pattern: "measurements\\.tsv$"
          dc_specific_properties:
            format: "TSV"
            polars_kwargs:
              separator: "\t"
              has_header: true
```

`structure: "flat"` means the data root itself is the run directory. Use
`structure: "sequencing-runs"` with a `runs_regex` when the root holds one
subdirectory per run.

### Catalog recipes work here too

Recipes under `depictio/catalog/` are not reserved for bundled templates. A
project YAML can declare a collection built from another one instead of scanned
from disk, which is how a tool-specific output reaches a shared visualisation:

```yaml
      - data_collection_tag: "coverage_track_canonical"
        config:
          type: "Table"
          metatype: "Aggregated"
          source: "transformed"
          transform:
            recipe: "mosdepth/coverage_track_canonical.py"
```

`source: "transformed"` is what makes it derived. The recipe names the
collection it reads by tag (here `mosdepth_genome_coverage`), so that tag has to
exist in the same workflow. It renames the tool's columns to the canonical roles
the `coverage_track` visualisation expects, which is why that visualisation can
render output it knows nothing about.

### Getting a dashboard too

A project YAML says what to ingest, not what to show. On its own it leaves you
with a project holding data and no dashboard, which is where people expect one:
for an nf-core pipeline the bundled template supplies dashboards, and a custom
pipeline has no template to supply them. Point the trigger at your own instead:

```groovy
params.depictio_dashboard = "${projectDir}/depictio_dashboard.yaml"
```

Pass a list to import several. The dashboard's `project_tag` must match the
`name` in the project YAML, and each component's `workflow_tag` and
`data_collection_tag` must match the ones that YAML declares, or the import
fails with a validation error naming the component. Templates already bring
their own dashboards, so this parameter is only for pipelines without one.

Both URLs are printed in the run summary at the end of the pipeline log:

```
• 📘 Project: http://localhost:5600/projects/6a9ab9a6a1d2ead141378e27
• 📘 Dashboard 'Nextflow trigger example': http://localhost:5600/dashboard/6a9acdf3835e12072990459a
```

A complete runnable example is in `depictio/cli/configs/nextflow/example/`:
pipeline, config, project YAML and dashboard. It fabricates the two output
shapes a QC pipeline produces (per-sample metrics and windowed depth in
mosdepth's column layout), so the dashboard can show eight cards each using a
different secondary layout, and a coverage track built by the catalog recipe
above. No bioinformatics tool is involved and none of the numbers mean
anything: the point is the ingestion path.

## New project or additional run

Two shapes of repeated execution, two settings:

- **A project per execution.** Leave `params.depictio_attach` at its default of
  `false`. Set `params.depictio_project` to name the project, or let the CLI
  derive a name from the template. Each run creates its own project.
- **One project, many runs.** Set `params.depictio_attach = true`, which passes
  `--attach-run`. The data root of this execution is registered as an additional
  run of the existing project named by `params.depictio_project`, rather than
  creating a new project. Use it when the same pipeline is executed repeatedly,
  per sample batch or per sequencing run, and all of it belongs in one place.

```groovy
params.depictio_project = 'Ampliseq 16S survey'
params.depictio_attach  = true
```

One limitation is worth knowing before you build a project this way. In a
template whose `data_location.structure` is `flat`, data collections declared
with `scan.mode: single` name one file, and that path is resolved from the data
root of the run that created the project. A samplesheet, a metadata table or a
tree file is typically declared that way. Attaching a second run adds its
`recursive` collections as expected, but the `single` ones keep pointing at the
first run's files, so they describe the project rather than the new run. The
CLI reports this in the attach summary rather than failing, and it is the
correct behaviour for a samplesheet that genuinely covers the whole project.
Templates whose structure is `sequencing-runs`, viralrecon among them, resolve
those paths per run and are unaffected.

### Re-running the same pipeline

A second execution finds its project already on the server. The CLI refuses to
touch it and says so, exiting 2, which is the safe default but stops every re-run.
Pick the behaviour you want:

- `params.depictio_update = true` refreshes the existing project's configuration
  and re-ingests the same data root, which is what you want after fixing a
  pipeline and re-running with `-resume`. It passes `--overwrite` as well,
  because the delta tables from the first ingestion are already written and
  rebuilding them is the point.
- `params.depictio_attach = true` keeps the existing runs and adds this one. It
  implies the update, so setting both is the same as setting only `depictio_attach`.

## Authentication

The simplest case needs nothing at all: save the configuration generated by the
viewer's CLI agents page to `~/.depictio/CLI.yaml`, which is what that page tells
you to do, and both the CLI and the snippet find it on their own. Everything
below is for the cases where that file is not an option, because the head job has
no writable home directory, or because the results belong to more than one
person.

### Single user or CI: `DEPICTIO_CLI_TOKEN`

One identity owns everything the pipeline produces, and the secret must not sit
in a file. Commit a CLI config without secrets and inject the token at runtime:

```bash
export DEPICTIO_CLI_TOKEN=<long-lived CLI token>
export DEPICTIO_CLI_API_BASE_URL=https://depictio.example.org
nextflow run <pipeline> --outdir results -c depictio.config
```

| Variable | Effect |
| --- | --- |
| `DEPICTIO_CLI_TOKEN` | Injected as `user.token.access_token`, overriding the file |
| `DEPICTIO_CLI_API_BASE_URL` | Overrides `api_base_url` from the file |
| `DEPICTIO_CLI_CONFIG_PATH` | Selects which CLI config file to load. It only applies when the caller left the path at its default, so an explicit `--CLI-config-path` (or `params.depictio_cli_config`) is never clobbered |

This is the right shape for a CI runner or a shared service account. On a laptop,
the generated `~/.depictio/CLI.yaml` is less work and does the same thing.

### Multi-user cluster: `--user` plus a provisioning key

On a shared cluster the results belong to whoever launched the pipeline, not to
a service account. Set `params.depictio_user` and make the provisioning secret
available to the head job:

```bash
export DEPICTIO_AUTH_PROVISIONING_API_KEY=<shared secret>
nextflow run <pipeline> --outdir results \
  -c depictio.config \
  --depictio_user alice@lab.org
```

The CLI creates or fetches Alice's account, runs the whole ingestion as her, so
the project and its dashboards are owned by her, and prints a single-use
passwordless login link to her dashboard. The provisioning key is read from
`DEPICTIO_AUTH_PROVISIONING_API_KEY`, which the child process inherits from the
head job, so it never appears in the config or on a command line.

The server must have `DEPICTIO_AUTH_PROVISIONING_API_KEY` set as well, otherwise
the provisioning endpoints return `503`. Full setup, security model and the
lifetime of the link: [Pipeline provisioning and passwordless
login](pipeline-provisioning-magic-link.md).

## Running the CLI from the published container

The CLI is published to GHCR as `ghcr.io/depictio/depictio-cli`, built by the
same workflow as the other Depictio images and tagged with the same versions.
Nothing has to be installed on the machine that runs `nextflow`, only a
container runtime.

`depictio_cli_executable` accepts a list as well as a string, which is what lets
the image be used without inventing a second parameter:

```groovy
def home = System.getProperty('user.home')

params.depictio_cli_executable = [
    'docker', 'run', '--rm',
    '-v', '{DATA_ROOT}:{DATA_ROOT}',
    '-v', "${home}/.depictio:${home}/.depictio:ro",
    '--network', 'host',
    'ghcr.io/depictio/depictio-cli:1.9.2',
]
```

`{DATA_ROOT}` is substituted when the pipeline completes, and it is the only way
to mount the directory being ingested. The list itself is built when the config
is *parsed*, and `params.outdir` is not set yet at that point: a
`"${params.outdir}"` written inside the list expands to the string `null`, and
docker dutifully mounts a directory called `null`. `System.getProperty` is fine
there, which is why the home path above is interpolated normally.

The image sets `depictio-cli` as its entrypoint, so the list stops at the image
name and the handler appends `run` and its options.

That same entrypoint is how you get the snippet itself on a machine with no CLI
installed, which is otherwise the one case where
`$(depictio-cli config nextflow)` has nothing to run:

```bash
docker run --rm ghcr.io/depictio/depictio-cli:<version> config nextflow --print \
  > depictio.config
```

Then pass that file with `-c`, and put the `depictio_cli_executable` list above
in it or in your own `nextflow.config`.

Both binds map a host path onto **the same path inside the container**, and
that is not cosmetic. The handler builds an absolute `--data-root` and an
absolute `--CLI-config-path` from the host's point of view and passes them
through verbatim, so a bind that lands them anywhere else makes the CLI fail on
a path it cannot see. The data root is also what gets recorded in the project.

Instead of binding the configuration you can supply `DEPICTIO_CLI_TOKEN` and
`DEPICTIO_CLI_API_BASE_URL` with `-e`, which is the better fit for CI, where the
token comes from a secret rather than a file on disk.

The container must also reach both the Depictio API and its S3 endpoint;
`--network host` is the simplest way to do that against a local stack.

Singularity or Apptainer works the same way, with `--bind` in place of `-v`:

```groovy
params.depictio_cli_executable = [
    'singularity', 'exec',
    '--bind', '{DATA_ROOT}',
    'docker://ghcr.io/depictio/depictio-cli:1.9.2',
    'depictio-cli',
]
```

Under Singularity the host home is bind-mounted by default and paths keep their
names, so the configuration is usually already reachable.

## When a run is incomplete

The trigger refuses to ingest a pipeline that failed, but a pipeline can succeed
and still not produce everything a template expects: `--skip_multiqc`, a
protocol that skips a whole output subtree, a run resumed with different flags.

Templates handle most of that themselves. Data collections the template marks
optional are skipped with a warning and the run carries on, and conditional
gating removes whole groups of collections when the run's parameters say they
cannot exist.

What is left is a **required** collection whose source is genuinely absent. That
fails, and the CLI exits non-zero at step 6 with the collections named. Steps 1
to 5 have already run at that point, so the project exists, is scanned, and has
whatever could be processed, but no dashboard was imported. That is a partial
project, not an absent one: fix the missing outputs and re-run with
`depictio_update`, or delete the project if the run is not worth keeping.

Measured on an ampliseq run missing both `multiqc/` and
`qiime2/rel_abundance_tables/`: 8 optional collections skipped with a warning, 7
required ones failed, 1 processed, no dashboard, exit 1. The pipeline itself
stayed green, as designed.

## Parameters

| Parameter | Default | CLI option it drives |
| --- | --- | --- |
| `depictio_enabled` | `true` | none, set to `false` to disable the trigger |
| `depictio_data_root` | `params.outdir` | `--data-root` |
| `depictio_cli_config` | `$DEPICTIO_CLI_CONFIG_PATH`, else `~/.depictio/CLI.yaml` | `--CLI-config-path` |
| `depictio_template` | none | `--template` |
| `depictio_project_config` | none | `--project-config-path` (wins over `--template`) |
| `depictio_project` | none | `--project-name` |
| `depictio_dashboard` | none | `--dashboard` (one path or a list; templates bring their own) |
| `depictio_attach` | `false` | `--attach-run` |
| `depictio_update` | `false` | `--update-config --overwrite` (ignored with `--attach-run`, which implies both) |
| `depictio_user` | none | `--user` |
| `depictio_cli_executable` | `depictio-cli` | the executable that is run, or a list (a container invocation); `{DATA_ROOT}` in a list element is substituted at completion |

Booleans are coerced explicitly, so `--depictio_enabled false` and
`--depictio_attach false` behave as expected. Groovy treats every non-empty
string as true, and command-line and params-file values arrive as strings.

## Troubleshooting

Everything the handler emits is prefixed with `[depictio]`, on the console and in
`.nextflow.log`.

| Symptom | Cause |
| --- | --- |
| No `[depictio]` lines at all | `params.depictio_enabled` is false, or the snippet was never included. Re-run with `-preview` against a non-existent `--outdir` to see whether the handler fires at all |
| `Pipeline did not complete successfully, skipping ingestion` | Working as designed. Fix the pipeline first |
| `No data root to ingest` | Neither `params.depictio_data_root` nor `params.outdir` is set |
| `Could not start the Depictio CLI, so nothing was ingested` | `depictio-cli` is not on the head job's PATH. Installing it in the pipeline's containers does not help: the handler runs on the head job. Set `params.depictio_cli_executable` to an absolute path, or to a container invocation |
| `Ingestion trigger failed, pipeline result unchanged` | Anything else the handler hit. The exception is on that line; the pipeline's own result is never affected |
| `depictio-cli exited with code N` | The ingestion itself failed. The CLI's own output is in the log above that line, prefixed with `[depictio]` |

To see the exact command without running a pipeline, read the
`[depictio] <executable> run ...` line: it is the full argument list, logged
before the process starts.

## Notes on the snippet's implementation

Two details are load-bearing and easy to break when editing the snippet:

- **The child's output is drained before `waitFor()`.** Waiting first would
  deadlock as soon as the CLI fills the operating system's pipe buffer, and the
  head job would hang after the pipeline is otherwise finished.
- **The handler binds its own logger.** A handler defined in a config file does
  not get the script-level `log` binding, which resolves to `null` there, so the
  snippet obtains an SLF4J logger under the `nextflow.` namespace. That prefix is
  what puts messages on the console as well as in `.nextflow.log`.

The strict Nextflow config language (25.10 and later) also rejects helper
closures assigned with `def` and then invoked as `helper(...)`, which is why the
string and boolean handling in the snippet is spelled out inline.
