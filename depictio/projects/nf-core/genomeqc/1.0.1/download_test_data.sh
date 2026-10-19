#!/usr/bin/env bash
# Download the nf-core/genomeqc 1.0.1 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# genomeqc does not publish its samplesheet and has no design, so the vendored
# design table is placed under input/, where the reference vars point.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/genomeqc/1.0.1/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/genomeqc/1.0.1/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline genomeqc --version 1.0.1 --max-file-mb 50 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/genome_metadata.tsv" "$dest/input/genome_metadata.tsv"
