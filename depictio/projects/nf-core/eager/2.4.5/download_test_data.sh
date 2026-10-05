#!/usr/bin/env bash
# Download the nf-core/eager 2.4.5 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/eager/2.4.5/megatest
#
# eager's megatest fetch carries no input/ prefix (see megatest.yaml and
# VALIDATION_REPORT.md): after this runs, copy input/benchmarking_vikingfish.tsv
# from this directory into TARGET_DIR/input/ by hand before `depictio-cli run`.
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline eager --version 2.4.5 \
  --dest "${1:-$HOME/Data/depictio-nfcore/eager/2.4.5/megatest}"
