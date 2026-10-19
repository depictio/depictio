# nf-core/hic drift report — 2.0.0 → 2.1.0

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/`

> ⚠️ nf-core/hic 2.1.0: megatest run s3://nf-core-awsmegatests/hic/results-fe4ac656317d24c37e81e7940a526ed9ea812f8e/ is empty, failed or truncated (3 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 25 keys; need 5 of each). Falling back to the newest real run `hic/results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d/` (release 2.0.0).

## Recipe execution — 1 pass, 0 fail, 9 skipped
- ✅ `samples` (nf-core/hic/samples.py) — 1 rows × 3 cols
- ⚪ `pair_stats` (hicpro/pair_stats.py) — consumes upstream DCs (dc_ref)
- ⚪ `pair_flow` (hicpro/pair_flow.py) — consumes upstream DCs (dc_ref)
- ⚪ `contact_matrix` (cooler/contact_matrix.py) — consumes upstream DCs (dc_ref)
- ⚪ `distance_profile` (cooltools/distance_profile.py) — consumes upstream DCs (dc_ref)
- ⚪ `compartment_eigenvector` (cooltools/eigenvector.py) — consumes upstream DCs (dc_ref)
- ⚪ `compartment_eigenvalues` (cooltools/eigenvalues.py) — consumes upstream DCs (dc_ref)
- ⚪ `tad_insulation` (cooltools/insulation.py) — consumes upstream DCs (dc_ref)
- ⚪ `tad_domains` (cooltools/domains.py) — consumes upstream DCs (dc_ref)
- ⚪ `distance_decay` (hicexplorer/distance_decay.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 1 resolved, 0 missing, 0 optional-absent (of 1)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline hic --new-version 2.1.0
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
