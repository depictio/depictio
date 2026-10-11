# Try Depictio in Codespaces

This codespace runs the published `depictio[local]` package, without Docker.
When the codespace was created, it ran:

```bash
uv tool install "depictio[local]"
```

Each time the codespace starts, it runs:

```bash
depictio local up --no-open --port 8058
```

The first start downloads MongoDB, Redis and SeaweedFS from conda-forge and loads
the Iris and Penguins examples. It takes about a minute; later starts take seconds.

## Open the dashboards

Port 8058 opens in a new browser tab once the server is up. If the tab did not
open, go to the **Ports** panel and click the globe icon next to *Depictio*.
The server runs in single-user mode, so there is no login. The port is private,
which means only you can open it.

`depictio local status` shows whether each service runs; their logs are in
`~/.depictio/local/logs`.

## Add your own results

Drag a results folder from your computer onto the Explorer, then run:

```bash
depictio ingest path/to/results
```

`depictio ingest` picks the template from the pipeline name and version the run
recorded. nf-core results do not contain the samplesheet: when the template
cannot find it under `input/`, pass it explicitly.

```bash
depictio ingest path/to/results \
  --template nf-core/rnaseq/latest \
  --var SAMPLESHEET_FILE=$PWD/samplesheet.csv
```

The nf-core templates are listed at
<https://depictio.github.io/depictio-docs/latest/nf-core/>.

## Manage the server

| Command | What it does |
|---------|--------------|
| `depictio local status` | Show each service and its port, and whether the API answers |
| `depictio local down` | Stop the services. The data is kept |
| `depictio local up` | Start them again |
| `depictio local wipe` | Stop the server and delete its data |

Stopping the codespace stops the services. The next start brings them back,
with your data.

## More

- Python package docs: <https://depictio.github.io/depictio-docs/latest/installation/local/>
- Contributor environment, with the full Docker Compose stack built from the
  sources: [`../devcontainer.json`](../devcontainer.json). Open it from
  **Code → Codespaces → New with options**, or with *Reopen in Container*
  in VS Code.
