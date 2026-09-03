<p align="center">
  <img src="https://raw.githubusercontent.com/depictio/depictio/main/docs/images/logo_hd.png" alt="Depictio logo" width="300">
</p>

# Depictio CLI

A command-line interface for interacting with the Depictio API.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/depictio/depictio)

## Installation

### From Source

To install the CLI directly from the repository:

```bash
# Clone the repository
git clone https://github.com/depictio/depictio.git
cd depictio

# Install the CLI package
cd depictio/cli
pip install -e .
```

## Usage

The Depictio CLI provides commands for managing projects, scanning data, and processing datasets.

### Configuration Commands

```bash
# Sync a project configuration to the server
depictio-cli config sync \
  --CLI-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml \
  --update

# Show CLI configuration
depictio-cli config show \
  --CLI-config-path ~/.depictio/admin_config.yaml

# Run preflight checks (server accessibility + S3 storage)
depictio-cli config check \
  --CLI-config-path ~/.depictio/admin_config.yaml

# Validate a project configuration
depictio-cli config check \
  --CLI-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml
```

### Data Commands

```bash
# Scan data files
depictio-cli data scan \
  --CLI-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml

# Process data
depictio-cli data process \
  --CLI-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml
```

## Automatic triggering from Nextflow

`depictio/cli/configs/nextflow/depictio.config` is a drop-in Nextflow config
snippet. It adds a `workflow.onComplete` handler that runs `depictio-cli run`
on the pipeline's output directory once the pipeline finishes successfully, so
results reach Depictio without anyone typing a command.

Two rules the handler never breaks: it skips ingestion when `workflow.success`
is false (a partially written output directory is worse than none), and it is
best effort throughout. A missing CLI, an unreachable server or a failed
ingestion logs a warning and leaves the pipeline's own exit status untouched.

`depictio-cli` must be installed on the PATH of the **Nextflow head job**, the
shell or scheduler job that runs `nextflow run`. The handler executes there, not
on compute nodes.

### Quick start, nf-core pipeline

```bash
nextflow run nf-core/ampliseq \
  -profile docker \
  --outdir results \
  -c /path/to/depictio/cli/configs/nextflow/depictio.config
```

The snippet forwards the pipeline's manifest as
`--nextflow-manifest nf-core/ampliseq/2.16.0`. The CLI matches it against its
bundled templates and builds the project and dashboards from there. Nothing else
to configure.

To make it permanent, add `includeConfig` to your own `nextflow.config` instead
of passing `-c` on every run:

```groovy
includeConfig '/path/to/depictio/cli/configs/nextflow/depictio.config'
```

### Custom pipelines

Pipelines Depictio ships no template for point at a project YAML of their own:

```groovy
params.depictio_project_config = "${projectDir}/depictio_project.yaml"
```

The handler exports `DEPICTIO_DATA_ROOT` into the CLI's environment, so the YAML
can stay generic:

```yaml
data_location:
  structure: "flat"
  locations:
    - "{DEPICTIO_DATA_ROOT}"
```

A runnable example lives in `depictio/cli/configs/nextflow/example/`.
`params.depictio_project_config` wins over `params.depictio_template` when both
are set.

### New project or additional run

By default each triggered run creates (or updates) a project named by
`params.depictio_project`. To register a run as an **additional run of an
existing project** instead, set `params.depictio_attach = true`, which passes
`--attach-run`. Use it when the same pipeline is executed repeatedly and every
execution should land in one project rather than in a new one.

### Authentication

The head job usually has environment variables but no writable home directory,
so the CLI reads these:

| Variable | Effect |
| --- | --- |
| `DEPICTIO_CLI_TOKEN` | Injects the access token, so a CLI config file can be committed without secrets |
| `DEPICTIO_CLI_API_BASE_URL` | Overrides `api_base_url` from the config file |
| `DEPICTIO_CLI_CONFIG_PATH` | Selects which CLI config file to load (an explicit `--CLI-config-path` still wins) |
| `DEPICTIO_AUTH_PROVISIONING_API_KEY` | Shared provisioning secret used with `params.depictio_user` |

Set `params.depictio_user` to provision that user's account, run the pipeline as
them, and print a passwordless login link to their dashboard. It requires the
provisioning key. See `docs/pipeline-provisioning-magic-link.md`.

### Snippet parameters

| Parameter | Default | CLI option it drives |
| --- | --- | --- |
| `depictio_enabled` | `true` | none, set to `false` to disable the trigger |
| `depictio_data_root` | `params.outdir` | `--data-root` |
| `depictio_cli_config` | `$DEPICTIO_CLI_CONFIG_PATH`, else `~/.depictio/CLI.yaml` | `--CLI-config-path` |
| `depictio_template` | none | `--template` |
| `depictio_project_config` | none | `--project-config-path` (wins over `--template`) |
| `depictio_project` | none | `--project-name` |
| `depictio_attach` | `false` | `--attach-run` |
| `depictio_user` | none | `--user` |
| `depictio_cli_executable` | `depictio-cli` | the executable itself |

Every default is written to keep a value that is already set, so the snippet can
be included before or after the parameters it defaults, and `--depictio_*` on
the `nextflow run` command line always wins.

Longer version, including both authentication paths and troubleshooting:
`docs/nextflow-trigger.md`.

## Development

### Package Structure

The CLI package is structured as follows:

```
depictio/cli/
├── pyproject.toml  # CLI-specific package configuration
├── setup.py        # Setup script with version synchronization
├── README.md       # This file
├── test_cli_install.py  # Script to test CLI installation
└── depictio_cli.py      # Main CLI entry point
    └── cli/             # CLI implementation
        ├── commands/    # CLI commands
        └── utils/       # Utility functions
```

### Testing the Installation

You can test if the CLI package is correctly installed by running:

```bash
python test_cli_install.py
```

### Versioning

The CLI package version is synchronized with the main Depictio package version. When you install the CLI package, the `setup.py` script reads the version from the main `pyproject.toml` file and updates the CLI's `pyproject.toml` accordingly.

### CI/CD Integration

For CI/CD integration, see the following files in the root directory:

- `run_ci_locally.sh`: Script to run the GitHub Actions workflow locally
- `debug_cli_steps.sh`: Script to debug CLI-specific steps
- `debug_docker_services.sh`: Script to debug Docker services
- `CI_DEBUGGING_GUIDE.md`: Guide for debugging CI issues
- `CI_LOCAL_TESTING_README.md`: Overview of local testing tools
