#!/usr/bin/env bash
# Download nf-core/ampliseq 2.16.0 AWS megatest data for local testing.
# Only downloads the files needed by the template recipes + MultiQC.
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR]
#   # Default TARGET_DIR: ./ampliseq-2.16.0-testdata
set -euo pipefail

S3_PREFIX="s3://nf-core-awsmegatests/ampliseq/results-3d5c7e5bec28de279337f3ffe3c312a45940b782"
TARGET="${1:-./ampliseq-2.16.0-testdata}"

echo "Downloading ampliseq 2.16.0 test data to: $TARGET"
mkdir -p "$TARGET"

# --- Pipeline params ---
# The CLI reads pipeline_info/params*.json to learn how the run was configured:
# it auto-fills METADATA_FILE (this run used --metadata) and sets the route/skip
# flags that decide which data collections the template keeps. Without it the
# metadata and ANCOM-BC collections are pruned and the files below go unused.
aws s3 cp "$S3_PREFIX/pipeline_info/params_2026-02-13_10-48-05.json" \
  "$TARGET/pipeline_info/params.json" --no-sign-request

# --- Samplesheet (user-provided input) ---
# Required: the samplesheet DC is not optional, and SAMPLESHEET_FILE is
# auto-detected from <TARGET>/input/. Without this file the template run stops
# at validation with "{SAMPLESHEET_FILE} does not exist".
aws s3 cp "$S3_PREFIX/input/Samplesheet_full.tsv" "$TARGET/input/Samplesheet_full.tsv" --no-sign-request

# --- Metadata (user-provided input) ---
aws s3 cp "$S3_PREFIX/input/Metadata_full.tsv" "$TARGET/input/Metadata_full.tsv" --no-sign-request

# --- MultiQC parquet ---
aws s3 cp "$S3_PREFIX/multiqc/multiqc_data/multiqc.parquet" "$TARGET/multiqc/multiqc_data/multiqc.parquet" --no-sign-request

# --- Alpha diversity: Faith PD vector ---
aws s3 cp "$S3_PREFIX/qiime2/diversity/alpha_diversity/faith_pd_vector/metadata.tsv" \
  "$TARGET/qiime2/diversity/alpha_diversity/faith_pd_vector/metadata.tsv" --no-sign-request

# --- Alpha rarefaction: Faith PD CSV ---
aws s3 cp "$S3_PREFIX/qiime2/alpha-rarefaction/faith_pd.csv" \
  "$TARGET/qiime2/alpha-rarefaction/faith_pd.csv" --no-sign-request

# --- Taxonomy composition: barplot level-2 ---
aws s3 cp "$S3_PREFIX/qiime2/barplot/level-2.csv" \
  "$TARGET/qiime2/barplot/level-2.csv" --no-sign-request

# --- Taxonomy relative abundance: rel-table-2 ---
aws s3 cp "$S3_PREFIX/qiime2/rel_abundance_tables/rel-table-2.tsv" \
  "$TARGET/qiime2/rel_abundance_tables/rel-table-2.tsv" --no-sign-request

# --- ANCOM-BC: 5 slices for Category-habitat-level-2 ---
for f in lfc_slice.csv p_val_slice.csv q_val_slice.csv w_slice.csv se_slice.csv; do
  aws s3 cp "$S3_PREFIX/qiime2/ancombc/differentials/Category-habitat-level-2/$f" \
    "$TARGET/qiime2/ancombc/differentials/Category-habitat-level-2/$f" --no-sign-request
done

echo ""
echo "Download complete. Total files:"
find "$TARGET" -type f | wc -l

echo ""
echo "=== Quick test commands ==="
echo ""
echo "# METADATA_FILE and the route flags come from pipeline_info/params.json, so"
echo "# no --var is needed for them. GROUP_COL is auto-detected as the first"
echo "# annotation column ('name', one value per sample); 'habitat' is the one the"
echo "# ANCOM-BC slices were computed on, so pass it for meaningful grouping."
echo ""
echo "# 1. Dry run (validates the template against the data, no ingestion)"
echo "depictio-cli run --template nf-core/ampliseq/2.16.0 --data-root $TARGET \\"
echo "  --var GROUP_COL=habitat --dry-run"
echo ""
echo "# 2. Full run (needs a reachable server and ~/.depictio/CLI.yaml)"
echo "depictio-cli run --template nf-core/ampliseq/2.16.0 --data-root $TARGET \\"
echo "  --var GROUP_COL=habitat"
