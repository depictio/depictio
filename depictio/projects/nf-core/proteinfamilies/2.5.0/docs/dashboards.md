# nf-core/proteinfamilies 2.5.0: Depictio dashboards

One dashboard: an **Overview**, then six child tabs in three groups, read as a funnel from the
input sequences to one family's profile model. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What does the MultiQC report say about the families? |
| Data & QC | Input & Clustering | How many sequences went in, and how did they cluster? |
| Families | Families | Which families were built, and how large and conserved? |
| Families | Members | How close are the members to their family's representative? |
| Alignment | Family alignment | How conserved is each family's representative, residue by residue? |
| Alignment | Profile HMM | What does a family's profile model look like? |

nf-core/proteinfamilies clusters protein sequences with MMseqs2, aligns each cluster that is large
enough to seed a family (FAMSA or MAFFT, trimmed with ClipKIT), builds a profile HMM from the seed
alignment (`hmmbuild`), recruits the sequences the model matches (`hmmsearch`), aligns them
(`hmmalign`), removes redundant sequences and families, and optionally infers a CMAPLE tree of each
family. A run either creates families from its input sequences or, given the HMMs and alignments of
an existing library, first matches the sequences against those families and extends them. The
template reads the MultiQC report, the SeqFu statistics of the input, the MMseqs2 cluster size
distribution, the family metadata and member rosters, the family alignments, the family HMMs, the
hmmalign alignments and the trees.

The design comes from the samplesheet (`samples`): one row per sample, with the `mode` the sheet
implies (`update` when the row names existing HMMs, else `create`), which is the default
`GROUP_COL`. Every filter starts there: the links carry a pick to every sample-level table by
`sample`, and the families table carries a pick on a family to every family-level table.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC row |
| `sequence_stats` | `qc/<sample>/<sample>_{before,after}.tsv` | sample and stage |
| `cluster_sizes` | `mmseqs/initial_clustering/*_clustering_distribution_mqc.csv` | sample and cluster size |
| `families` | `family_reps/<sample>/*_meta_mqc.csv` (and `update_families/`), with the HMM headers and alignments | family |
| `family_members` | `family_reps/<sample>/<sample>.tsv` (and `update_families/`), with the alignments | member |
| `family_msa`, `family_residues` | `full_msa/filtered/{famsa_align,mafft_align,hhsuite_reformat}/<sample>/<family>.{aln,fas}` | aligned row, residue |
| `hmm_profile` | `hmm/filtered/<sample>/<family>.hmm.gz` (and `update_families/hmm/`), with the hmmalign alignments | family, match state and letter |
| `hmmalign_hits` | `full_msa/raw/hmmer_hmmalign/<sample>/<family>.sto.gz` | family and member |
| `family_trees` | `phylogeny/cmaple/<sample>/<family>.treefile` | tree segment |

proteinfamilies reads its samplesheet from `--input` and does not publish it, so the template ships
the test_full sheet under `input/` and reads it by default; point `METADATA_FILE` at the sheet of
another run. The per-family files are laid out `<step>/<sample>/<family>.<ext>`, so every family
collection carries the sample (the directory) and the family (the file name). Families an update run
extended live under `update_families/` and carry the origin `updated`; the others are `new`.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `mode`, `Mode` | group filters, the Samples card and the group colours; any design column added to the sheet can replace `mode` |
| `SKIP_PHYLOGENETIC_INFERENCE` | unset | set for runs with `--skip_phylogenetic_inference`: drops the tree collections and the Family tree section |

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples (from the samplesheet),
  the clustering tool and identity, the aligner, the seed cluster size threshold and the recruiting
  E-value (from the run parameters).
- **Pipeline**: six steps (cluster, align, model, recruit, prune, place). Each step opens the
  parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split by
  mode), the input sequences (the box shows the spread per sample), the families (split into new
  families and existing ones the run extended) and the family members (the box shows the spread per
  family). A mode and a sample filter above them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the share of
  input sequences that stay singletons, the family and member counts with the size of the largest
  family, the median identity of a member to its representative with the share of it covered, and
  the median residue conservation. Below them, four figures in two rows: the initial cluster size
  distribution beside the family landscape, then the member scatter beside the histogram of residue
  conservation. The cluster curves and the member scatter draw one curve per sample or one point per
  member, so their highlights hide the legend. The bar of this section filters by mode and family
  origin.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (mode, sample) sit in the collapsed left panel and narrow every
tab. The `Sample sheet` and `Reference tables` (the family table) sections are pinned to the bottom
of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read the
tab), then a strip of four key numbers, each card with its own colour and a secondary that reads it,
then at most three open sections; tables and record cards follow, collapsed.

**MultiQC.** MultiQC panels only: the family metadata table of the report (members and
representative length of every family). The report holds custom content only, and the SeqFu and
cluster size sections are named after each sample, so a template cannot address them; the same
numbers are read from their source files on the next tab. The `Report scope` filter narrows the
table to selected report rows, and the pinned sample filters narrow it too.

**Input & Clustering.** Strip: the input sequences (their spread per sample), the sequences kept
after the length filter, gap removal and deduplication (the samples keeping most), the mean sequence
length (its distribution) and the share of sequences left as singleton clusters (its spread). Then
the initial cluster size distribution, one curve per sample on log axes, and the sequences before and
after preprocessing. Collapsed: the sequence statistics and the cluster size tables. Filter: the
cluster size band.

**Families.** Strip: the families (split by origin), the members per family (its spread), the
members recruited beyond the seed (the samples recruiting most) and the mean residue conservation
(its distribution). Then the family landscape, size against mean conservation with the record of the
picked family beside it, and the family size per sample. The full family table is the pinned
reference table. Filters: origin, members per family and mean conservation.

**Members.** Strip: the members (split by family origin), their identity to the representative (its
spread), the share of the representative they cover (its distribution) and their length (its
spread). Then the identity per family and the member scatter, coverage against identity, with the
record of the picked member beside it. Collapsed: the member roster. Filters: identity, coverage and
family origin.

**Family alignment.** Strip: the aligned sequences (the families with most rows), their identity to
the representative (its spread), the residue conservation (its distribution) and the column
occupancy (its spread). Then two histograms of the representative's residues, by conservation score
and by column occupancy, coloured by class; the family scatter beside the predicted structure of the
picked family's representative, coloured by conservation, with the sequence track under them; and the
alignment. The structure is folded on demand from the representative's sequence by the structure
resolver, so it needs `DEPICTIO_STRUCTURE_RESOLVER_ENABLED`; with the resolver off the tile shows its
empty state. Residues picked in the structure, on the track or by brushing alignment columns are
selected in all three. Collapsed: the maximum-likelihood tree of the family (CMAPLE, absent on a run
that skips phylogenetic inference) and the residue table. Filter: identity to the representative.

**Profile HMM.** The tab shows one family: its `Family` filter is `always_selected`, so it opens
on the first family of its list on any run, a pick replaces it and it cannot be cleared, and the
logo, the structure and the track always agree on the family. Strip, for that family: the
conservation of its representative's residues (their spread), those residues split by
conservation class, the members' identity to the representative and their length (both with
their spread). The model's own descriptors (match states, seed and effective sequences) are one
value per family: the pinned family table, narrowed to the family's row, holds them. Then the
profile logo of the family HMM, one stack of letters per match state with the insert, occupancy
and consensus lanes and, under it, the members the hmmalign alignment placed on the model; the
predicted structure of the representative, coloured by conservation class; and the
representative's sequence track. A brush on the logo selects the representative residues its
states sit on, in the structure and on the track. The states are mapped onto the residues through the hmmalign alignment of the family,
so a family an update run extended (no such alignment) draws its logo but a pick on it selects no
residue. Collapsed: the family alignment and the table of members on the model. Filter: the
family. The family scatter is not repeated here (it would draw one point); it picks families on
the Families and Family alignment tabs.

## Colours

`category_colors` is declared once on the Overview and read by every tab. The group (`mode`, create
or update) takes the palette; the family origin (`new`, `updated`) and the conservation class
(`conserved`, `intermediate`, `variable`) are pinned, so the landscape, the histograms, the track and
the structure agree; the family id takes the palette for the eight largest families, largest first.

## Conditional routes

- `SKIP_PHYLOGENETIC_INFERENCE` removes `cmaple_tree_raw` and `family_trees`; the Family tree section
  of the Family alignment tab goes with them.
- A run that did not publish the family HMMs (`hmm/`) or the hmmalign alignments (`full_msa/raw/`)
  leaves `hmm_profile` or `hmmalign_hits` empty: the logo, the hits lane and the table of members on
  the model go, and the rest of the Profile HMM tab (the strip, the structure and the track)
  stays.
- A run with no update sample has no `updated` family: the origin splits show the new families alone.
