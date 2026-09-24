# nf-core/smrnaseq 2.4.1: Depictio dashboards

This template turns the output of [nf-core/smrnaseq](https://nf-co.re/smrnaseq) 2.4.1 into a
six-tab Depictio dashboard. smrnaseq trims small RNA libraries with fastp, checks them with
miRTrace, annotates miRNA isomiRs with mirtop and predicts novel miRNAs with miRDeep2. The
dashboard follows that order: are the libraries small RNA libraries, which miRNAs they carry,
which miRNAs separate the design groups, how the reads differ from the reference sequences,
and what miRDeep2 proposes beyond miRBase.

Data comes from the AWS megatest run `results-cb0af579b24cb8d5a3accd87b2f14ea93fe04832` (the
2.4.1 release tag): the pipeline's full test profile, 28 libraries in a 2x2 design.

---

## How the dashboard is built

- **Six tabs, one funnel.** MultiQC, Library QC, miRNA expression, Group comparison, isomiRs,
  Novel miRNAs.
- **Persistent sample scope.** `Sample scope` (sample, the design group, miRNA depth) is pinned
  on every tab. It reads the sample hub and the design table, which link to every sample-keyed
  collection, so one pick narrows every panel. Each tab adds an open filter section of its own.
- **Run at a glance.** Four cards pinned on every tab: samples, design groups, reads assigned to
  miRNAs, miRNAs detected per sample.
- **Sample sheet.** A collapsed pinned section with the design table and the sample hub.
- **Cross-selection.** Every table with an entity id selects rows on it (sample, miRNA,
  precursor), and the sample, miRNA and precursor planes, the read length profile, the
  complexity curves and the PCA select points the same way. A selection narrows every tile on
  the tab that shares or links to that column. Each record card sits beside the plane that
  drives it and stays a thin rail until a point or row is picked. The per-sample miRDeep2 call
  table is not selectable: its call id links to nothing else on the tab.
- **Design comes from a table, never from sample names.** `METADATA_FILE`, `METADATA_ID_COL`
  and `GROUP_COL` (default `condition`) follow the ampliseq convention. Without a design table
  the metadata collection and its filter and card are pruned, the figures fall back to one
  colour, and every other tile still renders from the hub.

## Data collections

| Collection | Source | Grain |
| --- | --- | --- |
| `multiqc_data` | MultiQC parquet | fastp, FastQC (raw and trimmed), miRTrace, mirtop, samtools |
| `metadata` (optional) | `{METADATA_FILE}` | one row per sample |
| `samples` | recipe `nf-core/smrnaseq/samples.py` | one row per sample: miRNA depth, detection, composition, clade, miRDeep2 calls |
| `mirtop_mirna_counts` | `mirtop/joined_samples_mirtop.tsv` | sample x miRNA: reads, CPM, isomiRs, reference share |
| `mirtop_mirna_summary` | counts | one row per miRNA |
| `mirtop_sample_matrix` | counts | wide sample x top 1000 miRNAs (CPM), for group_compare |
| `mirtop_sample_pca` | counts | PCA of log2 CPM, top 500 variable miRNAs |
| `mirtop_top_variable_heatmap` | counts | top 100 variable miRNAs x samples, design strips |
| `mirtop_isomir_composition` | joined table | sample x isomiR class, four partitions |
| `mirtop_isomir_landscape` | joined table | top 40 miRNAs x isomiR class |
| `mirtrace_composition` (optional) | MultiQC plot input | RNA type, read QC outcome, clade |
| `mirtrace_length` (optional) | MultiQC plot input | read length per sample |
| `mirtrace_complexity` (optional) | MultiQC plot input | miRNA complexity curves |
| `mirdeep2_results_raw` (optional) | `result_*.csv` | raw lines |
| `mirdeep2_predictions` (optional) | raw lines | one row per miRDeep2 call |
| `mirdeep2_novel_precursors` (optional) | predictions | novel calls merged across samples |
| `mirdeep2_score_summary` (optional) | raw lines | score cutoff table per sample |

## Tabs

### MultiQC
fastp filtering and trimmed length, the miRTrace QC plot, mirtop isomiR counts and samtools
mapping. The miRTrace RNA-type, length, contamination and complexity panels are not repeated:
Library QC draws them as tiles. The remaining FastQC and fastp panels sit in a collapsed section.

### Library QC
Median miRNA, rRNA and tRNA shares and the main-clade share, a read length profile with the
miRNA window shaded, the composition bars (RNA type, QC outcome, clade), complexity curves, a
parallel coordinates profile of every per-library measure, and a sample record card.

### miRNA expression
miRNAs with reads, the top miRNAs by reads, detection breadth, a clustered heatmap of the most
variable miRNAs, boxes of the top miRNAs by design group, a mean-variance plane with a miRNA
record card linked to miRBase, and the per-miRNA table.

### Group comparison
Sample PCA coloured by the design group with lasso selection, then a two-group test
(Wilcoxon on CPM, Benjamini-Hochberg) drawn as a volcano. The pipeline publishes no model-based
differential expression table in this run, so the tab presents it as a screen.

### isomiRs
Reference-sequence share per library and per miRNA, isomiR counts, composition bars of the four
isomiR partitions, a dot plot of isomiR classes for the 40 most expressed miRNAs, and the
landscape rows.

### Novel miRNAs
Novel precursor count, recurrence across samples, per-sample novel and known calls, miRDeep2's
signal-to-noise and known-recovery curves by score cutoff, a recurrence against score plane with
a precursor record card linked to the UCSC browser on `{GENOME}`, and the precursor and call
tables.

## Variables

| Variable | Default | Role |
| --- | --- | --- |
| `METADATA_FILE` | none | design table; absent prunes the design collection |
| `METADATA_ID_COL` | first column | sample id column of the design table |
| `GROUP_COL` / `GROUP_COL_DISPLAY` | first annotation column | design factor for colours, strips and the group test |
| `GENOME` | `hg38` | UCSC assembly for the precursor links |
| `SKIP_MIRDEEP` | unset | drops the four miRDeep2 collections |
| `SKIP_MULTIQC` | unset | drops the MultiQC and miRTrace collections |

## Known limits

- The megatest publishes no mature or hairpin count matrices and no edgeR tables, so expression
  is aggregated from the mirtop joined isomiR table and CPM is over miRNA-assigned reads.
- The group test is a rank test on CPM, not an edgeR or DESeq2 model.
- miRTrace tables are not published; its numbers are read back from the MultiQC plot input.
