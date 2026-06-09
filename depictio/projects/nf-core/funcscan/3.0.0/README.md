# nf-core/funcscan — Depictio scaffold (v3.0.0)

**Tier 2 — needs 1 new advanced-viz component (`gene_context_map`).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/funcscan/`
- Docs: <https://nf-co.re/funcscan/3.0.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| AMR Tool Overlap | Cross-tool UpSet | `upset_plot` | ✓ |
| AMR per Sample | Sample × gene heatmap | `complex_heatmap` | ✓ |
| AMR Drug Classes | Drug-class sunburst | `sunburst` | ✓ |
| Gene Context Map | Contig gene-hit map | `gene_context_map` | **PROPOSED** |

## Local handoff checklist

- [ ] Implement `gene_context_map` (small effort — see PROPOSED_COMPONENTS.md).
- [ ] Implement recipes (hAMRonization TSV parsing).
- [ ] Register IDs + reseed.
