#!/usr/bin/env bash
#
# Stage one ingestion batch for the iris_versioned demo.
#
# `depictio run` scans everything under the project's `locations`; there is no
# flag to ingest a single run directory. So the batches live in `batches/` and
# this swaps one at a time into `data/`.
#
# Exactly one batch is staged at a time, never accumulated. Each batch file is
# already the *complete* state of the survey at that point — batch 2 contains
# batch 1's hundred rows plus Virginica — so staging them side by side would
# make the scanner read the same flowers three times over and every count would
# triple.
#
# Ingest with the default `overwrite` write mode, not `replace-runs`. Since only
# one run is ever staged, `replace-runs` would decline to partition ("only one
# run in this data collection") and, worse, its whole purpose is to leave other
# runs' files untouched — which here would keep the previous batch's rows alive
# alongside the new one. `overwrite` replaces the table contents, which is
# exactly what "the survey now looks like this" means.
#
# The history is not lost: Delta writes a new commit per ingestion regardless of
# mode, so `depictio data versions` still walks all three.
#
# Usage:  ./stage_batch.sh 1|2|3
#         ./stage_batch.sh reset     # back to nothing staged

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/batches"
DEST="$HERE/data"

BATCHES=(
  batch_01_initial_survey
  batch_02_virginica_added
  batch_03_virginica_recalibrated
)

usage() {
  echo "usage: $(basename "$0") 1|2|3|reset" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage

if [[ "$1" == "reset" ]]; then
  rm -rf "${DEST:?}"
  mkdir -p "$DEST"
  echo "Reset: data/ is empty."
  exit 0
fi

[[ "$1" =~ ^[1-3]$ ]] || usage
batch="${BATCHES[$(($1 - 1))]}"

rm -rf "${DEST:?}"
mkdir -p "$DEST"
cp -R "$SRC/$batch" "$DEST/$batch"

rows=$(($(wc -l < "$DEST/$batch/iris.csv") - 1))
echo "Staged $batch ($rows rows) — data/ holds this batch only."
echo
echo "Now run:"
echo "  depictio run --project-name \"Iris Versioned Demo\""
