#!/usr/bin/env bash
# Download the nf-core/atacseq 1.2.2 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# The run wrote MultiQC 1.9, which ships no parquet, so after the download run
#   python -m depictio.dev_scripts.multiqc_reprocess --src TARGET_DIR --dest TARGET_DIR
# (see megatest.yaml post_fetch_help).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline atacseq --version 1.2.2 \
  --dest "${1:-$HOME/Data/depictio-nfcore/atacseq/1.2.2/megatest}"
