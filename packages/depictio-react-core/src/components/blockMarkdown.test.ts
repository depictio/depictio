import { describe, expect, it } from 'vitest';

import {
  isLinksOnly,
  parseBlocks,
  parseFact,
  parseLinkRow,
  parseStatRow,
  readsAsSteps,
  splitStepValue,
} from './blockMarkdown';

describe('parseBlocks', () => {
  it('keeps a body without block syntax as one paragraph, line breaks included', () => {
    expect(parseBlocks('First line.\nSecond line.')).toEqual([
      { type: 'paragraph', text: 'First line.\nSecond line.' },
    ]);
  });

  it('splits paragraphs on blank lines', () => {
    expect(parseBlocks('One.\n\nTwo.')).toEqual([
      { type: 'paragraph', text: 'One.' },
      { type: 'paragraph', text: 'Two.' },
    ]);
  });

  it('reads headings up to level 3', () => {
    expect(parseBlocks('# Title\n## Sub\n### Minor\n#### Not a heading')).toEqual([
      { type: 'heading', level: 1, text: 'Title' },
      { type: 'heading', level: 2, text: 'Sub' },
      { type: 'heading', level: 3, text: 'Minor' },
      { type: 'paragraph', text: '#### Not a heading' },
    ]);
  });

  it('reads bullet and numbered lists, with indented continuations', () => {
    expect(parseBlocks('- a\n- b\n  continued\n\n1. one\n2) two')).toEqual([
      { type: 'list', ordered: false, items: ['a', 'b continued'] },
      { type: 'list', ordered: true, items: ['one', 'two'] },
    ]);
  });

  it('ends a list at a line that is neither an item nor indented', () => {
    expect(parseBlocks('- a\nafter')).toEqual([
      { type: 'list', ordered: false, items: ['a'] },
      { type: 'paragraph', text: 'after' },
    ]);
  });

  it('reads a rule rather than an empty bullet', () => {
    expect(parseBlocks('above\n\n---\n\n***\nbelow')).toEqual([
      { type: 'paragraph', text: 'above' },
      { type: 'rule' },
      { type: 'rule' },
      { type: 'paragraph', text: 'below' },
    ]);
  });

  it('reads a pipe table with its alignment', () => {
    expect(parseBlocks('| Tab | Shows |\n|:---|---:|\n| QC | reads |\n| Alpha | richness |')).toEqual([
      {
        type: 'table',
        header: ['Tab', 'Shows'],
        align: ['left', 'right'],
        rows: [
          ['QC', 'reads'],
          ['Alpha', 'richness'],
        ],
      },
    ]);
  });

  it('leaves a lone pipe row without a separator as a paragraph', () => {
    expect(parseBlocks('| not | a table |')).toEqual([
      { type: 'paragraph', text: '| not | a table |' },
    ]);
  });

  it('normalises CRLF line endings', () => {
    expect(parseBlocks('- a\r\n- b')).toEqual([{ type: 'list', ordered: false, items: ['a', 'b'] }]);
  });
});

describe('parseFact', () => {
  it('reads an icon, a bold label and a value', () => {
    expect(parseFact('![](icon:mdi:dna) **Pipeline** nf-core/ampliseq 2.18.0')).toEqual({
      icon: 'mdi:dna',
      label: 'Pipeline',
      value: 'nf-core/ampliseq 2.18.0',
    });
  });

  it('takes a colon after the label and no icon', () => {
    expect(parseFact('**Taxonomy**: SILVA 138.2')).toEqual({
      icon: null,
      label: 'Taxonomy',
      value: 'SILVA 138.2',
    });
  });

  it('refuses an item that only opens in bold', () => {
    expect(parseFact('**Locality drives the community.**')).toBeNull();
    expect(parseFact('plain item')).toBeNull();
  });
});

describe('isLinksOnly', () => {
  it('accepts one or several links', () => {
    expect(isLinksOnly('[Ordination](tab:Ordination & Clustering)')).toBe(true);
    expect(isLinksOnly('[CTD](tab:Environment (CTD)) · [QC](tab:Sequencing QC)')).toBe(true);
  });

  it('refuses prose around a link', () => {
    expect(isLinksOnly('see [Ordination](tab:Ordination & Clustering)')).toBe(false);
  });
});

describe('parseStatRow', () => {
  it('reads figure, claim, context and a tab link', () => {
    expect(
      parseStatRow(
        '**41%** Locality drives the community — of the variation between samples [Ordination](tab:Ordination & Clustering)',
      ),
    ).toEqual({
      stat: '41%',
      claim: 'Locality drives the community',
      context: 'of the variation between samples',
      link: '[Ordination](tab:Ordination & Clustering)',
    });
  });

  it('keeps parentheses in a tab name', () => {
    expect(parseStatRow('**46** casts matched [CTD](tab:Environment (CTD))')?.link).toBe(
      '[CTD](tab:Environment (CTD))',
    );
  });

  it('accepts a context without a link', () => {
    expect(parseStatRow('**3.2×** more reads – than the 2023 run')).toEqual({
      stat: '3.2×',
      claim: 'more reads',
      context: 'than the 2023 run',
      link: null,
    });
  });

  it('rejects a fact: no digit, or no context nor link', () => {
    expect(parseStatRow('**Pipeline** nf-core/ampliseq 2.18.0')).toBeNull();
    expect(parseStatRow('**16S** amplicons only')).toBeNull();
  });
});

describe('parseLinkRow', () => {
  it('reads a labelled row of links, parentheses in tab names included', () => {
    expect(
      parseLinkRow('**Also** · [Env (CTD)](tab:Environment (CTD)) · [QC](tab:Sequencing QC)'),
    ).toEqual({
      label: 'Also',
      links: ['[Env (CTD)](tab:Environment (CTD))', '[QC](tab:Sequencing QC)'],
    });
  });

  it('reads two or more bare links', () => {
    expect(parseLinkRow('[A](tab:A) | [B](https://example.org)')?.links).toHaveLength(2);
  });

  it('leaves a lone link, and prose with links, as paragraphs', () => {
    expect(parseLinkRow('[A](tab:A)')).toBeNull();
    expect(parseLinkRow('See [A](tab:A) and [B](tab:B) for more')).toBeNull();
    expect(parseLinkRow('**Note** the [A](tab:A) tab')).toBeNull();
  });
});

describe('splitStepValue', () => {
  it('sets trailing links apart from the prose', () => {
    expect(splitStepValue('DADA2 to ASVs · Q ≥ 25 · [Settings](params:dada2) · [QC](tab:Sequencing QC)')).toEqual({
      text: 'DADA2 to ASVs · Q ≥ 25',
      links: ['[Settings](params:dada2)', '[QC](tab:Sequencing QC)'],
    });
  });
  it('leaves a link inside the prose where it is', () => {
    expect(splitStepValue('[SILVA](params:silva) + PR2')).toEqual({ text: '[SILVA](params:silva) + PR2', links: [] });
  });
  it('keeps a value made only of a link as text', () => {
    expect(splitStepValue('[Ordination](tab:Ordination)').links).toEqual([]);
  });
});

describe('readsAsSteps', () => {
  it('needs an icon on every item', () => {
    expect(
      readsAsSteps(['![](icon:mdi:dna) **Amplicon** V4–V5', '![](icon:mdi:sigma) **Test** PERMANOVA']),
    ).toBe(true);
  });

  it('leaves a bold-led numbered list a list', () => {
    expect(readsAsSteps(['**Install** the CLI', '**Run** the pipeline'])).toBe(false);
    expect(readsAsSteps(['![](icon:mdi:dna) **Amplicon** V4–V5', '**Denoise** DADA2'])).toBe(false);
    expect(readsAsSteps([])).toBe(false);
  });
});
