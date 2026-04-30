#!/usr/bin/env bash
# Generate nf-core/viralrecon 3.0.0 test data for depictio template testing.
#
# The aggregated output files (multiqc.parquet, variants_long_table.csv,
# pangolin.csv, nextclade.csv, summary_variants_metrics_mqc.csv) are NOT
# available from nf-core AWS megatests — they are only produced by the full
# Illumina amplicon workflow. This script runs the pipeline with the built-in
# test_illumina profile to generate them.
#
# Prerequisites:
#   - Nextflow >= 24.10  (https://www.nextflow.io)
#   - Docker or Singularity
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR]
#   # Default TARGET_DIR: ./viralrecon-3.0.0-testdata
#
# Output is organized in a sequencing-runs structure so that multiple
# runs can be aggregated over time:
#   TARGET_DIR/
#     run_1/
#       multiqc/...
#       variants/ivar/...
set -euo pipefail

TARGET="${1:-./viralrecon-3.0.0-testdata}"
RUN_DIR="$TARGET/run_1"

echo "=== nf-core/viralrecon 3.0.0 test data generator ==="
echo ""
echo "Output directory: $RUN_DIR"
echo ""

# Check for nextflow
if ! command -v nextflow &> /dev/null; then
    echo "ERROR: nextflow not found. Install from https://www.nextflow.io"
    exit 1
fi

echo "Running nf-core/viralrecon 3.0.0 with test_illumina profile..."
echo "This may take 10-30 minutes depending on your machine."
echo ""

nextflow run nf-core/viralrecon \
    -r 3.0.0 \
    -profile test_illumina,docker \
    --outdir "$RUN_DIR" \
    --variant_caller ivar

echo ""
echo "Pipeline complete. Verifying expected output files..."
echo ""

MISSING=0
# Single files
for f in \
    "multiqc/multiqc_data/multiqc.parquet" \
    "multiqc/summary_variants_metrics_mqc.csv" \
    "variants/ivar/variants_long_table.csv" \
    "variants/bowtie2/mosdepth/amplicon/all_samples.mosdepth.coverage.tsv" \
    "variants/bowtie2/mosdepth/genome/all_samples.mosdepth.coverage.tsv" \
    "variants/bowtie2/mosdepth/amplicon/all_samples.mosdepth.heatmap.tsv"; do
    if [ -f "$RUN_DIR/$f" ]; then
        echo "  OK  $f"
    else
        echo "  MISSING  $f"
        MISSING=$((MISSING + 1))
    fi
done
# Per-sample directories (glob)
PANGOLIN_COUNT=$(find "$RUN_DIR/variants/ivar/consensus/bcftools/pangolin" -name "*.pangolin.csv" 2>/dev/null | wc -l)
NEXTCLADE_COUNT=$(find "$RUN_DIR/variants/ivar/consensus/bcftools/nextclade" -name "*.csv" 2>/dev/null | wc -l)
if [ "$PANGOLIN_COUNT" -gt 0 ]; then
    echo "  OK  variants/ivar/consensus/bcftools/pangolin/ ($PANGOLIN_COUNT per-sample files)"
else
    echo "  MISSING  variants/ivar/consensus/bcftools/pangolin/*.pangolin.csv"
    MISSING=$((MISSING + 1))
fi
if [ "$NEXTCLADE_COUNT" -gt 0 ]; then
    echo "  OK  variants/ivar/consensus/bcftools/nextclade/ ($NEXTCLADE_COUNT per-sample files)"
else
    echo "  MISSING  variants/ivar/consensus/bcftools/nextclade/*.csv"
    MISSING=$((MISSING + 1))
fi

echo ""
if [ "$MISSING" -gt 0 ]; then
    echo "WARNING: $MISSING expected file(s)/dir(s) not found."
    echo "Check the pipeline log above for errors."
else
    echo "All expected files present."
fi

echo ""
echo "Total output files:"
find "$TARGET" -type f | wc -l

echo ""
echo "=== Quick test commands ==="
echo ""
echo "# 1. Test individual recipes against generated data"
echo "depictio recipe run nf-core/viralrecon/summary_metrics.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/variants_long.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/pangolin_lineages.py -d $RUN_DIR"
echo "depictio recipe run nf-core/viralrecon/nextclade_results.py -d $RUN_DIR"
echo ""
echo "# 2. Full template run (requires running depictio server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET"
echo ""
echo "# 3. Dry run (validate template without server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run"
echo ""
echo "# 4. Deep validation (checks file headers match expected columns)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run --deep"
