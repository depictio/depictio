#!/usr/bin/env bash
# Download the nf-core/mhcquant 3.2.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# mhcquant does not publish its samplesheet, so the vendored copy is placed
# under input/, where the template's METADATA_FILE default points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/mhcquant/3.2.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/mhcquant/3.2.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline mhcquant --version 3.2.0 --max-file-mb 300 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.tsv" "$dest/input/samplesheet.tsv"
