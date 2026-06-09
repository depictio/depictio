# nf-core/atacseq — Depictio scaffold (v2.1.2)

**Tier 2 — shares `signal_profile` with chipseq + methylseq (PROPOSED).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/atacseq/`
- Docs: <https://nf-co.re/atacseq/2.1.2/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| Coverage | BigWig signal | `coverage_track` | ✓ |
| Peak Significance | MACS2 q-values | `manhattan` | ✓ |
| Consensus Peaks | UpSet + heatmap | `upset_plot`, `complex_heatmap` | ✓ |
| TSS Enrichment | Meta-profile around TSS | `signal_profile` | **PROPOSED** |

## Local handoff checklist

- [ ] Build `signal_profile` (highest-leverage new component — also unlocks chipseq + methylseq).
- [ ] Implement recipes (deepTools BigWig + MACS2 narrowPeak parsing).
- [ ] Register IDs + reseed.
