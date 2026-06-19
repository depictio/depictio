#!/usr/bin/env bash
# Generate nf-core/ampliseq 2.16.0 validation runs for template generalization testing.
#
# Produces 3 runs under TARGET_ROOT to test whether the ampliseq Depictio template
# generalizes beyond the AWS megatest dataset it was authored against:
#
#   run_16s_pe/     — baseline 16S paired-end (test profile)
#   run_16s_multi/  — 2nd 16S run (test_multi profile, multiple samples)
#   run_its_pacbio/ — divergent run (ITS / PacBio; barplot/level-2 may be absent)
#
# Unlike download_test_data.sh (which fetches pre-computed AWS megatest outputs),
# this script runs the pipeline locally so non-megatest profiles can be exercised.
#
# After each run the script:
#   1. Verifies expected file presence
#   2. Auto-detects a valid GROUP_COL from the metadata TSV (if present)
#   3. Prints the depictio ingestion command with the detected GROUP_COL
#
# Prerequisites:
#   - Nextflow >= 24.10  (https://www.nextflow.io)
#   - Docker
#
# Usage:
#   bash generate_validation_runs.sh [TARGET_ROOT]
#   # Default TARGET_ROOT: ~/Data/depictio-nfcore/ampliseq/2.16.0
set -euo pipefail

TARGET_ROOT="${1:-$HOME/Data/depictio-nfcore/ampliseq/2.16.0}"

echo "=== nf-core/ampliseq 2.16.0 — generalization validation ==="
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
# Helper: detect first non-ID column from a metadata TSV
# $1 = run dir
# Returns the column name (or empty string if no metadata / no extra columns)
# ---------------------------------------------------------------------------
detect_group_col() {
    local metadata_path="$1/input/Metadata_full.tsv"
    if [ ! -f "$metadata_path" ]; then
        echo ""
        return
    fi
    # Skip the ID column (first); return the second header column.
    awk -F'\t' 'NR==1 {print $2}' "$metadata_path"
}

# ---------------------------------------------------------------------------
# Helper: verify template-expected files for a completed run
# $1 = run dir
# $2 = run label
# $3 = "16s" | "its"  (controls NOT_APPLICABLE annotation)
# ---------------------------------------------------------------------------
verify_run() {
    local run_dir="$1"
    local label="$2"
    local amplicon_type="$3"
    local missing=0

    echo "--- File verification: $label ($amplicon_type) ---"

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

    # MultiQC + QIIME2 core outputs: expected for all profiles (ITS and 16S)
    check_required "multiqc/multiqc_data/multiqc.parquet"
    check_required "qiime2/rel_abundance_tables/rel-table-2.tsv"
    check_required "qiime2/diversity/alpha_diversity/faith_pd_vector/metadata.tsv"
    check_required "qiime2/alpha-rarefaction/faith_pd.csv"

    # barplot/level-2.csv: expected for 16S, may be absent for ITS/PacBio
    if [ "$amplicon_type" = "16s" ]; then
        check_required "qiime2/barplot/level-2.csv"
    elif [ -f "$run_dir/qiime2/barplot/level-2.csv" ]; then
        printf "  OK           qiime2/barplot/level-2.csv\n"
    else
        printf "  N/A          qiime2/barplot/level-2.csv  (may not be produced for ITS/PacBio)\n"
    fi

    # ANCOM-BC: only present when metadata + GROUP_COL provided to the pipeline run
    local ancombc_root="$run_dir/qiime2/ancombc/differentials"
    local ancombc_count
    ancombc_count=$(find "$ancombc_root" -name "lfc_slice.csv" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$ancombc_count" -gt 0 ]; then
        printf "  OK           qiime2/ancombc/differentials/ (%s lfc_slice files)\n" "$ancombc_count"
    else
        printf "  N/A          qiime2/ancombc/differentials/  (requires --metadata + --metadata_category in pipeline run)\n"
    fi

    echo ""
    if [ "$missing" -gt 0 ]; then
        echo "  RESULT: $missing file(s) missing — check pipeline log"
    else
        echo "  RESULT: all expected files present (N/A items are informational)"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Run 1: run_16s_pe — baseline 16S paired-end (test profile)
# ---------------------------------------------------------------------------
RUN1="$TARGET_ROOT/run_16s_pe"
echo ">>> [1/3] run_16s_pe (test profile, 16S paired-end)"
echo "    Output: $RUN1"
echo ""

run_nextflow "run_16s_pe" \
    nextflow run nf-core/ampliseq \
    -r 2.16.0 \
    -profile test,docker \
    --outdir "$RUN1"

verify_run "$RUN1" "run_16s_pe" "16s"

GROUP_COL_RUN1=$(detect_group_col "$RUN1")

# ---------------------------------------------------------------------------
# Run 2: run_16s_multi — 2nd 16S run (test_multi profile, multi-region)
# ---------------------------------------------------------------------------
RUN2="$TARGET_ROOT/run_16s_multi"
echo ">>> [2/3] run_16s_multi (test_multi profile, 16S multi-region)"
echo "    Output: $RUN2"
echo ""

run_nextflow "run_16s_multi" \
    nextflow run nf-core/ampliseq \
    -r 2.16.0 \
    -profile test_multi,docker \
    --outdir "$RUN2"

verify_run "$RUN2" "run_16s_multi" "16s"

GROUP_COL_RUN2=$(detect_group_col "$RUN2")

# ---------------------------------------------------------------------------
# Run 3: run_its_pacbio — divergent ITS / PacBio run
# barplot/level-2.csv expected to be absent or differ in structure
# ---------------------------------------------------------------------------
RUN3="$TARGET_ROOT/run_its_pacbio"
echo ">>> [3/3] run_its_pacbio (test_pacbio_its profile — DIVERGENT)"
echo "    Output: $RUN3"
echo "    NOTE: qiime2/barplot/level-2.csv may be absent for ITS — this is expected."
echo ""

run_nextflow "run_its_pacbio" \
    nextflow run nf-core/ampliseq \
    -r 2.16.0 \
    -profile test_pacbio_its,docker \
    --outdir "$RUN3"

verify_run "$RUN3" "run_its_pacbio" "its"

GROUP_COL_RUN3=$(detect_group_col "$RUN3")

# ---------------------------------------------------------------------------
# Summary + ingestion commands
# ---------------------------------------------------------------------------
TEMPLATE="nf-core/ampliseq/2.16.0"

echo ""
echo "=== All runs complete ==="
echo ""
echo "Total output files:"
find "$TARGET_ROOT" -type f 2>/dev/null | wc -l | tr -d ' '
echo ""
echo "=== Detected GROUP_COL per run ==="
echo ""
[ -n "$GROUP_COL_RUN1" ] && echo "  run_16s_pe:     $GROUP_COL_RUN1" || echo "  run_16s_pe:     (no metadata TSV found)"
[ -n "$GROUP_COL_RUN2" ] && echo "  run_16s_multi:  $GROUP_COL_RUN2" || echo "  run_16s_multi:  (no metadata TSV found)"
[ -n "$GROUP_COL_RUN3" ] && echo "  run_its_pacbio: $GROUP_COL_RUN3" || echo "  run_its_pacbio: (no metadata TSV found)"
echo ""
echo "=== Dry-run validation (no server needed) ==="
echo ""
echo "# Per-run deep dry-run:"
echo "depictio run --template $TEMPLATE --data-root $RUN1 --dry-run --deep"
echo "depictio run --template $TEMPLATE --data-root $RUN2 --dry-run --deep"
echo "depictio run --template $TEMPLATE --data-root $RUN3 --dry-run --deep"
echo ""
echo "=== Per-run ingestion (requires running Depictio stack) ==="
echo ""
echo "# Ampliseq uses flat structure: each run is its own --data-root ingestion."
echo "# Use /import-template skill (worktree-aware, auto-picks config + ports):"
echo ""
echo "/import-template $TEMPLATE \\"
echo "  --data-root $RUN1 \\"
[ -n "$GROUP_COL_RUN1" ] && echo "  --var GROUP_COL=\"$GROUP_COL_RUN1\" \\" || echo "  # --var GROUP_COL=<col>  (no metadata detected — omit or set manually) \\"
echo "  --project-name \"ampliseq — 16S paired-end\""
echo ""
echo "/import-template $TEMPLATE \\"
echo "  --data-root $RUN2 \\"
[ -n "$GROUP_COL_RUN2" ] && echo "  --var GROUP_COL=\"$GROUP_COL_RUN2\" \\" || echo "  # --var GROUP_COL=<col>  (no metadata detected) \\"
echo "  --project-name \"ampliseq — 16S multi\""
echo ""
echo "/import-template $TEMPLATE \\"
echo "  --data-root $RUN3 \\"
[ -n "$GROUP_COL_RUN3" ] && echo "  --var GROUP_COL=\"$GROUP_COL_RUN3\" \\" || echo "  # --var GROUP_COL=<col>  (no metadata detected) \\"
echo "  --project-name \"ampliseq — ITS PacBio\""
echo ""
echo "=== Aggregated ingestion (all 3 runs under one project) ==="
echo ""
echo "# Re-run each with the same --project-name and --overwrite to accumulate"
echo "# all runs as distinct depictio_run_id entries in one project:"
echo ""
APROJECT="ampliseq — aggregated"
agg_runs=("$RUN1" "$RUN2" "$RUN3")
agg_gcols=("$GROUP_COL_RUN1" "$GROUP_COL_RUN2" "$GROUP_COL_RUN3")
for i in 0 1 2; do
    run_dir="${agg_runs[$i]}"
    gcol="${agg_gcols[$i]}"
    if [ -n "$gcol" ]; then
        echo "/import-template $TEMPLATE --data-root $run_dir --var GROUP_COL=\"$gcol\" --project-name \"$APROJECT\" --overwrite"
    else
        echo "/import-template $TEMPLATE --data-root $run_dir --project-name \"$APROJECT\" --overwrite  # add --var GROUP_COL=<col> if metadata present"
    fi
done
