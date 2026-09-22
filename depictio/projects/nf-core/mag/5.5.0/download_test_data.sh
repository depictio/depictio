#!/usr/bin/env bash
# Download the nf-core/mag 5.5.0 AWS megatest subset for local testing.
# Thin wrapper: the file list lives in megatest.yaml next to this script and the
# retrying fetch in scripts/nfcore_megatest.py (public bucket, no credentials).
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/mag/5.5.0/megatest
#
# Two things this run does not publish and this script therefore adds:
#   * the samplesheet. The pinned prefix carries no `input/` directory, so the
#     copy bundled with the template is placed into TARGET_DIR/input/ below.
#   * the MultiQC report. The run has no multiqc/ at all; the parquet Depictio
#     reads is produced afterwards by the command printed at the end.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/mag/5.5.0/megatest}"

python3 "${here}/../../../../../scripts/nfcore_megatest.py" fetch \
  --pipeline mag --version 5.5.0 --dest "${dest}" --max-file-mb 200

mkdir -p "${dest}/input"
cp "${here}/input/samplesheet.full.v4.csv" "${dest}/input/samplesheet.full.v4.csv"
echo "-> copied the bundled samplesheet into ${dest}/input/"

cat <<EOF

Next, rebuild the MultiQC report this run never wrote:

  python -m depictio.dev_scripts.multiqc_reprocess --src "${dest}" --dest "${dest}"

then validate the template against the data:

  depictio-cli run --template nf-core/mag/5.5.0 --data-root "${dest}" --dry-run
EOF
