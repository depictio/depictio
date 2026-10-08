<p align="center">
  <img src="https://raw.githubusercontent.com/depictio/depictio/main/docs/images/logo_hd.png" alt="Depictio logo" width="300">
</p>

# depictio-cli

`depictio-cli` is an alias of the [`depictio`](https://pypi.org/project/depictio/) package.
It installs the same version of `depictio` and provides the CLI under both of its commands:
`depictio`, and `depictio-cli` for existing scripts and the Nextflow hook.

New installs can use the package directly:

```bash
pip install depictio              # the CLI
pip install "depictio[multiqc]"   # the CLI, able to read MultiQC reports
```

`pip install "depictio-cli[multiqc]"` is equivalent to the second line.

`depictio-cli` ships a copy of files that older releases of it installed, so upgrading one
of them with pip does not delete files `depictio` now owns. The flip side: running
`pip uninstall depictio-cli` without also uninstalling `depictio` removes files `depictio`
needs. `pip install --force-reinstall --no-deps depictio` restores them.

## Documentation

- [Installing the CLI](https://depictio.github.io/depictio-docs/latest/installation/cli/)
- [Using the CLI](https://depictio.github.io/depictio-docs/latest/depictio-cli/usage/)
- [Triggering ingestion from Nextflow](https://depictio.github.io/depictio-docs/latest/depictio-cli/nextflow-trigger/)

## In this repository

The `depictio` package is built from the `pyproject.toml` at the repository root. The
`pyproject.toml` next to this file only defines the alias.
