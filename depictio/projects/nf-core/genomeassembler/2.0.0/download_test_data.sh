#!/usr/bin/env bash
# Download the nf-core/genomeassembler 2.0.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# The run publishes no copy of its samplesheet, so the bundled one is placed
# into TARGET_DIR/input/, where the METADATA_FILE default points.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/genomeassembler/2.0.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/genomeassembler/2.0.0/megatest}"
python3 "${here}/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline genomeassembler --version 2.0.0 --dest "${dest}" --max-file-mb 50
mkdir -p "${dest}/input"
cp "${here}/input/samplesheet.csv" "${dest}/input/samplesheet.csv"
