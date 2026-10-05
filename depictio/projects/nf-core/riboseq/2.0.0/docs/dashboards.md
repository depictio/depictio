# nf-core/riboseq 2.0.0: Depictio dashboards

This template turns the output of [nf-core/riboseq](https://nf-co.re/riboseq) 2.0.0 into a
six-tab Depictio dashboard. riboseq takes paired ribosome profiling (Ribo-seq) and total RNA
(RNA-seq) libraries, removes rRNA with SortMeRNA, aligns with STAR, quantifies with Salmon,
checks footprint periodicity with riboWaltz and Ribo-TISH, calls ORFs with Ribo-TISH and
RiboCode, and tests translational regulation per contrast with anota2seq.

Data comes from the AWS megatest run
`results-11d66a3b8ae1f41f9c385af36bd431c35bf015ab`: twelve libraries (Ribo-seq and RNA-seq
pairs) from a two-condition design with one contrast.

---

## How the dashboard is built

- **One funnel, six tabs.** MultiQC, Ribo-seq QC, Sample space, Translational regulation,
  Translational efficiency, ORF discovery. Library filters (Sample scope) are pinned and
  follow every tab; each tab adds its own local filters.
- **Run at a glance** (pinned, four cards): libraries by assay, contrasts tested, genes
  quantified, P-sites assigned by riboWaltz.
- **Sample sheet** (pinned, collapsed): the samplesheet as the run saw it, plus the design
  table when `METADATA_FILE` is given.
- **Design variables.** `METADATA_FILE` (optional), `METADATA_ID_COL` and `GROUP_COL`
  follow the ampliseq convention. Without a metadata file the design table and the group
  filter are dropped; everything else renders.
- **Cross-selection.** Every entity table selects rows on its identifier (`sample` for the
  sample sheet and the riboWaltz tables, `sample_id` for the PCA table, `gene_id` for the
  regulation and efficiency tables, `orf_id` for the pooled ORF table), and the phasing plane,
  the PCA and the fold-change and efficiency planes select on the same columns. A selection
  narrows the tiles that read the same collection and those its links lead to. Each record card sits on the same row as the tile that drives it (phasing plane,
  PCA, regulation table, efficiency plane, pooled ORF table) and stays a thin rail until a
  record is picked, so the source keeps the full width.

## Tabs

| Tab | Question | Main views |
| --- | --- | --- |
| MultiQC | Did the reads survive trimming, rRNA removal and alignment? | FastQC (raw, trimmed, rRNA-filtered), SortMeRNA, STAR, Salmon, Ribo-TISH and riboWaltz panels |
| Ribo-seq QC | Do the footprints step one codon at a time and sit on coding sequence? | frame composition per region, footprint length profiles, start and stop metagene profiles, P-site region enrichment, phasing plane, library record |
| Sample space | Do libraries separate by assay first, then by design? | Salmon TPM PCA embedding, library record |
| Translational regulation | Which genes change through translation, buffering or mRNA abundance? | ribosome-bound against total mRNA fold-change plane coloured by regulatory mode, translation volcano, per-analysis volcano, gene record |
| Translational efficiency | Which genes are translated more or less than their mRNA predicts? | Ribo-seq against RNA-seq abundance plane, gene record, per-gene table |
| ORF discovery | Which ORFs are found, of which class, and do both callers agree? | ORF classes per library (stacked), caller agreement (upset), ORF record |

## Data collections

| DC | Source | Recipe |
| --- | --- | --- |
| multiqc_data | `multiqc/star/multiqc_report_data/multiqc.parquet` | MultiQC |
| samples | samplesheet | `recipes/samplesheet.py` |
| metadata (optional) | `METADATA_FILE` | none (table scan) |
| gene_counts, sample_pca | Salmon merged gene matrices | `salmon/*` via `use:` |
| ribowaltz_* (6 DCs, optional) | `psites/ribowaltz/ribowaltz_qc/*.tsv` | `ribowaltz/*` |
| anota2seq_results, anota2seq_regulation (optional) | `translational_efficiency/anota2seq/*.anota2seq.results.tsv` | `anota2seq/*` |
| translational_efficiency (optional) | `quantification/inframe_psite/gene_counts.tsv` + samplesheet | `recipes/translational_efficiency.py` |
| ribotish_orfs, ribocode_orfs (optional) | `orf_predictions/ribotish/*_pred.txt`, `orf_predictions/ribocode/*_collapsed.txt` | `ribotish/orfs.py`, `ribocode/orfs.py` |
| orf_calls, orf_overlap (optional) | the two ORF DCs | `recipes/orf_calls.py`, `recipes/orf_overlap.py` |

## Method notes

- **Regulatory mode** follows anota2seq's default selection: adjusted p below 0.15 and an
  absolute effect of at least log2(1.2), with the APV slope inside [-1, 2] for translation
  and [-2, 1] for buffering. Priority: translation, buffering, mRNA abundance (total and
  ribosome-bound both significant with the same sign), otherwise not regulated.
- **ORF key.** Ribo-TISH and RiboCode are compared on `chrom:strand:stop`, the genomic stop
  codon, so alternative start sites of one ORF collapse onto one row.
- **Translational efficiency** is log2 of Ribo-seq CPM over RNA-seq CPM, computed from the
  in-frame P-site count matrix, genes kept when both assays reach 1 CPM on average.
- **Frame 0 share** is taken on frame 0 explicitly, not the dominant frame, so a mis-set
  P-site offset shows as a low value rather than hiding behind another frame.

## Running it

```bash
bash download_test_data.sh            # tables only, about 100 MB
depictio-cli run --template nf-core/riboseq/2.0.0 --data-root <dest> \
  --var METADATA_FILE=<dest>/input/metadata.tsv
```
