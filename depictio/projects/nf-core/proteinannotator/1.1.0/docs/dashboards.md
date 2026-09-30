# nf-core/proteinannotator 1.1.0: Depictio dashboards

This template turns the output of [nf-core/proteinannotator](https://nf-co.re/proteinannotator)
into a three-tab Depictio dashboard. proteinannotator takes one protein FASTA per sample,
filters it by length (and optionally removes duplicate sequences), searches it with hmmsearch
against four HMM libraries (Pfam, FunFam, NMPFamsDB, MetagRoot), runs InterProScan, and
predicts the secondary structure of every sequence with S4PRED. The template reads each tool's
own files and joins them per residue, per domain, per protein and per sample.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `seqfu_stats` | `qc/<sample>/<sample>_{before,after}.tsv` (SeqFu) | sample and filter stage |
| `seqkit_sequences` | `qc/<sample>/<sample>.fasta`, the filtered FASTA | protein |
| `hmmer_hmmsearch_domtbl` | `domain_annotation/<db>/<sample>.domtbl.gz` | reported domain |
| `interproscan_matches` | `functional_annotation/interproscan/<sample>/<sample>.tsv` | signature match |
| `s4pred_secondary_structure` | `s4pred/<sample>/ss2/<sequence id>.ss2` | residue |
| `proteinannotator_domains` | the two tables above, joined | domain span |
| `proteinannotator_proteins` | FASTA, domains and S4PRED, joined | protein |
| `proteinannotator_residues` | FASTA, S4PRED and domains, joined | residue |
| `proteinannotator_database_coverage`, `proteinannotator_database_sets` | FASTA and domains | protein x database |
| `samples` | SeqFu statistics and the protein summary | sample |
| `metadata` | the optional design table (`METADATA_FILE`) | sample |

The raw files are read as whole lines (`*_raw` collections) and parsed by the catalog recipes
(`hmmer`, `interproscan`, `s4pred`, `seqfu`, `seqkit`, `proteinannotator`). Empty files are
normal (InterProScan writes an empty TSV for a sample with no match, hmmsearch a header-only
table) and read as no rows.

## Methods

- **Domain inclusion.** The unified domain table keeps an hmmsearch domain when its
  independent E-value is at most 0.01, HMMER's own default domain inclusion threshold
  (`--incdomE`). The pipeline's `hmmsearch_evalue_cutoff` applies per sequence, so a
  sequence that passes it can still report weak extra domains; they stay visible in the
  collapsed *hmmsearch hits* section of the Domains tab. InterProScan matches are kept as
  reported, since each member database applies its own curated cut-offs.
- **Spans.** hmmsearch domains use the envelope coordinates (`env from` / `env to`), the
  span Pfam annotates; the alignment span is kept in the hmmsearch table.
- **Coverage.** A protein's annotated share is the number of residues covered by at least one
  domain over its length; overlapping domains count a residue once. The coverage matrix does
  the same per database.
- **Best domain.** The domain with the lowest E-value names the protein (`top_domain`) and,
  per residue, colours the 3D structure (`domain` in the residue table).
- **Structure.** The pipeline predicts no 3D structure. The structure tile folds the picked
  protein from its sequence through the Depictio structure resolver (ESMFold, cached), so the
  resolver must be enabled on the server. The model's B-factor holds ESMFold's pLDDT.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | design table; enables the design filter and the design card |
| `METADATA_ID_COL` | first column | design table id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | grouping filter and glance card |
| `SKIP_INTERPROSCAN` | unset | set for runs with `--skip_interproscan`: drops the InterProScan collections |
| `SKIP_S4PRED` | unset | set for runs with `--skip_s4pred`: drops the S4PRED collections; the residue table keeps its sequence and domains |

The pipeline's samplesheet has only `id` and `fasta`, so a design is always an extra table.
The bundled reference dataset vendors one (`input/sample_metadata.tsv`, a `protein_set`
column written for the demo from the test dataset's provenance) next to the test samplesheet
(`input/samplesheet.csv`).

## Tabs

1. **Overview.** The persistent glance strip counts samples, design groups, proteins and
   residues; the sample sheet (design table and per-sample summary) is pinned and collapsed.
   Input filtering shows what the length and duplicate filter removed, the mean protein length
   and the share of proteins annotated per sample, and sequence counts before and after the
   filter. The length against annotated share scatter finds proteins mostly outside any known
   family; the protein table at the end opens a protein record beside it.
2. **Domains.** Domain counts, distinct families, spans and databases per protein. The
   protein x database heatmap shows how much of each protein each database covers, the UpSet
   plot which databases agree on which proteins. Significance against span separates whole
   families from motifs and borderline calls. The domain table opens a domain record with a
   link to its family entry; the raw hmmsearch hits are collapsed at the end.
3. **Structure.** Pick one protein in the left panel. The predicted structure is coloured by
   the best domain on each residue, and the sequence track below draws the S4PRED state, its
   probability and every domain span. Clicking a residue in 3D or brushing the track selects
   the same residues in both; hovering one highlights them in the other.

Every tab filters through the persistent sample filters; the Overview adds protein length,
annotated share and status, the Domains tab database, family, significance and span, the
Structure tab the protein, residue range and secondary structure state.
