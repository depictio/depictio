# nf-core/proteinannotator 1.1.0: Depictio dashboards

This template turns the output of [nf-core/proteinannotator](https://nf-co.re/proteinannotator)
into an Overview and four tabs in two groups. proteinannotator takes one protein FASTA per sample,
filters it by length (and optionally removes duplicate sequences), searches it with hmmsearch
against four HMM libraries (Pfam, FunFam, NMPFamsDB, MetagRoot), runs InterProScan, and predicts
the secondary structure of every sequence with S4PRED. The template reads each tool's own files
and joins them per residue, per domain, per protein and per sample. The family rules it follows
are in `depictio/projects/nf-core/RULES.md`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `seqfu_stats` | `qc/<sample>/<sample>_{before,after}.tsv` (SeqFu) | sample and filter stage |
| `seqkit_sequences` | `qc/<sample>/<sample>.fasta`, the filtered FASTA | protein |
| `hmmer_hmmsearch_domtbl` | `domain_annotation/<db>/<sample>.domtbl.gz` | reported domain |
| `interproscan_matches` | `functional_annotation/interproscan/<sample>/<sample>.tsv` | signature match |
| `s4pred_secondary_structure` | `s4pred/<sample>/ss2/<sequence id>.ss2` | residue |
| `proteinannotator_domains` | the hmmsearch and InterProScan tables, joined | domain span |
| `proteinannotator_proteins` | FASTA, domains and S4PRED, joined | protein |
| `proteinannotator_residues` | FASTA, S4PRED and domains, joined | residue |
| `proteinannotator_database_coverage`, `proteinannotator_database_sets` | FASTA and domains | protein x database |
| `samples` | SeqFu statistics and the protein summary | sample |
| `metadata` | the optional design table (`METADATA_FILE`) | sample |

The raw files are read as whole lines (`*_raw` collections) and parsed by the catalog recipes
(`hmmer`, `interproscan`, `s4pred`, `seqfu`, `seqkit`, `proteinannotator`). Empty files are
normal (InterProScan writes an empty TSV for a sample with no match, hmmsearch a header-only
table) and read as no rows.

**Protein ids.** The `entity` of a protein is the first word of its FASTA header, the id hmmsearch,
InterProScan and S4PRED report. Characters outside `A-Za-z0-9._+-` are turned into `_` in every
table (`GI|225038609|EFDID|719595|FULL` becomes `GI_225038609_EFDID_719595_FULL`, the spelling an
`indexed_file` sample id would have), so the S4PRED, domain, residue and protein tables, and any
structure file named after the protein, share one `entity`. The original id stays in
`seqkit_sequences.sequence_id`.

## Methods

- **Domain inclusion.** The unified domain table keeps an hmmsearch domain when its
  independent E-value is at most 0.01, HMMER's own default domain inclusion threshold
  (`--incdomE`). The pipeline's `hmmsearch_evalue_cutoff` applies per sequence, so a
  sequence that passes it can still report weak extra domains; they stay visible in the
  collapsed *hmmsearch hits* section of the Domains tab. InterProScan matches are kept as
  reported, since each member database applies its own curated cut-offs.
- **Spans.** hmmsearch domains use the envelope coordinates (`env from` / `env to`), the
  span Pfam annotates; the alignment span is kept in the hmmsearch table. The HMM span
  (`hmm_from`, `hmm_to`, `hmm_length`) travels with each domain and is what the architecture
  draws as a zigzag edge when only part of the HMM matched; it is null for InterProScan rows,
  which draw as complete matches.
- **Coverage.** A protein's annotated share is the number of residues covered by at least one
  domain over its length; overlapping domains count a residue once. The coverage matrix does
  the same per database.
- **Best domain.** The domain with the lowest E-value names the protein (`top_domain`) and,
  per residue, colours the 3D structure (`domain` in the residue table).
- **Secondary structure.** S4PRED calls helix, strand or coil per residue; `value` is the
  probability of the called state and `p_helix`, `p_strand`, `p_coil` the three probabilities.
- **Structure.** The pipeline predicts no 3D structure. The structure tile folds the picked
  protein from its sequence through the Depictio structure resolver (ESMFold, cached), which is
  **off by default**: an administrator turns it on with `DEPICTIO_STRUCTURE_RESOLVER_ENABLED=true`.
  With it off the tile shows an explanation ("Structure lookup is disabled on this server") and
  the sequence track and the other tabs are unaffected. ESMFold takes sequences of up to 400
  residues. This is an external call: the sequence is sent to the public ESM Atlas service
  (`api.esmatlas.com`, run by Meta), and the tile's info popover names the service and links to it.
  The tab's length filter has no default window, so every protein is listed; the
  structure tile of a longer one explains why it is empty, and the Longest protein card flags
  a protein above the limit.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | design table; enables the group filters, the Samples card and the design table |
| `METADATA_ID_COL` | first column | design table id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | grouping filter and Samples card breakdown |
| `SKIP_INTERPROSCAN` | unset | set for runs with `--skip_interproscan`: drops the InterProScan collections and the step that cites them |
| `SKIP_S4PRED` | unset | set for runs with `--skip_s4pred`: drops the S4PRED collections, so the Secondary structure tab, its finding and its highlight go; the residue table keeps its sequence and domains |

The pipeline's samplesheet has only `id` and `fasta`, so a design is always an extra table.
The bundled reference dataset vendors one (`input/sample_metadata.tsv`, a `protein_set`
column written for the demo from the test dataset's provenance) next to the test samplesheet
(`input/samplesheet.csv`).

The run publishes a MultiQC report, but it holds only SeqFu custom-content sections anchored by
sample name (`<sample>_before-section-plot`), so no panel can be named generically and the
template has no MultiQC tab; the SeqFu tables carry the same numbers.

## Tabs

The Overview follows the family layout (`RULES.md` section 3): hero, About and run cards, a five
step pipeline flow, four key figures with a group and sample filter bar, four findings with a
highlight each, and a link list of the tabs. The page stays at compact width; the findings
highlights sit in two rows of w3 + w5 instead of the family's w4 + w4, so the domain
architecture and the sequence track, which lay a protein out along its chain, get five of the
eight columns (the length against annotated share scatter and the state shares take three). The persistent sample filters and the collapsed
sample sheet (design table and per-sample summary) sit in the left panel and at the bottom of
every other tab.

**Data & QC**

1. **Input filtering.** *Which sequences passed the filter, and how well are they annotated?*
   Four cards: sequences removed (with the samples that lost none), protein length, residues
   kept per sample and domains per protein. A bar chart of sequences before and after the filter,
   and the length against annotated share scatter, whose picked protein opens in a record card
   beside it. The protein table is collapsed.

**Annotation**

2. **Domains.** *Which domains does each protein carry, and do the databases agree?* The
   `domain_architecture` tile draws one backbone per protein with its domains from all five
   databases, coloured by database; a click selects the protein and the span on the residue
   tables and the family on the domain table, scatter and record card beside it. The View control
   groups proteins by architecture. The protein x database heatmap and the UpSet plot show which
   databases agree, and significance against span separates families from motifs and borderline
   calls. The domain table and the raw hmmsearch hits are collapsed.
3. **Secondary structure.** *Which stretches of each protein fold as helix, strand or coil?*
   The `secondary_structure` tile shows the S4PRED ribbon of one protein over the probability of
   each state, with its segment list; a brush or a segment pick selects the residues on the
   `sequence_track` below, which also draws the domain spans. A stacked bar compares the state
   shares of the proteins. The residue table is collapsed.
4. **Structure.** *Where do the domains sit on one protein's 3D structure?* A table of the
   proteins (sample, length, annotated share, best domain) picks the protein; its structure
   (coloured by best domain, over its written sequence) and the sequence track (state,
   probability and domain spans) stand linked residue by residue. Clicking a residue in 3D, a letter of the
   sequence or brushing the track selects the same residues in all three. The residue table is
   collapsed.

Every child tab filters through the persistent sample filters plus its own left-panel filters:
protein length, annotated share and status (Input filtering); database, family, significance and
span (Domains); protein and residue window (Secondary structure); protein, length and residue
window (Structure).

## Colours

`category_colors` is declared once on the Overview: the group column (`auto`), the annotation
databases (`database`, `source` and `top_domain_database` share one palette), the S4PRED states
(`category`: Helix, Strand, Coil), the filter stage and the annotation status.

## Height budget

Open rows per tab (the collapsed sections excluded): Overview 23, Input filtering 14, Domains 20,
Secondary structure 19, Structure 14.
