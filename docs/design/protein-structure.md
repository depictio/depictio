# Protein structure, alignment and sequence tiles

**Status:** Landed with the third nf-core template lot (`molecule_3d`, `msa`, `sequence_track`,
the `residue_selection` cross-filter and the hover highlight bus). A second set of five kinds
(`hmm_logo`, `domain_architecture`, `secondary_structure`, `pae_matrix`, `ramachandran`) joins
the same two column names and the same two linking channels, with the parsers they need in
`depictio/recipes/lib/`.
**Audience:** maintainers and template authors wiring protein outputs into a dashboard.
**Related:** `docs/design/advanced-viz.md` (sections 7 to 9), `docs/indexed-files.md`,
`depictio/models/components/advanced_viz/configs.py`,
`depictio/recipes/lib/{hmm,secondary_structure,pae}.py`,
`packages/depictio-react-core/src/components/advanced_viz/{molecule,protein}/` and, for the
second set, `{logo,domains,pae,secstruct,ramachandran}/` beside them.

Structure prediction, protein annotation and protein family pipelines publish three things a
reader wants to see together: a 3D model, the alignment it was folded from or classified
against, and per-residue facts (confidence, secondary structure, domains, variants). Before this
module a dashboard could only draw those facts as lines and bars on a residue axis. The goal is a
small set of tiles that show one protein three ways and stay linked: pick a residue anywhere and
every tile moves to it, point at a residue anywhere and every tile marks it. A full molecular
viewer is out of scope (see section 7).

The second set draws what the same pipelines publish around the model: the profile HMM of a
protein family and the hits that matched it, the domain architecture of many proteins at once,
the secondary-structure probabilities behind a prediction, the predicted aligned error matrix
and the backbone torsions of the model. They are linked the same way, so a state picked in a
logo, a domain, a block of the error matrix or a point of the Ramachandran plot selects that
range in 3D, on the track and in the alignment.

## 1. Data contract

Every protein tile reads tables joined on two column names, `entity` (which protein, or which
target of a prediction) and `position` (the 1-based residue number in the structure's own
numbering). Nothing else links them: no project link, no shared collection. A residue pick
travels between tiles because their collections carry those two names.

**Structure files.** An `indexed_file` data collection with `format: pdb` or `format: mmcif`
(aliases `ent` and `cif`; `.pdb`, `.ent`, `.cif`, `.mmcif`, each optionally gzipped). One object
per entity: the sample id the scan derives is the entity id, so it must equal the `entity` value
of the residue tables. No index sidecar, the file is fetched whole. Predictors write pLDDT into
the B-factor column, which is what `color_mode: plddt` reads.

**Residue table** (one row per residue and entity):

| column | type | role |
| --- | --- | --- |
| `entity` | string | join key |
| `chain` | string | chain id, needed on complexes (numbering restarts per chain) |
| `position` | int | residue number, required |
| `residue` | string | one-letter amino acid |
| `value` | float | per-residue score (pLDDT, conservation) |
| `category` | string | per-residue class (secondary structure, domain) |

`depictio/recipes/lib/protein_structure.py` builds the first five straight from a PDB
(`RESIDUE_SCHEMA`), rescaling a 0 to 1 pLDDT to 0 to 100 when every B-factor of a model lies in
[0, 1]. `sequence_track` reads `chain` by that fixed name on a complex and stacks one strip per chain
(each on its own numbering, "All chains" by default, a select narrows it to one).

**Variant table:** `entity`, `position`, `ref_aa`, `alt_aa`, a consequence column, a label
column (a protein change), optionally a numeric column that sizes the marks.

**Domain table:** `entity`, `start`, `end`, `label` (each configurable on `sequence_track`), and
optionally `source` (the annotation database), which is read by that fixed name.

**MSA table** (`MSA_SCHEMA` in `depictio/recipes/lib/msa.py`): one row per aligned sequence,
`msa_id`, `seq_id`, `rank`, `aligned_sequence`, `identity`, `coverage`, plus the optional
`chains` layout of a multi-chain reference row (`A:1-664,B:665-1004`: each chain's first and last
residue, in concatenation order). Every row of one `msa_id` has the same length (A3M insertions
are dropped by the recipe), rank 0 is the query or reference row, and `msa_id` must equal the
`entity` value it aligns, because the tiles use it as the entity. The recipe parses
integer-coded proteinfold MSAs, A3M, Stockholm and aligned FASTA.

### Inputs of the second set

The second set reads four more inputs. Only `entity` and `position` are shared between tables;
every other column name belongs to one table, because a filter reaches every collection that has
a column of its name (a `category` shared by two tables would let a consequence filter empty the
residue table), and a filter on a column a collection lacks is skipped. That is also why the
profile table below has no `residue` column: the name belongs to the residue tables its rows are
linked to. Where each input comes from:

| input | pipeline output | parser |
| --- | --- | --- |
| profile HMM table | nf-core/proteinfamilies: the profile `hmmbuild` wrote (`<family>.hmm.gz`, and the concatenated library `<sample>.lib.gz`) and the family alignment `hmmalign` wrote (`<family>.sto.gz`, Stockholm with a `#=GC RF` line) | `read_hmm`, `reference_positions_from_stockholm` and `profile_frame` in `depictio/recipes/lib/hmm.py` |
| domain hits table | nf-core/proteinannotator: the `hmmsearch` domain table (`.domtbl.gz`) | the lot 3 `hmmer/hmmsearch_domtbl` catalog recipe, which splits the domtbl lines |
| secondary-structure table | nf-core/proteinannotator: the S4PRED prediction (`<sequence>.ss2`) | `parse_ss2` in `depictio/recipes/lib/secondary_structure.py` |
| PAE file | nf-core/proteinfold: `paes/<name>_<rank>_pae.tsv` (AlphaFold DB and ColabFold JSON are read too) | none, the file is bound as it is; `read_pae` in `depictio/recipes/lib/pae.py` reads the same formats in Python |

The parsers live in `depictio/recipes/lib/`, beside `msa.py` and `protein_structure.py`, so that
the lot 3 catalog recipes can call them instead of repeating the split. They use the standard
library and Polars only (no HMMER, no Biopython).

**Profile HMM table** (`PROFILE_SCHEMA` in `hmm.py`, built by `profile_frame`): one row per match
state and letter, sorted by `hmm_position` then `hmm_letter`. State-level values repeat on every
letter row of the state.

| column | type | role |
| --- | --- | --- |
| `entity` | string | the reference sequence the states are mapped onto (the model name when none is given); the join key |
| `position` | int, nullable | residue number of the reference at the state, null where the reference has a deletion; the join key to the other protein tiles |
| `hmm_name`, `hmm_acc` | string | the model (`NAME`, `ACC`); a table may hold several, one logo each |
| `hmm_position` | int | match state number, 1 to M: the x axis of the logo |
| `hmm_letter` | string | the letter the row's emission belongs to |
| `emission` | float | match emission probability of the letter at the state; the only column the logo's heights need |
| `height_bits` | float | letter height in bits for the mode given to `profile_frame` (default `relent_abovebg`); the tile does not read it |
| `info_bits` | float | stack height: `RE_k` for the two entropy modes, 1 for `probability` |
| `insert_prob`, `insert_length` | float | `t_k(M->I)` and `1 / (1 - t_k(I->I))` after the state, 0 after the last state; an infinite length is stored as null |
| `occupancy`, `delete_prob` | float | probability that the state is used, and one minus it |
| `consensus`, `rf`, `cs` | string | the `CONS`, `RF` and `CS` annotation characters of the state (null for `-`) |
| `map_column` | int | column of the seed alignment the state was built from (`MAP`) |

`position` comes from the `hmmalign` Stockholm file. `reference_positions_from_stockholm(text,
reference_id, model_length)` takes the match columns from the `#=GC RF` line (every RF character
outside `.~-_`; with no RF line, the columns where some row has an upper-case letter or `-`,
HMMER's convention that inserts are lower case), checks their number against the model's `LENG`,
and numbers the reference row's residues along the alignment. Insert columns are skipped but
their residues still count, so the numbering stays true to the reference sequence; a
`/start-end` suffix on the row name sets the first residue number. `reference_positions_from_map`
does the same from the model's `MAP` annotation and the aligned FASTA the model was built from,
when no Stockholm file is at hand.

**Domain hits table** (the lot 3 `hmmsearch_domtbl` recipe schema, one row per domain hit; the
target is the sequence, the query the HMM):

| column | type | role |
| --- | --- | --- |
| `entity` | string | the protein the domain was found on |
| `sample`, `source` | string | the run (file name without `.domtbl(.gz)`) and the annotation database (the directory the file sits in) |
| `label`, `accession`, `description` | string | the family: HMM name, accession and free text (`-` is null) |
| `start`, `end` | int | the envelope on the protein, 1-based inclusive: the span the domain is annotated over |
| `protein_length`, `hmm_length` | int | lengths of the protein and of the HMM |
| `domain_index`, `domain_count` | int | this domain among those of the same family on the protein |
| `seq_evalue`, `seq_score` | float | E-value and bit score of the whole sequence |
| `c_evalue`, `i_evalue`, `dom_score`, `dom_bias` | float | conditional and independent E-values, bit score and bias of the domain |
| `hmm_from`, `hmm_to` | int | the HMM states the domain aligns to |
| `ali_from`, `ali_to` | int | the residues of the alignment on the protein |
| `acc` | float | mean posterior probability of the aligned residues |
| `hmm_coverage` | float | `(hmm_to - hmm_from + 1) / hmm_length` |
| `neg_log10_evalue` | float | minus log10 of `i_evalue`, for plotting |

**Secondary-structure table** (`SS2_SCHEMA` in `secondary_structure.py`, the columns of the s4pred
catalog recipe): one row per residue line of an `.ss2` file, which is PSIPRED's VFORMAT, `position
residue state P(coil) P(helix) P(strand)` after a comment line. `parse_ss2(text, entity, sample)`
skips comment and blank lines and any line whose first field is not an integer, and sorts by
sample, entity and position. The file is named after the sequence, so the caller passes the
entity.

| column | type | role |
| --- | --- | --- |
| `entity`, `sample` | string | the protein, and the run (defaults to the entity) |
| `position`, `residue` | int, string | residue number as the file writes it (1-based) and the one-letter amino acid |
| `ss_code` | string | the called state: `H`, `E` or `C` |
| `category` | string | its name: `Helix`, `Strand`, `Coil` (null for any other code); what `sequence_track` reads |
| `value` | float | the probability of the called state: `p_helix` for `H`, `p_strand` for `E`, `p_coil` otherwise |
| `p_coil`, `p_helix`, `p_strand` | float | the three state probabilities |

`segments(states)` turns a state sequence into `(state, start, end)` runs. Several sources of one
protein (a prediction and the call from the structure) are several sets of rows of one table, told
apart by a source column that the table adds (`parse_ss2` writes none).

**PAE files.** An `indexed_file` data collection with `format: pae` (`.pae.tsv` and `.pae.json`,
each optionally gzipped; no alias). The shape is the structure files': one object per entity, the
sample id the scan derives is the entity id and must equal the `entity` value of the residue
table, no index sidecar, fetched whole by the browser through the manifest's presigned URL. The
scan strips `.pae.tsv` and `.pae.json` (with the dot), so proteinfold's `<name>_<rank>_pae.tsv` is
not shortened to the entity: name it with a `sample_regex` (section 9). The content is one
square N x N matrix of errors in angstroms, row = aligned residue, column = scored residue, and
no residue numbers (they come from the residue table, section 2). `read_pae` and the browser
parser accept:

- delimited text (the proteinfold TSV): whitespace, tab, comma or semicolon separated, an
  optional header row of names before the first row skipped;
- AlphaFold DB v3 and v4 JSON, `[{"predicted_aligned_error": [[...]], "max_predicted_aligned_error": 31.75}]`;
- ColabFold JSON, `{"predicted_aligned_error": [[...]]}` or `{"pae": [[...]]}`;
- AlphaFold DB v1 JSON, `[{"residue1": [...], "residue2": [...], "distance": [...]}]`, the matrix
  flattened into 1-based residue pairs.

A matrix that is not square, or that holds a non-numeric value, is refused with a message.

## 2. The kinds

Eight kinds in two sets. The first three, `molecule_3d`, `msa` and `sequence_track`, are described
first; the second set of five starts at [The second set](#the-second-set-five-kinds).

All three use the `none` sampling policy (`KIND_SAMPLING_POLICY`): a sampled residue table
leaves holes in the colouring and the ruler. The MSA is capped at `max_rows` in rank order
instead. All three default `selection_enabled` to `true` (`SELECTION_ON_BY_DEFAULT` in
`record_link.py` and `selection.ts`), unlike every kind outside this module. Required roles are
`position` for `molecule_3d` and `sequence_track`, `msa_id` + `seq_id` + `sequence` for `msa`.

| kind | renderer | config fields (defaults) |
| --- | --- | --- |
| `molecule_3d` | 3Dmol.js in a lazy chunk | `structure_source` (`file` \| `resolve`), `structure_dc_id` / `structure_wf_id` / `structure_dc_tag`, `entity_col` (`entity`), `uniprot_col`, `gene_col`, `sequence_col`, `taxon` (9606), `position_col` (`position`), `chain_col`, `value_col`, `category_col`, `ref_aa_col`, `alt_aa_col`, `label_col`, `color_mode` (`plddt` \| `chain` \| `spectrum` \| `value` \| `category` \| `secondary_structure` \| `residue_type` \| `hydrophobicity` \| `uniform`), `colour_scale` (Viridis when null), `representation` (`cartoon` \| `trace` \| `stick` \| `sphere` \| `surface`), `representations` (a list of the same, replaces `representation` when set), `highlight_site` (true), `spin` (false), `show_variants` (true), `show_labels` (false), `layout` (`structure` \| `structure_sequence` \| `structure_msa` \| `structure_text`), `msa_dc_id` / `msa_wf_id` / `msa_dc_tag`, `selection_enabled` (true), `follow_selection` (true) |
| `msa` | canvas `MsaPanel` | `msa_id_col` (`msa_id`), `seq_id_col` (`seq_id`), `sequence_col` (`aligned_sequence`), `rank_col` (`rank`), `identity_col` (`identity`), `color_scheme` (`clustal` \| `zappo` \| `hydrophobicity` \| `identity` \| `none`), `max_rows` (200, at most 1000), `sort_by` (`rank` \| `identity` \| `input`), `show_consensus` (true), `show_conservation` (true), `entity_col_for_selection` (`entity`), `position_col_for_selection` (`position`), `chains_col` (`chains`), `chain_col_for_selection` (`chain`), `selection_enabled` (true), `follow_selection` (true) |
| `sequence_track` | canvas `SequenceStrip` | `entity_col` (`entity`), `position_col` (`position`), `residue_col` (`residue`), `value_col`, `category_col`, `value_label`, `domains_dc_id` / `domains_wf_id` / `domains_dc_tag`, `domain_start_col` (`start`), `domain_end_col` (`end`), `domain_label_col` (`label`), `variants_dc_id` / `variants_wf_id` / `variants_dc_tag`, `variant_position_col` (`position`), `variant_label_col` (`label`), `variant_category_col` (`category`), `selection_enabled` (true), `follow_selection` (true) |

`molecule_3d` validates two combinations: `structure_source: resolve` needs one of
`uniprot_col`, `gene_col` or `sequence_col`, and `layout: structure_msa` needs `msa_dc_id` or
`msa_dc_tag`. Its bound collection is the residue or variant table that colours and marks the
model; the structure comes from the companion collection or the resolver. Variants are spheres
on the alpha carbon, sized by `value_col` when bound. The entity shown is the one the dashboard's
filters name on `entity_col`, else the reader's pick in the tile, else the first.

Colour modes that read the structure itself: `secondary_structure` paints the helix and strand
3Dmol assigns (from the file's HELIX and SHEET records, else computed from the backbone), in the
RasMol structure colours the sequence track's glyphs use, coil neutral; `residue_type` hands the
model to 3Dmol's `amino` scheme and draws no legend; `hydrophobicity` colours each residue by its
Kyte-Doolittle score on the ramp the `msa` kind's hydrophobicity scheme uses, so a residue has one
colour in both tiles. `representations` combine in one style (a cartoon or a trace, sticks,
spheres, sticks with spheres drawn as ball and stick, a surface on top); a surface alone keeps a
cartoon under it, because 3Dmol does not hover or pick a surface. `highlight_site` draws the
picked residue or range (the tile's own pick, or another tile's when following) as red ball and
stick over the representation, up to 50 residues; a longer range keeps the plain selection
sticks. `spin` starts the model turning; the view buttons (reset, spin, save as PNG) sit at the
top right of the canvas whatever the setting.

In the tile, the Style control is a multi-select over the representations (the last one cannot
be removed), and Colour by lists every mode whose inputs are bound (`value` and `category` need
their column).

`sequence_track` draws, on one 2D canvas: a ruler, the one-letter sequence (blocks when too dense
to read), a value lane, a category lane, domain spans and variant lollipops. The value lane uses
the AlphaFold confidence bands (above 90, 70 to 90, 50 to 70, below 50) when `value_label`
contains "pLDDT", else a colour scale. The category lane draws helix and strand glyphs when every
value reads as a DSSP or S4PRED class (`H`, `G`, `I`, `E`, `B`, `T`, `S`, `C`, or the words), else
categorical blocks. The `Residue width` slider (0 fits the tile, up to 24 px per residue; a view
setting, not a config field) also answers to Ctrl or Cmd + wheel, and the strips of a complex share
that width and one horizontal scroll. The domain and variant companions are fetched with the tile's filters plus a
scope filter on the entity column, so they must carry the same entity column name.

`msa` shows one alignment at a time, the one whose `msa_id` another tile or a sidebar selector
names on the entity column. A row click emits a `scatter_selection` on `seq_id_col`; a column
brush emits a `residue_selection` in the reference row's numbering (gap columns of the reference
carry no residue number). With a `chains` layout on the reference row, the brush is translated
into one chain's own numbering and the chain is named on `chain_col_for_selection`.

### Combined layouts

`molecule_3d` `layout` puts a second panel in the same tile, beside or under the structure
depending on the tile's aspect (side by side when the tile is at least 1.3 times wider than
tall), with a draggable divider (structure share 0.2 to 0.85):

- `structure_sequence`: a `SequenceStrip` of the model's own primary chain, letters and pLDDT
  read from the structure (or the bound `value_col` outside the pLDDT colour mode), variant ticks
  from the bound table. Default structure share 0.75.
- `structure_msa`: an `MsaPanel` of the `msa_dc_id` collection, filtered server-side to
  `msa_id = entity`, so only that alignment travels. The embedded panel reads the canonical MSA
  column names (`msa_id`, `seq_id`, `aligned_sequence`, `rank`, `identity`, `coverage`, `chains`),
  not the `msa` kind's config. Default structure share 0.55. Without an MSA binding the tile falls
  back to `structure`.
- `structure_text`: the model's one-letter sequence written as plain monospace text under the
  structure, every chain of the model in its own block, wrapped to the pane in lines of
  ten-letter blocks with the number of each line's first residue at its start (structure
  numbering). A letter click picks that residue exactly as a click in 3D does (a
  `residue_selection`, the red site), and zooms onto it; shift-click extends from the last pick
  to a range. Hovering a letter publishes on the highlight bus and marks the residue in 3D. The
  letters show what the rest of the dashboard says: the pick red, underlined, on a light red
  background; the bound table's variants in red; the hovered residue outlined. A pick made
  elsewhere scrolls into view when it is out of sight. The text scrolls inside its pane, one
  listener per gesture on the text area (event delegation), and a hover re-renders only the lines
  it enters and leaves. Default structure share 0.7, always stacked.

Hover and selection are shared inside the tile as between tiles. One combined tile costs one
WebGL slot and one set of chrome, which is the reason for the layout rather than two tiles.

### Compact placement

The protein tabs put the 3D tile on half the section width, about 520 px high (`w: 4, h: 5`),
beside the selector that drives it (a scatter or a lollipop whose click names one entity or one
residue range), with the sequence track and the alignment full width below and the tables
collapsed under them. At that size the tile keeps its controls behind the settings icon at
both levels: `controls_placement: popover` on the component (else the frame docks them above
the canvas, `controlsDock.ts`) and in the config (else the header strip draws them there, about
200 px of a 520 px tile). Below 560 by 440 px of body the colour legend flows its
swatches in rows in the bottom-left corner and lets the pointer through. The written sequence
wraps to the pane width, so nothing overflows sideways.

### The second set: five kinds

`hmm_logo`, `domain_architecture`, `secondary_structure`, `pae_matrix` and `ramachandran` share
the first set's rules. They use the `none` sampling policy: a sampled table leaves holes in a
profile, a ruler or a domain list. What is capped is capped by a count the config names, in table
order, never by a uniform sample (`max_hits` of `hmm_logo`, `max_proteins` and
`max_architectures` of `domain_architecture`). All five default `selection_enabled` and
`follow_selection` to `true`, are in `RESIDUE_EMITTING_KINDS` (a `record_card` linked to one
receives the pick as column filters) and export as `client_only`; `pae_matrix` and
`ramachandran`, like `molecule_3d`, have no static HTML export because they fetch a file when
they render. An HTML export or embed carries, beside the tile's own table, every table companion
its config binds with a `<base>_dc_id` (the logo's `hits_dc_id`, the sequence track's
`domains_dc_id` and `variants_dc_id`), keyed by that real id as the tile asks for it; an
`indexed_file` companion (a structure, a PAE file) is left out. Required roles are `state` + `letter` + `emission` for `hmm_logo` (with
`profile_source: msa`, `msa_id` + `seq_id` + `sequence`), `position` + `state` for
`secondary_structure`, `entity` + `start` + `end` + `label` for `domain_architecture` and
`position` for `pae_matrix` and `ramachandran`. Every other role is optional and a tile draws
without the column it lacks. Every config also inherits `controls_placement` from the base class
(see Compact placement).

| kind | renderer | config fields (defaults) |
| --- | --- | --- |
| `hmm_logo` | canvas `LogoPanel` | `profile_source` (`hmm` \| `msa`), `entity_col` (`entity`), `position_col` (`position`), `model_col` (`hmm_name`), `state_col` (`hmm_position`), `letter_col` (`hmm_letter`), `emission_col` (`emission`), `insert_prob_col` (`insert_prob`), `insert_length_col` (`insert_length`), `occupancy_col` (`occupancy`), `consensus_col` (`consensus`), `rf_col` (`rf`), `cs_col` (`cs`), `msa_id_col` (`msa_id`), `seq_id_col` (`seq_id`), `sequence_col` (`aligned_sequence`), `rank_col` (`rank`), `height_mode` (`relent_abovebg` \| `relent_all` \| `probability`), `color_scheme` (`clustal`, the `msa` kind's schemes), `show_indel_rows` (true), `show_consensus` (true), `window_start` / `window_end` (null, 1-based states), `collapse_below_ic` (null, bits), `collapse_min_run` (4), `hidden_tracks` / `collapsed_tracks` (`[]`; any of `consensus`, `insert`, `occupancy`, `hits`, `ruler`, each at most once and in one list only), `hits_dc_id` / `hits_wf_id` / `hits_dc_tag`, `hits_model_col` (`label`), `hits_entity_col` (`entity`), `hits_from_col` (`hmm_from`), `hits_to_col` (`hmm_to`), `hits_length_col` (`hmm_length`), `hits_evalue_col` (`i_evalue`), `hits_score_col` (`dom_score`), `hits_ali_from_col` (`ali_from`), `hits_ali_to_col` (`ali_to`), `hits_evalue_max` (0.01), `max_hits` (200, 1 to 2000), `selection_enabled` (true), `follow_selection` (true) |
| `domain_architecture` | canvas `DomainArchitecturePanel` | `entity_col` (`entity`), `start_col` (`start`), `end_col` (`end`), `label_col` (`label`), `protein_length_col` (`protein_length`), `hmm_from_col` (`hmm_from`), `hmm_to_col` (`hmm_to`), `hmm_length_col` (`hmm_length`), `hmm_coverage_col` (`hmm_coverage`), `evalue_col` (`i_evalue`), `source_col` (`source`), `description_col` (`description`), `accession_col` (`accession`), `view` (`proteins` \| `architectures`), `max_architectures` (15, 1 to 100), `max_proteins` (2000, 1 to 20000), `evalue_threshold`, `sources`, `scale` (`shared` \| `per_protein`), `residue_width` (0, 0 to 24), `color_by` (`label` \| `source`), `partial_coverage` (0.9), `position_col_for_selection` (`position`), `label_selection` (true), `selection_column` (null uses `label_col`), `selection_enabled` (true), `follow_selection` (true) |
| `secondary_structure` | canvas `SecondaryStructurePanel` and a Mantine segment list | `entity_col` (`entity`), `position_col` (`position`), `residue_col` (`residue`), `state_col` (`ss_code`), `source_col`, `reference_source`, `p_helix_col` (`p_helix`), `p_strand_col` (`p_strand`), `p_coil_col` (`p_coil`), `confidence_col`, `show_probabilities` (true), `show_agreement` (true), `show_segments` (true), `show_composition` (true), `show_letters` (true), `shade_confidence` (true), `show_coil_segments` (false), `residue_width` (0 fits the tile, 0 to 24), `ribbon_height` (null: a 30 px lane that grows into spare room up to 52 px; 16 to 64 is drawn exactly), `min_segment_length` (1, 1 to 50), `state_colors` (`{}`, class to CSS colour), `selection_enabled` (true), `follow_selection` (true) |
| `pae_matrix` | canvas `PaePanel` | `entity_col` (`entity`), `position_col` (`position`), `value_col`, `chain_col`, `pae_dc_id` / `pae_wf_id` / `pae_dc_tag`, `max_pae`, `colour_scale`, `brush` (`diagonal` \| `rectangle`), `show_plddt` (true), `selection_enabled` (true), `follow_selection` (true) |
| `ramachandran` | Plotly SVG `scatter` | `structure_source` (`file` \| `resolve`), `structure_dc_id` / `structure_wf_id` / `structure_dc_tag`, `uniprot_col`, `gene_col`, `sequence_col`, `taxon` (9606), `entity_col` (`entity`), `position_col` (`position`), `chain_col`, `value_col`, `category_col`, `color_mode` (`plddt` \| `residue_class` \| `secondary_structure` \| `value` \| `category` \| `chain`), `show_regions` (true), `residue_classes` (null: all four), `marker_size` (6, 2 to 20), `selection_enabled` (true), `follow_selection` (true) |

Three combinations are validated: `pae_matrix` needs `pae_dc_id` or `pae_dc_tag`, `ramachandran`
applies `molecule_3d`'s source check (`structure_source: resolve` needs one of `uniprot_col`,
`gene_col` or `sequence_col`, one helper for both), and `secondary_structure` accepts
`reference_source` only with `source_col`. The dashboard import resolves `hits_dc_tag`,
`pae_dc_tag` and `structure_dc_tag` into ids like every other `<base>_dc_tag`. Each tile shows
one entity at a time, the one the dashboard's filters name on `entity_col`, else the reader's
pick in the tile, else the entity the dashboard's protein tiles agreed to open on.

### `hmm_logo`: profile HMM logo

The sequence logo of one profile HMM, with HMMER `hmmlogo` and Skylign semantics: a stack of
letters per match state whose height is the state's information, the insert and occupancy lanes
under it, and, with a hits companion, where the hits of an `hmmsearch` land on the model. The
canvas is `logo/LogoPanel.tsx` under `HmmLogoRenderer.tsx`; the arithmetic is in the pure
modules `logo/heights.ts`, `profileModel.ts`, `hitsModel.ts`, `layout.ts` and `glyphAtlas.ts`.

**Profile source.** `profile_source: hmm` (default) reads the profile table of section 1. Heights
are always recomputed in the browser from `emission_col`, so switching the height mode costs no
fetch; `height_bits` is for other uses. A table may hold several models and the tile shows one.
`profile_source: msa` builds the profile from an MSA table (`MSA_SCHEMA`) instead, and the
binding roles switch with it. The match states are the residue columns of the reference row
(rank 0, else the lowest rank, else the first row), numbered 1 to M, and state k sits on
reference residue k. Per match column the counts are plain, with no sequence weighting and no
Dirichlet prior, so a shallow alignment overstates information:

- emission: the share of each alphabet letter among the column's residues (X and other letters
  outside the alphabet are left out);
- occupancy: the share of all rows with a residue in the column, and the delete probability is
  its complement;
- insert probability after state k: among the rows with a residue at k, the share with at least
  one residue in the columns between k and k+1 (the reference's gap columns), an estimate of
  `t_k(M->I)`; expected insert length: the mean number of inserted residues of those rows (none
  when no row inserts); both are 0 after the last state;
- consensus: the likeliest letter, upper case from 0.5; the RF lane shows the reference row's
  own letter and is labelled "Reference".

The entity of an alignment is its `msa_id`, as for the `msa` tile.

**Heights.** With `p_a` the match emission of letter `a`, `b_a` its background frequency and
`RE_k` the relative entropy of state `k` in bits (letters with `p_a = 0` are skipped):

```
RE_k = sum_a p_a * log2(p_a / b_a)

relent_all       height_a = RE_k * p_a
relent_abovebg   height_a = RE_k * p_a / A_k   if p_a > b_a, else 0     A_k = sum of p_a over p_a > b_a
probability      height_a = p_a
```

This is `hmmlogo_RelativeEntropy_all` and `hmmlogo_RelativeEntropy_above_bg` of HMMER's
`src/hmmlogo.c`, as `hmm.py::letter_heights` and `logo/heights.ts` port it. The "above
background" rule is easy to get wrong: the stack keeps the **full** `RE_k`, in which a letter
below background counts negatively, and that height is only redistributed over the letters above
background. A sum restricted to the positive terms is not what `hmmlogo` prints. The stack height
is `RE_k` for the two entropy modes and 1 for `probability`. The background is the Swiss-Prot
50.8 composition HMMER uses as its null model (`p7_AminoFrequencies`, Easel's
`esl_composition_SW50`; `BACKGROUND_AMINO`) for amino acids and 1/4 for DNA and RNA, the alphabet
being nucleic when every letter of the model is A, C, G, T or U. The two indel lanes are
`hmmlogo_IndelValues`: the insert probability after state k is `t_k(M->I)` and the expected
insert length `1 / (1 - t_k(I->I))`, both **0 at the last state M**, where no insert follows.
Occupancy is `occ[1] = t_0(M->M) + t_0(M->I)` and `occ[k] = occ[k-1] * (t_{k-1}(M->M) +
t_{k-1}(M->I)) + (1 - occ[k-1]) * t_{k-1}(D->M)`. The two implementations are pinned to each
other: `test_hmm_logo_parity.py` parses `BACKGROUND_AMINO` out of `heights.ts` and recomputes the
JSON fixture `logo/__fixtures__/heights.json` with the Python, and `heights.test.ts` asserts the
same fixture.

**Reference positions.** The ruler shows the HMM state numbers above the reference residue
numbers. They drift apart at every insertion and deletion, which is why `position` is a column of
the profile table and is null where the reference has a deletion. It is filled by the mapping from
the Stockholm `RF` line described in section 1, and it is what turns a brush on states into a
residue range other tiles can follow.

**Hits companion** (the "HMM hit coverage" lane). An optional domain hit table, in the hmmer
`hmmsearch_domtbl` schema or any table with a model, a protein and an HMM span. It is fetched with
the tile's filters minus every `residue_selection` (the hits keep their rows), scoped to
`hits_model_col` equal to the model shown. Hits above `hits_evalue_max` are dropped (a hit with no
E-value is kept) and the lane draws the best `max_hits` by score. The coverage area counts every
hit under the threshold; the bars are packed greedily (first fit, best hits first, one state of
clearance) and coloured by -log10 E-value on a ramp from the theme's primary colour. A hit that
stops short of the model gets Pfam-style jagged ends (`hmm_from > 1` on the left, `hmm_to <
hmm_length` on the right, the table's `hmm_length` else the profile's length). The hits of the
protein a pick names on `hits_entity_col` are ringed, those of a protein hovered elsewhere
outlined.

`show_indel_rows` hides the insert and occupancy lanes, `show_consensus` the consensus, RF and CS
rows, and a null `*_col` drops its lane. The tile also offers the model (or alignment) picker, the
height mode, the colour scheme, the state width (fit, or a pixel width), occupancy or deletion
bars, the E-value threshold and the maximum hit count.

**Hiding parts of a long profile.** Three ways, none on by default, all tile controls seeded from
the config. A position window (`window_start`, `window_end`, 1-based state numbers, either side
open) leaves the states outside it undrawn. `collapse_below_ic` folds every run of at least
`collapse_min_run` states whose information (the relative entropy the tooltip reports, whatever
the height mode) is under that many bits into a 14 px hatched stub labelled with its state count
when the logo lane is tall enough; a click on a stub opens that run for the session, and "Fold
opened runs again" closes them. "Hide selection" folds the states of the shaded residue range the
same way (a click opens it), and "Show all" clears the window, the threshold and every fold. The
layout is the pure `logo/collapse.ts`: it plans the segments from the window, the runs and the
hidden ranges, places them at the state width (the "Fit" width leaves the stubs their own width,
and a wheel zoom does not scale them) and maps a column to its pixel and back. Everything that
leaves the tile stays in the original coordinates: a brush that crosses a stub covers the hidden
states too, so the residue range it emits, the hover and the highlight keep following the
structure and the sequence tracks, and a hit bar runs over a stub. The insert, occupancy,
coverage and consensus lanes fold with the stacks. The hand-hidden ranges and the opened runs are
not saved; the window and the threshold are.

**Hiding tracks (the height of the panel).** The parts above fold the profile along its length;
tracks fold it along its height. The panel draws five tracks under the logo stacks: `consensus`
(consensus, RF and CS rows), `insert` (insert probability and length strips), `occupancy` (the
occupancy or deletion bars), `hits` (the coverage area and the hit bars) and `ruler`. The
stacks are never hidden. `hidden_tracks` removes a track, `collapsed_tracks` reduces it to a 10 px
strip that keeps its name (the hits strip also keeps a tiny coverage summary), and the logo takes
the room either frees; a track listed in both is rejected, and the tile's "Shown tracks" picker
keeps the two lists apart (hiding a collapsed track drops it from the collapsed one). Every
track has a chevron button in the label gutter ("Collapse track" / "Expand track") and the
"Tracks" control group offers "Collapse all tracks" and "Expand all tracks"; all of it is saved
with the tile controls. One pure vertical stack (`logo/tracks.ts`, applied by
`layoutLanes`) drives the drawing, the hit testing of the bars, the hover and the natural height
of the tile, so a hidden or collapsed track also lowers the height autofit asks for. The number of
hit bars drawn is still `max_hits` (the "Max hits" control of the Hits group), further limited by
the room the hits block may take.

**Lanes**, top to bottom: the logo (y axis in bits, or probability, scaled to the tallest stack of
the model so that scrolling never rescales it), the consensus (coloured, lower case dimmed), RF
and CS when the model has them, insert probability and expected insert length as heat strips
(values written from 24 px per state), occupancy bars, the hit coverage area and the packed hit
bars, and the ruler. The tooltip gives the state, its reference residue, the likeliest letters
with their probabilities, the information in bits, the insert probability and length, the
occupancy and the annotations; over a hit, its protein, HMM span (with the missing end of a
partial hit), residues, E-value and score.

**Interactions.**

- One model at a time. The picker defaults to the first model. It follows a single model named on
  `hits_model_col` elsewhere (a domain click in `domain_architecture` names a model label, which
  is how a domain selects the logo of its family) or on `model_col`, and, when a pick names one
  protein on `entity_col` that is the reference of a model of the table, it moves to that model
  (the longest one). In msa mode it follows the entity like the `msa` tile and agrees on the
  opening alignment with the other protein tiles; in hmm mode it does not share its opening, since
  a model name claimed under the entity key would block the protein tiles' agreement.
- A drag across states emits a `residue_selection` on the profile's entity, from the smallest to
  the largest reference residue of the brushed states (nothing when they are all deletions). A
  click is a one-residue pick, a second click on it clears, a click in the gutter clears.
- A click on a hit bar picks the hit's aligned residues (`hits_ali_from_col` to
  `hits_ali_to_col`) on its own protein, with `hits_entity_col` as the entity column, so the
  structure, the sequence track and the alignment of that protein move to the hit. Hovering a bar
  publishes the same span on the highlight bus, hovering a state its reference residue.
- Incoming: a residue range on the profile's entity shades the states whose reference residue
  falls in it, a hover elsewhere draws a crosshair over those states, and the view scrolls them
  into sight.
- The logo is never narrowed by a residue pick. Its own pick is dropped
  (`filtersExcludingOwnResidue`), and so are the selection-sourced filters on the position, entity
  and model columns (in msa mode the position, entity, `msa_id` and `seq_id` columns, so that a
  row click in the alignment does not cut the profile to one sequence), before fetching
  (`withoutPositionSelections`). The profile fetch also drops every filter on the position
  column, a sidebar slider included (`withoutFiltersOn`): the logo is the whole model, and a
  slider would take states out of it.

**Performance.** One DPR-aware 2D canvas virtualised to the visible states inside a horizontal
scroll spacer (the `MsaPanel` arrangement); a pointer move or a scroll redraws through refs, at
most once per frame. Letters come from a glyph atlas: each (letter, colour) is rasterised once, at
128 px per cell (256 from device pixel ratio 2), into an offscreen sheet that doubles when full,
and each stacked letter is a scaled `drawImage` of its ink box, so it fills its share of the stack
as in Skylign. The atlas is keyed by font, DPR and colour scheme, and shared by the tiles of a
page (at most four kept). Below 6 px per state the letters become stacked colour bars. None of
this is benchmarked, as in section 8 of this document.

**Why this is a kind** (section 8 of `docs/design/advanced-viz.md`: a new set of marks and a new
interaction shape). No existing kind draws a stacked, height-encoded letter logo: `msa` draws
residues per sequence and a conservation bar, `sequence_track` one letter per residue, and a
Plotly figure would need one trace per letter and could not stretch glyphs. The logo also owns
semantics no generic chart carries: HMMER's height formulas, pinned to the Python by a parity
test; insert and occupancy values that live between columns; a ruler in two coordinate systems;
and the translation of a brush on states into a residue range of the reference.

### `domain_architecture`: domain architectures

Protein domain architectures: one row per protein, a backbone of the protein's length, and its
domain hits as rounded shapes coloured by family. The canvas is
`domains/DomainArchitecturePanel.tsx` under `DomainArchitectureRenderer.tsx`, the data model
`domains/architecture.ts`, the glyph `domains/shapes.ts`.

**Data.** The bound collection is the domain hit table of section 1 or any plain
`entity, start, end, label` table; every optional column may be absent, since the server drops a
requested column the table lacks. Every column name comes from the config. Notes on how the
columns are read:

- `protein_length`: the largest value the table states for the protein, and at least the end of
  its last domain; without the column the backbone ends at the last domain. It is read from every
  hit before filtering, so a filter never shortens a backbone.
- `hmm_coverage`: a fraction from 0 to 1; a value above 1 and up to 100 reads as a percentage.
- a hit with no label takes its accession (and `unlabelled` without one); `dom_score` is read for
  the tooltip by that fixed name and has no config role.

**Drawing.**

- *Partial matches, Pfam graphics style.* `hmm_from > 1` draws the left (N-terminal) edge as a
  zigzag, `hmm_to < hmm_length` the right one, both for a match missing both ends. When the HMM
  states cannot decide (a column unbound, or no HMM length and an intact left end), a coverage
  under `partial_coverage` marks the domain partial on a side that is not known: a dashed outline.
  The legend explains whichever of the two marks is on screen.
- *Overlaps.* Hits overlapping on one protein (two databases, nested families) are packed into
  sub-lanes inside the row, greedily in start order with inclusive ends; the backbone runs
  through the first lane, a faint guide through the others.
- *Proteins view* (`view: proteins`). Rows sorted by architecture string, then entity (natural
  order, stable). `max_proteins` caps the rows: the first in that order plus any protein picked
  elsewhere, and a badge says "N of M proteins". `scale: shared` puts every backbone on the longest
  protein's scale with a residue ruler, `per_protein` stretches each to the full width.
- *Residue width.* `residue_width` is the pixels per residue of the longest protein; 0 fits the
  tracks to the tile. Above 0 the track is `residue_width` times the longest length wide and the
  tile scrolls sideways under a fixed label column, the ruler following; Ctrl or Cmd + wheel (a
  trackpad pinch too) zooms it about the residue under the pointer, a plain wheel keeps scrolling.
  On the `per_protein` scale every backbone is that same total width, so the width still means
  pixels per residue of the longest protein and the shorter ones are stretched to match.
- *Architectures view* (`view: architectures`). The architecture of a protein is its hit labels
  in start order joined by `~` (`SH3_1~SH2~Pkinase`), after the E-value and source filters. Groups
  are ordered by count, ties by the string, and each is drawn with its median-length member (lower
  median, ties by entity) and a count pill. The groups past `max_architectures` are summarised as
  "N other architectures (M proteins)", and a disclosure triangle lists a group's proteins.
- *Colours.* A stable colour map over the colour column's whole universe, so a family keeps its
  colour while filters come and go, on the theme's categorical palette, with the dashboard's
  pinned `category_colors` laid over it. `color_by: source` colours by annotation database.
- *Legend and badges.* The 12 most frequent labels (or sources) with their hit counts, "+N more".
  Badges for proteins capped, proteins whose every hit was filtered out, rows without a protein or
  a span (skipped), a source filter with no source column, "Large table" past 50,000 rows, and
  `estimated` when the server sampled anyway.

In the tile, View and Colour by are the encoding controls; the E-value threshold (presets 1 to
1e-20), the sources, the scale, `max_architectures` and `max_proteins` are persisted controls. A
hit with no E-value passes the threshold, and a source filter is ignored, with a badge, when no
hit has a source.

**Interactions.**

- A domain click emits a `residue_selection` (entity on `entity_col`, `start` to `end` on
  `position_col_for_selection`) and, with `label_selection`, a point selection
  (`scatter_selection`) on `selection_column` (default `label_col`) holding the raw value. Several
  hits can share a label, so name a per-hit key (`domain_id`) there and as the linked record
  card's `id_col` to pick exactly one domain. Both come from one click
  handler. A table without the position column skips that half of the pair, so residue tables, the
  structure and the sequence track narrow or move, and the profile logo follows the label. A
  second click on the picked domain clears both, and so does a residue pick in another tile (the
  label is paired with the span, see §3 "Last gesture wins").
- A click on a protein name emits `residue_selection(entity, 1 to length)`; again clears.
- A click on a group (architectures view) emits a point selection on `entity_col` holding the
  group's member proteins, after clearing the residue pick; again clears.
- Hover on a domain publishes `{entity, start, end, positionColumn}` on the highlight bus.
- In: selections naming entities ring their rows (a group row stands for its members), the residue
  range in force is shaded on its protein's row, the tile's own picked domain is outlined, and a
  hover from another tile on an entity rings that row and shades its residues. A pick naming one
  protein scrolls its row (or its group) into view with `follow_selection`.
- The tile never narrows itself: before fetching it drops its own picks and every
  selection-sourced filter on `entity_col`, `label_col` and the position column. A sidebar filter
  on those columns has no source and narrows.

**Performance.** One DPR-aware canvas in a scroll spacer. Row heights vary with the sub-lanes and
are kept as prefix offsets; the visible rows are found by binary search (`rowOffsets`, `rowAt`,
`rowWindow`), so thousands of proteins scroll at the cost of the few dozen on screen. A pointer
move redraws through refs and never re-renders the tile.

**Why this is a kind** (a new set of marks and a new interaction shape). A domain list is an
interval table, which `sequence_track` already draws as one lane under one protein's sequence.
What a domain table answers that a lane does not is comparative: which proteins share an
architecture, how often, and which hits are fragments of their model. That needs the whole table
at once (every protein, grouped and counted, not one entity scoped from the dashboard), the HMM
span to draw truncation the way the community reads it, and overlap packing across databases. No
other kind groups proteins by an ordered label string, and a Plotly figure of thousands of shapes
is far slower than a virtualised canvas. It joins the module through `entity` and `position`, so a
family picked here moves the structure, the track and the alignment to it.

### `secondary_structure`: predicted helices, strands and coil

A dedicated view of one protein's secondary structure: the helices, strands, turns and coil as a
topology ribbon, the per-residue probabilities behind the call, several sources compared residue
by residue, the composition in percent and the list of segments. The canvas is
`secstruct/SecondaryStructurePanel.tsx` (with `SegmentList.tsx` and `compositionBadges.tsx`) under
`SecondaryStructureRenderer.tsx`, the model `secstruct/ssModel.ts`.

**Data.** One table with one row per residue (and per source when several are compared), joined to
the other protein tiles by `entity` and `position`. The S4PRED table of section 1 is the reference
shape. A second source is a second set of rows of the same table, told apart by `source_col` (for
example `S4PRED` rows and `structure` rows holding the DSSP states of the 3D model); a source with
no probabilities leaves those cells null. Where a source lists a position twice the first row
wins, and a position a source does not list is not drawn for it. `state_col` is read through
`secondaryStructureOf`: `H G I P` are helix, `E B` strand, `T S` turn, `C L -` coil, and the words
(`Helix`, `Strand`, `Coil`...).

**Drawing.** One DPR-aware 2D canvas virtualised to the visible window like `SequenceStrip`, with
a ruler, one-letter residues once the cells are 7 px wide, then:

- the **topology ribbon** of the main source: helix bars, strand arrows, turn bars and a coil
  line. Each residue's opacity follows its confidence (floor 0.3, five steps; a glyph is drawn
  once per step, clipped to its cells), so a helix keeps its shape while its shade varies along it.
  `confidence_col` (0 to 1; a 0 to 100 column is rescaled) sets the confidence, else it is the
  largest of the three probabilities (the probability of the call the predictor made, which is
  why the default S4PRED table needs no extra column), else the ribbon is opaque. Below one pixel
  per residue a run takes its mean opacity;
- one thin ribbon per additional source under it;
- the **agreement lane**: per residue a tall mark where the other sources do not give the main
  source's state and a short one where they all do, with the agreement percentage in the lane
  title. The comparison is Q3 (helix, strand, coil; a turn counts as coil), which is how a DSSP
  call is reduced before it is compared with a three-state predictor. The main source is
  `reference_source` when the table has it, else the first source; every other source must agree
  for a residue to count as agreeing, and a residue a source does not cover is not compared with
  it. With one other source the figure is the Q3 score; with several, the per-source figures are in
  the tooltip;
- the **probability lanes**: P(helix), P(strand) and P(coil) of the first source that has them,
  stacked to the lane height (helix at the bottom), in the glyph colours (coil in the panel's
  neutral grey). Below one pixel per residue each bin is the mean of its residues.

Around the canvas: composition badges in the frame header (percent helix, strand, coil; one
summary badge per source when several; a turn only when a source has one), a legend row and the
segment list, a Mantine `ScrollArea` of the main source's helix, strand and turn segments
("Helix 12–30 (19 aa, mean P 0.86)"; the mean is of P(state), or of the confidence for a turn),
with a switch for the coil segments and a minimum length under which a segment is left out of the
list (the ribbon still draws it). Colours come from the shared glyph fills (`SS_GLYPH_FILLS`, the
RasMol structure colours the sequence track uses) and the panel theme, unless the dashboard pins
the states: `category_colors` entries for `Helix`, `Strand`, `Turn` or `Coil` (or their codes) on
the state column or on `category` colour the glyphs, the probability lanes, the legend and the
segment list, class by class, so a state left unpinned keeps its default. The config's
`state_colors` (class to CSS colour) ranks over those pins, and the tile's Colours controls (one
Mantine colour input per drawn class, with a reset) write the same map. Agree and differ take the
theme's teal and red.

**Interactions.** A brush or a click on the canvas picks a residue range (a click on the picked
residue clears it); a click on a segment picks its range and a second click clears it. All three
emit `residueRangeFilters` (entity half and `::res` half, source `residue_selection`), so every
protein tile with the same column names follows. Hover publishes the residue on the highlight bus,
and the hover and the range of other tiles come back as a marked residue and a shaded range,
scrolled into view with `follow_selection`. The tile keeps all its rows: it drops its own pick
(`filtersExcludingOwnResidue`) and every position selection (`withoutPositionSelections`) before
fetching, and shades the range instead. Controls: entity, reference source, residue width,
ribbon height, letters, confidence shading, coil segments, minimum segment length, colours.
Ctrl or Cmd with the wheel zooms the residue width about the residue under the cursor; a plain
wheel keeps scrolling. A ribbon height that has been chosen is drawn exactly; until then the lane
is 30 px and grows into spare room up to 52 px. The last seven are persisted (`show_letters`,
`shade_confidence`, `show_coil_segments`, `residue_width`, `ribbon_height`, `min_segment_length`,
`state_colors`): a dashboard author's change is saved with the component, and each key's default
is what the tile did before it existed.

**Design choices.** The model is pure: per-source state arrays aligned on one ascending position
list, so that agreement, composition and segments are loops over arrays and the canvas reads
dense typed arrays by `position - min` in its draw loop and never parses a row.

**Why this is a kind, and not a preset of `sequence_track`** (a new set of marks and a new
interaction shape). `sequence_track` already draws a category lane as secondary-structure glyphs,
and pointing it at an S4PRED table gives the ribbon and nothing else. This view needs marks the
strip does not have (stacked probability lanes, an agreement lane) and an interaction it does not
have (a click that picks a segment, under a header of composition percentages computed from the
states). The per-source ribbons and the reference are also a data shape, several sources of one
residue table, for which the strip's single category column has no place.

**Known limits.** One chain per entity: on a complex that numbers each chain on its own, a source
listing a position twice keeps its first row (the strip's `chain` column is not read). A source
column with many distinct values draws one ribbon each. The segment list stops at 400 entries.

### `pae_matrix`: predicted aligned error

The predicted aligned error of one entity's structure as an N x N heatmap on residue axes, as
AlphaFold DB draws it. Cell (x = scored residue j, y = aligned residue i) is the expected position
error, in angstroms, of residue j when the predicted and the true structures are aligned on
residue i. A low-error block on the diagonal is a confident domain; a low-error block off the
diagonal is a confident relative placement of two domains or two chains. The canvas is
`pae/PaePanel.tsx` under `PaeMatrixRenderer.tsx`, with `pae/paeParse.ts`, `axis.ts`, `brush.ts`
and `paeImage.ts`.

**Data.** The matrix is a file, not a table: the `pae` collection of section 1, bound by
`pae_dc_id` (or `pae_dc_tag`), found in the manifest (`GET /files/indexed/{dc_id}`) and fetched
through its presigned URL, as a `molecule_3d` structure is. The bound collection is the residue
table (`entity`, `position`, optionally pLDDT on `value_col` and `chain_col`). It gives the matrix
its **index to residue mapping**: matrix index k is the k-th residue of the entity's rows,
positions ascending, and with `chain_col` the chains concatenated in the order the table first
names them (the order a predictor writes a multimer's chains in), each in its own numbering. When
the table has no rows for the entity, or a residue count other than N (a construct, a table
narrowed by a dashboard filter, a complex whose chain column is not bound), the axes fall back to
1 to N, the numbering of a single-chain prediction, carry no pLDDT, and a grey `Residues 1–N`
badge says why; picks then travel as 1 to N.

`max_pae` is the top of the colour scale in angstroms: null takes the maximum the file declares
(`max_predicted_aligned_error` or `max_pae`), else the matrix's largest value, else 31.75.
`colour_scale` names a `ColourScale` with low error at the start of the scale; null is the
theme's AlphaFold-like ramp (the theme's green for no error fading into the panel background, so
the confident blocks stand out in light and dark). `value_col` draws pLDDT as strips along both
axes in the AlphaFold confidence bands, and `show_plddt` switches them off.

**Drawing.** One DPR-aware 2D canvas. The matrix is rendered to an image once per (matrix, colour
scale, maximum, theme, size) and blitted without smoothing, so a hover or a pick redraws a blit
and a few lines. When the matrix has more residues than the plot has device pixels it is averaged
down by blocks, each pixel the mean of the residues it covers, with sizes stepped by 64 px so that
a resize does not re-render it on every pixel. Residue ticks (1-2-5 steps) on both axes, "Scored
residue" and "Aligned residue" titles, a colour bar in angstroms, chain labels and boundaries on a
complex.

**Brush semantics.** A pick is one position range on the position column (the `residue_selection`
pair, plus the chain filter on a complex), last gesture wins:

- `brush: diagonal` (default): a drag selects the smallest square on the diagonal holding the
  dragged rectangle, [a, b] x [a, b], and emits residues a to b: "select this domain". The echo
  gives the block's mean PAE.
- `brush: rectangle`, or shift-drag in diagonal mode: emits the **scored** (x) range; the aligned
  (y) range stays as a dashed outline in the tile and in its echo (`PAE of residues 80–120
  aligned on 12–40: mean 21.3 Å`) until another gesture anywhere replaces the pick.
- A click on a cell picks the scored residue, on a pLDDT strip that strip's residue; a second
  click on the picked residue clears it, and a click off the plot clears the pick.
- On a complex, a range across a chain boundary is clamped to the chain holding most of it, and
  that chain is named on `chain_col`.
- Hover draws a crosshair and a tooltip (both residues, the error, both pLDDT values and their
  bands) and publishes the scored residue (the strip's residue on a strip) on the highlight bus.
- Incoming: a residue range from any tile shades its row and column bands (the block itself keeps
  its colours) and outlines [a, b]²; an incoming hover draws crosshair lines at that residue,
  through the strips. A pick or hover naming another entity, or another position column, is
  ignored; on a complex the named chain is honoured, else the first chain holding the residue.
- The residue table is never narrowed by a residue pick or a chain pick
  (`withoutPositionSelections` on the position and chain columns), and the tile's own pick is
  dropped from its fetch. Nor is it narrowed by a sidebar filter on those two columns
  (`withoutFiltersOn`): the table numbers the axes, so a residue-range slider that keeps 71 of 172
  residues would send the axes back to 1 to N, take the pLDDT strips away and, on a protein not
  numbered from 1, emit picks at the wrong positions. A filter on any other column still narrows
  it.

Empty states: no PAE collection bound (or its tag not in the project), no PAE files in the
collection, `No PAE file for <entity>`, a file the parser refuses (with its message), and the
catalog preview or a component embed, which have no object store behind them.

**Caching.** The parsed matrix, not the text, is cached per object in `molecule/objectText.ts`
under the `pae` namespace (keyed on the URL without its query string, its own 4-object budget:
`PAE_MAX_CACHED_OBJECTS`, passed as `maxCachedObjects`, because a matrix is N x N Float32 values,
25 MB at 2500 residues, against the 24 objects a structure's text gets), so a refresh that signs a
new URL, or two tiles on the same file, parse it once. An expired URL (403) re-reads the manifest
once. Parsing runs on the main thread.

**Why this is a kind** (a new interaction shape, on a new data shape). A PAE matrix is a square,
residue-by-residue heatmap read from a per-entity file in object storage, which no existing kind
can do: `contact_map` and the heatmaps read rows from a table (an N x N matrix as a long table is
N² rows, a million for a 1000-residue protein, and the ingest would have to explode every file),
and none of them knows a residue axis, a residue pick or the highlight bus. Brushing a confident
block on the diagonal picks that domain in the structure, the sequence and the alignment beside
it, and a residue pointed at anywhere shows its row and column of confidence here. The file
contract is the one `molecule_3d` already uses, so the pipelines' native outputs are bound as
they are, with no recipe step.

### `ramachandran`: backbone torsions

The phi and psi torsions of one structure as a Ramachandran plot, a structure-quality check to sit
beside the 3D tile (proteinfold, ESMFold and AlphaFold models in particular). The angles are not
in any table: the browser computes them from the N, CA and C atoms of the model
(`molecule/backbone.ts`: `parseBackbone`, `phiPsi`, `residueClass`), from the same files and
through the same caches `molecule_3d` uses, so the two tiles on one protein share one download.

**Data.** Two inputs. The **structure** is found as `molecule_3d` finds its own (section 4):
`structure_source: file` reads the `indexed_file` collection `structure_dc_id` (pdb or mmcif, one
object per entity, sample id equal to the `entity` value), `structure_source: resolve` asks the
structure resolver with the shown entity's `uniprot_col`, `gene_col` (plus `taxon`) or
`sequence_col`. The entity shown is chosen as in `molecule_3d`, so both tiles open on the same
protein. The **bound collection** is the residue table (`entity`, `position`, optionally `chain`,
a numeric `value`, a categorical `category`); it colours the points and lists the proteins to
pick, while the plot itself needs only the structure. A row naming a chain matches that chain's
residue, a row without one the residue of that number on any chain.

`color_mode`: `plddt` is the structure's B-factor in the AlphaFold confidence bands (the same
helper as the sequence track, with the 0 to 1 scale decided once per structure);
`residue_class` colours by general, glycine, proline or pre-proline; `secondary_structure` reads
`category_col` when every value is a DSSP or S4PRED state, else classes each residue by the
favoured region it falls in (alpha-R is helix, beta is strand, alpha-L is turn, outside is coil)
and says which in the legend title; `value` is a Viridis colour bar; `category` and `chain` are
categorical, capped at twelve legend entries (the smallest groups fold into "Other (n)") with a
category keeping its colour across entities. `value` and `category` fall back to `plddt` when
their column is not bound. `residue_classes` restricts the plot to some of the four classes,
`marker_size` is the point diameter.

**Drawing.** One Plotly SVG `scatter` (never `scattergl`: the tile takes no WebGL slot), phi on x
and psi on y, both from -180 to 180 with a tick every 60 degrees, a square plot area and the
origin lines. One point per residue that has both angles, so each chain's first and last residue
and the neighbours of a chain break or a missing atom are left out (the line under the title counts
them: "12 without phi/psi"). Marker symbols follow the residue class (circle for general, triangle
for glycine, square for proline, diamond for a residue before a proline); glycine and proline come
first, as in MolProbity, and a residue counts as pre-proline only when the next residue is bonded
to it. Points are grouped by colour, one trace per group, with the general residues drawn first so
that the special classes sit on top. The tooltip gives residue and number, chain, phi and psi,
class, pLDDT (or B-factor in `file` mode outside the pLDDT colouring) and the bound value and
category.

**The regions are approximate.** `show_regions` draws hand-drawn polygons of the textbook
boundaries as one `layout.shapes` path under the points (`ramachandran/regions.ts`): alpha-R, beta
(including the polyproline II band, with its wrap across psi = +-180) and alpha-L for the general
case; a plot filtered to glycine alone gets the point-symmetric glycine set, filtered to proline
alone the narrow proline set, and any mixture the general one (pre-proline uses it too). They are
**approximate regions, not MolProbity contours**: no MolProbity or Top8000 data is used, and the
legend entry (which hides the polygons when clicked) says so. The line under the title counts the
residues inside and outside the approximate regions, each judged against its own class's set, and
says "approximate". Read it as a glance at structure quality, not as a validation.

**Interactions.** A click picks that residue (`residue_selection` on `entity_col` and
`position_col`; clicking the picked residue again clears it, shift-click extends from the last
pick); on a complex the pick also names its chain through `chainSelectionFilter`, as
`molecule_3d` does. A box or lasso picks the range from the smallest to the largest position among
the points it caught (the chain is named only when they all share one); an empty drag or a double
click clears. Hover publishes the residue on the highlight bus. An incoming range, from another
tile or this one's own pick, selects its residues through Plotly's `selectedpoints` and dims the
rest, with `selectionrevision` keyed on the range so that a range set elsewhere wins over a box the
reader drew. An incoming hover is ringed by a separate overlay trace appended after the finished
figure, so that a hover never rebuilds the points under it. The tile drops its own residue and
chain pick before fetching (`filtersForMoleculeFetch`) and never narrows its points to a range.

**Design choices.** What decides what is drawn is pure and tested in node: `torsions.ts` (backbone
to points, class filter, join of the bound rows), `regions.ts` (polygons, point-in-polygon,
counts) and `figure.ts` (Plotly data and layout from points, mode and theme tokens). The renderer
owns the theme, the hooks and the events. The structure plumbing is one hook,
`ramachandran/useStructureSource.ts`, which composes `useIndexedManifest`, `useResolvedStructure`
and `useStructureText` the way `Molecule3DRenderer` does. Symbols are per point and traces per
colour group, so that the legend says what the colour means and a one-class plot is still one
trace.

**Why this is a kind** (a new interaction shape, on points no table holds). The nearest preset
would be a `scatter_xy` bound to phi and psi columns, but no table holds them: they are computed
in the browser from a structure file, which a recipe could precompute only with a structure
library in every template and not at all for the `resolve` source. The marks are not a scatter's
either: per-class symbols, region polygons that change with the class filter, and a count of
residues inside them. And a pick is a residue, not a row: it travels as a `residue_selection` to
the 3D tile, the sequence track and the alignment, and the tile consumes theirs and their hover,
which `scatter_xy` (a row selection on a label column) does not.

**Known limits.** First model only; alternate locations use the first conformer met in a residue.
Positions with insertion codes share their number for picks. Cis-peptides and omega are not shown.
The region polygons are coarse by design (a wrapped region is two polygons, glycine is exactly
point symmetric) and pre-proline residues are judged against the general regions. A row selection
(table or lasso) on the position column of the bound table does not emphasise points. Clicking the regions' legend entry hides the polygons but leaves their alpha and beta
labels, which are annotations. The legend sits at the right of the tile, so a very wide tile
leaves a gap between the square plot and the legend.

## 3. Linking: `residue_selection` and the highlight bus

Two channels, because a pick and a hover have opposite costs.

### A pick is a filter

A residue pick is an ordinary filter pair with `source: 'residue_selection'`, built by
`residueRangeFilters` in `packages/depictio-react-core/src/selection.ts`: a `MultiSelect` on the
entity column carrying `[entity]` (index = the tile's index), and a `RangeSlider` on the
position column carrying `[start, end]`, inclusive (index suffix `::res`, as a genome region uses
`::pos`). A tile bound to a single entity omits the entity half. On a complex a third filter, a
`MultiSelect` on the chain column (suffix `::chain`), names the chain. Because these are plain
column filters, any residue or variant table with the same column names narrows with no server
change.

- **Emitters:** `molecule_3d` (click, shift-click extends the range), `sequence_track` (brush or
  click), `msa` (column brush), `lollipop` with `selection_enabled: true` (click on a stem; the
  entity column is `feature_id_col`; opt-in, default false, plus a point selection on
  `selection_column`, else `label_col`). The second set adds `hmm_logo` (a brush or click on
  states, in the reference's residues; a click on a hit bar picks the hit's aligned residues on
  the hit's own protein, with `hits_entity_col` as the entity column), `domain_architecture` (a
  click on a domain picks its span and, with `label_selection`, adds a point selection on
  `selection_column`, else `label_col`; a click on a protein name picks the whole protein; a click on an architecture
  group is a point selection on `entity_col`, not a residue pick), `secondary_structure` (a brush,
  a click, or a click on a segment), `pae_matrix` (a diagonal or rectangle brush emits the scored
  range, a click on a cell or a strip one residue) and `ramachandran` (a click, shift-click
  extends, a box or a lasso).
- **Readers:** every protein tile reads the range back by column name with
  `residueRangeFromFilters`, whatever tile or sidebar control set it. Several ranges on one
  position column intersect (they all apply server-side); an entity column carrying several
  values yields no range. `molecule_3d` rings the range and, with `follow_selection`, zooms onto a
  pick made elsewhere (its own click leaves the camera alone). `msa` shades the columns,
  `sequence_track` highlights the residues. `lollipop` and `profile` keep every row and shade the
  range (`withoutResidueRanges`): a range is a place to look, not a subset. In the second set
  `hmm_logo` shades the states whose reference residue falls in the range, `domain_architecture`
  shades it on its protein's row, `secondary_structure` on its ribbons, `pae_matrix` shades the
  row and column bands and outlines the square [a, b]², and `ramachandran` selects the points of
  those residues (Plotly's `selectedpoints`) and dims the rest. With `follow_selection`,
  `hmm_logo` and `secondary_structure` scroll the range into sight and `domain_architecture` the
  row of a picked protein.
- **Own pick:** an emitting tile drops both halves of its own selection before fetching
  (`filtersExcludingOwnResidue`), so it keeps drawing the whole protein and rings its pick. The
  second set also drops, before fetching, every selection-sourced filter on its position column
  (and, by kind, its entity, label, model or chain column: `withoutPositionSelections`), or a
  point selection from a table or another tile would narrow the profile, the domain list or the
  matrix's residue table to the picked rows. A sidebar filter on the same column has no source
  and still narrows, except where the fetch is a whole axis: the matrix's residue table and the
  logo's profile drop every filter on the position column (and the matrix's on its chain column),
  whatever its source (`withoutFiltersOn`).

**Last gesture wins.** `mergeFiltersBySource` replaces every `residue_selection` filter on the
same column when a new one arrives, whichever tile emitted it. Without that, a click on one
residue in 3D followed by a brush over another stretch in the alignment would intersect to
nothing. The whole gesture of the replaced tile goes, not only its filters on the shared column:
both halves, its `::chain` filter, and the point selection it emitted with the pick, which the
emitter marks with `pairedWithResiduePick` (`paired_with: 'residue_selection'`, ignored by the
server): the label of a `domain_architecture` domain, the point selection of a `lollipop` stem.
Otherwise a 3D click after a domain click kept the logo and the hits table on the domain's
family, and a pick after a PAE brush on a complex kept the residue tables on the brushed chain.
A pick that a move of the entity column leaves behind goes the same way. A tile's own new pick
drops its previous chain and paired selection (emitted after the pair, so a pick that has them
puts them back), or a pick on a single-chain protein after one on a complex kept the old chain.
Selections a tile makes on their own, an `msa` row or an architecture group, are unmarked and
stay, like every other tile's selections and the sidebar's controls.

**Cards and sidebar controls ignore it.** Like a genome region, a residue range is scoped out of
cards, of figures that do not encode its column, and of interactive filters' option lists, on the
client (`cardScopedFilters`) and on the server (`depictio/api/v1/region_scope.py`, both halves).
A card opts back in with `follow_region_filter: true`. A `record_card` linked to a
`molecule_3d`, `sequence_track`, `lollipop` or any kind of the second set receives the pair as
ordinary column filters and shows the rows in the range, so the `id_col` agreement check is
skipped for those sources (`RESIDUE_EMITTING_KINDS` in `record_link.py`). For the point selection
a card can link on instead, the second set emits its position column, except `domain_architecture`,
which emits its label column (`SELECTION_EMITTING_KINDS`).

### A hover is not a filter

Routing a hover through the filter list would refetch every tile on every mouse move. The
highlight bus (`packages/depictio-react-core/src/highlight/bus.ts`) is an in-memory store, one per
dashboard view, created by `HighlightProvider` in `DashboardGrid` (nest-safe: an inner provider
reuses the outer bus). An event carries `sourceIndex`, `start`, `end`, and optionally `entity`,
`chain`, `rowKeys` and `positionColumn`.

- Publishes are coalesced to one per animation frame (`requestAnimationFrame`, a 16 ms timer
  without it); the last event queued before the frame wins, and subscribers are notified only
  when it differs from the event in force.
- `usePublishHighlight(index)` binds the source; publishing `null` clears only what that tile put
  up, so one tile's pointer-leave never wipes another tile's hover.
- `useHighlight(index, enabled)` returns the event in force, `null` for the tile's own events. A
  tile that is not on a residue axis passes `enabled: false` and does not subscribe at all.
- Outside a provider (catalog preview, record panels, tests) the hook returns `null` and publish
  is a no-op.

Publishers and consumers: `molecule_3d`, `msa` and `sequence_track` both publish and consume
(translucent spheres in 3D, a crosshair in the alignment, a marked residue on the track);
`lollipop` publishes on stem hover and draws an incoming one as a dotted line, drawn over the
finished figure so a hover never rebuilds it; `profile` with
`residue_axis` draws the hovered residue as a vertical line and the picked range as a shaded band,
and publishes its own hover. `residue_axis: null` guesses from the x column name (`position`),
`true` or `false` forces it, so a coverage or fragment-length profile never re-renders on a
protein hover.

The second set publishes and consumes too. `hmm_logo` publishes the reference residue of a
hovered state, or the aligned span of a hovered hit bar on the hit's own protein, and draws an
incoming hover as a crosshair over the matching states. `domain_architecture` publishes
`{entity, start, end}` of a hovered domain, rings the row of a hovered entity and shades its
residues. `secondary_structure` publishes the hovered residue and marks an incoming one.
`pae_matrix` publishes the scored residue (the strip's residue over a pLDDT strip) and draws
crosshair lines through the strips at an incoming one. `ramachandran` publishes the hovered
residue and rings an incoming one with an overlay trace appended after the finished figure. Each
of the five ignores an event whose `positionColumn` is not its own.

## 4. Where the structure comes from

**`structure_source: file`** reads the manifest of the companion `indexed_file` collection
(`GET /depictio/api/v1/files/indexed/{dc_id}`), picks the object whose sample id equals the
entity, and fetches it through its presigned URL (15 minutes). This is the default and needs no
outbound network from the server.

**`structure_source: resolve`** asks `POST /depictio/api/v1/advanced_viz/structure/resolve` with
the shown entity's value in `uniprot_col`, `gene_col` (plus `taxon`) or `sequence_col`. The
answer is a presigned URL of a PDB in the deployment's bucket plus `source` (`afdb`, `esmfold` or
`cache`), `origin` (where the model came from, also on a cache hit), `upstream` (`{host, url}`,
scheme and host only, of the external service behind `origin`, read from the settings; null when
the origin is unknown), `accession` and the model's sequence. The browser keeps a per-session memo keyed by the normalised request.

`ramachandran` finds its structure through the same two sources, with the same hooks and caches,
so it and a `molecule_3d` tile on one protein share one download. A
`pae_matrix` fetches its matrix like a `file` structure, from its own `pae` collection, and has no
resolver path: a model folded by the resolver comes without an error matrix.

### The resolver

Order, first hit wins (`structure_resolver.py`):

1. the bucket cache, keyed by the SHA-256 of the normalised request (accession and gene upper
   cased, whitespace and a trailing `*` stripped from the sequence, taxon counted only with a
   gene);
2. `uniprot`: AlphaFold DB `/api/prediction/{accession}`, then the entry's `pdbUrl`;
3. `gene` + `taxon`: UniProt REST search (`gene_exact`, `organism_id`, `reviewed:true`, first
   result) for the accession, then AlphaFold DB as above;
4. `sequence`: ESMFold, when the sequence is at most `esmfold_max_length` residues.

Input is validated first: a UniProtKB accession pattern, a gene-symbol pattern that keeps the
value out of the UniProt query syntax, a positive taxon, the 20 standard amino-acid letters. A
sequence over the ESMFold cap with no accession or gene is a 400; with one, it is only noted as a
miss. Answers: 403 when disabled or when the caller is the anonymous visitor of a public
instance (single-user mode, whose one user is the anonymous account, is served), 400 for an
invalid request, 404 when every upstream answered
without a structure, 502 when an upstream failed (the detail names which; a failure outranks a
miss), 500 when the bucket write failed.

Limits and safety: only the hosts of the three configured URLs are contacted, redirects included
(followed by hand, at most three, each re-checked); every response is capped at `max_bytes`,
by `Content-Length` and while streaming; a body with no `ATOM` record is rejected; a 502, 503 or
504 is retried once after 2 s (ESM Atlas answers 504 while a fold warms up); each upstream call
has a `timeout_s` timeout, and one resolve request spends at most `total_timeout_s` across all its
calls and retries (a strategy reached after that fails fast with a 502), so a request cannot hold
a worker thread for minutes. Identical concurrent requests in one process wait for the first and then
read its cache entry. A hit is stored as `<cache_prefix>/<sha>.pdb` plus a `<sha>.json` sidecar
written last (the lookup reads the sidecar, so a half-written entry is a miss). Negative results
are not cached: a 404 or 502 asks the upstreams again next time.

| setting | env var | default |
| --- | --- | --- |
| `enabled` | `DEPICTIO_STRUCTURE_RESOLVER_ENABLED` | `false` |
| `afdb_base_url` | `DEPICTIO_STRUCTURE_RESOLVER_AFDB_BASE_URL` | `https://alphafold.ebi.ac.uk` |
| `uniprot_base_url` | `DEPICTIO_STRUCTURE_RESOLVER_UNIPROT_BASE_URL` | `https://rest.uniprot.org` |
| `esmfold_url` | `DEPICTIO_STRUCTURE_RESOLVER_ESMFOLD_URL` | `https://api.esmatlas.com/foldSequence/v1/pdb/` |
| `timeout_s` | `DEPICTIO_STRUCTURE_RESOLVER_TIMEOUT_S` | `60.0` |
| `total_timeout_s` | `DEPICTIO_STRUCTURE_RESOLVER_TOTAL_TIMEOUT_S` | `120.0` |
| `max_bytes` | `DEPICTIO_STRUCTURE_RESOLVER_MAX_BYTES` | `20971520` (20 MiB) |
| `esmfold_max_length` | `DEPICTIO_STRUCTURE_RESOLVER_ESMFOLD_MAX_LENGTH` | `400` |
| `cache_prefix` | `DEPICTIO_STRUCTURE_RESOLVER_CACHE_PREFIX` | `structures/resolved` |

Compose and Helm forward only `DEPICTIO_STRUCTURE_RESOLVER_ENABLED`; the other variables reach a
container only if added to the service's `environment:` (or the Helm configmap). `depictio local
up` passes every `DEPICTIO_STRUCTURE_RESOLVER_*` variable of the shell through, so
`DEPICTIO_STRUCTURE_RESOLVER_ENABLED=true depictio local up` turns it on for a local instance.

**Privacy.** When enabled, exactly the accession, the gene symbol and taxon, or the sequence
leaves the server, to EBI (AlphaFold DB), UniProt, or Meta's ESM Atlas. For unpublished
sequences that can be a disclosure, which is why the resolver is off by default and answers 403
until an operator turns it on. The route refuses anonymous visitors outside single-user mode, so
on a public instance only signed-in users trigger those calls (and fill the bucket cache); the
tile tells an anonymous visitor to sign in. The tile's info popover states the external call and
names the service from `upstream`, with links to it.

**Licence.** AlphaFold DB models are CC-BY 4.0. The tile shows a credit line with the model
(`Model: AlphaFold DB, CC-BY 4.0`, or `Model: ESMFold`), from `origin`, so a cached model keeps
its credit.

## 5. Numbering mismatch

A variant table and a structure do not always number residues the same way (a construct, an
isoform, an off-by-one in a caller). `checkVariants` (`molecule/residueData.ts`) sorts each row
into three lists:

- **drawn:** the structure has a residue at that position (on the row's chain, else the primary
  chain, else any chain) and either the row has no `ref_aa` or it matches;
- **mismatched:** the residue exists but `ref_aa` disagrees with it. The mark is not drawn; a
  "numbering mismatch" badge lists each one with the residue the model has there, and the residue
  tooltip repeats it;
- **outside:** the model has no residue at that position (a truncated model); counted in an
  "outside the model" badge.

Drawing a variant on the wrong residue is worse than not drawing it, hence the rule.

## 6. Storage origin and CSP

File-backed tiles (and resolved models) fetch presigned URLs from the storage endpoint the
browser can reach (`DEPICTIO_S3_PUBLIC_URL`, else `DEPICTIO_S3_EXTERNAL_HOST` and
`DEPICTIO_S3_EXTERNAL_PORT`). When that is another origin than the app, the browser blocks the
fetch unless the page's CSP `connect-src` allows it. This is the same path the `genome_view`
file tracks take, and the 3D tile needs nothing of its own on top of it (nor do `ramachandran`
and `pae_matrix`, which fetch structures and matrices from the same endpoint):

- The API builds its policy with `build_security_headers` (`depictio/api/v1/configs/
  security_headers.py`), which appends the origin of `settings.s3.external_url` to
  `connect-src`; `s3_connect_source` leaves it out when it equals the API's own external
  origin, already covered by `'self'`.
- The nginx viewer image serves its own policy and appends `${DEPICTIO_CSP_S3_ORIGIN}`. The
  compose files and the Helm chart (`depictio.s3CspOrigin`) derive it from the same public S3
  URL; set it on the viewer container only to override that.

The bucket also needs CORS for the viewer origin; see `docs/indexed-files.md`.

## 7. Why not embed Mol*

Mol* is the reference web viewer, and a reader doing structural analysis should use it. The tile
is not that viewer, it complements it:

- **Bundle.** 3Dmol.js loads through `import('3dmol')` into its own chunk, only when a 3D tile
  mounts. A dashboard without one never downloads it; the catalog preview and the embed build
  alias it to a stub. Mol* is a much larger application with its own UI framework.
- **Cross-filtering.** What the tile adds is the dashboard link: residue picks as filters, hover
  on the bus, colours from a Depictio table. Those need hover and click callbacks at residue level
  and styling from a per-residue function, which the narrow adapter in `molecule/viewer.ts`
  exposes. Mol*'s plugin state model would have to be driven from outside for the same result.
- **WebGL budget.** The tile takes one slot of the page-wide budget (`useWebglSlot`), like a
  `scattergl` plot or a GenomeSpy track, and releases its context on unmount.

Linking out to a full viewer for the shown entity (AlphaFold DB page, or a Mol* instance on the
same file) is future work.

## 8. Performance mechanisms

None of the following is benchmarked; they are the mechanisms, not measured gains.

- **Lazy 3Dmol chunk**, as above. A tile probes the module before fetching a structure and
  shows an explained empty state when it is the preview stub.
- **WebGL slot budget.** `useWebglSlot(true)` asks for one of the page's GL slots
  (`webglBudget.ts`). A tile that gets none says so and keeps its sequence or alignment panel;
  the CA-only parser in `structureText.ts` still gives it the sequence, numbering and pLDDT
  without a context.
- **Canvas virtualisation.** `MsaPanel` and `SequenceStrip` draw on one DPR-aware 2D canvas and
  only the rows and columns intersecting the viewport plus an overscan (`visibleWindow` in
  `protein/canvas.ts`). Letters appear only above a readable cell size.
- **No re-parse on an unchanged object.** Structure text is cached per object, keyed by the URL
  without its query string (a new presigned signature is the same object), as a shared promise so
  two tiles share one download, capped at 24 entries per namespace unless the namespace passes a
  smaller `maxCachedObjects` (the `pae` matrices do: 4) (LRU by insertion order). The viewer's
  effects run in order (load, colours, style, selection, overlays), and a filter change that
  leaves the object alone reaches none of the first three. A hover adds and removes shapes and
  never restyles the model.
- **Hover off the filter path**, coalesced per frame, as in section 3.
- **The second set** reuses the canvas helpers (`LogoPanel`, `DomainArchitecturePanel`,
  `SecondaryStructurePanel` and `PaePanel` draw on one DPR-aware 2D canvas, virtualised where the
  data is long); what each adds is under its kind in section 2: a glyph atlas, row offsets found
  by binary search, a matrix rendered to an image once and blitted, a parsed matrix cached per
  object. `ramachandran` is an SVG scatter and takes no WebGL slot.

## 9. Adding a protein tile to a template

Declare the structure collection as an `indexed_file` with `format: pdb` (or `mmcif`) and a
`sample_regex` whose result equals the `entity` value of the residue tables. A regex without a
`sample` group names the object by its named groups joined with `__`, which covers an entity
built from two path parts. Then bind the tiles, naming companion collections by tag:
`structure_dc_tag`, `msa_dc_tag`, `domains_dc_tag`, `variants_dc_tag`. The dashboard import
resolves every `<base>_dc_tag` of a config into `<base>_dc_id` and `<base>_wf_id` in the same
workflow, and clears both when the tag names no collection of the project. The seed generator
does not resolve tags, so a showcase seed binds companions by id.

```yaml
- component_type: advanced_viz
  tag: <prefix>-structure
  section: <section>
  workflow_tag: <workflow>
  data_collection_tag: <pipeline>_residues
  viz_kind: molecule_3d
  controls_placement: popover
  config:
    viz_kind: molecule_3d
    controls_placement: popover
    structure_source: file
    structure_dc_tag: <pipeline>_structures
    entity_col: entity
    position_col: position
    layout: structure_text
    msa_dc_tag: <pipeline>_msa
    color_mode: plddt
    highlight_site: true
  layout: {x: 4, y: 0, w: 4, h: 5}
- component_type: advanced_viz
  tag: <prefix>-sequence
  section: <section>
  workflow_tag: <workflow>
  data_collection_tag: <pipeline>_residues
  viz_kind: sequence_track
  config:
    viz_kind: sequence_track
    entity_col: entity
    position_col: position
    residue_col: residue
    value_col: value
    value_label: pLDDT
    category_col: category
    domains_dc_tag: <pipeline>_domains
    variants_dc_tag: <pipeline>_variants
  layout: {x: 0, y: 4, w: 8, h: 4}
```

The selector on the other half is any tile whose click leaves one value on a column named like
`entity_col` (a `scatter_xy` with one point per structure, for example): the 3D tile shows the
entity a filter names when it names exactly one, and in file mode that value must equal the
structure's indexed_file sample id.

A catalog output can carry the same bindings as a `Render` entry (`kind: molecule_3d`,
`roles: {position: position, entity: entity, ...}`), which a template consumes with `use:`. Put
the 3D tile, the sequence track and the residue table in one section, add a sidebar selector on
the entity column so the reader picks the protein, and set `residue_axis: true` on a per-residue
`profile` whose x column is not called `position`.

The second set binds the same way. `hmm_logo` names its hits by `hits_dc_tag`, `pae_matrix` its
matrix collection by `pae_dc_tag` and `ramachandran` its structures by `structure_dc_tag`, all
resolved at import like the first set's tags. The `pae` collection is an `indexed_file` with
`format: pae` whose `sample_regex` must give the `entity` value; proteinfold's
`paes/<name>_<rank>_pae.tsv` is not shortened by the default suffix rule, so it needs one.
`domain_architecture` and `secondary_structure` bind a table and need no companion. Keep `entity`
and `position` as the shared names across the tables of a tab and give every other column a name
of its own (section 1). A domain click selects the logo of its family when the logo's
`hits_model_col` is the architecture tile's `label_col`. The showcase tabs (section 11) are a
working example of each.

## 10. Testing

- **vitest** (`packages/depictio-react-core`): `highlight/bus.test.ts`,
  `selection.residue.test.ts`, `selection.proteinKinds.test.ts`,
  `selectionGroups.residue.test.ts`, `components/advanced_viz/molecule/{residueData,resolve,
  sequenceLines,splitView,structureText,viewer}.test.ts` (the written sequence's wrapping,
  numbering, marks and click-to-range; the representation, site and colour-mode mapping), `components/advanced_viz/protein/{alignment,canvas,
  rendererData,residueColours,sequence}.test.ts`, `components/advanced_viz/lollipopOverlay.test.ts`,
  plus the protein cases in `splitPanels.test.ts` (kind buckets) and
  `record_card/recordSelection.test.ts` (a residue pick reaching a record card). For the second
  set, under `components/advanced_viz/`:
  `logo/{heights,profileModel,hitsModel,layout,glyphAtlas}.test.ts` (heights against the
  Python fixture, the profile from rows and from an MSA, hit selection, packing and coverage,
  lane geometry, the atlas),
  `domains/{architecture,shapes}.test.ts` (parsing, coverage normalisation, partial flags from
  the HMM columns and from the coverage fallback, lane packing, architecture strings and grouping,
  filters, the cap, row windows; the zigzag edge vertices),
  `secstruct/ssModel.test.ts` (sources, segments, composition, Q3 agreement, confidence),
  `pae/{paeParse,paeImage,brush}.test.ts` (every file format, the colour ramps and block means,
  the axis mapping, the diagonal and rectangle gestures, chain clamping),
  `ramachandran/{torsions,regions,figure}.test.ts` (backbone to points, classes, the approximate
  polygons and their counts, the Plotly figure),
  `molecule/{backbone,objectText}.test.ts` and `protein/ssGlyphs.test.ts` (the backbone and
  object-cache code the second set shares with the 3D tile), and `utils/colorScale.test.ts`
  (every advanced-viz colour scale is sampled, none falls back to Blues).
- **pytest:** `depictio/tests/models/test_advanced_viz_protein_kinds.py`,
  `depictio/tests/models/test_record_link_residue.py`,
  `depictio/tests/models/data_collections_types/test_indexed_file.py`,
  `depictio/tests/api/v1/test_structure_resolver.py` (upstreams and bucket faked: order, cache,
  retry, timeout, size cap, redirect allowlist, validation),
  `depictio/tests/api/v1/test_security_headers.py` (the S3 origin in `connect-src`, nginx and
  API policies identical once `${DEPICTIO_CSP_S3_ORIGIN}` is rendered),
  `depictio/tests/unit/test_region_scope_residue.py`,
  `depictio/tests/cli/utils/test_indexed_file_ingest.py`,
  `depictio/tests/unit/recipes/{test_msa_lib,test_protein_structure_lib}.py` and
  `depictio/tests/cli/commands/test_local.py` (`depictio local up` passes the resolver
  settings through). For the second set,
  `depictio/tests/unit/recipes/{test_hmm_lib,test_hmm_logo_parity,test_secondary_structure_lib,
  test_pae_lib}.py` (the HMMER parser, heights, occupancy and Stockholm mapping; the logo heights
  recomputed against the TypeScript fixture; the `.ss2` parser held to the s4pred recipe schema;
  every PAE format), `depictio/tests/models/test_showcase_protein_families.py` (the committed
  fixtures against the contracts the kinds read, and each tab's column bindings against the tables
  they point at), and the `pae` cases of `test_indexed_file.py` (format, suffixes, sample id) and
  `test_indexed_file_ingest.py` (no index, entity id as sample). The kinds' registry, roles,
  validators, sampling policy and record-link tables are in `test_advanced_viz_protein_kinds.py`
  and `test_record_link_residue.py`; the export capabilities (`client_only`, no static HTML for
  `pae_matrix` and `ramachandran`) in `depictio/tests/api/v1/services/export/test_capabilities.py`
  and the table companions of an export (the logo's hits, a sequence track's domains and variants)
  in `test_embed_payload.py` beside it.
  The existing
  `depictio/tests/models/test_advanced_viz_config_alignment.py` keeps the TypeScript config
  interfaces in step with the models.
- **e2e:** `depictio/tests/e2e-playwright/tests/catalog/catalog-modules-on-dashboard.spec.ts`
  accepts
  `.depictio-molecule-3d canvas` or `[data-testid="advanced-viz-empty"]` for `molecule_3d` (a
  tile placed alone has no structure bound and CI runs with the resolver off),
  `.depictio-msa canvas` for `msa` and `.depictio-sequence-track canvas` for `sequence_track`; for
  the second set a canvas or an SVG under `.depictio-hmm-logo`, `.depictio-secondary-structure`
  and `.depictio-domain-architecture`, and, for `pae_matrix` and `ramachandran`, which fetch a
  file at render time that the catalog preview cannot serve, a canvas or an SVG or the explained
  empty state. The showcase's protein structure tab exercises the linked view end to end, and the
  two tabs of section 11 the second set.

## 11. Showcase tabs

The advanced-viz showcase (`depictio/projects/init/advanced_viz_showcase/`) carries three protein
tabs under the volcano dashboard: Protein structure (`dashboards/protein_structure.yaml`, the first
set) and, for the second set, **Protein families** (`protein_families.yaml`) and **Structure
confidence** (`protein_quality.yaml`). They share one demo protein, `demo_protein`: a ColabFold
model of 172 residues with its residue table and the 34-sequence alignment it was folded from.
Companion collections are bound by id in the YAML, since the seed generator resolves no
`*_dc_tag`; the seeds are `.db_seeds/dashboard_protein_families.json` and
`dashboard_protein_quality.json`.

**Protein families.** A text tile and then, linked on `entity` and `position`: an `hmm_logo` of the
two demo models with the hits that matched them (`hits_dc_id`; pick the model in the tile, click or
brush states to select those residues of the demo protein); a `domain_architecture` in the
proteins view beside a `molecule_3d` of the demo protein; the domain hits as a table; the
architectures view; and a left-panel section (Family, Annotation source, Domain score) that narrows
the hits and, with them, the architectures and the hit lane under the logo. The profile table reads
the demo protein as its reference, so a state picked in the logo selects that residue in 3D. The
hits table has no `position`, so the span of a domain click lands on the residue tables and the
structure and is skipped for the hits table, while the click's `label` selects the family's logo.
The other 33 proteins are members of the alignment with no structure. Six of them are fragments
whose domains match only part of the model (the zigzag edge); three loop insertions, each in three
members, make three states stand out in the insert-probability lane; and ten members also carry
one of three extra families that have no HMM, which is what gives the architectures view about six
distinct architectures.

**Structure confidence.** A text tile, then: a `pae_matrix` of the demo model beside a
`molecule_3d` with `layout: structure_text` (brush a block of the matrix diagonal and those
residues are red ball and stick in 3D and marked in the written sequence); a
`secondary_structure` comparing a synthetic S4PRED-style prediction (`reference_source: S4PRED`,
with probabilities and `confidence_col`) with the call from the structure's own geometry, with two
deliberate disagreements for the agreement lane to show; a full-width `sequence_track`; then a
`ramachandran` of the same model, coloured by pLDDT, beside a `profile` of pLDDT on the residue
axis (`residue_axis: true`), which shades a pick and marks a hover. A left-panel residue-range
slider narrows the tiles that draw a range of residues; the `pae_matrix` ignores it, since its
axes are the whole protein.
The secondary-structure table (`protein_ss_demo`) is a separate collection whose columns are named
for it (`ss_source`, `ss_code`, `ss_probability`, `p_helix`, `p_strand`, `p_coil`, no `residue`) and
shares only `entity` and `position` with the residue table, which is what carries a pick from one
tile to the others.

**The fixtures are estimated or synthetic.** None of the HMMs, hits, S4PRED calls or error
matrices is pipeline output: no HMMER, S4PRED or AlphaFold run is vendored, so
`scripts/generate_fixtures.py` (the protein families block) builds files shaped like what those
programs write, in Python, from the demo alignment and the demo structure, and every number is
seeded so that the script reproduces the committed files.

- `protein_family_demo.hmm` is a two-model HMMER3/f library (DemoFamA over residues 30 to 101,
  DemoFamB over 102 to 172) and `protein_family_demo.sto` the `hmmalign`-shaped Stockholm records.
  The models are a simple `hmmbuild`-like estimate, **not `hmmbuild`**: match columns are those
  with fewer than half gaps; Henikoff position-based sequence weights are scaled to an effective
  sequence number equal to the single-linkage clusters at 80% identity; emissions take one
  background-weighted pseudocount and transitions are counted along each row's path with a small
  prior. The alignment of the demo has no insertions and almost no truncated members, which would
  leave the insert lane and the partial edges with nothing to show, so loop insertions, fragments
  and extra domains are simulated on a copy of the rows.
- `protein_family_hits_demo.tsv` carries the domtbl columns of section 1. Coordinates come from the
  alignment; scores, E-values and posterior accuracies are synthetic, monotone in identity to the
  demo protein times the share of the HMM covered, with E-values that follow HMMER's own tail.
- `demo_protein.ss2` is PSIPRED VFORMAT, the structure-derived state blurred along the sequence and
  mixed with seeded noise, with the two disagreements; `protein_ss_demo.tsv` holds that prediction
  and the structure's own call as a second source.
- `demo_protein.pae.tsv` is a 172 x 172 matrix: low inside each confident segment, higher between
  segments and high around the low-confidence ends, clipped to 0 to 31.75.

The profile table is built by the library functions of section 1 (`reference_positions_from_stockholm`
and `profile_frame`), and the `.ss2` and PAE files are read back with `parse_ss2` and `read_pae`,
so the showcase also exercises the parsers a template would call.
`depictio/tests/models/test_showcase_protein_families.py` holds the committed files to the
contracts the kinds read.
