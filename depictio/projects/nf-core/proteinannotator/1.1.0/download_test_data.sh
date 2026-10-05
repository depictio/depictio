#!/usr/bin/env bash
# Download the nf-core/proteinannotator AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# The pipeline does not publish its samplesheet or a design table, so the
# vendored copies are placed under input/, where the reference METADATA_FILE
# points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/proteinannotator/1.1.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/proteinannotator/1.1.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline proteinannotator --version 1.1.0 --max-file-mb 50 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.csv" "$here/input/sample_metadata.tsv" "$dest/input/"
