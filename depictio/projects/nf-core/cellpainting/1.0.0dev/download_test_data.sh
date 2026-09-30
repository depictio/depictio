#!/usr/bin/env bash
# Download the nf-core/cellpainting 1.0.0dev AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# The pipeline takes no plate map, so the vendored subset is placed under
# input/, where the template's METADATA_FILE default points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/cellpainting/1.0.0dev/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/cellpainting/1.0.0dev/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline cellpainting --version 1.0.0dev --max-file-mb 300 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/platemap.csv" "$dest/input/platemap.csv"
