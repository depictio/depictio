#!/usr/bin/env bash
# Download the nf-core/isoseq 3.0.1 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# isoseq does not publish a design table, so the vendored one is placed under
# input/, where the reference seed's METADATA_FILE points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/isoseq/3.0.1/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/isoseq/3.0.1/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline isoseq --version 3.0.1 --max-file-mb 250 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/sample_metadata.tsv" "$dest/input/sample_metadata.tsv"
