#!/usr/bin/env bash
# Download the nf-core/hlatyping 2.2.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# hlatyping does not publish its samplesheet, so the vendored copy (the
# test-datasets sheet the run read, revision 2adcc84) is placed under input/,
# where the template's METADATA_FILE default points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/hlatyping/2.2.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/hlatyping/2.2.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline hlatyping --version 2.2.0 --max-file-mb 50 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.csv" "$dest/input/samplesheet.csv"
