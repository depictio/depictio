import { describe, expect, it } from 'vitest';

import {
  firstSentence,
  hasMoreThanSubtitle,
  capitalizeLead,
  linkifySource,
  paragraphsOf,
  parseSections,
  splitValues,
  plainText,
  readableParagraphs,
  splitSentences,
  splitSources,
  titleCarriesDescription,
} from './descriptionText';

describe('firstSentence', () => {
  it('takes the text up to the first full stop', () => {
    expect(firstSentence('Reads per sample. Each dot is one library. Hover for ids.')).toBe(
      'Reads per sample.',
    );
  });

  it('is the whole text when there is no stop', () => {
    expect(firstSentence('Relative abundance per sample')).toBe('Relative abundance per sample');
  });

  it('does not break at abbreviations, decimals, initials or stops in code', () => {
    expect(firstSentence('Ratio, e.g. a log2 fold change vs. control. Second.')).toBe(
      'Ratio, e.g. a log2 fold change vs. control.',
    );
    expect(firstSentence('Cut-off at 0.05 adjusted p. Next one.')).toBe(
      'Cut-off at 0.05 adjusted p.',
    );
    expect(firstSentence('Described by J. Smith in the paper. More.')).toBe(
      'Described by J. Smith in the paper.',
    );
    expect(firstSentence('Column `a. B` is read. More.')).toBe('Column a. B is read.');
  });

  it('breaks at ! and ? followed by a capital', () => {
    expect(firstSentence('Is it flat? Then read on.')).toBe('Is it flat?');
  });

  it('strips markdown to plain text', () => {
    expect(firstSentence('**Depth** of `bam` in [the docs](https://x.org). More.')).toBe(
      'Depth of bam in the docs.',
    );
  });

  it('reads one paragraph only, so a title line never swallows the next', () => {
    expect(firstSentence('How to read this\n\nEach bar is a sample. More.')).toBe(
      'How to read this',
    );
  });

  it('reads only the first line of a list', () => {
    expect(firstSentence('- first item. Yes\n- second')).toBe('first item.');
  });

  it('caps a very long sentence at a word with an ellipsis', () => {
    const long = `${'word '.repeat(60)}end.`;
    const out = firstSentence(long, 40);
    expect(out.length).toBeLessThanOrEqual(40);
    expect(out.endsWith('…')).toBe(true);
    expect(out).not.toMatch(/\s…$/);
  });

  it('cuts one unbroken token where it stands', () => {
    const out = firstSentence('x'.repeat(200), 30);
    expect(out).toBe(`${'x'.repeat(29)}…`);
  });

  it('is empty for empty input', () => {
    expect(firstSentence('   ')).toBe('');
  });
});

describe('hasMoreThanSubtitle', () => {
  it('is false for a single short sentence shown whole', () => {
    expect(hasMoreThanSubtitle('Reads per sample.')).toBe(false);
    expect(hasMoreThanSubtitle('**Reads** per sample.')).toBe(false);
  });

  it('is true for further sentences, further paragraphs or a cut sentence', () => {
    expect(hasMoreThanSubtitle('One. Two.')).toBe(true);
    expect(hasMoreThanSubtitle('One\n\nTwo')).toBe(true);
    expect(hasMoreThanSubtitle('word '.repeat(60))).toBe(true);
  });

  it('is false for nothing', () => {
    expect(hasMoreThanSubtitle('')).toBe(false);
  });
});

describe('splitSentences', () => {
  it('splits a folded scalar and keeps the last sentence without a stop', () => {
    expect(splitSentences('A one. B two! C three')).toEqual(['A one.', 'B two!', 'C three']);
  });
});

describe('readableParagraphs', () => {
  const folded =
    'Lead sentence here. Second one. Third one follows. Fourth one. Fifth one ends it.';

  it('breaks a run-on line into a lead then pairs', () => {
    expect(readableParagraphs(folded)).toBe(
      'Lead sentence here.\n\nSecond one. Third one follows.\n\nFourth one. Fifth one ends it.',
    );
  });

  it('leaves one or two sentences alone', () => {
    expect(readableParagraphs('One. Two.')).toBe('One. Two.');
  });

  it('leaves text with its own breaks or blocks untouched', () => {
    const own = 'One.\n\nTwo. Three. Four.';
    expect(readableParagraphs(own)).toBe(own);
    const lines = 'One. Two. Three.\nFour.';
    expect(readableParagraphs(lines)).toBe(lines);
    expect(readableParagraphs('- One. Two. Three.')).toBe('- One. Two. Three.');
  });
});

describe('plainText', () => {
  it('drops markup and collapses whitespace', () => {
    expect(plainText('# Title\n\n*a*  **b**\n- c')).toBe('Title a b c');
  });
});

describe('titleCarriesDescription', () => {
  const base = { description: 'About it.', title: 'T' };

  it('is true for a titled figure, table and advanced viz', () => {
    expect(titleCarriesDescription('figure', base)).toBe(true);
    expect(titleCarriesDescription('table', base)).toBe(true);
    expect(titleCarriesDescription('advanced_viz', base)).toBe(true);
  });

  it('is false without a description', () => {
    expect(titleCarriesDescription('figure', { title: 'T' })).toBe(false);
    expect(titleCarriesDescription('figure', { title: 'T', description: '  ' })).toBe(false);
  });

  it('is false for an untitled figure or table, and for other types', () => {
    expect(titleCarriesDescription('figure', { description: 'x.' })).toBe(false);
    expect(titleCarriesDescription('table', { description: 'x.' })).toBe(false);
    expect(titleCarriesDescription('card', base)).toBe(false);
    expect(titleCarriesDescription('map', base)).toBe(false);
  });

  it('is false in the minimal style, whose header shows the subtitle field', () => {
    expect(titleCarriesDescription('figure', { ...base, figure_style: 'minimal' })).toBe(false);
    expect(titleCarriesDescription('advanced_viz', { ...base, figure_style: 'minimal' })).toBe(
      false,
    );
  });
});

describe('parseSections', () => {
  const kinds = (text: string) => parseSections(text).map((s) => s.kind);

  it('takes the first paragraph as the lead and labelled paragraphs as blocks', () => {
    const text = [
      'Depth along the gene.',
      'How to read: each line is a sample.',
      'Lines and annotations: the dashed line is the cut-off.',
      'Note: low-depth samples are dropped.',
      'Source: Smith 2020.',
    ].join('\n\n');
    const sections = parseSections(text);
    expect(sections.map((s) => s.kind)).toEqual(['lead', 'labelled', 'labelled', 'callout', 'source']);
    expect(sections[1]).toMatchObject({ label: 'How to read', text: 'Each line is a sample.' });
    expect(sections[3]).toMatchObject({ label: 'Note', tone: 'note' });
  });

  it('knows the label family, in any case after the capital', () => {
    expect(kinds('Lead.\n\nAnnotations: a\n\nReference lines: b\n\nSources: c')).toEqual([
      'lead',
      'labelled',
      'labelled',
      'source',
    ]);
    expect(parseSections('Lead.\n\nWarning: w\n\nCaution: c').map((s) => s.tone)).toEqual([
      undefined,
      'warning',
      'caution',
    ]);
    expect(parseSections('Lead.\n\nHOW TO READ: x')[1].kind).toBe('labelled');
  });

  it('does not take prose for a label', () => {
    // No colon.
    expect(kinds('Lead.\n\nNote that the median is shown, not the mean.')).toEqual(['lead', 'body']);
    // A label in the middle of a paragraph.
    expect(kinds('Lead.\n\nSee e.g. Source: x for the data.')).toEqual(['lead', 'body']);
    // Lower case, or a label that is not on the list.
    expect(kinds('Lead.\n\nnote: lower case')).toEqual(['lead', 'body']);
    expect(kinds('Lead.\n\nRatio: log2 fold change')).toEqual(['lead', 'body']);
    // The word and the colon must touch the label, not another word.
    expect(kinds('Lead.\n\nNotes: plural is not a label')).toEqual(['lead', 'body']);
  });

  it('keeps a list under its label as written', () => {
    const [, block] = parseSections('Lead.\n\nHow to read:\n- a bar is a sample\n- red is high');
    expect(block).toMatchObject({ kind: 'labelled', text: '- a bar is a sample\n- red is high' });
  });

  it('never makes a list or heading the lead', () => {
    expect(kinds('- one\n- two')).toEqual(['body']);
    expect(kinds('# Title\n\nText.')).toEqual(['body', 'body']);
  });

  it('splits a run-on line into a lead then paragraphs', () => {
    const sections = parseSections('Lead one. Two. Three. Four. Five.');
    expect(sections.map((s) => s.kind)).toEqual(['lead', 'body', 'body']);
    expect(sections[0].text).toBe('Lead one.');
  });

  it('does not sentence-split a single labelled line', () => {
    const sections = parseSections('Source: Smith 2020. Nature. Vol 4. Page 2.');
    expect(sections).toHaveLength(1);
    expect(sections[0].kind).toBe('source');
  });

  it('leaves a description with its own paragraphs unsplit', () => {
    const sections = parseSections('Lead. Two. Three. Four.\n\nBody. A. B. C.');
    expect(sections.map((s) => s.text)).toEqual(['Lead. Two. Three. Four.', 'Body. A. B. C.']);
  });
});

describe('subtitle with labels', () => {
  it('speaks for the first unlabelled paragraph', () => {
    expect(firstSentence('Note: careful.\n\nThe lead sentence. More.')).toBe('The lead sentence.');
  });

  it('falls back to a labelled paragraph without its label', () => {
    expect(firstSentence('Source: Smith 2020. Nature.')).toBe('Smith 2020.');
  });
});

describe('sources', () => {
  it('splits at semicolons and line breaks, not inside parentheses', () => {
    expect(splitSources('Smith 2020; Lee 2021')).toEqual(['Smith 2020', 'Lee 2021']);
    expect(splitSources('Smith (Nature; 2020)\n- Lee 2021')).toEqual([
      'Smith (Nature; 2020)',
      'Lee 2021',
    ]);
    expect(splitSources('')).toEqual([]);
  });

  it('links a doi token to doi.org and keeps the citation text', () => {
    expect(linkifySource('Smith 2020, Nature. doi:10.1038/s41586-020-2649-2.')).toBe(
      'Smith 2020, Nature. [doi:10.1038/s41586-020-2649-2](https://doi.org/10.1038/s41586-020-2649-2).',
    );
    expect(linkifySource('doi: 10.1000/xyz123')).toBe(
      '[doi:10.1000/xyz123](https://doi.org/10.1000/xyz123)',
    );
  });

  it('links a bare URL without its closing punctuation', () => {
    expect(linkifySource('Docs at https://example.org/a/b?c=1.')).toBe(
      'Docs at [https://example.org/a/b?c=1](https://example.org/a/b?c=1).',
    );
    expect(linkifySource('(see https://example.org/x)')).toBe(
      '(see [https://example.org/x](https://example.org/x))',
    );
  });

  it('keeps a DOI whose suffix has balanced parentheses, escaped in the href', () => {
    expect(linkifySource('doi:10.1016/S0140-6736(20)30183-5')).toBe(
      '[doi:10.1016/S0140-6736(20)30183-5](https://doi.org/10.1016/S0140-6736%2820%2930183-5)',
    );
  });

  it('leaves a link the author wrote alone', () => {
    const md = 'Lee [paper](https://example.org/p) 2021';
    expect(linkifySource(md)).toBe(md);
  });
});

describe('folded YAML scalars (a blank line arrives as one newline)', () => {
  const folded = [
    'Each genotype call, with its depth. A second sentence of the lead.',
    'How to read: a bar is a sample; red is a failed call.',
    'Note: low-depth calls are masked.',
    'Source: Smith 2020; doi:10.1000/xyz.',
  ].join('\n');

  it('breaks paragraphs at single newlines, so labels are found per paragraph', () => {
    const sections = parseSections(folded);
    expect(sections.map((s) => s.kind)).toEqual(['lead', 'labelled', 'callout', 'source']);
    expect(sections[0].text).toBe('Each genotype call, with its depth. A second sentence of the lead.');
    expect(sections[1]).toMatchObject({ label: 'How to read', text: 'A bar is a sample; red is a failed call.' });
  });

  it('makes the lead the first unlabelled paragraph only', () => {
    const sections = parseSections('First paragraph.\nSecond paragraph.\nNote: n');
    expect(sections.map((s) => s.kind)).toEqual(['lead', 'body', 'callout']);
  });

  it('gives the subtitle the first paragraph only', () => {
    expect(firstSentence('A title line with no stop\nThe next paragraph. More.')).toBe(
      'A title line with no stop',
    );
  });

  it('keeps a list under its label together, and a label alone on its line with its text', () => {
    const sections = parseSections('Lead.\nHow to read:\n- a bar is a sample\n- red is high\nNote:\ncareful');
    expect(sections.map((s) => s.kind)).toEqual(['lead', 'labelled', 'callout']);
    expect(sections[1].text).toBe('- a bar is a sample\n- red is high');
    expect(sections[2].text).toBe('Careful');
  });

  it('does not split the lines of a list, a table or a heading block', () => {
    expect(paragraphsOf('- one\n- two')).toEqual(['- one\n- two']);
    expect(paragraphsOf('| a | b |\n|---|---|\n| 1 | 2 |')).toHaveLength(1);
    expect(paragraphsOf('# Title\nText')).toEqual(['# Title', 'Text']);
    expect(paragraphsOf('- a\n  continued\n- b\nAfter')).toEqual(['- a\n  continued\n- b', 'After']);
    expect(paragraphsOf('::: steps\n- a\ntext\n:::\nAfter')).toEqual(['::: steps\n- a\ntext\n:::', 'After']);
  });

  it('still reads a literal block with blank lines', () => {
    const literal = 'Lead.\n\nHow to read: x\n\nNote: y\n\nSource: z';
    expect(parseSections(literal).map((s) => s.kind)).toEqual([
      'lead',
      'labelled',
      'callout',
      'source',
    ]);
  });
});

describe('capitalising the text after a label', () => {
  it('upper-cases a plain lower-case first word, in labelled blocks and callouts', () => {
    const sections = parseSections('Lead.\nHow to read: the dotted line is the cut-off.\nNote: low depth is masked.');
    expect(sections[1].text).toBe('The dotted line is the cut-off.');
    expect(sections[2].text).toBe('Low depth is masked.');
  });

  it('leaves names, identifiers and markup alone', () => {
    for (const t of ['pH is read', 'mRNA counts', 'log2 ratio', 'p-value cut', 'e.g. a ratio', '`x` is read', '[a](https://x.org) b', 'x is read']) {
      expect(capitalizeLead(t)).toBe(t);
    }
    expect(capitalizeLead('the bar')).toBe('The bar');
    expect(capitalizeLead('a bar')).toBe('A bar');
    expect(capitalizeLead('protein-coding genes sit right')).toBe('Protein-coding genes sit right');
    expect(capitalizeLead('p-value cut')).toBe('p-value cut');
  });

  it('leaves a citation as written', () => {
    expect(parseSections('Lead.\nSource: smith 2020')[1].text).toBe('smith 2020');
  });

  it('gives every labelled section a line icon, a warning the alert one', () => {
    const text = [
      'Lead.',
      'How to read: a.',
      'Lines and annotations: b.',
      'Annotations: c.',
      'Reference lines: d.',
      'Sources: e.',
      'Note: f.',
      'Warning: g.',
    ].join('\n\n');
    const sections = parseSections(text);
    expect(sections[0].icon).toBeUndefined();
    for (const section of sections.slice(1)) expect(section.icon).toMatch(/^tabler:[a-z0-9-]+$/);
    expect(sections.find((s) => s.tone === 'warning')?.icon).toBe('tabler:alert-triangle');
  });
});

describe('splitValues', () => {
  const values = (text: string) => splitValues(text).filter((s) => s.value).map((s) => s.text);

  it('picks a number with its unit, sign and comparison', () => {
    expect(values('The dashed line sits at 1 Mb; below 95 % it fails, at 10X it is masked.')).toEqual([
      '1 Mb',
      '95 %',
      '10X',
    ]);
    expect(values('Binders are <= 500 nM or rank 2.')).toEqual(['<= 500 nM', '2']);
    expect(values('The median is 0.5, over 1,000 reads.')).toEqual(['0.5', '1,000 reads']);
  });

  it('leaves digits that belong to a name or an identifier', () => {
    expect(values('log10 scale, Q40 standard, MHC v2, tabler:chart-line, doi 10.1038/x')).toEqual(['10.1038']);
    expect(values('The Mapping tab')).toEqual([]);
  });

  it('keeps every character in order', () => {
    const text = 'a 3 b 45 % c';
    expect(splitValues(text).map((s) => s.text).join('')).toBe(text);
  });
});
