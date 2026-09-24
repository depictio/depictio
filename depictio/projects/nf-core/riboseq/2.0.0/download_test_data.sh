#!/usr/bin/env bash
# Download the nf-core/riboseq 2.0.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# Tables only (about 100 MB); no BAM, bigWig or FASTQ.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/riboseq/2.0.0/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline riboseq --version 2.0.0 --max-file-mb 200 \
  --dest "${1:-$HOME/Data/depictio-nfcore/riboseq/2.0.0/megatest}"
