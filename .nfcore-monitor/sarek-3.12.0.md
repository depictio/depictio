# nf-core/sarek drift report — 3.11.0 → 3.12.0

**✅ verified — 2 of 3 file-based recipes ran on its data; 29 path(s) the template reads are unchanged** · Megatest: `s3://nf-core-awsmegatests/sarek/results-786a11bb4f989751d1c4bb87908ffc6096635ff3/test_full_germline_ncbench_agilent/` · run_root: `test_full_germline_ncbench_agilent/`

Upstream changes: https://github.com/nf-core/sarek/blob/master/CHANGELOG.md

## Run structure vs 3.11.0 — 638 → 638 keys
- same directories (to 2 levels) as 3.11.0

## Recipe execution — 2 pass, 0 fail, 33 skipped
- ✅ `samples` (nf-core/sarek/samples.py) — 2 rows × 7 cols
- ✅ `tracks` (nf-core/sarek/tracks.py) — 12 rows × 9 cols
- ⚪ `pairs` (nf-core/sarek/pairs.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_stats_summary` (bcftools/stats_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_stats_tstv` (bcftools/stats_tstv.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_stats_sections` (bcftools/stats_sections.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_substitution_spectrum` (nf-core/sarek/substitution_spectrum.py) — consumes upstream DCs (dc_ref)
- ⚪ `bcftools_indel_spectrum` (nf-core/sarek/indel_spectrum.py) — consumes upstream DCs (dc_ref)
- ⚪ `mosdepth_regions` (mosdepth/regions.py) — consumes upstream DCs (dc_ref)
- ⚪ `mosdepth_targets` (nf-core/sarek/mosdepth_targets.py) — consumes upstream DCs (dc_ref)
- ⚪ `mosdepth_windows` (nf-core/sarek/mosdepth_windows.py) — consumes upstream DCs (dc_ref)
- ⚪ `mosdepth_summary` (mosdepth/summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `mosdepth_xy_sex_check` (mosdepth/xy_sex_check.py) — glob source not executed
- ⚪ `vcftools_filter_summary` (vcftools/filter_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `vcftools_tstv_qual` (vcftools/tstv_qual.py) — consumes upstream DCs (dc_ref)
- ⚪ `vcf_variants` (nf-core/sarek/vcf_variants.py) — consumes upstream DCs (dc_ref)
- ⚪ `sv_calls` (nf-core/sarek/sv_calls.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_ann_variants` (nf-core/sarek/ann_variants.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_variant_upset` (nf-core/sarek/caller_overlap.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_protein_lollipop` (snpeff/protein_lollipop.py) — consumes upstream DCs (dc_ref)
- ⚪ `protein_genes` (nf-core/sarek/protein_genes.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_csv_stats` (snpeff/csv_stats.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_genes` (snpeff/genes.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_gene_upset` (snpeff/gene_upset.py) — consumes upstream DCs (dc_ref)
- ⚪ `snpeff_gene_heatmap` (snpeff/gene_heatmap.py) — consumes upstream DCs (dc_ref)
- ⚪ `callset_qc` (nf-core/sarek/callset_qc.py) — consumes upstream DCs (dc_ref)
- ⚪ `somatic_calls` (nf-core/sarek/somatic_calls.py) — consumes upstream DCs (dc_ref)
- ⚪ `somatic_vs_germline` (nf-core/sarek/somatic_vs_germline.py) — consumes upstream DCs (dc_ref)
- ⚪ `patient_call_counts` (nf-core/sarek/patient_call_counts.py) — consumes upstream DCs (dc_ref)
- ⚪ `somatic_variants` (nf-core/sarek/somatic_variants.py) — consumes upstream DCs (dc_ref)
- ⚪ `somatic_burden` (nf-core/sarek/somatic_burden.py) — consumes upstream DCs (dc_ref)
- ⚪ `germline_het_sites` (nf-core/sarek/germline_het_sites.py) — consumes upstream DCs (dc_ref)
- ⚪ `cnv_segments` (nf-core/sarek/cnv_segments.py) — consumes upstream DCs (dc_ref)
- ⚪ `cnv_summary` (nf-core/sarek/cnv_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `msi` (nf-core/sarek/msi.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 8 resolved, 0 missing, 0 optional-absent (of 8)

## Next steps
Ship the new version with:
```
python scripts/bump_template_version.py --pipeline sarek --new-version 3.12.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
