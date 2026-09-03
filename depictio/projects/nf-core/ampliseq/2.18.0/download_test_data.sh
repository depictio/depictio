#!/usr/bin/env bash
# Download nf-core/ampliseq 2.18.0 AWS megatest data for local testing.
# Only downloads the files needed by the template recipes + MultiQC, plus the
# raw inputs of the canonical-seed recipes (see generate_canonical_seeds.py).
#
# The bucket is public: plain HTTPS GETs, no AWS CLI or credentials needed
# (same fetch pattern as the ampliseq CLI job in .github/workflows/depictio-ci.yaml).
#
# Usage:
#   bash download_test_data.sh [TARGET_DIR]
#   # Default TARGET_DIR: ./ampliseq-2.18.0-testdata
#
# Do NOT point TARGET_DIR at this template directory: .gitignore allow-lists
# input/*.tsv and the raw Metadata_full.tsv would overwrite the committed,
# demo-augmented one (sampling_date / lon / lat / ctd_* columns). Download to a
# scratch dir and feed it to generate_canonical_seeds.py --raw-root instead.
set -euo pipefail

# Megatest run of the 2.18.0 release (s3://nf-core-awsmegatests/ampliseq/results-<hash>).
RESULTS_HASH="2723d4c298d48321594920d0324697e14d73ee94"
S3_URL="https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/ampliseq/results-${RESULTS_HASH}"
TARGET="${1:-./ampliseq-2.18.0-testdata}"

echo "Downloading ampliseq 2.18.0 test data to: $TARGET"
echo "  from s3://nf-core-awsmegatests/ampliseq/results-${RESULTS_HASH}"
mkdir -p "$TARGET"

# nf-core-awsmegatests intermittently answers 503 (SlowDown); retry so one blip
# does not kill the whole download under `set -e`.
# $1 = key under the results prefix, $2 = destination relative to TARGET (default: $1)
fetch() {
  local key="$1" dest="${2:-$1}"
  mkdir -p "$(dirname "$TARGET/$dest")"
  curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors \
       --connect-timeout 15 --max-time 300 \
       "$S3_URL/$key" -o "$TARGET/$dest"
  echo "  ✓ $dest"
}

# --- Pipeline params + software versions ---
# The CLI reads pipeline_info/params*.json to learn how the run was configured:
# it auto-fills METADATA_FILE (this run used --metadata) and sets the route/skip
# flags that decide which data collections the template keeps. Without it the
# metadata and ANCOM-BC collections are pruned and the files below go unused.
fetch "pipeline_info/params_2026-06-17_11-21-22.json" "pipeline_info/params.json"
fetch "pipeline_info/nf_core_ampliseq_software_mqc_versions.yml" "pipeline_info/software_versions.yml"

# --- Samplesheet (user-provided input) ---
# Required: the samplesheet DC is not optional, and SAMPLESHEET_FILE is
# auto-detected from <TARGET>/input/. Without this file the template run stops
# at validation with "{SAMPLESHEET_FILE} does not exist".
fetch "input/Samplesheet_full.tsv"

# --- Metadata (user-provided input) ---
fetch "input/Metadata_full.tsv"

# --- MultiQC parquet ---
fetch "multiqc/multiqc_data/multiqc.parquet"

# --- Alpha diversity: per-metric vectors (alpha_diversity + alpha_diversity_multi_canonical) ---
for metric in faith_pd shannon observed_features evenness; do
  fetch "qiime2/diversity/alpha_diversity/${metric}_vector/metadata.tsv"
done

# --- Alpha rarefaction CSVs (alpha_rarefaction + rarefaction_canonical) ---
for metric in faith_pd shannon observed_features; do
  fetch "qiime2/alpha-rarefaction/${metric}.csv"
done

# --- Taxonomy composition: barplot levels ---
# level-3 is the Phylum for this release's default database (sbdi-gtdb, 8 ranks)
# and is what template.yaml points the recipe at; level-2 is kept because the
# recipes' own default paths (used by `depictio-cli dev recipe run` and CI's
# standalone recipe step) still name it.
fetch "qiime2/barplot/level-2.csv"
fetch "qiime2/barplot/level-3.csv"

# --- Relative abundance tables: level 2 (Phylum) … 6 (Genus) + ASV with DADA2 taxonomy ---
# rel-table-2: taxonomy_rel_abundance; 2–6: stacked_taxonomy_canonical;
# 6: sunburst/sankey_canonical; ASV_with-DADA2-tax: tree_metadata_canonical.
for level in 2 3 4 5 6; do
  fetch "qiime2/rel_abundance_tables/rel-table-${level}.tsv"
done
fetch "qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv"

# --- Taxonomy assignments + phylogenetic tree (phylogenetic_tree_canonical + tip metadata) ---
fetch "qiime2/taxonomy/taxonomy.tsv"
fetch "qiime2/phylogenetic_tree/tree.nwk"

# --- ANCOM-BC: 5 slices per level (level-3 = Phylum here, level-2 for the
#     recipe defaults) ---
for level in 2 3; do
  for f in lfc_slice.csv p_val_slice.csv q_val_slice.csv w_slice.csv se_slice.csv; do
    fetch "qiime2/ancombc/differentials/Category-habitat-level-${level}/$f"
  done
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
echo "depictio-cli run --template nf-core/ampliseq/2.18.0 --data-root $TARGET \\"
echo "  --var GROUP_COL=habitat --dry-run"
echo ""
echo "# 2. Full run (needs a reachable server and ~/.depictio/CLI.yaml)"
echo "depictio-cli run --template nf-core/ampliseq/2.18.0 --data-root $TARGET \\"
echo "  --var GROUP_COL=habitat"
echo ""
echo "# 3. Regenerate this template's committed seed TSVs from the download"
echo "python $(dirname "$0")/generate_canonical_seeds.py --raw-root $TARGET"
