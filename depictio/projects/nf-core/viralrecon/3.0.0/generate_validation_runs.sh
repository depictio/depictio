#!/usr/bin/env bash
# Generate nf-core/viralrecon 3.0.0 validation runs for template generalization testing.
#
# Produces 3 runs under TARGET_ROOT to test whether the viralrecon Depictio template
# generalizes beyond the single reference dataset it was authored against:
#
#   run_illumina_amplicon/  — baseline amplicon run (same profile as download_test_data.sh)
#   run_amplicon_custom/    — 2nd amplicon run using the full nf-core test samplesheet
#   run_nanopore/           — divergent run (nanopore protocol; ivar/bowtie2 files absent)
#
# After each run, expected vs. actual file presence is printed. The nanopore run is
# expected to be missing ivar / mosdepth / bowtie2 files — those gaps are the experiment.
#
# Prerequisites:
#   - Nextflow >= 24.10  (https://www.nextflow.io)
#   - Docker
#
# Usage:
#   bash generate_validation_runs.sh [TARGET_ROOT]
#   # Default TARGET_ROOT: ~/Data/depictio-nfcore/viralrecon/3.0.0
set -euo pipefail

TARGET_ROOT="${1:-$HOME/Data/depictio-nfcore/viralrecon/3.0.0}"

echo "=== nf-core/viralrecon 3.0.0 — generalization validation ==="
echo ""
echo "Output root: $TARGET_ROOT"
echo ""

if ! command -v nextflow &> /dev/null; then
    echo "ERROR: nextflow not found. Install from https://www.nextflow.io"
    exit 1
fi

echo "nextflow $(nextflow -version 2>&1 | head -1)"
echo ""

# ---------------------------------------------------------------------------
# Helper: run nextflow tolerantly, warning (not aborting) on non-zero exit.
# Keeps the set +e / NF_EXIT / set -e sandwich so a failed run still verifies.
# $1 = run label; remaining args = nextflow command + args
# ---------------------------------------------------------------------------
run_nextflow() {
    local label="$1"
    shift
    set +e
    "$@"
    local nf_exit=$?
    set -e
    [ $nf_exit -ne 0 ] && echo "WARNING: $label exited $nf_exit — verify output below"
    echo ""
}

# ---------------------------------------------------------------------------
# Helper: verify template-expected files for a completed run
# $1 = run dir
# $2 = run label
# $3 = "amplicon" | "nanopore"  (controls which files are expected vs N/A)
# ---------------------------------------------------------------------------
verify_run() {
    local run_dir="$1"
    local label="$2"
    local protocol="$3"
    local missing=0

    echo "--- File verification: $label ($protocol) ---"

    # Redefine to avoid stale closure from a prior call under set -e.
    unset -f check_required
    # Check a required file: print OK, else MISSING and bump the counter.
    check_required() {
        local f="$1"
        if [ -f "$run_dir/$f" ]; then
            printf "  OK           %s\n" "$f"
        else
            printf "  MISSING      %s\n" "$f"
            missing=$((missing + 1))
        fi
    }

    # Files present in ALL protocols
    check_required "multiqc/multiqc_data/multiqc.parquet"
    check_required "multiqc/summary_variants_metrics_mqc.csv"

    # Files expected for amplicon (ivar) only; on other protocols their absence is fine.
    local ivar_files=(
        "variants/ivar/variants_long_table.csv"
        "variants/bowtie2/mosdepth/amplicon/all_samples.mosdepth.coverage.tsv"
        "variants/bowtie2/mosdepth/genome/all_samples.mosdepth.coverage.tsv"
        "variants/bowtie2/mosdepth/amplicon/all_samples.mosdepth.heatmap.tsv"
    )
    for f in "${ivar_files[@]}"; do
        if [ "$protocol" = "amplicon" ]; then
            check_required "$f"
        elif [ -f "$run_dir/$f" ]; then
            printf "  UNEXPECTED   %s  (present despite divergent protocol)\n" "$f"
        else
            printf "  N/A          %s  (not produced by %s protocol)\n" "$f" "$protocol"
        fi
    done

    # Per-sample globs (amplicon only)
    if [ "$protocol" = "amplicon" ]; then
        local pangolin_count nextclade_count
        pangolin_count=$(find "$run_dir/variants/ivar/consensus/bcftools/pangolin" -name "*.pangolin.csv" 2>/dev/null | wc -l | tr -d ' ')
        nextclade_count=$(find "$run_dir/variants/ivar/consensus/bcftools/nextclade" -name "*.csv" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$pangolin_count" -gt 0 ]; then
            printf "  OK           variants/ivar/consensus/bcftools/pangolin/ (%s files)\n" "$pangolin_count"
        else
            printf "  MISSING      variants/ivar/consensus/bcftools/pangolin/*.pangolin.csv\n"
            missing=$((missing + 1))
        fi
        if [ "$nextclade_count" -gt 0 ]; then
            printf "  OK           variants/ivar/consensus/bcftools/nextclade/ (%s files)\n" "$nextclade_count"
        else
            printf "  MISSING      variants/ivar/consensus/bcftools/nextclade/*.csv\n"
            missing=$((missing + 1))
        fi
    fi

    echo ""
    if [ "$missing" -gt 0 ]; then
        echo "  RESULT: $missing file(s) missing — check pipeline log"
    else
        echo "  RESULT: all expected files present"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Run 1: run_illumina_amplicon — baseline amplicon (same as download_test_data.sh)
# ---------------------------------------------------------------------------
RUN1="$TARGET_ROOT/run_illumina_amplicon"
echo ">>> [1/3] run_illumina_amplicon (test_illumina profile, ivar)"
echo "    Output: $RUN1"
echo ""

run_nextflow "run_illumina_amplicon" \
    nextflow run nf-core/viralrecon \
    -r 3.0.0 \
    -profile test_illumina,docker \
    --variant_caller ivar \
    --outdir "$RUN1"

verify_run "$RUN1" "run_illumina_amplicon" "amplicon"

# ---------------------------------------------------------------------------
# Run 2: run_amplicon_custom — 2nd amplicon run using the full nf-core test samplesheet
#
# The full samplesheet uses more samples than the minimal test profile, exercising
# aggregation across more rows. Verify the URL exists before passing to nextflow.
# ---------------------------------------------------------------------------
RUN2="$TARGET_ROOT/run_amplicon_custom"
CUSTOM_SAMPLESHEET="https://raw.githubusercontent.com/nf-core/test-datasets/viralrecon/samplesheet/samplesheet_test_illumina_amplicon.csv"

echo ">>> [2/3] run_amplicon_custom (full nf-core amplicon samplesheet, ivar)"
echo "    Samplesheet: $CUSTOM_SAMPLESHEET"
echo "    Output: $RUN2"
echo ""

if ! curl --silent --head --fail --location --max-time 10 "$CUSTOM_SAMPLESHEET" > /dev/null 2>&1; then
    echo "WARNING: samplesheet URL not reachable — skipping run_amplicon_custom"
    echo "         Check https://github.com/nf-core/test-datasets/tree/viralrecon/samplesheet"
    echo "         and update CUSTOM_SAMPLESHEET in this script."
    echo ""
else
    run_nextflow "run_amplicon_custom" \
        nextflow run nf-core/viralrecon \
        -r 3.0.0 \
        -profile docker \
        --input "$CUSTOM_SAMPLESHEET" \
        --platform illumina \
        --protocol amplicon \
        --variant_caller ivar \
        --genome 'MN908947.3' \
        --outdir "$RUN2"

    verify_run "$RUN2" "run_amplicon_custom" "amplicon"
fi

# ---------------------------------------------------------------------------
# Run 3: run_nanopore — divergent protocol (nanopore)
# Expected absent: variants/ivar/, variants/bowtie2/mosdepth/
# ---------------------------------------------------------------------------
RUN3="$TARGET_ROOT/run_nanopore"
echo ">>> [3/3] run_nanopore (test_nanopore profile — DIVERGENT)"
echo "    Output: $RUN3"
echo "    NOTE: ivar / bowtie2 / mosdepth files will be absent — this is expected."
echo ""

run_nextflow "run_nanopore" \
    nextflow run nf-core/viralrecon \
    -r 3.0.0 \
    -profile test_nanopore,docker \
    --outdir "$RUN3"

verify_run "$RUN3" "run_nanopore" "nanopore"

# ---------------------------------------------------------------------------
# Summary + ingestion commands
# ---------------------------------------------------------------------------
TEMPLATE="nf-core/viralrecon/3.0.0"
RUNS=(run_illumina_amplicon run_amplicon_custom run_nanopore)

echo ""
echo "=== All runs complete ==="
echo ""
echo "Total output files:"
find "$TARGET_ROOT" -type f 2>/dev/null | wc -l | tr -d ' '
echo ""
echo "=== Dry-run validation (no server needed) ==="
echo ""
echo "# Per-run deep dry-run (checks file headers match template expectations):"
for run in "${RUNS[@]}"; do
    if [ -d "$TARGET_ROOT/$run" ]; then
        echo "depictio run --template $TEMPLATE --data-root $TARGET_ROOT/$run --dry-run --deep"
    fi
done
echo ""
echo "# Aggregated dry-run (all run_* dirs at once via sequencing-runs structure):"
echo "depictio run --template $TEMPLATE --data-root $TARGET_ROOT --dry-run --deep"
echo ""
echo "=== Per-run ingestion (requires running Depictio stack) ==="
echo ""
echo "# Use /import-template skill (worktree-aware, auto-picks config + ports):"
echo ""
for run in "${RUNS[@]}"; do
    label="${run/run_/}"
    label="${label//_/ }"
    if [ -d "$TARGET_ROOT/$run" ]; then
        echo "/import-template $TEMPLATE \\"
        echo "  --data-root $TARGET_ROOT/$run \\"
        echo "  --project-name \"viralrecon — $label\""
        echo ""
    fi
done
echo "=== Aggregated ingestion ==="
echo ""
echo "/import-template $TEMPLATE \\"
echo "  --data-root $TARGET_ROOT \\"
echo "  --project-name \"viralrecon — aggregated\""
