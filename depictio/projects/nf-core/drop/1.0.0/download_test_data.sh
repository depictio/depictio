#!/usr/bin/env bash
# Download the nf-core/drop 1.0.0 test data for local testing.
#
# The AWS megatest bucket publishes no result tables for drop (see megatest.yaml), so the
# shared megatest fetch has nothing to get. This script instead pulls the real DROP outputs
# of the pipeline's chr21 test run from the nf-core/test-datasets `drop` branch and lays them
# out the way nf-core/drop writes them under its outdir:
#   processed_results/aberrant_expression/<annotation>/outrider/<group>/OUTRIDER_results.tsv
#   processed_results/aberrant_splicing/results/<annotation>/fraser/<group>/results.tsv
#   processed_results/mae/<group>/MAE_results_*.tsv  and  gene_name_mapping_<annotation>.tsv
# plus the small chr21 BAMs and VCFs of that run under input/ (the Locus tab's tracks) and
# the vendored sample sheet. About 55 MB in total. The megatest params (and the 62,700 x 120
# exported gene counts, 4.9 MB) come from the public bucket when the `aws` CLI is installed.
#
# Usage: bash download_test_data.sh [TARGET_DIR]
#   Default TARGET_DIR: ~/Data/depictio-nfcore/drop/1.0.0/megatest
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${1:-$HOME/Data/depictio-nfcore/drop/1.0.0/megatest}"
base="https://raw.githubusercontent.com/nf-core/test-datasets/drop/data"
ann="v29"

get() { # get <path under data/> <destination under dest>
  mkdir -p "$dest/$(dirname "$2")"
  [ -s "$dest/$2" ] || curl -fsSL --retry 3 -o "$dest/$2" "$base/$1"
}

# Result tables, in the layout of the pipeline's outdir.
get intermediates/resultsourtider/OUTRIDER_results.tsv \
  "processed_results/aberrant_expression/$ann/outrider/outrider/OUTRIDER_results.tsv"
get intermediates/fraser/extractresults/results.tsv \
  "processed_results/aberrant_splicing/results/$ann/fraser/fraser/results.tsv"
get intermediates/mae/results/MAE_results_HG00096.tsv "processed_results/mae/mae/MAE_results_$ann.tsv"
get intermediates/mae/results/MAE_results_HG00096_rare.tsv "processed_results/mae/mae/MAE_results_${ann}_rare.tsv"
get intermediates/mae/results/MAE_results_all_HG00096.tsv.gz "processed_results/mae/mae/MAE_results_all_$ann.tsv.gz"
get intermediates/mae/genenamemapping/gene_name_mapping_$ann.tsv "processed_results/mae/gene_name_mapping_$ann.tsv"

# Tracks: the small chr21 alignments and genotypes the sample sheet points at.
for s in HG00096_ncbi HG00103 HG00106 HG00111 HG00116 HG00126 HG00132 HG00149 HG00150 HG00176; do
  get "inputs/$s.bam" "input/rna_bam/$s.bam"
  get "inputs/$s.bam.bai" "input/rna_bam/$s.bam.bai" 2>/dev/null || true
done
for v in demo_chr21 demo_chr21_ncbi; do
  get "inputs/dna_vcf/$v.vcf.gz" "input/dna_vcf/$v.vcf.gz"
  get "inputs/dna_vcf/$v.vcf.gz.tbi" "input/dna_vcf/$v.vcf.gz.tbi"
done

# The sample sheet is not a pipeline output: use the vendored copy.
mkdir -p "$dest/input"
cp "$here/input/samplesheet.tsv" "$dest/input/samplesheet.tsv"

# Megatest provenance and exported counts (optional: needs the aws CLI, no credentials).
if command -v aws >/dev/null 2>&1; then
  mkdir -p "$dest/pipeline_info"
  aws s3 cp --no-sign-request --recursive --exclude '*' --include 'params_*.json' \
    s3://nf-core-awsmegatests/drop/results-dev/pipeline_info/ "$dest/pipeline_info/"
  aws s3 cp --no-sign-request s3://nf-core-awsmegatests/drop/input/counts/1.0.0/geneCounts.tsv.gz \
    "$dest/input/geneCounts.tsv.gz"
else
  echo "aws CLI not found: skipped the megatest params and exported gene counts" >&2
fi
echo "Done: $dest"
