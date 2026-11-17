#!/usr/bin/env bash
# Download the nf-core/stableexpression 1.1.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# The design is published by the pipeline (merged_data/whole_design.csv), so
# nothing is vendored. About 358 MB, all but 17 MB of it the merged matrix.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/stableexpression/1.1.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/stableexpression/1.1.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline stableexpression --version 1.1.0 --dest "$dest"
