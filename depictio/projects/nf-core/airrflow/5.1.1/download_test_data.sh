#!/usr/bin/env bash
# Download the nf-core/airrflow 5.1.1 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# There is no 5.1.1 megatest run: the bucket has no prefix for the release sha and
# results_sha is null in megatest.yaml, so this wrapper has nothing to download
# until one is published. The bump was validated on an EMBL HPC run of the test
# profile instead, repatriated with
#   python scripts/nfcore_validation_hpc.py fetch --run airrflow511
# and the 5.1.0 megatest the template was built on is still fetched by
#   bash depictio/projects/nf-core/airrflow/5.1.0/download_test_data.sh
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/airrflow/5.1.1/megatest
set -euo pipefail
exec python3 "$(dirname "$0")/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline airrflow --version 5.1.1 \
  --dest "${1:-$HOME/Data/depictio-nfcore/airrflow/5.1.1/megatest}"
