#!/usr/bin/env bash
# Download the nf-core/nascent 2.3.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# nascent publishes no samplesheet and no design, so the vendored copies are
# placed under input/, where the reference vars point.
#
# About 5.2 GB, 4.8 GB of it the strand bedGraphs (up to 442 MB each, hence the
# default --max-file-mb 500). Pass a lower --max-file-mb to scripts/nfcore_megatest.py
# directly to skip the largest of them; the binned collections then cover fewer
# libraries.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/nascent/2.3.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/nascent/2.3.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline nascent --version 2.3.0 --max-file-mb 500 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.csv" "$dest/input/samplesheet.csv"
cp "$here/input/design.tsv" "$dest/input/design.tsv"
