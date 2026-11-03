# nf-core/mhcquant drift report — 3.2.0 → 3.3.0

**🟡 probable — 7 path(s) the template reads are unchanged; 1 directory change(s) elsewhere; 0 of 5 recipes ran** · Megatest: `s3://nf-core-awsmegatests/mhcquant/results-a4b6d51803af0fbde5acd8e9802df76280ba8306/`

Upstream changes: https://github.com/nf-core/mhcquant/blob/master/CHANGELOG.md

## Run structure vs 3.2.0 — 111 → 114 keys
- ➖ `multiqc/ms2rescore/` only in 3.2.0

## Recipe execution — 0 pass, 0 fail, 14 skipped
- ⚪ `samples` (nf-core/mhcquant/samples.py) — user input, not a run output: input/samplesheet.tsv
- ⚪ `mhcquant_fragment_ions` (mhcquant/fragment_ions.py) — glob source not executed
- ⚪ `mhcquant_peptides` (mhcquant/peptides.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_length_distribution` (mhcquant/length_distribution.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_peptide_composition` (mhcquant/peptide_composition.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_motif_matrix` (mhcquant/motif_matrix.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_replicate_intensity` (mhcquant/replicate_intensity.py) — glob source not executed
- ⚪ `mhcquant_sample_summary` (mhcquant/sample_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_replicate_pairs` (mhcquant/replicate_pairs.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_replicate_detection` (mhcquant/replicate_detection.py) — consumes upstream DCs (dc_ref)
- ⚪ `mhcquant_source_proteins` (mhcquant/source_proteins.py) — consumes upstream DCs (dc_ref)
- ⚪ `peptide_condition_sharing` (nf-core/mhcquant/condition_sharing.py) — consumes upstream DCs (dc_ref)
- ⚪ `openms_comet_psms` (openms/comet_psms.py) — glob source not executed
- ⚪ `openms_comet_fdr_curve` (openms/comet_fdr_curve.py) — glob source not executed

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Ship the new version with:
```
python scripts/bump_template_version.py --pipeline mhcquant --new-version 3.3.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
