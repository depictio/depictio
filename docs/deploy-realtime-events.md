# Deploy Depictio with real-time dashboards

- Bring up Depictio, import the `adapt_feedb_ms` demo, watch its dashboard refresh live over WebSocket as rows land.
- Tested on `1.1.4-b3`. Needs Docker + Python 3.11 (CLI). All local — no external S3/DB.

## 1. Stack

```bash
curl -LO https://raw.githubusercontent.com/depictio/depictio/stable/docker-compose.yaml

cat > .env <<'EOF'
DEPICTIO_VERSION=1.1.4-b3
DEPICTIO_AUTH_SINGLE_USER_MODE=true                 # admin, no login (compose default)
DEPICTIO_EVENTS_ENABLED=true                        # opens /events/ws + the React RealtimeIndicator
EOF

docker compose up -d
```

- Viewer `:5080`, API `:8058`.
- Single-user mode drops you in as admin — no login.
- No dev endpoints needed: the CLI re-ingest (`/deltatables/upsert`) broadcasts the refresh itself.

## 2. CLI + token

```bash
pip install depictio-cli        # or: uv tool install depictio-cli
```

- `http://localhost:5080/cli-agents` → create token → download `CLI.yaml`.
- Install it + check:

```bash
mkdir -p ~/.depictio && mv ~/Downloads/CLI.yaml ~/.depictio/CLI.yaml
depictio-cli config check
```

## 3. Import the demo

```bash
git clone --depth 1 https://github.com/depictio/depictio.git && cd depictio

depictio-cli run \
  --project-config-path depictio/projects/test/adapt_feedb_ms/project.yaml \
  --update-config --rescan-folders --overwrite --skip-s3-check --skip-join
```

- Creates DC `750a1b2c3d4e5f6a7b8c9d10` + the **Microscopy Real-time Monitor** dashboard.
- Open `http://localhost:5080/dashboard/750a1b2c3d4e5f6a7b8c9d20` — RealtimeIndicator goes green once subscribed.
- Indicator only shows for opted-in projects. `adapt_feedb_ms` already carries the block:
  ```yaml
  realtime:
    enabled: true
  ```

## 4. Drive events — synthetic (`stream_test.sh`)

The quickest way to see the dashboard move. No extra deps — reuses the CLI + token from §2.

```bash
cd depictio/projects/test/adapt_feedb_ms
./stream_test.sh reset          # seed 2 rows + ingest
./stream_test.sh stream 3       # one row every 3s until Ctrl+C
```

- Each tick: appends a row → re-ingests via CLI (`/deltatables/upsert`) → broadcast → subscribed viewers refetch.
- No manual refresh: new images in the gallery, cards recompute (counts, averages, timeline), updated items flash.
- Other modes: `bump 5` (rows back-to-back), `status`.
- Defaults target §1 (`API_URL=http://localhost:8058`, `CLI_CONFIG=~/.depictio/CLI.yaml`) — export either to override.

## 5. Drive events — real simulator (SVLT + `svltx-depictio`)

The realistic path: a **virtual-microscopy acquisition simulator** (SVLT) produces a
live `PhenoBase` table of segmented cells with image patches, and the `svltx-depictio`
extension exports each acquisition to MinIO as a Delta table and notifies the API —
exactly what a real instrument feed would do.

> Needs the SVLT project (`svlt-core` + an experiment script), which lives outside this
> repo (EMBL: `git.embl.de/rhodes/svlt-projects`). `svltx-depictio` is the glue and ships
> in that same `svltx/` tree. The synthetic driver in §4 needs none of this.

### 5.1 Environment

Create an isolated env (the script defaults to one named `svlt-simulate`; override with
`SVLT_ENV`) and install SVLT, your experiment script's deps, and the extension **editable**:

```bash
micromamba create -n svlt-simulate python=3.11 -y   # or conda/mamba
micromamba activate svlt-simulate

pip install svlt-core           # + the experiment project's deps
pip install -e svltx/depictio   # editable: edits apply on next run, no reinstall
```

The extension activates by wrapping `session_phenobase.write`, so the experiment script
must import it once (the `proj0039` simulate script already does):

```python
import svltx.depictio  # noqa: F401  — inert unless SVLT_S3_ENDPOINT is set
```

### 5.2 Run the simulation

`run_simulation.sh` wires the extension to *this* Depictio instance and launches the
experiment. Point it at your experiment directory and go:

```bash
cd depictio/projects/test/adapt_feedb_ms

SVLT_EXP_ROOT=/path/to/your/svlt/experiment \
  ./run_simulation.sh
```

Every value has a default targeting a stock local stack (FastAPI `:8058`, MinIO `:9000`,
DC `750a1b2c3d4e5f6a7b8c9d10`); override any by exporting it first. The essentials:

| Var | Default | Purpose |
|-----|---------|---------|
| `SVLT_EXP_ROOT` | — (**required**) | your SVLT experiment directory (holds the simulate script + inputs) |
| `SVLT_API_TOKEN` | from `admin_config.yaml` if present | Bearer token for the API notify — set it explicitly outside a worktree |
| `SVLT_ENV` | `svlt-simulate` | conda/micromamba env holding svlt + the extension |
| `SVLT_SCRIPT` | `$SVLT_EXP_ROOT/proj0039-exp0002-simulate-experiment.py` | experiment entry point |
| `SVLT_DC_ID` | `750a1b2c3d4e5f6a7b8c9d10` | target data collection → S3 prefix + Delta path |
| `SVLT_EXTRA_ARGS` | *(empty)* | extra flags for the simulate script, e.g. `--delay 1 --port 6221` |

In a worktree the script auto-derives ports, MinIO creds, and the token from
`.env.instance` + `admin_config.yaml`; outside one it uses the stock defaults and you
supply `SVLT_API_TOKEN`.

Open `http://localhost:5080/dashboard/750a1b2c3d4e5f6a7b8c9d20` and watch acquisitions land
live — same refresh as §4, but with real segmented-cell images and morphology.

### 5.3 Two details the script handles for you

- **One event per acquisition.** The pipeline writes `PhenoBase` twice per tick (after
  segmentation, then after image-patch rendering). The script sets
  `SVLT_IMAGE_COLUMN=patches_patches_2d_rgb_path` so the sync fires only once that column
  is populated — dashboards never refresh onto image-less rows. Unset to notify per write.
- **Cards recompute, not just refresh.** It notifies `/deltatables/upsert` (not the dev-only
  `/events/test-trigger`, which only broadcasts). `/upsert` re-reads the new Delta,
  recomputes column specs, and bumps the version — so cards/timeline actually update.
