/**
 * The markdown a text tile's body understands, as copyable examples.
 *
 * The editor's text builder shows these under the body field. They live next
 * to the parsers rather than in the builder so the test beside them can hold
 * every example to what `blockMarkdown.ts` and `inlineMarkdown.ts` actually
 * read: a cheatsheet that drifts from the grammar teaches syntax that renders
 * as literal text.
 */

/** How the renderer reads an example. The test pins each example to its own. */
export type MarkdownRendering =
  | 'heading'
  | 'emphasis'
  | 'code'
  | 'link'
  | 'tab-link'
  | 'params-link'
  | 'icon'
  | 'list'
  | 'table'
  | 'rule'
  | 'facts'
  | 'steps'
  | 'results'
  | 'tab-tiles'
  | 'link-row'
  | 'figure';

export interface MarkdownExample {
  label: string;
  /** The markdown to copy, exactly as it would be typed. */
  example: string;
  /** What it turns into, or what it needs to. */
  note?: string;
  renders: MarkdownRendering;
}

export interface MarkdownExampleGroup {
  group: string;
  examples: MarkdownExample[];
}

export const MARKDOWN_CHEATSHEET: MarkdownExampleGroup[] = [
  {
    group: 'Text',
    examples: [
      {
        label: 'Headings',
        example: '# Heading\n## Subheading\n### Small heading',
        note: "Three levels, set one step below the tile's own title.",
        renders: 'heading',
      },
      { label: 'Bold and italic', example: '**bold** and *italic*', renders: 'emphasis' },
      { label: 'Inline code', example: 'run `nextflow run nf-core/ampliseq`', renders: 'code' },
      {
        label: 'List',
        example: '- First point\n- Second point',
        note: '`1.` numbers the items.',
        renders: 'list',
      },
      {
        label: 'Table',
        example: '| Site | Samples |\n| --- | ---: |\n| Naples | 28 |\n| Athens | 29 |',
        note: 'A `:` in the separator row aligns the column.',
        renders: 'table',
      },
      { label: 'Divider', example: '---', renders: 'rule' },
    ],
  },
  {
    group: 'Links and icons',
    examples: [
      {
        label: 'Web link',
        example: '[nf-core/ampliseq](https://nf-co.re/ampliseq)',
        note: 'Opens beside the dashboard. A path such as `/dashboards` opens in place.',
        renders: 'link',
      },
      {
        label: 'Link to a tab',
        example: '[Alpha diversity](tab:Alpha Diversity)',
        note: "By the tab's displayed name; the link wears that tab's icon and colour.",
        renders: 'tab-link',
      },
      {
        label: 'Run parameters',
        example: "See [the run's parameters](params:) or [its primers](params:primer).",
        note: '`params:` opens the run parameters; text after it searches them.',
        renders: 'params-link',
      },
      {
        label: 'Inline icon',
        example: '![](icon:mdi:dna) 16S and 18S',
        note: 'An Iconify id, `prefix:name`.',
        renders: 'icon',
      },
    ],
  },
  {
    group: 'Lists drawn as layouts',
    examples: [
      {
        label: 'Fact list',
        example:
          '- ![](icon:mdi:dna) **Marker** 16S V4–V5\n- ![](icon:mdi:calendar-outline) **Period** May–Oct 2024',
        note: 'Every item: an icon (optional), a bold label, a value. One line of facts; a two-column table on a framed tile.',
        renders: 'facts',
      },
      {
        label: 'Steps',
        example:
          '1. ![](icon:mdi:dna) **Amplicon** V4–V5\n2. ![](icon:mdi:filter-variant) **Denoise** DADA2 to ASVs',
        note: 'A numbered fact list, drawn as steps.',
        renders: 'steps',
      },
      {
        label: 'Result rows',
        example:
          '- **41%** Of reads are Bacteria — mean over 85 samples [Community](tab:Community)\n- **×3** More ASVs in summer — against winter [Alpha](tab:Alpha Diversity)',
        note: 'A bold figure holding a digit, the claim, then a context after a dash and/or a closing link.',
        renders: 'results',
      },
      {
        label: 'Tab tiles',
        example:
          '- [Sequencing QC](tab:Sequencing QC): Did the run work?\n- [Environment (CTD)](tab:Environment (CTD))',
        note: "Every item a tab link, optionally followed by `: what it answers` (else the tab's own subtitle). Tabs this dashboard lacks are left out.",
        renders: 'tab-tiles',
      },
      {
        label: 'Numbered tab tiles',
        example:
          '1. [Alpha Diversity](tab:Alpha Diversity): How diverse is each sample?\n2. [Ordination](tab:Ordination & Clustering): Which samples look alike?',
        note: 'The same tiles, numbered as a reading order.',
        renders: 'tab-tiles',
      },
      {
        label: 'Link row',
        example: '**See also** · [Alpha](tab:Alpha Diversity) · [Phylogeny](tab:Phylogeny)',
        note: 'A bold label then links, or two links or more. Closing a framed tile, it sits on its bottom edge.',
        renders: 'link-row',
      },
    ],
  },
  {
    group: 'Framed tiles',
    examples: [
      {
        label: 'Headline figure',
        example: '# 41%\nof reads are Bacteria',
        note: 'With a frame, a leading heading holding a number is set as a key figure and the line under it as its caption.',
        renders: 'figure',
      },
    ],
  },
];
