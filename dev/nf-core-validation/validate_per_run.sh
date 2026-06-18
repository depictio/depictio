#!/usr/bin/env bash
# Per-run validation harness for the nf-core template system.
# ============================================================================
# Ingests ONE depictio project per pipeline run so each scenario's self-adapting
# dashboard can be validated in isolation in the UI. This is a THROWAWAY
# validation harness — it does NOT modify any template's data_location.structure.
#
#   ampliseq   (data_location.structure: flat)           — each run dir IS its
#              own --data-root.
#   viralrecon (data_location.structure: sequencing-runs) — the template
#              aggregates ALL run_* dirs under DATA_ROOT into ONE project. To
#              isolate one run per project WITHOUT touching the template, we
#              build a temp parent dir containing a single symlink to that one
#              run_* dir and point --data-root at the temp parent.
#
# All runs (in-scope + out-of-scope) are executed; exit codes are captured.
# The two out-of-scope runs use a DIFFERENT nf-core sub-workflow (ampliseq
# run_multiregion = SIDLE; viralrecon run_nanopore = ARTIC) and are EXPECTED to
# exit non-zero — that is a PASS for them (the template correctly fails loud).
#
# Usage:
#   bash dev/nf-core-validation/validate_per_run.sh
#   # optional overrides:
#   AMPLISEQ_ROOT=... VIRALRECON_ROOT=... CLI_CONFIG=... bash validate_per_run.sh
#
# Results are written to $RESULTS_DIR/validation_results.tsv and per-run logs.
# After this completes, run report_validation.py to produce the results table.
set -uo pipefail

# ---------------------------------------------------------------------------
# Configuration (overridable via environment)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CLI_VENV="${CLI_VENV:-$REPO_ROOT/depictio/cli/.venv/bin/python}"
CLI_CONFIG="${CLI_CONFIG:-$HOME/.depictio/CLI.chore-amplicon-viralrecon-validation-100.yaml}"

AMPLISEQ_ROOT="${AMPLISEQ_ROOT:-$HOME/Data/ampliseq/validation-runs-2.16.0}"
VIRALRECON_ROOT="${VIRALRECON_ROOT:-$HOME/Data/viralrecon/validation-runs-3.0.0}"

AMPLISEQ_TEMPLATE="nf-core/ampliseq/2.16.0"
VIRALRECON_TEMPLATE="nf-core/viralrecon/3.0.0"

# Run lists. Out-of-scope runs (divergent sub-workflow) are expected to exit 1.
AMPLISEQ_INSCOPE=(run_16s_pe run_16s_multi run_iontorrent run_its_pacbio)
AMPLISEQ_OUTSCOPE=(run_multiregion)
VIRALRECON_INSCOPE=(run_amplicon_custom run_illumina_amplicon run_hiv run_ev)
VIRALRECON_OUTSCOPE=(run_nanopore)

RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/validation_results}"
RESULTS_TSV="$RESULTS_DIR/validation_results.tsv"
LOG_DIR="$RESULTS_DIR/logs"
# Temp parent dirs for the viralrecon per-run symlink trick.
SYMLINK_ROOT="${SYMLINK_ROOT:-${TMPDIR:-/tmp}/depictio-valruns}"

mkdir -p "$RESULTS_DIR" "$LOG_DIR"
printf "project\trun\tpipeline\texit_code\texpected\tresult\n" > "$RESULTS_TSV"

echo "=== nf-core per-run validation harness ==="
echo "  CLI venv:    $CLI_VENV"
echo "  CLI config:  $CLI_CONFIG"
echo "  Results:     $RESULTS_TSV"
echo ""

if [ ! -x "$CLI_VENV" ]; then
    echo "ERROR: CLI venv interpreter not found/executable: $CLI_VENV" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Ingest one run. Captures exit code without aborting the harness (set +e).
#   $1 = template id
#   $2 = pipeline label (ampliseq|viralrecon)
#   $3 = run name
#   $4 = data-root to pass to the CLI
#   $5 = expected exit semantics: "ok" (exit 0) | "fail" (exit 1)
# ---------------------------------------------------------------------------
run_one() {
    local template="$1" pipeline="$2" run="$3" data_root="$4" expected="$5"
    local project="val-${pipeline}-${run}"
    local log="$LOG_DIR/${project}.log"

    echo ">>> [$pipeline] $run  ->  project '$project'  (expect: $expected)"
    echo "    data-root: $data_root"

    # The script runs with `set -uo pipefail` (no `-e`), so a non-zero CLI exit
    # does NOT abort the harness — we capture it in $code. No set +e/-e sandwich
    # is needed (and re-enabling -e here would wrongly abort later runs).
    "$CLI_VENV" -m depictio.cli run \
        --CLI-config-path "$CLI_CONFIG" \
        --template "$template" \
        --data-root "$data_root" \
        --project-name "$project" \
        --overwrite \
        --update-config \
        > "$log" 2>&1
    local code=$?

    # Translate exit code vs expectation into PASS/FAIL.
    local result
    if [ "$expected" = "ok" ]; then
        [ "$code" -eq 0 ] && result="PASS" || result="FAIL"
    else
        # Out-of-scope: any non-zero exit is the expected loud failure.
        [ "$code" -ne 0 ] && result="PASS" || result="FAIL"
    fi

    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$project" "$run" "$pipeline" "$code" "$expected" "$result" >> "$RESULTS_TSV"
    echo "    exit=$code  result=$result  (log: $log)"
    echo ""
}

# ---------------------------------------------------------------------------
# ampliseq — flat structure: run dir IS the data-root.
# ---------------------------------------------------------------------------
echo "--- ampliseq (flat) ---"
for run in "${AMPLISEQ_INSCOPE[@]}"; do
    run_one "$AMPLISEQ_TEMPLATE" "ampliseq" "$run" "$AMPLISEQ_ROOT/$run" "ok"
done
for run in "${AMPLISEQ_OUTSCOPE[@]}"; do
    run_one "$AMPLISEQ_TEMPLATE" "ampliseq" "$run" "$AMPLISEQ_ROOT/$run" "fail"
done

# ---------------------------------------------------------------------------
# viralrecon — sequencing-runs structure: isolate one run via a temp parent
# dir that symlinks just that one run_* dir, then point --data-root at it.
# ---------------------------------------------------------------------------
echo "--- viralrecon (sequencing-runs, symlink-parent isolation) ---"
make_symlink_parent() {
    # $1 = run name; echoes the temp parent path to stdout.
    local run="$1"
    # Guard the rm -rf below: never act on an empty/traversing run name.
    if [ -z "$run" ] || [[ "$run" == *..* ]] || [[ "$run" == */* ]]; then
        echo "ERROR: invalid run name for symlink parent: '$run'" >&2
        return 1
    fi
    local parent="$SYMLINK_ROOT/viralrecon/$run"
    rm -rf "$parent"
    mkdir -p "$parent"
    ln -s "$VIRALRECON_ROOT/$run" "$parent/$run"
    echo "$parent"
}

for run in "${VIRALRECON_INSCOPE[@]}"; do
    parent="$(make_symlink_parent "$run")"
    run_one "$VIRALRECON_TEMPLATE" "viralrecon" "$run" "$parent" "ok"
done
for run in "${VIRALRECON_OUTSCOPE[@]}"; do
    parent="$(make_symlink_parent "$run")"
    run_one "$VIRALRECON_TEMPLATE" "viralrecon" "$run" "$parent" "fail"
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "=== Done. Results: $RESULTS_TSV ==="
column -t -s $'\t' "$RESULTS_TSV"
echo ""
fails=$(awk -F'\t' 'NR>1 && $6=="FAIL"' "$RESULTS_TSV" | wc -l | tr -d ' ')
echo "Harness-level FAILs (unexpected): $fails"
echo ""
echo "Next: $CLI_VENV dev/nf-core-validation/report_validation.py"
