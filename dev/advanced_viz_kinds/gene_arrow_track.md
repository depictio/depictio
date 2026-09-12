# `gene_arrow_track`

A genomic neighbourhood viewer. One horizontal lane per contig, one strand
aware arrow per coding sequence positioned by base pair, coloured by class and
optionally labelled. This is the standard gene cluster diagram used to read a
biosynthetic gene cluster, a prophage or a resistance island: the coloured core
is the called region, the grey arrows either side are the neighbourhood that
tells you what the region sits in.

## Model

- Config: `GeneArrowTrackConfig` in
  `depictio/models/components/advanced_viz/configs.py`
- Canonical roles: `CANONICAL_SCHEMAS["gene_arrow_track"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely `contig`
  (string), `feature_id` (string), `start` (numeric), `end` (numeric), `strand`
  (string)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. Half the CDSs of a
  locus is not a lower resolution locus map, it is a wrong one, so the frame is
  served whole.

Every field the model declares, and nothing else, may be read off `config` in
the renderer. The full set is `contig_col`, `feature_id_col`, `start_col`,
`end_col`, `strand_col`, `class_col`, `label_col`, `region_start_col`,
`region_end_col`, `show_labels`, `arrow_height`.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/GeneArrowTrackRenderer.tsx`

Built to the shape of `CoverageTrackRenderer`, which is the house pattern for a
base pair axis track: the same `AdvancedVizFrame` chrome (loading, error, empty,
Show data popover, Settings popover), the same `plotlyTheme` helpers, the same
Mantine hue list for categorical colour, the same `AdvancedVizPlot` wrapper. It
differs in one place: the fetch goes through the generic
`fetchAdvancedVizData` (as `MetricCiBarsRenderer` does) rather than a Celery
dispatch and poll pair, because there is no server side aggregation to do. The
renderer receives the projected role columns and draws them.

### Arrows as filled scatter rings, not layout shapes

The brief allowed either. The choice is filled scatter, for three reasons:

1. **Hover.** A Plotly `shape` has no hover and no legend entry. The whole
   question a locus map answers is "what is this arrow", so a drawing primitive
   that cannot be interrogated is the wrong one. The annotation strip in
   `CoverageTrackRenderer` gets away with shapes precisely because it is
   furniture nobody points at.
2. **Trace count.** One filled trace per *class*, with the per feature pentagons
   pushed into it as null separated rings (`fill: 'toself'` restarts the fill at
   every gap), keeps the trace count at O(classes) instead of O(features). One
   trace per feature would be a few thousand traces on a real funcscan run.
3. **Legend and theming.** A class trace gets its legend entry for free, and
   `applyDataTheme` has something to act on.

Hover then rides on a *separate* transparent marker trace, three anchors across
each arrow (15%, midpoint, 85%), carrying the per feature `customdata`.
`hoveron: 'fills'` was rejected: it reports one label for a whole multi ring
trace, not for the ring under the cursor, so every arrow in a class would say
the same thing.

### Layout

- **Lanes.** One lane per contig at integer `y`, `yaxis` in `tickmode: 'array'`
  with the contig names as tick text and the range reversed so lane 0 is at the
  top. Not one subplot per contig: subplots would need N y axis domains and a
  height budget per lane, and the lanes here share one x axis anyway.
- **Backbone.** A single null separated line trace draws each contig's
  `min..max` extent under its arrows, so a lane with a gap still reads as one
  molecule.
- **Region band.** Every distinct `(region_start, region_end)` pair seen in a
  lane's rows becomes a `layer: 'below'` rect. Distinct pairs rather than a
  single span, so a contig carrying two called regions gets two bands instead of
  one that swallows the gap between them.
- **Arrow geometry.** A five point pentagon plus its closing point. The head
  length is `max(xSpan * 0.006, featureLength * 0.3)` clamped to the feature's
  own length, which turns a CDS shorter than one head into a plain triangle
  rather than an inside out arrow. Strand is normalised: anything reading as
  minus (`-`, `-1`, `minus`, `reverse`) points left, everything else points
  right.
- **Labels.** Drawn as layout annotations under each arrow, only where the
  feature spans at least 3% of the x range and only while there are 12 lanes or
  fewer. Past that a label row does not fit between lanes.

### Colour

Classes are coloured from the Mantine hue list in the order they appear on
screen, so the legend never carries a hue nothing uses. Class values in
`NEUTRAL_CLASSES` (`flanking`, `flank`, `none`, `other`, `unknown`, `na`, `n/a`,
empty) keep a grey instead of consuming a hue. That is what makes the coloured
core read as the cluster. **Recipes should spell the neighbourhood class
`flanking`.**

## Tier-2 controls

Written back into the component's config through `usePersistedVizControl`, each
call keeping `metadata` and the string key on one line so
`test_persisted_controls_survive_their_model` can parse it:

| Control        | Config key     | Default |
| -------------- | -------------- | ------- |
| Feature labels | `show_labels`  | `true`  |
| Arrow height   | `arrow_height` | `0.5`   |

The remaining controls are view only, held in plain `useState`, because the
model has no field for them and `extra="forbid"` means a persisted key with no
field does not merely go unvalidated, it makes the whole component unloadable:

| Control      | Values                          | Default      |
| ------------ | ------------------------------- | ------------ |
| Contigs      | multi select over the fetched contigs | all    |
| Lanes shown  | 4 / 8 / 16 / 32                 | 8            |
| Lane order   | most features first / contig name | features   |
| Align lanes  | absolute bp / region start      | absolute     |
| Highlight region | on / off                    | on           |

"Align lanes: region start" re-expresses each lane's coordinates as an offset
from that contig's region start, which is the only way lanes from unrelated
contigs line up on a shared x axis. It is offered only when both region columns
are bound. Absolute stays the default because it is what the bound columns
actually say.

## Selection

`gene_arrow_track` does not declare selection, so the renderer emits none: it
takes `metadata`, `filters` and `refreshTick`, and never touches
`onFilterChange`. Nothing is needed in `selection.ts`.

## Recipe specification (funcscan 4.0.0)

Nothing is written yet. This section is the contract the recipe and the catalog
entry have to meet. The data lives in the megatest bucket and is not fetched
locally, so every file path below is asserted from the pipeline's own output
layout plus this run's `params.json` and `software_versions.yml`, both of which
*are* in the repo under
`depictio/projects/nf-core/funcscan/4.0.0/pipeline_info/`.

### What funcscan already has in the catalog

| Catalog module | Outputs | Grain |
| -------------- | ------- | ----- |
| `combgc` | `combgc_summary`, `combgc_tool_overlap` | one row per predicted BGC **region** |
| `ampcombi` | `summary`, `embedding`, `clusters` | one row per AMP candidate |
| `hamronization` | `report`, `gene_presence`, `gene_matrix`, `tool_overlap` | one row per ARG hit |
| `dbcan` | `overview`, `tool_overlap`, `substrates` | one row per CAZyme gene |

There is no `antismash`, no `gecco`, no `bakta` and no `prokka` module. The
closest existing output is `combgc/summary.yaml`, and it is the wrong grain:
comBGC reports a region as a single row with `BGC_start` / `BGC_end` /
`CDS_count`, and never emits per CDS coordinates or strands. A gene arrow track
cannot be built from it.

### Source files

**Primary: GECCO's per gene table.**

```
bgc/gecco/<sample>/<sample>.genes.tsv
```

GECCO 0.10.1 (confirmed in this run's `software_versions.yml` under
`GECCO_RUN`) writes one row per predicted gene with, in header order,
`sequence_id`, `protein_id`, `start`, `end`, `strand`, `average_p`, `max_p`. It
is a plain uncompressed TSV, it needs no GenBank parsing, and critically it
covers **every** gene on **every** contig GECCO scanned, not only the genes
inside GECCO's own clusters. Since funcscan feeds the same length filtered
contig set to every enabled BGC caller, that table also covers the contigs
antiSMASH called regions on, which is what lets one source serve every caller's
regions.

**Join: the comBGC run level summary.**

```
reports/combgc/combgc_complete_summary.tsv
```

Already fetched by `megatest.yaml` and already read by `combgc/summary.py`. It
supplies the region boundaries (`BGC_start`, `BGC_end`), the product class
(`Product_class`) and the caller (`Prediction_tool`) for all three callers. The
per sample `reports/combgc/<sample>/combgc_summary.tsv` files hold the antiSMASH
branch only and must not be used.

**Rejected as primary: the annotation GFF.**

```
annotation/{pyrodigal,prodigal,prokka,bakta}/<sample>/<sample>.gff
```

This run used `annotation_tool = pyrodigal` with `save_annotations = true`, and
`GUNZIP_PYRODIGAL_GFF` in the versions file means the GFF is published
uncompressed. Tempting, and it has full coverage. Two things rule it out as the
primary source:

1. `save_annotations` is **off by default** in funcscan. The megatest turned it
   on; an ordinary user run publishes no `annotation/` directory at all, so a DC
   built on it would prune itself for most runs.
2. The four annotation tools do not share a layout. Prokka and bakta append the
   assembly FASTA after a `##FASTA` line in the GFF, which a `read_csv` with
   `comment_prefix="#"` does not survive (the comment prefix eats the marker
   line, not the sequence lines under it).

Keep it as a documented fallback for a run that skipped GECCO
(`--bgc_skip_gecco`), wired through `source_overrides` rather than a second
recipe.

### Output columns and dtypes

`EXPECTED_SCHEMA`, in this order:

| Column         | polars dtype | viz role       | Notes |
| -------------- | ------------ | -------------- | ----- |
| `sample`       | `pl.Utf8`    | none           | Hub key. Every other funcscan DC has it and the `screening_summary` links join on it. |
| `contig`       | `pl.Utf8`    | `contig`       | One lane per distinct value. Must match `combgc_summary.contig` exactly. |
| `feature_id`   | `pl.Utf8`    | `feature_id`   | GECCO's `protein_id`. Unique within the DC. |
| `start`        | `pl.Int64`   | `start`        | 1-based inclusive, as GECCO writes it. Always `start <= end` whatever the strand. |
| `end`          | `pl.Int64`   | `end`          | |
| `strand`       | `pl.Utf8`    | `strand`       | Exactly `"+"` or `"-"`. Never null: an unknown strand is written `"+"`. |
| `class`        | `pl.Utf8`    | `class`        | Region product class for a CDS inside a region, the literal `"flanking"` outside. Never null. |
| `label`        | `pl.Utf8`    | `label`        | Short, drawn under the arrow. Never null. |
| `region_start` | `pl.Int64`   | `region_start` | Boundaries of the region this row's lane band should shade. |
| `region_end`   | `pl.Int64`   | `region_end`   | |

`start` / `end` / `region_start` / `region_end` as `Int64` satisfy the canonical
numeric family (`Int8..UInt64`, `Float32/64`); `contig` / `feature_id` /
`strand` / `class` / `label` as `Utf8` satisfy `{String, Utf8}`.

### Transform

```python
SOURCES = [
    RecipeSource(
        ref="genes",
        glob_pattern="bgc/gecco/*/*.genes.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
    RecipeSource(
        ref="regions",
        path="reports/combgc/combgc_complete_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]
```

1. **Regions.** From `regions` keep `contig_id`, `BGC_start`, `BGC_end`,
   `Product_class`, `Prediction_tool`. Merge overlapping intervals per contig
   (sort by start, fold forward). A merged interval's product class is the class
   of its widest contributing region, breaking ties by caller priority
   antiSMASH > GECCO > DeepBGC, so a contig called by two tools does not flicker
   between their vocabularies.
2. **Genes.** From `genes` keep `sequence_id`, `protein_id`, `start`, `end`,
   `strand`. Restrict to `sequence_id`s that appear in the region table: a
   neighbourhood only means something around a called cluster, and this is what
   keeps the DC to thousands of rows rather than millions.
3. **Flank window.** Drop CDSs further than `FLANK_BP = 10_000` from their
   contig's nearest region boundary. On this run's contigs (1 to 12 kb) nothing
   is dropped; on a run assembled into megabase contigs it is the difference
   between a locus map and a smear.
4. **Class.** A CDS whose midpoint falls inside a merged interval takes that
   interval's product class. Everything else gets the literal `"flanking"`,
   which is the value the renderer greys out.
5. **Region columns.** The interval the CDS belongs to, or for a flanking CDS
   the nearest interval on the same contig, so every row in a lane carries the
   band the lane should draw.
6. **Sample.** The glob harness concatenates matched files **without their
   path**, so `sample` has to come out of the file's own content. Take the
   `sequence_id` prefix before the first `.`, which is the convention
   `dbcan/overview.py` already relies on for these MGnify assemblies
   (`<sample>.<contig>`). Assemblies whose contig headers do not carry the
   sample id collapse to one pseudo sample, same as dbcan.
7. **Label.** The `protein_id` suffix after the last `_` (the CDS ordinal on the
   contig), falling back to the whole `protein_id`. Short enough to sit under an
   arrow. When the annotation fallback is in use and carries a gene symbol or
   product, that wins.
8. **Sort** by `sample`, `contig`, `start`, then `select(list(EXPECTED_SCHEMA))`.

Expected size on this run: 155 regions over roughly as many contigs, a handful
to a few dozen CDSs each, so low thousands of rows.

### Where it hangs off

**A new `depictio/catalog/gecco/` module.** The catalog is one folder per tool
and the folder is set by the tool that produced the raw file the output's `find`
matches. That file here is GECCO's, so:

```
depictio/catalog/gecco/
  module.yaml            # GECCO identity; nf_core_url -> modules/gecco/run
  gene_arrows.yaml       # id: gecco_gene_arrows, find + recipe + renders_as
  gene_arrows.py         # the recipe above
  gene_arrows.tsv        # fixture (a couple of contigs' worth)
```

```yaml
id: gecco_gene_arrows
name: BGC locus map
mode: bgc/genes
find: { path_glob: "**/bgc/gecco/*/*.genes.tsv" }
recipe: gecco/gene_arrows.py
fixture: gene_arrows.tsv
renders_as:
  - id: bgc_locus
    component: advanced_viz
    kind: gene_arrow_track
    roles:
      contig: contig
      feature_id: feature_id
      start: start
      end: end
      strand: strand
      class: class
      label: label
      region_start: region_start
      region_end: region_end
  - { component: table, row_selection_enabled: true, row_selection_column: contig }
```

Reading a second tool's file as a secondary source is precedented:
`deseq2/vst_pca.py` reads `input/samplesheet.tsv`, which no deseq2 module wrote.

**Rejected: hanging it off `combgc/`.** It is the tempting answer because the
region vocabulary is comBGC's and the render belongs on the same dashboard tab,
and the output schema even has an `origin_tool` field that would let a
`combgc/region_genes.yaml` declare `origin_tool: GECCO`. But `origin_tool` is
used for the inverse case, an aggregator republishing another tool's numbers
(the whole `multiqc/` folder, `enchantr` for alakazam). Here the file is GECCO's
own primary output and comBGC is the annotation layered on top, so a `find` glob
pointing at `**/gecco/*` from inside `combgc/` would put the module's identity
and its recognition rule in contradiction.

### Template wiring (not created)

In `depictio/projects/nf-core/funcscan/4.0.0/template.yaml`, next to the two
existing BGC collections:

- a `combgc_region_genes` (or `bgc_locus_map`) data collection, `optional: true`,
  `source: transformed`, `transform.recipe: gecco/gene_arrows.py`, with
  `columns_description` for the ten columns above;
- its tag added to the `SKIP_BGC` conditional's `remove_dc_tags`, alongside
  `combgc_summary` and `combgc_tool_overlap`;
- a link from `screening_summary.sample` to it, `resolver: direct`,
  `target_field: sample`, so the hub sample filter narrows it like every other
  screen;
- the render placed on the BGCs tab of `dashboards/base.yaml`, under the region
  table, as the drill down from a region row to its genes.

### Not verified

The bucket was not touched, so before writing the recipe confirm these three
against a single file fetch (not the 2.3 GB `bgc/` + `annotation/` prefixes):

1. The exact header of `*.genes.tsv` as GECCO 0.10.1 writes it. The column list
   above is from the GECCO output contract, not from this run's file.
2. That funcscan publishes GECCO per sample as `bgc/gecco/<sample>/` rather than
   flat under `bgc/gecco/`, and that the file is named `<sample>.genes.tsv`.
3. That GECCO's `sequence_id` is byte identical to comBGC's `contig_id` (the
   fixture in `depictio/catalog/combgc/summary.tsv` shows values of the form
   `ERZ1664501.1785-NODE-1785-length-1564-cov-1.431412`). The whole join depends
   on it, and a mismatch would present as an empty DC rather than an error.

## Shared edits this kind needs (owned elsewhere)

1. **`AdvancedVizDispatch.tsx`**: the import and the `RENDERERS` entry.

   ```tsx
   import GeneArrowTrackRenderer from './GeneArrowTrackRenderer';
   ```

   ```tsx
   gene_arrow_track: GeneArrowTrackRenderer,
   ```

2. **`api.ts`**: `| 'gene_arrow_track'` in the `AdvancedVizKind` union. Landed
   already, so the renderer sends the kind as a plain literal. Should it ever be
   reverted, `vizKind` must not simply be dropped: without it the server falls
   back to a uniform sample of a locus map.

3. **`schemas.py`**: the `_OPTIONAL_ROLES["gene_arrow_track"]` entry (`class`,
   `label`, `region_start`, `region_end`). Landed already. It was load bearing
   twice over: `validate_binding` reads `_OPTIONAL_ROLES[kind]` by subscript, so
   binding this kind used to raise `KeyError` before it could report a single
   error, and `_allowed_roles` would have rejected all four optional roles in
   the `renders_as` block above.

4. **`packages/tool-studio/public/catalog.json`**: regenerate
   (`pnpm --filter tool-studio genkinds`) when the catalog entry lands, or the
   drift check fails.

5. **`selection.ts`**: nothing. This kind declares no selection.
