#!/usr/bin/env bash
# Download the nf-core/rnasplice 1.0.4 test data subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# Tables only; no BAM, bigWig or FASTQ.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/rnasplice/1.0.4/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline rnasplice --version 1.0.4 --max-file-mb 200 \
  --dest "${1:-$HOME/Data/depictio-nfcore/rnasplice/1.0.4/megatest}"
