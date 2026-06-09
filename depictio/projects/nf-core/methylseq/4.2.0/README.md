# nf-core/methylseq — Depictio scaffold (v4.2.0)

**Tier 2 — shares `signal_profile` with atacseq + chipseq (PROPOSED).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/methylseq/`
- Docs: <https://nf-co.re/methylseq/4.2.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| Methylation Track | Per-region %methylation | `coverage_track` | ✓ |
| DMR Manhattan | Differential methylation | `manhattan` | ✓ |
| TSS Profile | Region-anchored %meth profile | `signal_profile` | **PROPOSED** |

## Local handoff checklist

- [ ] `signal_profile` lands once atacseq/chipseq pull it through.
- [ ] Implement recipes (MethylDackel/Bismark parsing + TSS binning).
- [ ] Register IDs + reseed.
