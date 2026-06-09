# nf-core Pipeline Dashboard Candidates

Catalogue of nf-core pipelines under evaluation for Depictio dashboard builds, with a
gap analysis comparing pipeline outputs against Depictio's **18 existing advanced-viz
components**.

**Already shipped (excluded):** [`ampliseq`](./ampliseq/), [`viralrecon`](./viralrecon/).

## Selection criteria

1. Released (≥1 stable tag), not dev/archived.
2. AWS megatest results available — confirmed by listing the public bucket
   `s3://nf-core-awsmegatests/<pipeline>/`.
3. Mature pipeline — multiple releases, active maintenance.
4. Mid-to-high star count.
5. Output schema maps onto Depictio's advanced-viz catalogue.

## Existing Depictio advanced-viz components (18)

`volcano`, `ma`, `da_barplot`, `enrichment`, `manhattan`, `lollipop`, `coverage_track`,
`stacked_taxonomy`, `sunburst`, `rarefaction`, `phylogenetic`, `dot_plot`, `embedding`,
`complex_heatmap`, `qq`, `upset_plot`, `sankey`, `oncoplot`
(see `depictio/models/components/advanced_viz/configs.py`).

## Ranked candidates (10)

All AWS megatest results were confirmed by direct S3 bucket listing. Pipelines also expose
results at `https://nf-co.re/<pipeline>/results`.

| # | Pipeline | ★ | Latest release | AWS megatest | Existing viz that fit | New viz dev needed | Rationale |
|---|----------|---|----------------|--------------|------------------------|---------------------|-----------|
| 1 | **differentialabundance** | ~96 | v1.5.0 | [s3://nf-core-awsmegatests/differentialabundance/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=differentialabundance/) | `volcano`, `ma`, `complex_heatmap`, `enrichment`, `embedding` | None | DESeq2/limma + gprofiler2/GSEA outputs map 1:1 to existing canonical schemas — zero-gap flagship. |
| 2 | **sarek** | ~574 | v3.8.1 | [s3://nf-core-awsmegatests/sarek/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=sarek/) | `manhattan`, `qq`, `coverage_track`, `lollipop`, `oncoplot` | None | Flagship variant calling; VCF/MAF + mosdepth outputs cover the genomics-track viz family. |
| 3 | **taxprofiler** | ~188 | v2.0.0 | [s3://nf-core-awsmegatests/taxprofiler/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=taxprofiler/) | `stacked_taxonomy`, `sunburst`, `rarefaction`, `embedding`, `upset_plot` | None | Multi-profiler metagenomics; TAXPASTA + Kraken kreports plug straight into the microbiome viz set. |
| 4 | **scrnaseq** | ~330 | v4.1.0 (2025-10-30) | [s3://nf-core-awsmegatests/scrnaseq/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=scrnaseq/) | `embedding`, `dot_plot`, `complex_heatmap` | **`knee_qc`** — barcode-rank knee + per-cell QC scatter | AnnData/cell-matrix output is native to embedding + marker dot plots; only the empty-droplet diagnostic is missing. |
| 5 | **mag** | ~302 | v3.4.0 | [s3://nf-core-awsmegatests/mag/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=mag/) | `stacked_taxonomy`, `sunburst`, `embedding`, `phylogenetic` | **`bin_qc_scatter`** — CheckM/QUAST completeness-vs-contamination | Taxonomy + GTDB-Tk tree fit existing components; bin-QC scatter is the core MAG deliverable. |
| 6 | **methylseq** | ~192 | v4.2.0 | [s3://nf-core-awsmegatests/methylseq/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=methylseq/) | `coverage_track`, `manhattan` | **`signal_profile`** — methylation track / region heatmap (shared with atac/chip) | Mature epigenetics community; signal-along-coordinate reuses `coverage_track`, %-methylation views are the missing specialisation. |
| 7 | **raredisease** | ~117 | v2.6.0 | [s3://nf-core-awsmegatests/raredisease/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=raredisease/) | `manhattan`, `lollipop`, `coverage_track`, `oncoplot` | **`cnv_ideogram`** — chromosome ideogram w/ CNV gains/losses + ROH bands | Clinical WGS/WES + ranking output; reuses sarek-style components, adds the clinical CNV/ROH view. |
| 8 | **atacseq** | ~226 | v2.1.2 | [s3://nf-core-awsmegatests/atacseq/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=atacseq/) | `coverage_track`, `manhattan`, `upset_plot`, `complex_heatmap` | **`signal_profile`** — TSS/peak meta-profile + fragment-length panel | Peak/coverage maps to existing; ATAC-specific TSS-enrichment + fragment-length diagnostics fill the gap. |
| 9 | **chipseq** | ~241 | v2.1.0 (2024-10-07) | [s3://nf-core-awsmegatests/chipseq/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=chipseq/) | `coverage_track`, `manhattan`, `upset_plot`, `complex_heatmap` | **`signal_profile`** — deepTools-style signal heatmap around peak centers | Coverage + consensus-peak UpSet fit; meta-profile around peak centers is the standard missing view. |
| 10 | **funcscan** | ~111 | v3.0.0 (2025-10-04) | [s3://nf-core-awsmegatests/funcscan/](https://nf-core-awsmegatests.s3.eu-west-1.amazonaws.com/?prefix=funcscan/) | `upset_plot`, `complex_heatmap`, `sunburst` | **`gene_context_map`** — linear contig gene-hit map | Presence/absence + tool-overlap reuse `upset_plot`/`complex_heatmap`; only the contig gene-context map is new. |

## New components ranked by reusability (build leverage)

Aggregating proposed new components across the 10 pipelines:

| New `viz_kind` | Pipelines unlocked | Direct | Latent |
|----------------|-------------------|--------|--------|
| `signal_profile` | atacseq, chipseq, methylseq | **3** | also fits cutandrun, hic, rnafusion meta-profiles |
| `cnv_ideogram` | raredisease, sarek-somatic | **1** | + oncoanalyser, hgtseq |
| `knee_qc` | scrnaseq | **1** | + any future droplet protocol (spatial/CITE) |
| `bin_qc_scatter` | mag | **1** | + bacass, assembly-QC dashboards |
| `gene_context_map` | funcscan | **1** | narrow — distinct from `lollipop` / `coverage_track` |

Full spec for each is in
[`depictio/models/components/advanced_viz/PROPOSED_COMPONENTS.md`](../../models/components/advanced_viz/PROPOSED_COMPONENTS.md).

## Build-order recommendation

1. **Ship the zero-gap three first** — `differentialabundance`, `sarek`, `taxprofiler`.
   They need no new components and immediately validate the platform against three distinct
   biological domains (bulk transcriptomics, human variant calling, metagenomics).

2. **Build `signal_profile`** next — the highest-leverage new component. It single-handedly
   unlocks `atacseq` and `chipseq` and (with minor extension) `methylseq` from one effort.

3. **Then `cnv_ideogram`** — reusable across `raredisease`, `sarek` somatic CNV, and a
   future `oncoanalyser` dashboard.

4. **Then `knee_qc`** for `scrnaseq` — opens single-cell, reusable across any droplet-based
   protocol.

5. **Defer narrow single-pipeline views** — `bin_qc_scatter` (mag) and `gene_context_map`
   (funcscan) — until those dashboards are scheduled.

## Runners-up (considered, not in top 10)

- `rnaseq` — huge stars but raw outputs only directly hit PCA + MultiQC; volcano/heatmap
  work lives downstream in `differentialabundance` (#1).
- `nascent` / `cutandrun` — narrower communities; `cutandrun` becomes a natural pickup
  once `signal_profile` lands.
- `hic` — interesting but Hi-C contact maps need a dedicated 2D contact-matrix viz that
  doesn't generalise.
- `airrflow` — already partially covered by existing `sankey` (V→D→J flow) and `dot_plot`;
  candidate for a follow-up wave.

## Scaffolds

This catalogue is paired with skeleton project trees for all 10 pipelines under
`depictio/projects/nf-core/<pipeline>/<version>/`. Tier 1 (zero-gap three) ship as
near-complete templates ready for recipe wiring; Tier 2 (the seven with proposed
components) ship as skeletons that mark the missing `viz_kind`s with
`# PROPOSED: <viz_kind>` comments. See each pipeline's `README.md` for the megatest URL
and the local-handoff checklist.

## Verification trail

- **Star counts:** GitHub API on the nf-core org.
- **AWS megatest availability:** direct S3 bucket listings under
  `s3://nf-core-awsmegatests/<pipeline>/results-*`.
- **Latest releases:** GitHub tags + nf-co.re docs versions.
- **Viz fit:** matched against `depictio/models/components/advanced_viz/{configs.py,schemas.py}`
  role-by-role.
