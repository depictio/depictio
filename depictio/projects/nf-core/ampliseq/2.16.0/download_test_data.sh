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
echo "# 1. List available recipes"
echo "depictio recipe list"
echo ""
echo "# 2. Test individual recipes against downloaded data"
echo "depictio recipe run nf-core/ampliseq/alpha_diversity.py -d $TARGET"
echo "depictio recipe run nf-core/ampliseq/alpha_rarefaction.py -d $TARGET"
echo "depictio recipe run nf-core/ampliseq/taxonomy_composition.py -d $TARGET"
echo "depictio recipe run nf-core/ampliseq/ancombc.py -d $TARGET"
echo ""
echo "# 3. Full template run (requires running depictio server)"
echo "depictio run --template nf-core/ampliseq/2.16.0 --data-root $TARGET"
echo ""
echo "# 4. Dry run (validate template without server)"
echo "depictio run --template nf-core/ampliseq/2.16.0 --data-root $TARGET --dry-run"
echo ""
echo "# 5. Deep validation (checks file headers match expected columns)"
echo "depictio run --template nf-core/ampliseq/2.16.0 --data-root $TARGET --dry-run --deep"
