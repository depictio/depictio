#!/usr/bin/env bash
# Download the nf-core/viralmetagenome 1.2.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# viralmetagenome does not publish the --metadata table it merged into its
# overview, so the vendored copy is placed under input/, where the reference
# vars point. The run wrote no MultiQC parquet: rebuild it afterwards with
#   python -m depictio.dev_scripts.multiqc_reprocess --src DIR --dest DIR --exclude '*_mqc.tsv'
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/viralmetagenome/1.2.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/viralmetagenome/1.2.0/megatest}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline viralmetagenome --version 1.2.0 --max-file-mb 20 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/metadata.tsv" "$dest/input/metadata.tsv"
