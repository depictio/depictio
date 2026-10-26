# nf-core/genomeassembler drift report — 2.0.0 → 2.0.1

**✅ still valid** · Megatest: `s3://nf-core-awsmegatests/genomeassembler/results-a72d47d9cdb50f21b97882dfb2abf4af8f4c74ad/`

> ⚠️ nf-core/genomeassembler 2.0.1: megatest run s3://nf-core-awsmegatests/genomeassembler/results-c608622876dc627020e6627a5ea8cffd0d2e3f3d/ is empty, failed or truncated (0 data object(s) outside pipeline_info/, 0 of them under 50 MB, in 5 keys; need 5 of each). Falling back to the newest real run `genomeassembler/results-a72d47d9cdb50f21b97882dfb2abf4af8f4c74ad/` (release 2.0.0).

## Recipe execution — 0 pass, 0 fail, 14 skipped
- ⚪ `merqury_assembly_qv` (merqury/assembly_qv.py) — consumes upstream DCs (dc_ref)
- ⚪ `merqury_sequence_qv` (merqury/sequence_qv.py) — consumes upstream DCs (dc_ref)
- ⚪ `merqury_copy_number` (merqury/copy_number_composition.py) — consumes upstream DCs (dc_ref)
- ⚪ `busco_batch_summary` (busco/batch_summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `busco_composition` (busco/composition.py) — consumes upstream DCs (dc_ref)
- ⚪ `quast_assembly_report` (quast/assembly_report.py) — consumes upstream DCs (dc_ref)
- ⚪ `quast_length_ladder` (quast/length_ladder.py) — consumes upstream DCs (dc_ref)
- ⚪ `quast_reference_report` (quast/reference_report.py) — consumes upstream DCs (dc_ref)
- ⚪ `genomescope_summary` (genomescope/summary.py) — consumes upstream DCs (dc_ref)
- ⚪ `jellyfish_histogram` (jellyfish/histogram.py) — consumes upstream DCs (dc_ref)
- ⚪ `assemblies` (nf-core/genomeassembler/assemblies.py) — consumes upstream DCs (dc_ref)
- ⚪ `nx_curve` (nf-core/genomeassembler/nx_curve.py) — consumes upstream DCs (dc_ref)
- ⚪ `stage_steps` (nf-core/genomeassembler/stage_steps.py) — consumes upstream DCs (dc_ref)
- ⚪ `sample_status` (nf-core/genomeassembler/sample_status.py) — consumes upstream DCs (dc_ref)

## Catalog validate — ✅ PASS
- OK: 120 catalog tool(s) valid in /home/runner/work/depictio/depictio/depictio/catalog

## Source paths — 0 resolved, 0 missing, 0 optional-absent (of 0)

## Next steps
Template still valid (or once the drift above is fixed), ship the new version with:
```
python scripts/bump_template_version.py --pipeline genomeassembler --new-version 2.0.1
```
then follow the checklist it prints. Seeding, CLI (`--template …/latest`), CI and docs all pick the new version up automatically.
