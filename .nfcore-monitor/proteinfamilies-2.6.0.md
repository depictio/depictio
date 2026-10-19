# nf-core/proteinfamilies drift report — 2.5.0 → 2.6.0

**❌ action needed** · Megatest: `s3://nf-core-awsmegatests/proteinfamilies/results-f8c0b183e59df3d87c38d0f7c4acc6918593f4f5/`

> ⚠️ nf-core/proteinfamilies 2.6.0: megatest run s3://nf-core-awsmegatests/proteinfamilies/results-318acd54eb9c679553338b2db46313bb469d03d1/ is empty, failed or truncated (0 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 5 keys; need 5 of each). Falling back to the newest real run `proteinfamilies/results-f8c0b183e59df3d87c38d0f7c4acc6918593f4f5/` (release 2.5.0).

## Recipe execution — 0 pass, 0 fail, 9 skipped
- ⚪ `samples` (nf-core/proteinfamilies/samples.py) — unresolved var in {DATA_ROOT}/input/samplesheet.csv
- ⚪ `sequence_stats` (seqfu/stats.py) — consumes upstream DCs (dc_ref)
- ⚪ `cluster_sizes` (proteinfamilies/cluster_size_distribution.py) — consumes upstream DCs (dc_ref)
- ⚪ `families` (proteinfamilies/family_metadata.py) — consumes upstream DCs (dc_ref)
- ⚪ `family_members` (proteinfamilies/family_members.py) — consumes upstream DCs (dc_ref)
- ⚪ `family_msa` (famsa/alignment.py) — consumes upstream DCs (dc_ref)
- ⚪ `family_residues` (famsa/conservation.py) — consumes upstream DCs (dc_ref)
- ⚪ `hmm_profile` (hmmer/hmm_profile.py) — consumes upstream DCs (dc_ref)
- ⚪ `hmmalign_hits` (hmmer/hmmalign_hits.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 1 missing, 0 optional-absent (of 1)
- ❌ `samples` (samplesheet) → {DATA_ROOT}/input/samplesheet.csv

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline proteinfamilies --new-version 2.6.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
