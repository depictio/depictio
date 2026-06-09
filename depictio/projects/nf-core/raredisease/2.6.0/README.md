# nf-core/raredisease — Depictio scaffold (v2.6.0)

**Tier 2 — needs 1 new advanced-viz component (`cnv_ideogram`).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/raredisease/`
- Docs: <https://nf-co.re/raredisease/2.6.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| SNV Manhattan | Rank-score Manhattan | `manhattan` | ✓ |
| Coverage | Mosdepth | `coverage_track` | ✓ |
| Gene Lollipop | aa lollipop | `lollipop` | ✓ |
| Oncoplot | Sample × gene rare variants | `oncoplot` | ✓ |
| CNV / ROH Ideogram | Chromosome ideogram | `cnv_ideogram` | **PROPOSED** |

## Local handoff checklist

- [ ] Implement `cnv_ideogram` (see PROPOSED_COMPONENTS.md).
- [ ] Implement recipes (VCF parsing + ROH merging).
- [ ] Register IDs + reseed.
