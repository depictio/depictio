#!/usr/bin/env bash
# Run Chris's SVLT virtual microscopy simulation with S3/depictio integration.
# PhenoBase.write() will push delta tables to MinIO and notify the depictio API.
#
# Usage: ./run_simulation.sh
#        SVLT_DELAY=10 ./run_simulation.sh

export SVLT_S3_ENDPOINT="${SVLT_S3_ENDPOINT:-http://localhost:9000}"
export SVLT_S3_KEY="${SVLT_S3_KEY:-minio}"
export SVLT_S3_SECRET="${SVLT_S3_SECRET:-minio123}"
export SVLT_S3_BUCKET="${SVLT_S3_BUCKET:-depictio-bucket}"
export SVLT_DC_ID="${SVLT_DC_ID:-750a1b2c3d4e5f6a7b8c9d10}"
export SVLT_DEPICTIO_API="${SVLT_DEPICTIO_API}"
export SVLT_DEPICTIO_TOKEN="${SVLT_DEPICTIO_TOKEN}"

EXP_ROOT="${SVLT_EXP_ROOT:-/Users/tweber/Data/chris-microscopy-virtual-experiment/exp0002}"
DELAY="${SVLT_DELAY:-5}"
PORT="${SVLT_PORT:-6221}"

# Clean stale output from previous runs (SVLT refuses to overwrite)
rm -rf "$EXP_ROOT/experiment" "$EXP_ROOT/session"

exec micromamba run -n svlt-simulate python \
    "$EXP_ROOT/proj0039-exp0002-simulate-experiment.py" \
    --root "$EXP_ROOT" \
    --delay "$DELAY" \
    --port "$PORT"
