#!/usr/bin/env bash
# Run an SVLT virtual-microscopy simulation against a Depictio instance.
# Each acquisition tick, the svltx-depictio extension (hooked onto
# session_phenobase.write) exports the PhenoBase table to MinIO as a Delta
# table, then POSTs to depictio so connected dashboards refresh.
#
# Requires the `svltx-depictio` package installed in $SVLT_ENV and the
# experiment script to `import svltx.depictio` (proj0039-...-simulate does).
#
# Usage — set at least these two, then run the script:
#   export SVLT_EXP_ROOT=/path/to/your/svlt/experiment
#   export SVLT_API_TOKEN=<depictio admin/user token>
#   ./run_simulation.sh
#
# Every value below can be overridden by exporting the matching env var first;
# defaults target a stock local Depictio (FastAPI :8058, MinIO :9000, MinIO
# creds minio/minio123).
#
# Worktree/dev convenience: if this script lives inside a depictio checkout,
# it auto-discovers the instance's ports + MinIO creds (.env.instance) and the
# admin token (depictio/.depictio/admin_config.yaml) by searching upward from
# the script's own directory. Run it anywhere else and those files simply
# aren't found — the SVLT_* vars / defaults take over. No file is ever read
# from a fixed relative depth, so the script is safe to copy elsewhere.
#
# NOTE: svltx.depictio reads SVLT_API_URL / SVLT_API_ENDPOINT / SVLT_API_TOKEN /
# SVLT_API_PAYLOAD and the SVLT_S3_* vars (the older SVLT_DEPICTIO_API /
# SVLT_DEPICTIO_TOKEN names are no longer read).
#
# We notify via /deltatables/upsert (NOT /events/test-trigger). test-trigger
# only broadcasts + drops the cache; it does NOT recompute column specs or bump
# aggregation_version — so card values (which read the precomputed, version-
# salted specs) stay frozen at the last CLI-ingested numbers. /upsert re-reads
# the S3 delta SVLT just wrote, recomputes specs, bumps the version, AND
# broadcasts the refresh event.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Walk up from the script dir looking for a file/dir; print its path if found.
# Used only to opportunistically locate a depictio checkout's config files —
# absent outside a checkout, in which case we silently fall back to defaults.
find_up() {
    local rel="$1" dir="$SCRIPT_DIR"
    while :; do
        [[ -e "$dir/$rel" ]] && { printf '%s\n' "$dir/$rel"; return 0; }
        [[ "$dir" == "/" ]] && return 1
        dir="$(dirname "$dir")"
    done
}

# --- Instance config (optional) ---------------------------------------------
# In a worktree, .env.instance provides MINIO_PORT / FASTAPI_PORT /
# DEPICTIO_MINIO_ROOT_USER / DEPICTIO_MINIO_ROOT_PASSWORD. Absent elsewhere —
# fall back to stock defaults or the SVLT_* overrides below.
ENV_INSTANCE="${ENV_INSTANCE:-$(find_up .env.instance || true)}"
if [[ -n "$ENV_INSTANCE" && -f "$ENV_INSTANCE" ]]; then
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
# This simulator uses PhenoBase.write() directly, so svlt's own sync_to_bucket
# never runs — have the extension mirror images itself. In deployments where
# svlt pushes images to the same bucket, leave this unset (default: off).
export SVLT_UPLOAD_IMAGES="${SVLT_UPLOAD_IMAGES:-1}"

# Completeness gate: the analysis pipeline writes PhenoBase twice per
# acquisition — once after segmentation (cells, no image patches) and once after
# ROI-square generation (same cells, now with 2D-RGB image paths). Only the
# second write yields displayable rows, so gate the Depictio sync on this column
# being populated: each acquisition then fires a single realtime event, and
# dashboards never refresh onto rows whose images don't exist yet. Unset it to
# restore per-write notifications.
export SVLT_IMAGE_COLUMN="${SVLT_IMAGE_COLUMN:-patches_patches_2d_rgb_path}"

# --- API notify -> depictio (re-specs the delta + fires the WS broadcast) ----
export SVLT_API_URL="${SVLT_API_URL:-http://localhost:${FASTAPI_PORT}/depictio/api/v1}"
export SVLT_API_ENDPOINT="${SVLT_API_ENDPOINT:-/deltatables/upsert}"
export SVLT_API_PAYLOAD="${SVLT_API_PAYLOAD:-{\"data_collection_id\":\"${DC_ID}\",\"delta_table_location\":\"s3://${SVLT_S3_BUCKET}/${DC_ID}\",\"update\":true}}"

# Token: explicit SVLT_API_TOKEN wins; else read a checkout's admin_config.yaml
# if one is found by searching upward. Neither present -> error out below.
if [[ -z "${SVLT_API_TOKEN:-}" ]]; then
    ADMIN_CONFIG="${ADMIN_CONFIG:-$(find_up depictio/.depictio/admin_config.yaml || true)}"
    if [[ -n "$ADMIN_CONFIG" && -f "$ADMIN_CONFIG" ]]; then
        SVLT_API_TOKEN="$(grep 'access_token:' "$ADMIN_CONFIG" | head -1 | awk '{print $2}')"
    fi
fi
: "${SVLT_API_TOKEN:?set SVLT_API_TOKEN (or run inside a depictio checkout with admin_config.yaml) for the API notify}"
export SVLT_API_TOKEN
# Headless: svlt's startup.main() opens a browser on launch. SVLT_NO_BROWSER
# only helps if svlt carries the guard patch; BROWSER=echo is the universal
# no-op (Python's webbrowser runs `echo <url>` instead of opening a browser).
export SVLT_NO_BROWSER=1
export BROWSER="${BROWSER:-echo}"

echo "SVLT -> S3   : $SVLT_S3_ENDPOINT  (dc $DC_ID)"
echo "SVLT -> API  : ${SVLT_API_URL}${SVLT_API_ENDPOINT}"
echo "EXP_ROOT     : $EXP_ROOT   (extra args: ${SVLT_EXTRA_ARGS:-none})"

# SVLT refuses to overwrite prior output
rm -rf "$EXP_ROOT/experiment" "$EXP_ROOT/session"

# SVLT_EXTRA_ARGS is intentionally word-split into separate CLI args.
# shellcheck disable=SC2086
exec "${MAMBA_EXE:-micromamba}" run -n "$SVLT_ENV" python \
    "$SVLT_SCRIPT" \
    --root "$EXP_ROOT" \
    $SVLT_EXTRA_ARGS
