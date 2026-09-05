#!/usr/bin/env bash
# Download the nf-core/taxprofiler 2.0.1 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# taxprofiler never copies its two input sheets into the results tree, so they
# are pulled straight from the nf-core test-datasets URLs recorded in
# pipeline_info/params.json (`input` and `databases`) into <TARGET_DIR>/input/.
# The template's samplesheet and database_sheet data collections read them from
# there; byte-identical copies also ship next to this script in input/.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/taxprofiler/2.0.1/megatest
set -euo pipefail
DEST="${1:-$HOME/Data/depictio-nfcore/taxprofiler/2.0.1/megatest}"

python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline taxprofiler --version 2.0.1 --dest "$DEST"

TESTDATA="https://raw.githubusercontent.com/nf-core/test-datasets/taxprofiler"
mkdir -p "$DEST/input"
curl -sSfL -o "$DEST/input/samplesheet_full.csv" "$TESTDATA/samplesheet_full.csv"
curl -sSfL -o "$DEST/input/database_full_v2.1.csv" "$TESTDATA/database_full_v2.1.csv"
echo "Input sheets written to $DEST/input/"
