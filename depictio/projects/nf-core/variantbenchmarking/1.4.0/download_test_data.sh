#!/usr/bin/env bash
# Download the nf-core/variantbenchmarking 1.4.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no AWS CLI needed).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/variantbenchmarking/1.4.0/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline variantbenchmarking --version 1.4.0 \
  --dest "${1:-$HOME/Data/depictio-nfcore/variantbenchmarking/1.4.0/megatest}"
