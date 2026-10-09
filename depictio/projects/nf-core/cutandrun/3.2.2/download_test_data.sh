#!/usr/bin/env bash
# Download the nf-core/cutandrun 3.2.2 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# There is no usable 3.2.2 megatest yet: every cutandrun 3.2.x prefix in the
# bucket is empty and results_sha is null in megatest.yaml, so this wrapper has
# nothing usable to download until one is published. The template was validated
# on EMBL HPC runs instead, repatriated and reprocessed with
#   python scripts/nfcore_validation_hpc.py fetch --run cutandrun322-full
#   python scripts/nfcore_validation_hpc.py reprocess --run cutandrun322-full
# (--run cutandrun322-small for the test_full_small profile).
#
# The release writes MultiQC 1.19, which ships no parquet, so after a download run
#   python -m depictio.dev_scripts.multiqc_reprocess --src TARGET_DIR --dest TARGET_DIR
# and ingest with --var MULTIQC_REPROCESSED=true (see megatest.yaml post_fetch_help).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/cutandrun/3.2.2/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline cutandrun --version 3.2.2 \
  --dest "${1:-$HOME/Data/depictio-nfcore/cutandrun/3.2.2/megatest}"
