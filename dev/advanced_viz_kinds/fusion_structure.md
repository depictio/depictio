# `fusion_structure`

A gene fusion drawn as its two partner proteins laid end to end: one horizontal
lane per partner, one bar per annotated protein domain positioned by
`start`/`end` along that partner, the breakpoint marked, and each domain styled
by how much of it the fusion keeps. `top_n` fusions are faceted, one small
multiple each.

Long format, one row per `(fusion_id, partner, feature, start, end)`, because
the domain count varies per partner and per call.

| Use                              | fusion_id       | partner    | feature          | start / end        |
| -------------------------------- | --------------- | ---------- | ---------------- | ------------------ |
| Arriba retained protein domains   | `GENE1--GENE2`  | gene symbol| Pfam domain name | slot along the fusion |
| Domain map from a Pfam/InterPro annotation | fusion call id | gene symbol | domain name | amino-acid coordinate |
| Exon-level fusion transcript      | transcript pair | transcript | exon number      | transcript offset  |

## Model

- Config: `FusionStructureConfig` in
  `depictio/models/components/advanced_viz/configs.py`
- Canonical roles: `CANONICAL_SCHEMAS["fusion_structure"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely
  `fusion_id` (string), `partner` (string), `feature` (string),
  `start` (numeric), `end` (numeric)
- Optional config bindings: `breakpoint_col`, `retained_col`, `colour_by`
- Display defaults: `top_n` (6), `show_breakpoint` (true)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. A domain map read as a
  sample would lose whole domains rather than resolution, and the frame is tiny
  anyway (tens of rows per sample), so the server serves it whole.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/FusionStructureRenderer.tsx`

Built to the shape of `LollipopRenderer` (the per-feature facet stack, the
`fetchAdvancedVizData` hook, the `AdvancedVizFrame` chrome, the `plotlyTheme`
helpers on the way in and at the `<Plot>` props) and of `CoverageTrackRenderer`
(the positional track with markers drawn as layout shapes over a per-facet
axis pair). Everything is client side: the frame arrives once and every control
reshapes what is already in hand.

### Geometry

- One **facet per fusion**, stacked vertically, each with its own `xaxis{n}` /
  `yaxis{n}` pair. Per-facet x axes matter: a two-domain fusion and a
  ten-domain fusion share no coordinate system, and a shared range would
  squeeze the small one into the left margin.
- One **lane per partner** inside a facet, on a numeric y axis whose ticks are
  the partner names. The range is reversed so the first lane sits on top, the
  way a fusion is written.
- Lanes are ordered by their **smallest `start`**, with first appearance as the
  tie-break. That puts the 5' partner first when the recipe lays the partners
  end to end on one axis (the arriba recipe below), and falls back to row order
  when the data is partner-relative and both lanes start at 0. Both conventions
  render without a config switch.
- A faint baseline runs the width of each lane: the protein backbone the
  domains sit on.

### Why every domain is two bars

Each domain is drawn twice, as overlaid horizontal bars (`barmode: 'overlay'`):

1. The **extent** bar spans `start` to `end` in a neutral track colour with a
   1 px outline in the domain's category colour. It carries the label and the
   hover.
2. The **retained** bar spans `start` to `start + retained * (end - start)` in
   the solid category colour, with `hoverinfo: 'skip'` so one domain never
   reports itself twice.

So a partially retained domain reads as a half-filled slot, which is a length
the eye measures, rather than as a colour it has to decode. With no
`retained_col` bound, `retained` is 1 and the solid bar covers the extent bar
exactly, so the plot degrades to a plain domain map.

Bars are used rather than shapes because a shape does not hover, does not
legend, and does not carry text.

### Colour

`colour_by`, when bound, colours by that column's values. With no `colour_by`
but a bound `retained_col`, domains are coloured by retention tier
(`Retained` at 99.9% or more, `Partially retained`, `Not retained`), which is
what makes the default legend say something. With neither, every domain is one
category. Colours come from `stableColorMap` over the brand colorway when the
instance has one, else `TAB10_PALETTE`; nothing is hardcoded.

### Breakpoint

`show_breakpoint` plus a bound `breakpoint_col` draws a dotted vertical line
across every lane of the facet, at the first finite breakpoint value seen for
that fusion (the recipe writes the same value on every row of a fusion). The
value is folded into the facet's x range, so a breakpoint outside the domain
span still shows. The word "breakpoint" is annotated once, on the first facet,
rather than on all of them.

### Defensive reads

- `retained` is documented as a fraction. A frame whose maximum is above 1.5 is
  read as whole percentages and scaled by 1/100 once, over the whole frame, so
  every bar uses one scale.
- Rows with a non-finite `start` or `end` are skipped; `start`/`end` are
  swapped if they arrive reversed.
- A facet whose features are all zero-width still gets a usable x range.

## Tier-2 controls

| Control        | Persisted as     | Default |
| -------------- | ---------------- | ------- |
| Fusions        | `top_n`          | 6       |
| Mark breakpoint| `show_breakpoint`| true    |
| Bar height     | local state      | 0.45    |
| Name each domain | local state    | true    |
| Show coordinates | local state    | false   |

Only the first two are written back through `usePersistedVizControl`, because
they are the only two with a field on `FusionStructureConfig`. `extra="forbid"`
means persisting a key the model does not declare makes the whole component
unloadable, so the three presentation controls stay in plain `useState` rather
than inventing config keys. Both hook calls keep `metadata` and the string key
on one line, which is what `test_persisted_controls_survive_their_model`
parses.

Fields worth adding to `FusionStructureConfig` so those three can persist:
`bar_height: float = 0.45`, `show_labels: bool = True`,
`show_position_axis: bool = False`. A `sort_by` (`"data" | "name" | "domains"`)
would also earn its place once a real cohort has more fusions than `top_n`;
today the renderer keeps the frame's own order, which for arriba is its
confidence ranking and is the right default.

## Selection

None. `fusion_structure` does not declare selection and the renderer emits no
`onFilterChange`: a domain bar is an annotation of a call, not a row anyone
would filter a dashboard by.

## The arriba recipe (specification, not yet written)

### Source

Same file the existing `arriba_fusions` recipe reads, so the two recipes are
two views of one output:

```python
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        glob_pattern="arriba/*.arriba.fusions.tsv",
        format="TSV",
        read_kwargs={
            "infer_schema_length": 10000,
            "quote_char": None,
            "null_values": ["."],
        },
    ),
]
```

`quote_char=None` is load bearing: `fusion_transcript` and `peptide_sequence`
carry characters a CSV quote rule would eat. `null_values=["."]` is arriba's
"not available" placeholder.

Suggested home: `depictio/catalog/arriba/fusion_domains.py`, with
`fusion_domains.yaml` (`id: arriba_fusion_domains`,
`find: { filename: "*.arriba.fusions.tsv" }`, `recipe: arriba/fusion_domains.py`)
and a `fusion_domains.tsv` fixture.

### The column being exploded

`retained_protein_domains` packs both partners into one field:

```
Immunoglobulin_I-set_domain(100%),Immunoglobulin_domain(100%),NA(100%),Protein_kinase_domain(100%)|Transforming_acidic_coiled-coil-containing_protein_(TACC)__C-terminal(100%)
```

Verified against
`~/Data/depictio-nfcore/rnafusion/4.1.3/megatest/arriba/test.arriba.fusions.tsv`
(15 calls). The grammar, and the traps in it:

- **Exactly one `|`** separates the 5' partner's domains from the 3' partner's.
  Either side may be empty: `|Protein_kinase_domain(100%)` and
  `Domain_of_unknown_function_(DUF4819)(100%),HMG_(high_mobility_group)_box(100%)|`
  both occur in the megatest file. 6 of the 15 calls have an empty side.
- **Commas** separate domains within a side. Arriba substitutes `_` for spaces
  and commas in domain names, so a comma is always a separator.
- Each item is `Name(percent%)`. **The name itself can contain parentheses**:
  `Domain_of_unknown_function_(DUF4819)(100%)`,
  `HMG_(high_mobility_group)_box(100%)`,
  `Sterile_alpha_motif_(SAM)/Pointed_domain(100%)`. A non-greedy or
  first-paren parse gets these wrong. Anchor on the last group:
  `^(?s)(.*)\((\d+(?:\.\d+)?)%\)$`, whose greedy `.*` runs to the final `(`.
- **`NA` is a real item**: `NA(100%)` is a retained domain with no name in the
  annotation. It occupies a real slot in the retained span, so it must be kept,
  relabelled rather than dropped.
- The whole field can be `.`, read as null by the source's `null_values`.

### Coordinates, since arriba gives none

Arriba reports which domains survive and what fraction of each, never their
amino-acid coordinates. The recipe therefore synthesises the positional axis:
domains are laid **end to end in listed order, one unit slot each, across the
whole fusion**, 5' partner first. Slot `k` becomes `start = k`, `end = k + 1`.

That makes the 5' lane occupy `[0, n5)` and the 3' lane `[n5, n5 + n3)`, so:

- The lanes really are laid end to end, which is the picture the kind is for.
- Partner order falls out of the coordinates, so the renderer needs no extra
  role to know which partner is 5'.
- `breakpoint` is `n5` for every row of the fusion: one vertical seam between
  the two lanes, which is exactly where the junction is.

Retention stays in its own column rather than being folded into the bar width,
so the renderer owns that geometry and a future source with real Pfam
coordinates drops into the same schema unchanged.

An empty side emits **one sentinel row** (`feature = "(none retained)"`,
`retained = 0.0`) so the partner still gets a named lane and the seam still has
two sides. A call with both sides empty is dropped: there is nothing to draw
and it would otherwise burn a `top_n` facet.

### Output

`EXPECTED_SCHEMA`, in order:

| Column          | Dtype     | Meaning |
| --------------- | --------- | ------- |
| `fusion_id`     | `Utf8`    | `GENE1--GENE2`, plus ` #2`, ` #3` … for the 2nd and later calls of the same pair (arriba emits `GOPC--ROS1` twice at different breakpoints) |
| `partner`       | `Utf8`    | Gene symbol of the side this row belongs to |
| `partner_side`  | `Utf8`    | `5'` or `3'`; a candidate for `colour_by` |
| `feature`       | `Utf8`    | Domain name, `_` replaced by spaces; `NA` becomes `(unnamed domain)`, an empty side becomes `(none retained)` |
| `start`         | `Int64`   | Slot index along the fusion, 0-based |
| `end`           | `Int64`   | `start + 1` |
| `breakpoint`    | `Int64`   | Domain count of the 5' side; identical on every row of a fusion |
| `retained`      | `Float64` | Fraction, `percent / 100`; `0.0` for the sentinel |
| `domain_index`  | `Int64`   | 0-based position within the partner |
| `confidence`    | `Utf8`    | arriba `confidence` (`high` / `medium` / `low`) |
| `reading_frame` | `Utf8`    | `in-frame` / `out-of-frame` / `stop-codon` |
| `fusion_type`   | `Utf8`    | arriba `type` |
| `site_5p`       | `Utf8`    | arriba `site1` |
| `site_3p`       | `Utf8`    | arriba `site2` |
| `breakpoint_5p` | `Utf8`    | arriba `breakpoint1`, the genomic coordinate (kept as text, for hover and tables; it is not the plotted axis) |
| `breakpoint_3p` | `Utf8`    | arriba `breakpoint2` |
| `call_rank`     | `Int64`   | 1-based row order in the source file, which is arriba's own confidence ranking |

The trailing columns are passthrough: the renderer reads only the bound roles,
so they exist to give `colour_by` something to bind and to make the Show-data
popover and any table on the same DC useful.

Verified output on the megatest file: **39 rows across 15 fusions, no nulls in
any column**, `retained` taking `{0.0, 0.36, 0.44, 0.56, 0.94, 1.0}`. The
`FGFR3--TACC3` call becomes 4 rows on the `FGFR3` lane (slots 0 to 3, including
the `(unnamed domain)` slot) plus 1 on `TACC3` (slot 4), with `breakpoint = 4`.

### The transform

```python
_DOMAIN_RE = r"^(?s)(.*)\((\d+(?:\.\d+)?)%\)$"

def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["fusions"]

    calls = (
        df.select(
            _text("#gene1").alias("gene_5p"),
            _text("gene2").alias("gene_3p"),
            _text("breakpoint1").alias("breakpoint_5p"),
            _text("breakpoint2").alias("breakpoint_3p"),
            _text("site1").alias("site_5p"),
            _text("site2").alias("site_3p"),
            _text("type").alias("fusion_type"),
            _text("confidence").alias("confidence"),
            _text("reading_frame").alias("reading_frame"),
            _text("retained_protein_domains").alias("_domains"),
        )
        # arriba writes its calls in confidence order; keep it as a column.
        .with_row_index("call_rank", offset=1)
        .with_columns(pl.concat_str("gene_5p", pl.lit("--"), "gene_3p").alias("_pair"))
        # The same partner pair can be called twice at different breakpoints.
        .with_columns(pl.col("_pair").cum_count().over("_pair").alias("_occ"))
        .with_columns(
            pl.when(pl.col("_occ") == 1)
            .then(pl.col("_pair"))
            .otherwise(pl.concat_str("_pair", pl.lit(" #"), pl.col("_occ").cast(pl.Utf8)))
            .alias("fusion_id")
        )
        # splitn pads to exactly two fields, so a trailing empty side survives.
        .with_columns(
            pl.col("_domains").str.splitn("|", 2)
            .struct.rename_fields(["_s5p", "_s3p"])
            .alias("_sides")
        )
        .unnest("_sides")
        .with_columns(
            pl.col("_s5p").fill_null("").str.strip_chars(),
            pl.col("_s3p").fill_null("").str.strip_chars(),
        )
        .filter((pl.col("_s5p") != "") | (pl.col("_s3p") != ""))
    )

    index_cols = [c for c in calls.columns if c not in ("_s5p", "_s3p")]
    long = (
        calls.unpivot(
            on=["_s5p", "_s3p"],
            index=index_cols,
            variable_name="_side_key",
            value_name="_side",
        )
        .with_columns((pl.col("_side_key") == "_s3p").cast(pl.Int8).alias("_side_idx"))
        # The [""] sentinel is what keeps an empty partner's lane alive.
        .with_columns(
            pl.when(pl.col("_side") == "")
            .then(pl.lit([""]))
            .otherwise(pl.col("_side").str.split(","))
            .alias("_items")
        )
        .explode("_items")
        .with_columns(
            pl.col("_items").str.extract(_DOMAIN_RE, 1).alias("_name"),
            pl.col("_items").str.extract(_DOMAIN_RE, 2).cast(pl.Float64).alias("_pct"),
        )
        .with_columns(
            pl.when(pl.col("_name").is_null())
            .then(pl.lit("(none retained)"))
            .when(pl.col("_name") == "NA")
            .then(pl.lit("(unnamed domain)"))
            .otherwise(
                pl.col("_name")
                .str.replace_all("_", " ")
                .str.replace_all(r"\s+", " ")
                .str.strip_chars()
            )
            .alias("feature"),
            (pl.col("_pct").fill_null(0.0) / 100.0).alias("retained"),
            pl.when(pl.col("_side_idx") == 0)
            .then(pl.col("gene_5p"))
            .otherwise(pl.col("gene_3p"))
            .alias("partner"),
            pl.when(pl.col("_side_idx") == 0)
            .then(pl.lit("5'"))
            .otherwise(pl.lit("3'"))
            .alias("partner_side"),
        )
        # 5' side first, so the slot index below is the end-to-end layout.
        .sort("call_rank", "_side_idx", maintain_order=True)
        .with_columns(
            pl.int_range(pl.len()).over("fusion_id").alias("_slot"),
            pl.int_range(pl.len()).over("fusion_id", "_side_idx").alias("domain_index"),
            (pl.col("_side_idx") == 0).sum().over("fusion_id").alias("breakpoint"),
        )
        .with_columns(
            pl.col("_slot").alias("start"),
            (pl.col("_slot") + 1).alias("end"),
        )
    )

    return long.select(
        [pl.col(name).cast(dtype).alias(name) for name, dtype in EXPECTED_SCHEMA.items()]
    )
```

`_text` is the same never-null string helper `arriba/fusions.py` already
defines. Polars 1.43 warns that `explode`'s `empty_as_null` default flips in
2.0; the `[""]` sentinel means this recipe never explodes an empty list, so the
change is a no-op here.

### Catalog binding

Today only the five required roles can be bound, because `fusion_structure` has
no `_OPTIONAL_ROLES` entry (see the shared edits below):

```yaml
renders_as:
  - id: fusion_domain_map
    component: advanced_viz
    kind: fusion_structure
    roles:
      fusion_id: fusion_id
      partner: partner
      feature: feature
      start: start
      end: end
```

Once the optional roles are registered, the binding this recipe is actually
shaped for is:

```yaml
renders_as:
  - id: fusion_domain_map
    component: advanced_viz
    kind: fusion_structure
    roles:
      fusion_id: fusion_id
      partner: partner
      feature: feature
      start: start
      end: end
      breakpoint: breakpoint
      retained: retained
      colour_by: reading_frame
```

`Render` has no `config` field, so `top_n` and `show_breakpoint` cannot be set
from a catalog render: the model defaults (6, true) are what a catalog-placed
component gets, and the author retunes them in the settings popover.

## Shared edits this kind needs (owned elsewhere)

1. **`AdvancedVizDispatch.tsx`**: the import and the `RENDERERS` entry.

   ```tsx
   import FusionStructureRenderer from './FusionStructureRenderer';
   // …inside RENDERERS:
   fusion_structure: FusionStructureRenderer,
   ```

   Required, not optional: `test_every_dispatched_kind_has_a_model_and_a_source`
   asserts that the dispatch table and the config union name the same kinds, so
   `FusionStructureConfig` existing without this entry fails CI.

2. **`api.ts`**: `'fusion_structure'` added to the `AdvancedVizKind` union.
   Until then the renderer sends the kind through a documented
   `as unknown as AdvancedVizKind` cast (`VIZ_KIND`), the same shape
   `ProfileRenderer`, `SashimiRenderer` and `SignalMatrixRenderer` use, because
   omitting the kind would make the server sample the frame uniformly.

3. **`schemas.py`**: `fusion_structure` is missing from both `ROLE_NAMES` and
   `_OPTIONAL_ROLES`. Two consequences, both real:

   - `validate_binding()` does `optional = _OPTIONAL_ROLES[kind]` and so raises
     `KeyError: 'fusion_structure'` for any `FusionStructureConfig`. Verified.
   - `_allowed_roles("fusion_structure")` returns only the five required roles,
     so a catalog `renders_as` binding `breakpoint`, `retained` or `colour_by`
     is rejected at load.

   The entry wants `breakpoint` numeric, `retained` float, `colour_by`
   string/categorical. A `ROLE_NAMES` entry (column-name aliases such as
   `fusion`, `gene`, `domain`, `pfam`, `pct_retained`) would additionally let
   the builder auto-suggest bindings.

4. **`role_config_key()` in `advanced_viz/catalog.py`**: it appends `_col` to
   every role that is not in its explicit passthrough list, so the role
   `colour_by` maps to the field `colour_by_col`, which
   `FusionStructureConfig` does not have and `extra="forbid"` rejects. Either
   add `colour_by` to that passthrough tuple, or rename the model field to
   `colour_by_col` and match every other config in the union (`category_col`,
   `class_col`, `label_col`). The second is the more consistent fix; it is a
   model change, so it belongs with whoever owns `configs.py`.
