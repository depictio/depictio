# nf-core/rnaseq drift report — 3.26.0 → 3.27.0

**❌ action needed** · Megatest: `s3://nf-core-awsmegatests/rnaseq/results-a1fcdddd3b826fe46eb46f0479f2ff8a7815af05/aligner_star_salmon/` · run_root: `aligner_star_salmon/`

> ⚠️ nf-core/rnaseq 3.27.0: run_root 'aligner_star_salmon/' not found under s3://nf-core-awsmegatests/rnaseq/results-a1fcdddd3b826fe46eb46f0479f2ff8a7815af05/ (top-level dirs: aligner_star_rsem). Falling back to the newest real run `rnaseq/results-a1fcdddd3b826fe46eb46f0479f2ff8a7815af05/` (release 3.27.0).

## Recipe execution — 0 pass, 3 fail, 1 skipped
- ❌ `sample_overview` (salmon/sample_pca.py) — source file absent: star_salmon/salmon.merged.gene_tpm.tsv
- ❌ `expression_heatmap` (salmon/top_variable_genes.py) — source file absent: star_salmon/salmon.merged.gene_tpm.tsv
- ❌ `gene_expression` (salmon/gene_expression_long.py) — source file absent: star_salmon/salmon.merged.gene_tpm.tsv
- ⚪ `samplesheet` (nf-core/rnaseq/samplesheet.py) — unresolved var in {DATA_ROOT}/input/samplesheet.csv

## Catalog validate — ✅ PASS
- OK: 37 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 4 missing, 3 optional-absent (of 7)
- ❌ `samplesheet` (samplesheet) → {DATA_ROOT}/input/samplesheet.csv
- ❌ `sample_overview` (matrix) → star_salmon/salmon.merged.gene_tpm.tsv
- ❌ `expression_heatmap` (matrix) → star_salmon/salmon.merged.gene_tpm.tsv
- ❌ `gene_expression` (matrix) → star_salmon/salmon.merged.gene_tpm.tsv
- ⚪ `sample_overview` (samplesheet) → {DATA_ROOT}/input/samplesheet.csv — optional route, not exercised by megatest
- ⚪ `expression_heatmap` (samplesheet) → {DATA_ROOT}/input/samplesheet.csv — optional route, not exercised by megatest
- ⚪ `gene_expression` (samplesheet) → {DATA_ROOT}/input/samplesheet.csv — optional route, not exercised by megatest

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline rnaseq --new-version 3.27.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
