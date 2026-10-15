#!/usr/bin/env bash
# Download the nf-core/pairgenomealign 3.0.4 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# pairgenomealign does not publish its samplesheet, so the vendored copy and the
# vendored design table are placed under input/, where the reference vars point.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/pairgenomealign/3.0.4/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/pairgenomealign/3.0.4/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline pairgenomealign --version 3.0.4 --max-file-mb 50 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.csv" "$dest/input/samplesheet.csv"
cp "$here/input/genome_metadata.tsv" "$dest/input/genome_metadata.tsv"
