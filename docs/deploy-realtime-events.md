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

## 4. Drive events

```bash
cd depictio/projects/test/adapt_feedb_ms
./stream_test.sh reset          # seed 2 rows + ingest
./stream_test.sh stream 3       # one row every 3s until Ctrl+C
```

- Each tick: appends a row → re-ingests via CLI (`/deltatables/upsert`) → broadcast → subscribed viewers refetch.
- No manual refresh: new images in the gallery, cards recompute (counts, averages, timeline), updated items flash.
- Other modes: `bump 5` (rows back-to-back), `status`.
- Defaults target §1 (`API_URL=http://localhost:8058`, `CLI_CONFIG=~/.depictio/CLI.yaml`) — export either to override.
