# nf-core/chipseq — Depictio scaffold (v2.1.0)

**Tier 2 — shares `signal_profile` with atacseq + methylseq (PROPOSED).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/chipseq/`
- Docs: <https://nf-co.re/chipseq/2.1.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| Coverage | BigWig signal | `coverage_track` | ✓ |
| Peak Significance | MACS2 q-values | `manhattan` | ✓ |
| Consensus Peaks | UpSet + heatmap | `upset_plot`, `complex_heatmap` | ✓ |
| Peak-Center Profile | Signal around peak centers | `signal_profile` | **PROPOSED** |

## Local handoff checklist

- [ ] `signal_profile` shared with atacseq + methylseq — build once.
- [ ] Implement recipes (deepTools BigWig + MACS2 narrowPeak parsing).
- [ ] Register IDs + reseed.
