#!/usr/bin/env bash
# nf-core/spatialvi is unreleased (dev branch), so there is no AWS megatest to
# download. The reference run is the `test` profile on the EMBL cluster:
#
#   python scripts/nfcore_validation_hpc.py run --key spatialvi
#   python scripts/nfcore_validation_hpc.py fetch --key spatialvi
#
# Copy the --input samplesheet to <DATA_ROOT>/input/ afterwards.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Only fetches the small test-datasets inputs (the Space Ranger sample sheets)
#   used for offline checks, into TARGET_DIR
#   (default ~/Data/depictio-nfcore/spatialvi/1.0.0dev/test_inputs).
set -euo pipefail
dest="${1:-$HOME/Data/depictio-nfcore/spatialvi/1.0.0dev/test_inputs}"
base="https://raw.githubusercontent.com/nf-core/test-datasets/spatialvi/testdata/human-brain-cancer-11-mm-capture-area-ffpe-2-standard_v2_ffpe_cytassist"
mkdir -p "$dest"
for f in samplesheet_spaceranger.csv samplesheet_downstream.csv; do
  curl -fsSL --retry 3 -o "$dest/$f" "$base/$f" || echo "not found: $f" >&2
done
echo "Small inputs in $dest. The results come from the HPC test run (see above)."
