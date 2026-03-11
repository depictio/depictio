#!/usr/bin/env bash
# Download nf-core/viralrecon 3.0.0 AWS megatest data for local testing.
# Only downloads the files needed by the template recipes + MultiQC.
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR]
#   # Default TARGET_DIR: ./viralrecon-3.0.0-testdata
#
# The data is organized in a sequencing-runs structure so that multiple
# runs can be aggregated over time:
#   TARGET_DIR/
#     run_1/
#       multiqc/...
#       variants/ivar/...
set -euo pipefail

S3_PREFIX="s3://nf-core-awsmegatests/viralrecon/results-395079f1d24dce731ac22e03d7a5e71f110103fc"
TARGET="${1:-./viralrecon-3.0.0-testdata}"
RUN_DIR="$TARGET/run_1"

echo "Downloading viralrecon 3.0.0 test data to: $TARGET"
mkdir -p "$RUN_DIR"

# --- MultiQC outputs ---
echo "  [1/5] MultiQC parquet..."
aws s3 cp "$S3_PREFIX/multiqc/multiqc_data/multiqc.parquet" \
  "$RUN_DIR/multiqc/multiqc_data/multiqc.parquet" --no-sign-request

echo "  [2/5] Summary variants metrics..."
aws s3 cp "$S3_PREFIX/multiqc/summary_variants_metrics_mqc.csv" \
  "$RUN_DIR/multiqc/summary_variants_metrics_mqc.csv" --no-sign-request

# --- Variant calling outputs (ivar) ---
echo "  [3/5] Variants long table..."
aws s3 cp "$S3_PREFIX/variants/ivar/variants_long_table.csv" \
  "$RUN_DIR/variants/ivar/variants_long_table.csv" --no-sign-request

# --- Pangolin lineage assignments ---
echo "  [4/5] Pangolin results..."
aws s3 cp "$S3_PREFIX/variants/ivar/pangolin/" \
  "$RUN_DIR/variants/ivar/pangolin/" --recursive --no-sign-request \
  --exclude "*" --include "*.csv"

# --- Nextclade clade assignments ---
echo "  [5/5] Nextclade results..."
aws s3 cp "$S3_PREFIX/variants/ivar/nextclade/" \
  "$RUN_DIR/variants/ivar/nextclade/" --recursive --no-sign-request \
  --exclude "*" --include "*.csv"

echo ""
echo "Download complete. Total files:"
find "$TARGET" -type f | wc -l

echo ""
echo "Directory structure:"
find "$TARGET" -type f | sed "s|$TARGET/||" | sort

echo ""
echo "=== Quick test commands ==="
echo ""
echo "# 1. List available recipes"
echo "depictio recipe list"
echo ""
echo "# 2. Test individual recipes against downloaded data"
echo "depictio recipe run nf-core/viralrecon/summary_metrics.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/variants_long.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/pangolin_lineages.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/nextclade_results.py -d $RUN_DIR"
echo ""
echo "# 3. Full template run (requires running depictio server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET"
echo ""
echo "# 4. Dry run (validate template without server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run"
echo ""
echo "# 5. Deep validation (checks file headers match expected columns)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run --deep"
