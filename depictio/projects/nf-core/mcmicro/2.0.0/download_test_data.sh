#!/usr/bin/env bash
# Download the nf-core/mcmicro 2.0.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
# mcmicro does not publish its samplesheet or its marker sheet, so the vendored
# copies are placed under input/, where METADATA_FILE and MARKER_SHEET point.
#
# Then the PNG previews the template's Image collection reads are written under
# previews/ by scripts/make_previews.py (needs numpy, tifffile and Pillow; set
# PYTHON to an interpreter that has them). Without them the rest still ingests.
# TODO(bioimage): replace the PNG previews with an OME-TIFF/zarr pyramid viewer (viv/deck.gl) once bioimage lands
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/mcmicro/2.0.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/mcmicro/2.0.0/megatest}"
python="${PYTHON:-python3}"
python3 "$here/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline mcmicro --version 2.0.0 --dest "$dest"
mkdir -p "$dest/input"
cp "$here/input/samplesheet.csv" "$dest/input/samplesheet.csv"
cp "$here/input/markers.csv" "$dest/input/markers.csv"
if "$python" -c "import numpy, tifffile, PIL" 2>/dev/null; then
  "$python" "$here/scripts/make_previews.py" "$dest" --markers "$dest/input/markers.csv"
else
  echo "warning: $python lacks numpy, tifffile or Pillow: no PNG previews written" >&2
  echo "         (the Previews tab and the cell-map underlay will be left out)" >&2
fi
