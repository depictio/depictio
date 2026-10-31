#!/usr/bin/env bash
# Download the nf-core/quantms 1.1.1 AWS megatest subset (DIA mode) for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# quantms does not publish a usable SDRF, so the vendored copy is placed under
# input/, where the template's METADATA_FILE default points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/quantms/1.1.1/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/quantms/1.1.1/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline quantms --version 1.1.1 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/sdrf.tsv" "$dest/input/sdrf.tsv"
