# nf-core/rnasplice 1.0.4: Depictio dashboards

This template turns the output of [nf-core/rnasplice](https://nf-co.re/rnasplice) 1.0.4 into a
six-tab Depictio dashboard. rnasplice trims reads with Trim Galore, aligns them with STAR,
quantifies transcripts with Salmon, and tests differential splicing per contrast with up to
five tools: DEXSeq on exonic bins, edgeR `diffSpliceDGE` on exons, DEXSeq on transcripts
(DTU), rMATS on junction-supported events and SUPPA2 on local events from transcript TPMs.

Validated against a `-profile test_full` run on the EMBL cluster (six samples, two
conditions, a contrast and its mirror), since no AWS megatest results are published for
1.0.4.

---

## How the dashboard is built

- **One funnel, six tabs.** MultiQC, Sample space, Splicing overview, Exon usage,
  Transcript usage, Splicing events. Every tab sets `advanced_viz_controls: header`.
- **Run scope** (pinned, persistent): sample, `{GROUP_COL}` and contrast filters. The
  contrast table is linked to every splicing collection, so one contrast pick scopes every
  tab. rnasplice often lists a contrast and its mirror; pick one.
- **Run at a glance** (pinned, four cards): samples by group, contrasts by treatment, genes
  detected per sample (box plot), genes tested for splicing.
- **Sample sheet** (pinned, collapsed): the validated sample sheet merged per sample, plus
  the design table when `METADATA_FILE` is given, and the contrast sheet.
- **Gene links.** The cross-tool `splicing_genes` table links on `gene_id` to the five tool
  collections, so a gene or tool-agreement filter on the overview reaches the per-tool tabs.
- **Selection.** The sample and contrast tables of the sample sheet, the sample PCA and every
  gene, transcript and event table emit a selection on their id column (`sample`,
  `contrast`, `sample_id`, `gene_id`, `event_id`), which narrows every tile linked to it.
  Each record card sits beside the table or scatter that drives it (`linked_component`) and
  stays a thin rail until a row or point is picked. The volcanoes and the UpSet do not
  select.
- **Every tool is optional.** A run that skips a tool drops its collection; its tiles stay
  empty and the UpSet shows an empty set.

## Tabs

| Tab | Question | Main views |
| --- | --- | --- |
| MultiQC | Are the libraries usable for splicing tests? | FastQC counts and adapters, Trim Galore, STAR summary, samtools mapping, featureCounts assignments, Salmon fragment lengths |
| Sample space | Do the samples group by condition? | Salmon TPM PCA embedding, top variable genes complex heatmap, sample record |
| Splicing overview | Which genes does each tool call, and where do the tools agree? | agreement cards, UpSet of called genes across the five tools, gene record with every tool's evidence |
| Exon usage | Which genes use their exons differently? | DEXSeq and edgeR gene volcanoes, call donuts, fold-change box plots |
| Transcript usage | Which transcripts switch within their gene? | DEXSeq DTU transcript volcano with QQ view |
| Splicing events | Which event types change, and by how much inclusion? | significant events per type and direction (stacked bars), rMATS and SUPPA2 volcanoes, rMATS event record with a UCSC link |

## Data collections

| DC | Source | Recipe |
| --- | --- | --- |
| multiqc_data | `multiqc/multiqc_data/multiqc.parquet` (reprocessed, MultiQC 1.18 writes none) | MultiQC |
| samples | `pipeline_info/samplesheet.valid.csv` (+ `metadata`) | `recipes/samples.py` |
| metadata (optional) | `METADATA_FILE` | none (table scan) |
| contrasts | `contrastsheet/contrastsheet.valid.csv` | none (table scan) |
| sample_pca, expression_heatmap | `{QUANT_ROUTE}/tximport/salmon.merged.gene_tpm.tsv` | `salmon/sample_pca`, `salmon/top_variable_genes` |
| dexseq_exon_genes (optional) | `**/DEXSeqResults.*.csv`, `**/perGeneQValue.*.csv` | `dexseq/exon_genes` |
| edger_genes (optional) | `**/contrast_*.usage.{gene,simes,exon}.csv` | `edger/diffsplice_genes` |
| dexseq_dtu (optional) | `{QUANT_ROUTE}/**/DEXSeqResults.*.tsv`, `perGeneQValue.*.tsv` | `dexseq/dtu` |
| rmats_events (optional) | `**/*.MATS.JCEC.txt` | `rmats/events` |
| suppa_events (optional) | `{QUANT_ROUTE}/**/*_local_diffsplice.dpsi` | `suppa/local_events` |
| splicing_genes | the five tool DCs | `recipes/splicing_genes.py` |

## Variables

| Variable | Default | Role |
| --- | --- | --- |
| `METADATA_FILE` | none | optional design table; its columns join the sample hub |
| `METADATA_ID_COL` | `sample` | sample column of the design table |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `condition`, `Condition` | grouping column of the sample filter and cards |
| `QUANT_ROUTE` | `star_salmon` | which Salmon copy feeds the PCA, DTU and SUPPA2 (`salmon` for pseudo-alignment-only runs) |
| `GENOME` | `hg38` | UCSC assembly for the event locus link |
| `SPLICING_FDR` | `0.05` | FDR / q-value cut-off of every tool's call (SUPPA2 uses it on its p-value) |
| `MIN_DPSI` | `0.1` | minimal absolute PSI change of an rMATS or SUPPA2 call |
| `RMATS_MIN_READS` | `10` | mean junction reads per replicate required in both conditions |

## Method notes

- **One sign for every tool: treatment minus control.** DEXSeq reports `log2fold_<A>_<B>`
  with the control first in rnasplice, so the sign is flipped when the contrast is
  `<treatment>-<control>`. SUPPA2 reports the second condition minus the first and is
  negated. rMATS (`--b1` is the treatment) and edgeR are already oriented. Mirrored
  contrasts give mirrored effects.
- **Gene-level calls.** DEXSeq exon usage and DTU use the per-gene q-value
  (`perGeneQValue`); edgeR uses the gene F-test FDR; rMATS and SUPPA2 call a gene when at
  least one of its events is significant with an absolute PSI change of at least
  `MIN_DPSI`. The volcano x axis of the gene-level tools is the fold change of the gene's
  most significant bin or exon.
- **Composite genes.** DEXSeq (`ENSG1+ENSG2`) and SUPPA2 (`ENSG1_and_ENSG2`) merge
  overlapping genes; the cross-tool table counts such a row for each gene it names.
- **Gene symbols** come from rMATS, the only tool that reports them; other genes keep their
  Ensembl id as name.
- **Coordinates.** rMATS uses `chr`-prefixed chromosome names, the other tools the bare
  names of the annotation; the UCSC link uses the rMATS locus.

## Running it

```bash
bash download_test_data.sh            # tables only
python -m depictio.dev_scripts.multiqc_reprocess --src <dest> --dest <dest>/multiqc/multiqc_data
depictio-cli run --template nf-core/rnasplice/1.0.4 --data-root <dest> \
  --var METADATA_FILE=<dest>/input/metadata.tsv --var GENOME=hg19
```
