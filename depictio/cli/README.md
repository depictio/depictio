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

Instead of running `depictio-cli run` by hand after a pipeline finishes, you can
have a **Nextflow pipeline trigger ingestion itself** on successful completion.

The mechanism is a small `nextflow.config` snippet
([`configs/nextflow/depictio.config`](configs/nextflow/depictio.config)) that
hooks into `workflow.onComplete` and shells out to `depictio-cli run`. All the
logic (template/nf-core resolution, ingestion, dashboards) stays in the CLI — the
snippet is just a thin, best-effort trigger that never fails the pipeline.

### Quick start (nf-core pipeline)

```bash
# Token kept out of CLI.yaml, injected at runtime (handy for CI/clusters)
export DEPICTIO_CLI_TOKEN="eyJhbGciOiJI...<JWT>"
export DEPICTIO_CLI_API_BASE_URL="http://localhost:8058"   # optional

nextflow run nf-core/rnaseq -r 3.18.0 -profile docker \
  --outdir results/ -c /path/to/depictio.config
```

On success the trigger runs (manifest forwarded so the CLI resolves the bundled
`nf-core/rnaseq/3.18.0` template automatically):

```bash
depictio-cli run --data-root results/ \
  --nextflow-manifest nf-core/rnaseq/3.18.0 \
  --CLI-config-path ~/.depictio/CLI.yaml
```

To make it permanent, add `includeConfig 'depictio.config'` to your
`nextflow.config` instead of passing `-c`.

### Custom (non-nf-core) pipelines

There is no bundled template, so provide a Depictio project config and let the
snippet pass it through:

```groovy
params.depictio_project_config = '/path/to/depictio_project.yaml'
```

The trigger exports `DEPICTIO_DATA_ROOT` (= `--outdir`) into the CLI environment,
so the project config can reference the output directory as
`{DEPICTIO_DATA_ROOT}` in `parent_runs_location`.

### Authentication via environment variables

`depictio-cli` now reads these env vars, so a `CLI.yaml` can be committed without
secrets:

| Variable | Overrides |
|----------|-----------|
| `DEPICTIO_CLI_TOKEN` | `user.token.access_token` in the CLI config |
| `DEPICTIO_CLI_API_BASE_URL` | `api_base_url` in the CLI config |
| `DEPICTIO_CLI_CONFIG_PATH` | path of the CLI config to load (when left at default) |

### Snippet parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `depictio_enabled` | `true` | Enable/disable the trigger |
| `depictio_cli_config` | `~/.depictio/CLI.yaml` | CLI config path |
| `depictio_data_root` | `params.outdir` | Directory to ingest |
| `depictio_template` | _none_ | Explicit depictio template id |
| `depictio_project_config` | _none_ | Path to a `depictio_project.yaml` |
| `depictio_cli_executable` | `depictio-cli` | CLI command name/path |

> **Requirement:** `depictio-cli` must be installed and on the `PATH` of the
> Nextflow head job.

A runnable end-to-end example lives in
[`configs/nextflow/example/`](configs/nextflow/example/).

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
