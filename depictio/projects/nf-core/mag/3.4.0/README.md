# nf-core/mag — Depictio scaffold (v3.4.0)

**Tier 2 — needs 1 new advanced-viz component (`bin_qc_scatter`).**

## Megatest

- Bucket: `s3://nf-core-awsmegatests/mag/`
- Docs: <https://nf-co.re/mag/3.4.0/docs/output>

## Dashboard inventory

| Tab | Component | `viz_kind` | Status |
|-----|-----------|-----------|--------|
| MultiQC | MultiQC tiles | (built-in) | ✓ |
| Taxonomy | Stacked taxonomy + Sunburst | `stacked_taxonomy`, `sunburst` | ✓ |
| MAG Tree | GTDB-Tk phylogeny | `phylogenetic` | ✓ |
| Bin QC | Completeness vs contamination | `bin_qc_scatter` | **PROPOSED** |

See PROPOSED_COMPONENTS.md for the `bin_qc_scatter` spec.

## Local handoff checklist

- [ ] Implement `bin_qc_scatter` (see PROPOSED_COMPONENTS.md — small effort).
- [ ] Implement recipes (CheckM + QUAST + GTDB-Tk parsing).
- [ ] Register IDs in `STATIC_IDS` + `DATASET_PATHS`.
- [ ] Replace `TODO_*` placeholders in the phylogenetic config.
- [ ] Reseed + verify.
