# nf-core/pairgenomealign 3.0.4: Depictio dashboards

This template turns the output of [nf-core/pairgenomealign](https://nf-co.re/pairgenomealign)
3.0.4 into a four-tab Depictio dashboard. pairgenomealign aligns every genome of its samplesheet
(the queries) to one target genome with LAST: `last-train` fits the scoring parameters of each
pair, `lastal` computes a many-to-one alignment and `last-split` reduces it to a one-to-one
alignment, written as MAF with a one-line identity summary and a substitution matrix beside it.
assembly-scan and `seqtk cutN` describe each query assembly. Every per-pair output is named
`<target>___<query>`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `genomes` | recipe over the collections below, plus the optional design table | query genome |
| `metadata` | the design table (`METADATA_FILE`, optional) | query genome |
| `last_split_identity` | `alignment/*.o2o.tsv` | genome pair |
| `last_split_matrix` | `alignment/*.o2o.matrix.txt` | genome pair |
| `last_train_params` | `alignment/*.train.tsv` | genome pair |
| `last_synteny_links` | `alignment/*.psl.gz` (only with `--export_aln_to psl`) | alignment |
| `assemblyscan_stats` | `assemblyscan/*.json` | query genome |
| `seqtk_cutn_gaps`, `seqtk_cutn_gap_lengths` | `cutn/*.bed` | query genome, length bin |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC row |

The MAF alignments (up to gigabytes per pair) and the merged CRAM are not read. The synteny
collection reads the PSL export instead, which carries the coordinates without the sequence. A
run without it skips that optional collection, and the dashboard import then leaves the Synteny
tab out (every tile of the tab reads that collection). To get the tab, run the pipeline with
`--export_aln_to psl` (on a finished run, `-resume` with its work directory kept reuses the
alignments) and re-run the template on the new results. Reading synteny out of the MAF files instead
would mean streaming tens of gigabytes per run for coordinates the PSL export already holds.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | design table joined into `genomes`; without it the design filter and group card show one group |
| `METADATA_ID_COL` | first column, or `sample` | design table genome-id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | design filter, glance card, genome record |
| `SKIP_ASSEMBLY_QC` | unset | set for runs with `--skip_assembly_qc`: drops the assembly statistics collection |

The pipeline samplesheet has only `sample` and `fasta`, so any grouping of the genomes comes
from a separate design table: genome id in a column named `sample` (or in the first column),
one column per factor. The bundled reference run ships one under `input/`.

## Tabs

1. **MultiQC.** The pipeline's report sections: one-to-one identity and fitted parameters per
   pair, contig length statistics and base content per assembly. The persistent glance strip
   counts query genomes, design groups, aligned bases and alignment blocks; the genome table is
   pinned as the sample sheet (genome first, then the design columns and the measures, the
   run-constant target and pair id last). The two assembly sections span the full width, one
   under the other, so every genome keeps a readable row.
2. **Assemblies.** N50, sequence count, length and gap bases per query assembly, sequence count
   against N50, and the gap length matrix: one row per assembly, log10 length bins across, the
   share of the assembly's runs of N in each bin as colour, with the mean over the assemblies on
   top and a dotted line at the common 100 bp filler.
3. **Alignment.** Identity, aligned length, K80 distance and transition bias per pair; target
   coverage against identity; the substitution spectrum heatmap and the transition bias against
   p-distance; the alignment table with the genome record beside it; and (collapsed) the
   substitution and parameter tables with the fitted gap cost against training identity. The
   scatters carry no point labels (hover names the genome); the tables leave out the target and
   pair id, the same on every row of a run.
4. **Synteny** (only with the PSL export). One ring holding the target sequences and the
   sequences of one query, one chord per long alignment, coloured by orientation, with the table
   of those alignments. The query picker always holds one genome and opens on the first.

## Selection

- The genome filters and the sample sheet select on `genome`, which the links carry to every
  per-genome and per-pair collection. The MultiQC alignment sections are reached by the pair id
  (prefix match, so the `.train` rows follow), the assembly sections by the genome id.
- The contiguity scatter selects `genome`; the coverage and saturation scatters and the alignment
  table select `query`, which narrows the genome hub and through it the other tabs.
- The genome record sits beside the alignment table and opens on the selected genome.
- Chords select their alignment (`label`), which narrows the link table.

## Methods and assumptions

- **Pair ids.** `<target>___<query>` is split on the last triple underscore; `query` is the
  samplesheet sample and the join key.
- **Coverage.** `target_aligned_pct` and `query_aligned_pct` divide the one-to-one aligned
  length (alignment columns, gaps included) by each genome's length; assembly gaps lower them
  independently of divergence.
- **Distances and spectrum.** Distances are LAST's estimates on the aligned A/C/G/T columns.
  The spectrum divides each of the 12 directed substitution counts (target base first) by all
  substitutions; the heatmap scales each column across genomes.
- **Gaps.** A genome without runs of N has an empty BED and no row in the gap collections; the
  hub reports 0 gaps for it. Gap lengths are binned four per decade on a log10 scale; the
  matrix colours each bin by its share of the genome's runs of N (`gaps_pct`), so assemblies
  with a handful and with a hundred thousand gaps share one scale.
- **Rounding.** Percentages and ratios are rounded to three decimals, LAST's distance
  estimates to three significant digits.
- **Synteny links.** Each PSL alignment becomes one link at the midpoint of its interval on each
  genome, weighted by matching bases; only the 2000 alignments with the most matches per pair
  are kept. Query sequence names get a `q:` prefix so a name shared with the target stays a
  separate arc.
- **Dot plots.** The `last-dotplot` PNGs are not shown: a template scan does not upload images.
