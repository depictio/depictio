#!/usr/bin/env bash
# Upload the nfcore_megatests_showcase project + DCs + dashboards into
# the .env.instance MongoDB. Two phases:
#   1. depictio CLI scan inside the API container — registers the
#      project doc, the workflow, and all DCs; materialises a Delta
#      table per fixture file.
#   2. mongoimport the dashboard seed JSONs — runs from the host
#      against the bind-mounted MongoDB port 27100.
#
# Idempotent: --overwrite tells the CLI to drop + re-register the project
# on each run; mongoimport --mode upsert avoids duplicate dashboards.
#
# Usage:
#   bash depictio/projects/init/nfcore_megatests_showcase/scripts/upload.sh

set -euo pipefail

# Pull the docker-compose project name (e.g. depictio-claude-volcano-plot-interactive-ctrtq)
# from .env.instance so we target the right compose project regardless of which
# worktree this runs in.
PROJECT_NAME=$(grep -E '^COMPOSE_PROJECT_NAME=' .env.instance | cut -d= -f2)
MONGO_PORT=$(grep -E '^MONGO_PORT=' .env.instance | cut -d= -f2)

FASTAPI_PORT=$(grep -E '^FASTAPI_PORT=' .env.instance | cut -d= -f2)

echo "→ Phase 0: mint fresh admin token (instance JWT secret may differ from"
echo "    the stored admin_config.yaml token)"
TOKEN=$(curl -s -X POST "http://localhost:${FASTAPI_PORT}/depictio/api/v1/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin@example.com&password=changeme" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
if [ -z "$TOKEN" ]; then
    echo "    ✗ failed to mint admin token (is the API up at :${FASTAPI_PORT}?)"
    exit 1
fi
echo "    ✓ minted (${#TOKEN} chars)"

# Build an in-container CLI config that (a) targets the API via its docker
# DNS hostname (depictio-backend:8058 is the in-network port regardless of
# any external FASTAPI_PORT remap) and (b) embeds the fresh access token.
CLI_CONFIG="depictio/projects/init/nfcore_megatests_showcase/scripts/.cli_config.generated.yaml"
# Use the project venv's Python — it has PyYAML (host system Python typically
# doesn't, especially on macOS with the python.org installer).
PY=${PY:-.venv/bin/python}
"$PY" - <<PY_END
import yaml, pathlib
src = yaml.safe_load(pathlib.Path("depictio/.depictio/admin_config.yaml").read_text())
# Rewrite all the host/port references the stored admin_config carries from
# whichever worktree last wrote it — every service lives at its docker DNS
# hostname when the CLI runs via `docker compose exec`.
src["api_base_url"] = "http://depictio-backend:8058"
src["s3_storage"]["external_host"] = "minio"
src["s3_storage"]["external_port"] = 9000
src["user"]["token"]["access_token"] = "$TOKEN"
src["user"]["token"]["logged_in"] = True
pathlib.Path("$CLI_CONFIG").write_text(yaml.safe_dump(src, sort_keys=False))
PY_END

echo ""
echo "→ Phase 1: depictio CLI scan inside compose project $PROJECT_NAME (service: depictio-backend)"
# `docker compose exec` targets the service name (not the container name) so
# we don't depend on the container's `-1`/`-2` replica suffix. `-T` disables
# TTY allocation so this works from non-interactive shells.
docker compose -p "$PROJECT_NAME" \
    -f docker-compose.dev.yaml -f docker-compose.override.yaml \
    --env-file .env.instance \
    exec -T depictio-backend python -m depictio.cli run \
        --CLI-config-path "/app/${CLI_CONFIG}" \
        --project-config-path /app/depictio/projects/init/nfcore_megatests_showcase/project.yaml \
        --overwrite \
        --update-config \
        --rescan-folders

echo ""
echo "→ Phase 2: mongoimport dashboard seeds → localhost:${MONGO_PORT}"
for f in depictio/projects/init/nfcore_megatests_showcase/.db_seeds/dashboard_*.json; do
    name=$(basename "$f")
    echo "    upserting $name"
    mongoimport \
        --uri "mongodb://localhost:${MONGO_PORT}/depictioDB" \
        --collection dashboards \
        --file "$f" \
        --mode upsert \
        --upsertFields dashboard_id \
        --quiet
done

echo ""
echo "✓ Done. Open the dashboards:"
for f in depictio/projects/init/nfcore_megatests_showcase/.db_seeds/dashboard_*.json; do
    id=$(python3 -c "import json,sys; print(json.load(open('$f'))['dashboard_id']['\$oid'])")
    viz=$(basename "$f" .json | sed 's/^dashboard_//')
    echo "    $viz → http://localhost:8100/dashboard-beta/$id"
done
