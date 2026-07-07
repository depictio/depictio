#!/usr/bin/env bash
# Run an SVLT virtual-microscopy simulation against a Depictio instance.
# Each acquisition tick: PhenoBase.write() pushes a delta table to MinIO, then
# POSTs to depictio so connected dashboards refresh.
#
# Works in two modes:
#   • Worktree/dev — auto-derives ports + MinIO creds from ../../../../.env.instance
#                    and the admin token from depictio/.depictio/admin_config.yaml.
#   • Generic SVLT — no worktree/.env.instance needed; set the SVLT_* vars below
#                    (at minimum SVLT_EXP_ROOT and SVLT_API_TOKEN) and go.
#
# Every value below can be overridden by exporting the matching env var first;
# defaults target a stock local Depictio (FastAPI :8058, MinIO :9000).
#
# NOTE: phenobase.py reads SVLT_API_URL / SVLT_API_ENDPOINT / SVLT_API_TOKEN /
# SVLT_API_PAYLOAD (the older SVLT_DEPICTIO_API / SVLT_DEPICTIO_TOKEN names are
# no longer read).
#
# We notify via /deltatables/upsert (NOT /events/test-trigger). test-trigger
# only broadcasts + drops the cache; it does NOT recompute column specs or bump
# aggregation_version — so card values (which read the precomputed, version-
# salted specs) stay frozen at the last CLI-ingested numbers. /upsert re-reads
# the S3 delta SVLT just wrote, recomputes specs, bumps the version, AND
# broadcasts the refresh event.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPICTIO_ROOT="${DEPICTIO_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"

# --- Instance config (optional) ---------------------------------------------
# In a worktree, .env.instance provides MINIO_PORT / FASTAPI_PORT /
# DEPICTIO_MINIO_ROOT_USER / DEPICTIO_MINIO_ROOT_PASSWORD. Absent elsewhere —
# fall back to stock defaults or the SVLT_* overrides below.
ENV_INSTANCE="${ENV_INSTANCE:-$DEPICTIO_ROOT/.env.instance}"
if [[ -f "$ENV_INSTANCE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_INSTANCE"
fi

MINIO_PORT="${MINIO_PORT:-9000}"
FASTAPI_PORT="${FASTAPI_PORT:-8058}"

DC_ID="${SVLT_DC_ID:-750a1b2c3d4e5f6a7b8c9d10}"
EXP_ROOT="${SVLT_EXP_ROOT:?set SVLT_EXP_ROOT to your SVLT experiment directory}"
SVLT_ENV="${SVLT_ENV:-svlt-simulate}"
SVLT_SCRIPT="${SVLT_SCRIPT:-$EXP_ROOT/proj0039-exp0002-simulate-experiment.py}"

# Extra CLI args for the simulate script — varies per script. Some accept
# --delay / --port; the proj0039 exp0002 script accepts only --root (delay/port
# are hardcoded inside it), so this defaults to empty. Override as needed, e.g.
# SVLT_EXTRA_ARGS="--delay 1 --port 6221".
SVLT_EXTRA_ARGS="${SVLT_EXTRA_ARGS:-}"

# --- S3 sync -> this instance's MinIO ---------------------------------------
export SVLT_S3_ENDPOINT="${SVLT_S3_ENDPOINT:-http://localhost:${MINIO_PORT}}"
export SVLT_S3_KEY="${SVLT_S3_KEY:-${DEPICTIO_MINIO_ROOT_USER:-minio}}"
export SVLT_S3_SECRET="${SVLT_S3_SECRET:-${DEPICTIO_MINIO_ROOT_PASSWORD:-minio123}}"
export SVLT_S3_BUCKET="${SVLT_S3_BUCKET:-depictio-bucket}"
export SVLT_DC_ID="$DC_ID"

# --- API notify -> depictio (re-specs the delta + fires the WS broadcast) ----
export SVLT_API_URL="${SVLT_API_URL:-http://localhost:${FASTAPI_PORT}/depictio/api/v1}"
export SVLT_API_ENDPOINT="${SVLT_API_ENDPOINT:-/deltatables/upsert}"
export SVLT_API_PAYLOAD="${SVLT_API_PAYLOAD:-{\"data_collection_id\":\"${DC_ID}\",\"delta_table_location\":\"s3://${SVLT_S3_BUCKET}/${DC_ID}\",\"update\":true}}"

# Token: explicit SVLT_API_TOKEN wins; else read admin_config.yaml if present.
if [[ -z "${SVLT_API_TOKEN:-}" ]]; then
    ADMIN_CONFIG="${ADMIN_CONFIG:-$DEPICTIO_ROOT/depictio/.depictio/admin_config.yaml}"
    if [[ -f "$ADMIN_CONFIG" ]]; then
        SVLT_API_TOKEN="$(grep 'access_token:' "$ADMIN_CONFIG" | head -1 | awk '{print $2}')"
    fi
fi
: "${SVLT_API_TOKEN:?set SVLT_API_TOKEN (or provide admin_config.yaml) for the API notify}"
export SVLT_API_TOKEN
export SVLT_NO_BROWSER=1

echo "SVLT -> S3   : $SVLT_S3_ENDPOINT  (dc $DC_ID)"
echo "SVLT -> API  : ${SVLT_API_URL}${SVLT_API_ENDPOINT}"
echo "EXP_ROOT     : $EXP_ROOT   (extra args: ${SVLT_EXTRA_ARGS:-none})"

# SVLT refuses to overwrite prior output
rm -rf "$EXP_ROOT/experiment" "$EXP_ROOT/session"

# shellcheck disable=SC2086 -- SVLT_EXTRA_ARGS is intentionally word-split
exec "${MAMBA_EXE:-micromamba}" run -n "$SVLT_ENV" python \
    "$SVLT_SCRIPT" \
    --root "$EXP_ROOT" \
    $SVLT_EXTRA_ARGS
