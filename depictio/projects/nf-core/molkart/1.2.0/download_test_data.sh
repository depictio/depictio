#!/usr/bin/env bash
# nf-core/molkart 1.2.0 has no usable AWS megatest (the prefix holds
# pipeline_info only), so there is nothing to download here. The reference run
# is produced on the EMBL cluster from the test_full profile (Zenodo data):
#
#   python scripts/nfcore_validation_hpc.py run --key molkart
#   python scripts/nfcore_validation_hpc.py fetch --key molkart   # needs rsync -L
#
# molkart publishes its masks, Mindagap tables and QC sheets as symlinks even
# with --publish_dir_mode copy, so the fetch must dereference them (rsync -L).
# Copy the --input samplesheet to <DATA_ROOT>/input/ afterwards.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Only fetches the small test-datasets inputs (images, spot table,
#   samplesheet) used for offline checks, into TARGET_DIR
#   (default ~/Data/depictio-nfcore/molkart/1.2.0/test_inputs).
set -euo pipefail
dest="${1:-$HOME/Data/depictio-nfcore/molkart/1.2.0/test_inputs}"
base="https://raw.githubusercontent.com/nf-core/test-datasets/molkart/test_data"
mkdir -p "$dest"
for f in input_data/nuclear.tiff input_data/membrane.tiff input_data/spots.txt \
  samplesheets/samplesheet_nuclear.csv samplesheets/samplesheet_membrane.csv \
  samplesheets/samplesheet_full_test.csv; do
  curl -fsSL --retry 3 -o "$dest/$(basename "$f")" "$base/$f"
done
echo "Small inputs in $dest. The results come from the HPC test_full run (see above)."
