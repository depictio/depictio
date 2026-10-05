import { describe, expect, it } from 'vitest';

import { parseBlocks } from './blockMarkdown';

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
