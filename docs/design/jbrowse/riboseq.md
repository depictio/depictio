# Genome browser in nf-core/riboseq 2.0.0

The `ORF discovery` tab carries a genome browser beside the pooled ORF table and its record
card: the coverage and P-sites of the libraries in view, framed on the ORF picked in the table.
Template `nf-core/riboseq/2.0.0`, recipe `riboseq/recipes/tracks.py`, collection `tracks`.

One change outside the new files: `riboseq/recipes/orf_overlap.py` gained three columns
(`chrom`, `orf_start`, `orf_end`). The ORF tables carry a contig and a strand but no start or
end (the ORF key `<chrom>:<strand>:<stop>` encodes the stop codon only), and the browser needs
a span to frame. The columns are read off that key and the protein length (3 bases per amino
acid, upstream of the stop on its strand), so the span is approximate: an ORF split over exons
covers more of the genome than that. The padding of the tile (300 bases) absorbs short introns,
not long ones.

## Tab map

| Tab | Question | Tiles | What drives the browser |
|---|---|---|---|
| Overview | The run in numbers | cards, findings, links | not in this tab |
| MultiQC | Did the reads survive trimming, rRNA removal and alignment? | MultiQC panels | not in this tab |
| Ribo-seq QC | Do the footprints come from translating ribosomes? | periodicity, frame, metagene | not in this tab |
| Sample space | Do the libraries separate by assay first, then by design? | PCA, library rows | not in this tab |
| Translational efficiency | Which genes carry more ribosomes than their mRNA level predicts? | TE plane, gene detail | not in this tab |
| Translational regulation | Which genes change translation between conditions, and through which mode? | anota2seq plane, gene detail | not in this tab |
| **ORF discovery** | Which ORFs are translated, and do Ribo-TISH and RiboCode agree? | ORF cards, classes per library, caller UpSet, **ORF detail (collapsed): pooled table, record card and genome browser**, calls per library | the ORF row picked in the pooled table (`locus_from`: `orf_overlap`, `chrom` and `orf_start` to `orf_end`), the libraries picked in the left panel (their tracks), a click on a track (picks its library back) |

The "why here" sits in the description of the `ORF detail` section: the pooled ORFs, the
record of the one picked and its footprints on the genome. The tab's intro is unchanged.

## Tracks

Paths are relative to the results folder (`TRACKS_URI`, or `DATA_ROOT` when the files are
uploaded). Coverage is stranded or not by library: the sheet's `strandedness` when it says,
else footprint libraries stranded and total mRNA unstranded (the layout the megatest has).
Where the run is read from `DATA_ROOT`, the files found there win over that guess.

| Track | Path | Format | Verified |
|---|---|---|---|
| Coverage, total mRNA | `coverage/<sample>.unstranded.bigWig` | bigWig, 100 to 140 MB | listed on the megatest bucket, magic bytes read |
| Coverage, footprints | `coverage/<sample>.forward.bigWig`, `.reverse.bigWig` | bigWig, 3 to 6 MB | listed, magic bytes read |
| P-sites, footprints | `psites/plastid/tracks/<sample>_fw.bedgraph`, `_rc.bedgraph` | plain bedGraph, 5 to 10 MB | listed, first bytes read: a `##` comment header, then `1<TAB>start<TAB>end<TAB>count` |
| Genome alignments | `alignment/star/sorted/<sample>.genome.sorted.bam` and `.bai` | BAM, 0.3 to 2 GB | listed, BGZF header read |

Left out: the transcriptome BAMs (`*.transcriptome.sorted.bam`, 6 GB, not genome tracks), the
unsorted STAR BAMs under `alignment/star/original/`, and the ORF calls: Ribo-TISH and
RiboCode write tables, not BED files, so there is no ORF track (the tile frames the picked ORF
instead).

Row order: coverage first (the first library of each assay before the second, so the first rows
put one total-mRNA and one footprint library side by side), then the P-sites, then the BAMs.
Colours are fixed per assay, the reverse strand lighter.

Assembly: the `GENOME` variable (default `hg38`, which is what the megatest was aligned to;
its Ensembl-style contig names are mapped by the preset's alias table).

Reading the run in place (megatest, `--var TRACKS_URI=...`):

```
s3://nf-core-awsmegatests/riboseq/results-11d66a3b8ae1f41f9c385af36bd431c35bf015ab
```

## Use cases

**The translation of a candidate uORF.**
1. Open `ORF discovery`, filter the ORF class to `Upstream ORF` and, if needed, the protein
   length to a few tens of amino acids.
2. Open the collapsed `ORF detail` section and click the row of an ORF reported by both
   callers (`ribotish` and `ribocode` both 1).
3. The browser jumps to the ORF. With no row picked it opens on the longest ORF
   (`sort_by: aa_length`), and the stepper walks the ORFs by length, the gene name beside the
   rank. Read the footprint coverage of a Ribo-seq library against the
   total mRNA coverage of an RNA-seq library: footprints well above what the mRNA coverage
   predicts over the ORF point to translation rather than transcription.

**Footprints against the annotated start.**
1. Filter the ORF class to `N-terminal variant`, pick one in the table.
2. Open the P-site tracks of two libraries in the track selector and check whether the
   P-sites start at the variant's first codon or at the annotated start.

**A library that does not behave.**
1. Click its coverage track: its library is picked in the left panel, and the Ribo-seq QC
   periodicity cards of that library are one tab click away.

## Limits

- The ORF span is approximate (see above), and only ORFs reported by a caller have one:
  `orf_overlap` is the table the tile frames from, so a run that skipped both callers has
  neither the tab nor the jump.
- The P-site bedGraphs are plain text read whole (5 to 10 MB per file), and Plastid writes a
  `##` header the browser has not been checked against. They come after the bigWigs for that
  reason. `--skip_plastid` removes them: a run read in place then lists tracks that do not
  exist.
- The strandedness guess for `auto` libraries follows the megatest. A total-mRNA library the
  pipeline inferred stranded lists an `.unstranded.bigWig` that was not written when read in
  place; run with the files on disk and the layout found there wins.

## Status

Recipe-tested only (`depictio/tests/recipes/test_riboseq_tracks.py`: missing files dropped,
all rows when tables-only, reads in place keeps all, ordering, strandedness, the ORF span
columns, template and `DCGenomicTracksConfig` validation). The tables-only megatest subset
holds no track file, so the browser was not run on this template.
