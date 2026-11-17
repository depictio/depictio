# nf-core/rnafusion 4.1.3: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the proteins the fusions would make. The layout follows the family rules in
`depictio/projects/nf-core/RULES.md`, with `ampliseq/2.18.0` as the reference.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the reads survive trimming and align to transcripts? |
| Fusion calls | Caller Agreement | Which fusions did the callers agree on, and how are they ranked? |
| Fusion calls | Caller Evidence | How much read support did each caller find for each fusion? |
| Fusion calls | Breakpoints | Where do the fusion partners sit, and what do the reads show? |
| Follow-up | Validation | Which calls hold up when the reads are re-aligned? |
| Follow-up | Protein Domains | Which protein domains would each fusion protein keep? |
| Follow-up | Splice Junctions | Which splice junctions do the reads support, and how strongly? |

rnafusion writes one file per tool per sample and none of them carries a sample column, so
every recipe reads the sample off the file name: each fusion and splicing table carries
`sample`, and the samplesheet links to all of them on it. The fusion is the unit of
analysis: `fusion_consensus` (the fusion-report table) is the hub every caller table is
linked to on `fusion`. The run has no design metadata, so there is no group column; the
colours are the pipeline's own vocabularies (below). Route flags are not read from
`pipeline_info/params.json`: a run that skipped a step passes the matching `SKIP_*`
variable, and the data collections of that step are pruned with the tabs and Overview tiles
that read them.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  genome and GENCODE release, callers, the caller cut-off), read from the run parameters
  and the sample sheet.
- **Pipeline**: six steps (align, call, pool, validate, annotate, splice). Each step opens
  the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Fusion calls
  (split by how many callers agree), the known fusions among them (split by the knowledge
  bases that list them), the median read support of a call and caller (with its spread) and
  the breakpoints FusionInspector validated (split by predicted protein). There is no sample
  card: the sample count sits in the run card, and a count of 1 says nothing. A sample and a
  caller-agreement filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the fusions found by two callers or more out of all fusions, the Arriba calls
  that join two chromosomes, the validated fusions that keep the reading frame, and the
  Pfam domain hits the breakpoint cuts through. Below them, four figures in two rows, each
  linking its tab: the caller UpSet beside the breakpoint chord, then the fusion allelic
  ratio balance bars (a fusion seen at several breakpoints is named by its coordinates, so
  each bar has its own row) beside the fusion protein structure. The bar of this section filters by
  sample and caller agreement.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

Two persistent filter sections sit in the collapsed left panel. `Sample filters` (the
sample) is bound to the samplesheet and narrows every tab; the declared strandedness has no
filter, since a run sets it once. The sample filters stay for cohort runs, where they
narrow every tab: which filters a run needs is not known at import, so none is hidden. `Fusion filters`
(fusion, caller agreement) is bound to `fusion_consensus` and fans a pick out to every
caller table through the `fusion` links; MultiQC and Splice Junctions carry no fusion, so
it is left off those two tabs. The `Sample sheet` section is pinned to the bottom of every
child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it (a box plot, a distribution, a ranking or a share),
then at most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, the raw FastQC quality
histograms beside fastp's filtered reads, then STAR's alignment scores beside Picard's
transcript region assignment. Collapsed: the post-trim FastQC quality scores (MultiQC
anchors the second FastQC pass as `fastqc-1`), Picard's insert size and gene body coverage,
and STAR's gene counts. The pinned sample filters narrow its panels.

**Caller Agreement.** Strip: distinct fusions (the 5' partners in most fusions ranked),
calls split by how many callers agree (a ring), the median Fusion Indication Index (its
distribution: most fusions tie at the top of the scale, which a box would draw as a line)
and the calls a knowledge base already lists (split by the bases). Then the UpSet of the
fusions each combination of callers found, its sets read from the caller flag columns by
`set_columns_pattern` so a run with another caller needs no change, and the 30 fusions
with the highest index, as bars coloured by how many callers agree. Fusions tied on the
index are ordered by the reads every caller found for them, so the bars are not in name
order; the tile reads the per-caller evidence rows, which carry the index too.
Collapsed: the consensus table. Filters: index and rank ranges, the number of knowledge
bases, the bases themselves and the 5' partner gene.

**Caller Evidence.** Strip: caller reports (one per fusion, sample and caller, a ring by
caller), their median read support (a box), the total support (split by caller) and the
median share of a fusion's reads one caller accounts for (its distribution). Then the dot
plot of read support per fusion and caller (colour: log10 reads, size: the caller's share);
a scatter of Arriba against STAR-Fusion was dropped, since the dot plot carries the same
comparison, and so were the three per-caller dot plots (Arriba by confidence, STAR-Fusion
by splice type, FusionCatcher by predicted effect), which repeated it. Collapsed: the four
tables (the per-caller evidence and each caller's calls). Filters: caller, supporting reads and caller share.

**Breakpoints.** Arriba's calls as loci. Strip: Arriba calls (split by event class), the
calls between chromosomes (a ring by Arriba confidence), the median share of the local
reads that support a call (its distribution) and the median split reads (a box). Then the
flow from the contig of the 5' partner to that of the 3' partner. Then the breakpoints and their
reads: the chord ring of the same calls beside the call record card (both w4), and the genome
browser at full width under them. Collapsed: the read support by event class (split by
confidence) and by breakpoint site (the open rows were 25 against a budget of 20). A link clicked on the ring, or a fusion picked in the left panel,
fills the record card, frames the browser on the call's 5' breakpoint (its Breakpoint view
shows both sides) and, through the `arriba_fusion_links -> tracks` link on `sample`, opens the
alignments of the sample that called it. Unpicked, the browser opens on the call the ranked
bars of Caller Agreement put first and its stepper walks the others in that order: the
`arriba_fusion_links` collection carries the fusion's index (`fii`) and a `rank_score` that
folds the index, the reads every caller found for the fusion and the call's own read weight
into one number (the browser sorts on a single column). The tracks are coloured by `sample`
(`color_by`, with `sample: auto` in `category_colors`; the manifest carries no colour, which
would win over the dashboard's palette), and the MANE Select transcripts are opened from UCSC
beside the assembly's gene track (`ucsc_tracks: [mane]`; an assembly without that track just
skips it). The section is not `display: linked`: the ring and the
browser no longer sit side by side, so there are no two heights to match. Filters: contig pair, event class and
Arriba confidence; they narrow the Arriba collection, not the chord's, which the sample and
fusion filters reach.

**Validation.** FusionInspector's re-quantified calls. Strip: validated fusions (ranked by
predicted protein), the median abundance (log10 of the fragments per million plus one, its distribution: the
values sit far above any floor, so a threshold always passed), the median share of the support that crosses the junction (its distribution) and
the median re-aligned support (a box). Then the abundance dot plot by predicted protein,
and the imbalance of the fusion allelic ratio per validated breakpoint (log2 of the 5' ratio
over the 3' one, sorted, a grey band for a two-fold balance, coloured by predicted protein)
beside the record of the picked call; the scatter of the two ratios held a handful of points. A fusion seen
at several breakpoints repeats on the axis, so its label carries the two coordinates (and
the sample when several are in view), which keeps one bar per row. Collapsed: the FusionInspector table. Filters: predicted protein and
fragments per million.

**Protein Domains.** The Pfam domains of both partners. Strip: domain hits (a ring by
partner side), the hits the breakpoint cuts through (split by predicted protein), the
median domain length (a box) and the median hit strength (its distribution). Then the
fusion protein structure (the six fusions with the most domains, partners end to end) and
the lollipop of every domain at its start position. Collapsed: the Pfam table. Filters:
partner side and predicted protein.

**Splice Junctions.** CTAT-splicing's junctions. Strip: distinct junctions (the genes
holding most ranked), the median unique read support (a box), the reads summed over every
junction (a ring by chromosome) and the median intron length (its distribution). Then the
Manhattan of junction support along the genome and the junction arcs over the busiest loci.
Collapsed: the junction table. Filters: chromosome and unique read support. Junctions are
keyed on the intron, so the fusion filters do not reach this tab. `cancer_introns` is an
optional collection no tile reads: the megatest's cancer intron file is header only.

## Routes and pruning

| Route | What changes |
|---|---|
| `SKIP_QC` | No MultiQC collection or tab. |
| `SKIP_ARRIBA` | No Arriba table, cards, flow, bars or browser calls, nor the translocation row. |
| `SKIP_STARFUSION`, `SKIP_FUSIONCATCHER` | That caller's table goes; the UpSet and the evidence read the callers the run had. |
| `SKIP_FUSIONINSPECTOR` | No Validation or Protein Domains tab, validated key figure, in-frame and domain rows, or their highlights. |
| `SKIP_CTATSPLICING` | No Splice Junctions tab. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.
`SAMPLESHEET_FILE` overrides where the samplesheet is looked for. rnafusion publishes no
bigWig, so the genome browser holds alignments only (BAM, or CRAM with `--cram`).

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. Caller
agreement runs from grey (one caller) to dark violet (three); each caller, Arriba's
confidence classes, the predicted protein (in frame, frameshift, unknown), the partner side
and Arriba's event classes (under both names the two Arriba collections give them) are
written out, with any other value coloured at import. The sample is coloured `auto`: the
genome browser colours its tracks by it. Code figures read the same map; the ranked fusion bars spread Analysis mode's groups when it has
some.

## Cross-selection

Tables select rows, and the ranked fusion bars and the allelic ratio bars select fusions; a pick becomes a dashboard filter
that narrows the other tiles of the same collection and, through the project links, the
collections downstream of it. Row selection is on `sample` in the sample sheet, `fusion` in
the consensus, evidence, caller, FusionInspector and Pfam tables, and `gene` in the junction
table and Manhattan. The validated call record follows the allelic ratio bars beside it
and waits for a pick.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of
a narrower one. Nothing is set per tab or per tile.

## Catalog modules

| Tool | Output | Read by |
|---|---|---|
| `fusionreport` | `fusions`, `caller_evidence` | Caller Agreement, Caller Evidence, Overview |
| `arriba` | `fusions`, `fusion_links` (through the template's `breakpoint_links.py`, which adds the index and the browser rank) | Breakpoints, Caller Evidence |
| `starfusion` | `fusions` | Caller Evidence |
| `fusioncatcher` | `fusion_genes` | Caller Evidence |
| `fusioninspector` | `fusions`, `protein_domains` | Validation, Protein Domains, Overview |
| `ctatsplicing` | `introns`, `cancer_introns` | Splice Junctions |

The MultiQC panels use the shared `multiqc/fastqc`, `fastp`, `star` and `picard` entries.

## Reproducing

The run does not publish its samplesheet, so fetch the one `params.json` points at.

```bash
python scripts/nfcore_megatest.py fetch --pipeline rnafusion --version 4.1.3 --dest <DATA_ROOT>
mkdir -p <DATA_ROOT>/input && curl -fsSL -o <DATA_ROOT>/input/samplesheet.csv \
  https://raw.githubusercontent.com/nf-core/test-datasets/rnafusion/testdata/human/samplesheet_valid.csv
depictio-cli ingest --template nf-core/rnafusion/4.1.3 --data-root <DATA_ROOT>
```

A run that skipped a step adds the matching variable, for example
`--var SKIP_FUSIONCATCHER=true --var SKIP_CTATSPLICING=true`. `VALIDATION_REPORT.md` next to
this file records the ingestion numbers and the discrepancies found while validating.
