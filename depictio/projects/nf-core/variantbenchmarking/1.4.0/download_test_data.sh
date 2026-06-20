#!/usr/bin/env bash
# Download nf-core/variantbenchmarking 1.4.0 AWS megatest data for local testing.
# Pulls only the final benchmark tables (+ optional hap.py ROC) needed by the
# template recipes — the most recent release-line megatest run.
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR]
#   # Default TARGET_DIR: ./variantbenchmarking-1.4.0-testdata
#
# Requires the AWS CLI (public bucket, no credentials: --no-sign-request).
# Without the AWS CLI you can browse/fetch the same keys over HTTPS, e.g.:
#   curl -s "https://nf-core-awsmegatests.s3.amazonaws.com/<key>" -o <local>
set -euo pipefail

S3_PREFIX="s3://nf-core-awsmegatests/variantbenchmarking/results-8b21c01749c4447b285d242a198127736f3ffe51"
TARGET="${1:-./variantbenchmarking-1.4.0-testdata}"

echo "Downloading variantbenchmarking 1.4.0 test data to: $TARGET"
mkdir -p "$TARGET"

# --- Germline (small/): rtg-tools vcfeval aggregated summary ---
aws s3 cp "$S3_PREFIX/small/summary/tables/" "$TARGET/small/summary/tables/" \
  --recursive --no-sign-request

# --- Germline (small/): per-sample hap.py summaries + SNP ROC sweep (optional) ---
# Sample dir / truth-set names vary (test1.HG002.giab_v1 …), so filter by suffix.
aws s3 cp "$S3_PREFIX/small/" "$TARGET/small/" --recursive --no-sign-request \
  --exclude "*" \
  --include "*/benchmarks/happy/*.summary.csv" \
  --include "*/benchmarks/happy/*.roc.Locations.SNP.PASS.csv.gz"

# --- Somatic (indel/): rtg-tools vcfeval + som.py aggregated summaries ---
aws s3 cp "$S3_PREFIX/indel/summary/tables/" "$TARGET/indel/summary/tables/" \
  --recursive --no-sign-request

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
echo "depictio recipe run nf-core/variantbenchmarking/vcfeval_summary.py -d $TARGET"
echo "depictio recipe run nf-core/variantbenchmarking/happy_summary.py -d $TARGET"
echo "depictio recipe run nf-core/variantbenchmarking/sompy_summary.py -d $TARGET"
echo "depictio recipe run nf-core/variantbenchmarking/sompy_regions.py -d $TARGET"
echo ""
echo "# 3. Full template run (requires running depictio server)"
echo "depictio run --template nf-core/variantbenchmarking/1.4.0 --data-root $TARGET"
echo ""
echo "# 4. Dry run (validate template without server)"
echo "depictio run --template nf-core/variantbenchmarking/1.4.0 --data-root $TARGET --dry-run"
echo ""
echo "# 5. Deep validation (checks file headers match expected columns)"
echo "depictio run --template nf-core/variantbenchmarking/1.4.0 --data-root $TARGET --dry-run --deep"
