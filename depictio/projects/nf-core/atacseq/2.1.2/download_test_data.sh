#!/usr/bin/env bash
# Download the nf-core/atacseq 2.1.2 megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# No usable S3 megatest exists for 2.1.2: the release prefix holds a single
# 12 GB object and megatest.yaml pins no results_sha, so `fetch` resolves the
# empty release prefix and stops with the fallback table instead of mirroring
# anything (see depictio/projects/nf-core/MEGATEST_STATUS.md). The template was
# validated on EMBL HPC runs instead:
#   python scripts/nfcore_validation_hpc.py ... (keys atacseq2-*)
#
# Once a run is pinned, the MultiQC 1.13 report ships no parquet, so after the
# download run
#   python -m depictio.dev_scripts.multiqc_reprocess --src TARGET_DIR --dest TARGET_DIR
# (see megatest.yaml post_fetch_help).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/atacseq/2.1.2/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline atacseq --version 2.1.2 \
  --dest "${1:-$HOME/Data/depictio-nfcore/atacseq/2.1.2/megatest}"
