# Depictio CLI

A command-line interface for interacting with the Depictio API.

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
depictio-cli config sync-project-config-to-server \
  --agent-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml \
  --update

# Show CLI configuration
depictio-cli config show-cli-config \
  --CLI-config-path ~/.depictio/admin_config.yaml

# Check S3 storage configuration
depictio-cli config check-s3-storage \
  --CLI-config-path ~/.depictio/admin_config.yaml
```

### Data Commands

```bash
# Scan data files
depictio-cli data scan \
  --agent-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml

# Process data
depictio-cli data process \
  --agent-config-path ~/.depictio/admin_config.yaml \
  --project-config-path path/to/project_config.yaml
```

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
