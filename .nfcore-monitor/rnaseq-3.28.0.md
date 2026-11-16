# nf-core/rnaseq drift report — 3.26.0 → 3.28.0

**🟡 probable — 37 path(s) the template reads are unchanged; 0 of 9 recipes ran** · Megatest: `s3://nf-core-awsmegatests/rnaseq/results-f24c6c0e9469d04975d87c3a8bf9020800978782/aligner_star_salmon/` · run_root: `aligner_star_salmon/`

Upstream changes: https://github.com/nf-core/rnaseq/blob/master/CHANGELOG.md

## Run structure vs 3.26.0 — 1527 → 1538 keys
- same directories (to 2 levels) as 3.26.0

## Recipe execution — 0 pass, 0 fail, 10 skipped
- ⚪ `samplesheet` (nf-core/rnaseq/samplesheet.py) — user input, not a run output: input/samplesheet.csv
- ⚪ `tracks` (nf-core/rnaseq/tracks.py) — user input, not a run output: input/samplesheet.csv
- ⚪ `sample_overview` (salmon/sample_pca.py) — user input, not a run output: input/samplesheet.csv
- ⚪ `expression_heatmap` (salmon/top_variable_genes.py) — user input, not a run output: input/samplesheet.csv
- ⚪ `gene_expression` (salmon/gene_expression_long.py) — user input, not a run output: input/samplesheet.csv
- ⚪ `deseq2_qc_pca` (deseq2/qc_pca.py) — glob source not executed
- ⚪ `deseq2_qc_dists` (deseq2/qc_sample_dists.py) — glob source not executed
- ⚪ `rseqc_read_distribution` (rseqc/read_distribution.py) — consumes upstream DCs (dc_ref)
- ⚪ `general_stats` (nf-core/rnaseq/general_stats.py) — glob source not executed
- ⚪ `gene_summary` (nf-core/rnaseq/gene_summary.py) — glob source not executed

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 4 resolved, 0 missing, 0 optional-absent (of 4)

## Next steps
Ship the new version with:
```
python scripts/bump_template_version.py --pipeline rnaseq --new-version 3.28.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
