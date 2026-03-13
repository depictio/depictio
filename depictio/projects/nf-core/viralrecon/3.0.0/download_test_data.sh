#!/usr/bin/env bash
# Generate nf-core/viralrecon 3.0.0 test data for depictio template testing.
#
# The aggregated output files (multiqc.parquet, variants_long_table.csv,
# pangolin.csv, nextclade.csv, summary_variants_metrics_mqc.csv) are NOT
# available from nf-core AWS megatests — they are only produced by the full
# Illumina amplicon workflow. This script runs the pipeline with the built-in
# test profiles to generate them.
#
# Prerequisites:
#   - Nextflow >= 24.10  (https://www.nextflow.io)
#   - Apptainer/Singularity OR Docker
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR] [OPTIONS]
#
# Options:
#   --profile test|test_full   Pipeline test profile (default: test_full)
#   --runtime docker|singularity|apptainer  Container runtime (default: auto-detect)
#   --work-dir DIR             Nextflow work directory (default: TARGET_DIR/work)
#   --multi-run                Create a second run (run_2) with a subset of samples
#
# Output is organized in a sequencing-runs structure so that multiple
# runs can be aggregated over time:
#   TARGET_DIR/
#     run_1/
#       multiqc/...
#       variants/ivar/...
#     run_2/  (optional, with --multi-run)
#       multiqc/...
#       variants/ivar/...
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
PROFILE="test_full"
RUNTIME=""
WORK_DIR=""
MULTI_RUN=false
TARGET=""

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)    PROFILE="$2"; shift 2 ;;
        --runtime)    RUNTIME="$2"; shift 2 ;;
        --work-dir)   WORK_DIR="$2"; shift 2 ;;
        --multi-run)  MULTI_RUN=true; shift ;;
        -h|--help)
            head -30 "$0" | grep "^#" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            if [ -z "$TARGET" ]; then
                TARGET="$1"; shift
            else
                echo "ERROR: Unknown argument: $1" >&2; exit 1
            fi
            ;;
    esac
done

TARGET="${TARGET:-./viralrecon-3.0.0-testdata}"
WORK_DIR="${WORK_DIR:-$TARGET/work}"

# ── Auto-detect container runtime ─────────────────────────────────────────────
if [ -z "$RUNTIME" ]; then
    if command -v apptainer &> /dev/null; then
        RUNTIME="apptainer"
    elif command -v singularity &> /dev/null; then
        RUNTIME="singularity"
    elif command -v docker &> /dev/null; then
        RUNTIME="docker"
    else
        echo "ERROR: No container runtime found (apptainer, singularity, or docker)."
        echo "Install one of them and retry."
        exit 1
    fi
fi

# Map apptainer -> singularity for Nextflow profile (Nextflow uses 'singularity' for both)
NF_RUNTIME="$RUNTIME"
if [ "$NF_RUNTIME" = "apptainer" ]; then
    NF_RUNTIME="singularity"
fi

echo "=== nf-core/viralrecon 3.0.0 test data generator ==="
echo ""
echo "  Profile:    $PROFILE"
echo "  Runtime:    $RUNTIME"
echo "  Output:     $TARGET"
echo "  Work dir:   $WORK_DIR"
echo "  Multi-run:  $MULTI_RUN"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────
if ! command -v nextflow &> /dev/null; then
    echo "ERROR: nextflow not found. Install from https://www.nextflow.io"
    exit 1
fi

echo "Nextflow version: $(nextflow -version 2>&1 | head -1)"
echo "$RUNTIME version: $($RUNTIME --version 2>&1 | head -1)"
echo ""

# ── Set Apptainer/Singularity cache if available ──────────────────────────────
if [ "$NF_RUNTIME" = "singularity" ]; then
    # Use standard Apptainer cache dir if set, or a local cache
    if [ -n "${APPTAINER_CACHEDIR:-}" ]; then
        export NXF_SINGULARITY_CACHEDIR="${APPTAINER_CACHEDIR}"
    elif [ -n "${SINGULARITY_CACHEDIR:-}" ]; then
        export NXF_SINGULARITY_CACHEDIR="${SINGULARITY_CACHEDIR}"
    elif [ -n "${NXF_SINGULARITY_CACHEDIR:-}" ]; then
        : # already set
    else
        # Default: use a cache dir next to the work dir
        export NXF_SINGULARITY_CACHEDIR="$TARGET/singularity_cache"
        mkdir -p "$NXF_SINGULARITY_CACHEDIR"
    fi
    echo "Singularity cache: $NXF_SINGULARITY_CACHEDIR"
    echo ""
fi

# ── Helper function to run one pipeline execution ─────────────────────────────
run_pipeline() {
    local run_dir="$1"
    local extra_args="${2:-}"

    echo "────────────────────────────────────────────────────────────────────"
    echo "Running nf-core/viralrecon 3.0.0 → $run_dir"
    echo "────────────────────────────────────────────────────────────────────"
    echo ""

    # shellcheck disable=SC2086
    nextflow run nf-core/viralrecon \
        -r 3.0.0 \
        -profile "${PROFILE},${NF_RUNTIME}" \
        --outdir "$run_dir" \
        --variant_caller ivar \
        -work-dir "$WORK_DIR" \
        $extra_args

    echo ""
    echo "Pipeline run complete for $run_dir"
    echo ""
}

# ── Run 1: Full test dataset ─────────────────────────────────────────────────
RUN1_DIR="$TARGET/run_1"
run_pipeline "$RUN1_DIR"

# ── Run 2 (optional): Second run for multi-run testing ────────────────────────
if [ "$MULTI_RUN" = true ]; then
    RUN2_DIR="$TARGET/run_2"
    echo ""
    echo "=== Creating second run for multi-run testing ==="
    echo ""
    # Run the pipeline again with the smaller test profile for run_2
    # This simulates having two independent sequencing runs
    run_pipeline "$RUN2_DIR" "-profile test,${NF_RUNTIME}"
fi

# ── Verify expected output files ─────────────────────────────────────────────
echo ""
echo "=== Verifying expected output files ==="
echo ""

verify_run() {
    local run_dir="$1"
    local run_name="$2"
    local missing=0

    echo "--- $run_name ($run_dir) ---"
    for f in \
        "multiqc/multiqc_data/multiqc.parquet" \
        "multiqc/summary_variants_metrics_mqc.csv" \
        "variants/ivar/variants_long_table.csv" \
        "variants/ivar/pangolin/pangolin.csv" \
        "variants/ivar/nextclade/nextclade.csv"; do
        if [ -f "$run_dir/$f" ]; then
            echo "  OK      $f"
        else
            echo "  MISSING $f"
            missing=$((missing + 1))
        fi
    done
    echo ""

    if [ "$missing" -gt 0 ]; then
        echo "  WARNING: $missing expected file(s) not found in $run_name."
        echo "  Check the pipeline log above for errors."
    else
        echo "  All expected files present in $run_name."
    fi
    echo ""
}

verify_run "$RUN1_DIR" "run_1"
if [ "$MULTI_RUN" = true ] && [ -d "$TARGET/run_2" ]; then
    verify_run "$TARGET/run_2" "run_2"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo "Total output files:"
find "$TARGET" -type f -not -path "*/work/*" | wc -l

echo ""
echo "=== Quick test commands ==="
echo ""
echo "# 1. Test individual recipes against generated data"
echo "depictio recipe run nf-core/viralrecon/summary_metrics.py -d $RUN1_DIR"
echo "depictio recipe run nf-core/viralrecon/variants_long.py -d $RUN1_DIR"
echo "depictio recipe run nf-core/viralrecon/pangolin_lineages.py -d $RUN1_DIR"
echo "depictio recipe run nf-core/viralrecon/nextclade_results.py -d $RUN1_DIR"
echo ""
echo "# 2. Full template run (requires running depictio server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET"
echo ""
echo "# 3. Dry run (validate template without server)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run"
echo ""
echo "# 4. Deep validation (checks file headers match expected columns)"
echo "depictio run --template nf-core/viralrecon/3.0.0 --data-root $TARGET --dry-run --deep"
echo ""
echo "# 5. Clean up work directory (reclaim disk space)"
echo "rm -rf $WORK_DIR"
