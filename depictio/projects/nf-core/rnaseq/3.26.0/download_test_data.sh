#!/usr/bin/env bash
# Download the nf-core/rnaseq 3.26.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/rnaseq/3.26.0/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline rnaseq --version 3.26.0 \
  --dest "${1:-$HOME/Data/depictio-nfcore/rnaseq/3.26.0/megatest}"
