# nf-core/pairgenomealign drift report — 3.0.4 → 3.0.5

**🟡 probable — 8 path(s) the template reads are unchanged; 0 of 7 recipes ran** · Megatest: `s3://nf-core-awsmegatests/pairgenomealign/results-1230582b79bd877a4b147140bf825301e16a2f1b/`

Upstream changes: https://github.com/nf-core/pairgenomealign/blob/master/CHANGELOG.md

## Params (from_params rules) — 3.0.4 → 3.0.5
- every rule reads a param of the release, with the same default result

## Differential ingestion — 3.0.4 → 3.0.5: 0 error(s), 0 warning(s)
- the template finds, reads and builds the same on both runs

## Run structure vs 3.0.4 — 359 → 359 keys
- same directories (to 2 levels) as 3.0.4

## Recipe execution — 0 pass, 0 fail, 8 skipped
- ⚪ `last_split_identity` (last/split_identity.py) — glob source not executed
- ⚪ `last_split_matrix` (last/split_matrix.py) — glob source not executed
- ⚪ `last_train_params` (last/train_params.py) — glob source not executed
- ⚪ `last_synteny_links` (last/synteny_links.py) — glob source not executed
- ⚪ `assemblyscan_stats` (assemblyscan/stats.py) — glob source not executed
- ⚪ `seqtk_cutn_gaps` (seqtk/cutn_gaps.py) — glob source not executed
- ⚪ `seqtk_cutn_gap_lengths` (seqtk/cutn_gap_lengths.py) — glob source not executed
- ⚪ `genomes` (nf-core/pairgenomealign/genomes.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 136 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Ship the new version with:
```
python scripts/bump_template_version.py --pipeline pairgenomealign --new-version 3.0.5
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
