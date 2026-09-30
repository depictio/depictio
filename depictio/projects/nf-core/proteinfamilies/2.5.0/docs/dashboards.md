# nf-core/proteinfamilies 2.5.0: Depictio dashboards

This template turns the output of [nf-core/proteinfamilies](https://nf-co.re/proteinfamilies)
2.5.0 into a four-tab Depictio dashboard. proteinfamilies builds protein families from a set of
amino-acid sequences: SeqFu and SeqKit check and clean the input, MMseqs2 clusters it, the
clusters above a size threshold are aligned (FAMSA or MAFFT), trimmed (ClipKIT) and modelled as
profile HMMs (hmmbuild), the models recruit further members from the input (hmmsearch), redundant
families and near-identical members are removed, the final family alignments are recomputed and
CMAPLE infers a tree per family. In update mode a sample first extends an existing family library
with the sequences its HMMs match, then builds new families from the rest.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | family (MultiQC row) |
| `sequence_stats` | `qc/<sample>/<sample>_{before,after}.tsv` (SeqFu) | sample and stage |
| `cluster_sizes` | `mmseqs/initial_clustering/<sample>_clustering_distribution_mqc.csv` | sample and cluster size |
| `families` | `family_reps/` and `update_families/family_reps/` metadata, family HMMs, full alignments | family |
| `family_members` | `family_reps/<sample>/<sample>.tsv` rosters and the full alignments | family and member |
| `family_msa` | full alignments (`full_msa/filtered/<aligner>/`, `update_families/full_msa/<aligner>/`) | family and aligned sequence |
| `family_residues` | the same alignments | family and representative residue |
| `family_trees` | `phylogeny/cmaple/<sample>/<family>.treefile` | family and tree segment |

The per-family files are read as text, one line per row (`*_raw` collections), and the recipes
rebuild each file: aligned FASTA for the alignments, the HMMER3 header for the models, Newick for
the trees. Every key comes from the file layout, `<step>/<sample>/<family>.<ext>`: the sample is
the directory, the family the file name, and a file under `update_families/` belongs to an
existing family the run extended (`origin: updated`), every other one to a family the run built
(`origin: new`).

proteinfamilies reads its samplesheet from `--input` and does not publish it, so the template
ships the test_full sheet under `input/` and reads it by default; point `METADATA_FILE` at the
sheet of another run.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `mode`, `Mode` | grouping filter and glance card |
| `SKIP_PHYLOGENETIC_INFERENCE` | unset | set for runs with `--skip_phylogenetic_inference`: drops the tree collections |

`mode` is derived by the `samples` recipe: `update` when the row names existing HMMs to extend,
else `create`. Any design column added to the sheet can replace it through `GROUP_COL`. When
`METADATA_FILE` is passed explicitly, the CLI's metadata auto-detection sets `GROUP_COL` to the
first non-id sheet column (`fasta` on a bare nf-core sheet), so pass `GROUP_COL` with it.

## Methods

- **Conservation.** For every column of a family alignment where the representative (the first
  row, as the pipeline writes it) has a residue, the score is `(1 - H / log2(20)) * occupancy`:
  `H` is the Shannon entropy of the column's residues, normalised to the 20 amino acids, and
  `occupancy` the share of members with a residue there. 1 is an invariant, gap-free column, 0 a
  column as diverse as random sequence or made of gaps. The class lane bins it: conserved (0.7
  and above), intermediate (0.4 to 0.7), variable (below 0.4). Positions are numbered along the
  ungapped representative, the numbering of a structure predicted from its sequence.
- **Identity and coverage.** For each member, identity is the share of identical residues over the
  columns where both the member and the representative have one; coverage is the share of the
  representative's residues the member aligns a residue to.
- **Seed and recruitment.** `seed_size` is the `NSEQ` of the family HMM, the sequences it was
  built from; `recruited` is the family size minus that. For an extended existing family the
  model is rebuilt from every member, so `recruited` is 0. The HMM's mean information per state
  is not reported: hmmbuild's entropy weighting pins it to a target for every family.
- **Trees.** A phylogeny collection serves one Newick file and the pipeline writes one per
  family, so each tree is laid out as a table instead: tips one slot apart in Newick order,
  internal nodes at the mean of their children, x the branch length summed from the root. A code
  figure joins the segments; once a family is clicked on the Family alignment tab it draws that
  family's tree (every family in scope, stacked, before).
- **Structure.** The 3D tile folds the representative sequence on demand through the structure
  resolver (ESMFold for a sequence without an accession) and colours it by the conservation
  score, over the representative written out one clickable letter per residue
  (`layout: structure_text`); picked residues are drawn red on both (`highlight_site`). It needs
  the resolver enabled on the server.

## Tabs

1. **MultiQC.** The family metadata table of the pipeline's report (member count and
   representative length per family). The report's SeqFu and cluster-size sections are named
   after each sample, so the template reads their source files on the next tab instead. The
   persistent glance strip counts samples (by mode), input sequences, families and family
   members; the sample sheet and the family table are pinned.
2. **Families.** Family size, representative length, members recruited beyond the seed and mean
   conservation; input sequences before and after preprocessing; the initial cluster size
   distribution on log axes; family size per sample; and every family by size against
   conservation, with the record of a lassoed family beside it.
3. **Family alignment.** One family at a time, picked by a click on the families plot (size
   against mean conservation, one point per family) that sits beside the predicted structure of
   the family's representative, written out under it. The click follows the family links to the
   alignment, residue and tree collections, so every tile shows the same family; before a click
   the aggregate tiles cover every family in scope and each protein tile opens on the largest one
   it holds. Aligned sequences, identity to the representative, residue conservation and column
   occupancy; the conservation profile along the representative; the plot and the structure side
   by side, then the sequence track and the alignment full width, linked by residue (click a
   residue on the structure or a letter of its sequence, brush the track or alignment columns);
   the member tree; the residue table. The tab-local filter narrows the alignment by identity to
   the representative.
4. **Members.** Members, identity, coverage and length; identity to the representative per
   family; every member by coverage against identity, with the record of a lassoed member beside
   it; the member table.
