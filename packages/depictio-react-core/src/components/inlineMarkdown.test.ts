import { describe, expect, it } from 'vitest';

import { parseInlineMarkdown } from './inlineMarkdown';

describe('parseInlineMarkdown', () => {
  it('leaves plain prose as one text token', () => {
    expect(parseInlineMarkdown('Reads, then peaks.')).toEqual([
      { type: 'text', value: 'Reads, then peaks.' },
    ]);
  });

  it('reads bold, italic and code', () => {
    expect(parseInlineMarkdown('**a** *b* `c`')).toEqual([
      { type: 'bold', value: 'a' },
      { type: 'text', value: ' ' },
      { type: 'italic', value: 'b' },
      { type: 'text', value: ' ' },
      { type: 'code', value: 'c' },
    ]);
  });

  it('links an https target and marks it external', () => {
    expect(parseInlineMarkdown('made by [ataqv](https://github.com/ParkerLab/ataqv).')).toEqual([
      { type: 'text', value: 'made by ' },
      {
        type: 'link',
        value: 'ataqv',
        href: 'https://github.com/ParkerLab/ataqv',
        external: true,
      },
      { type: 'text', value: '.' },
    ]);
  });

  it('keeps a site-relative path in the same tab', () => {
    expect(parseInlineMarkdown('see [the docs](/about)')).toEqual([
      { type: 'text', value: 'see ' },
      { type: 'link', value: 'the docs', href: '/about', external: false },
    ]);
  });

  it('reads several links in one body', () => {
    const tokens = parseInlineMarkdown(
      '[ataqv](https://github.com/ParkerLab/ataqv) and [MACS2](https://github.com/macs3-project/MACS)',
    );
    expect(tokens.filter((t) => t.type === 'link')).toHaveLength(2);
  });

  it('refuses a javascript: target, leaving it as literal text', () => {
    expect(parseInlineMarkdown('[x](javascript:alert(1))')).toEqual([
      { type: 'text', value: '[x](javascript:alert(1))' },
    ]);
  });

  it('refuses other schemes too', () => {
    for (const href of ['data:text/html;base64,PHA+', 'ftp://example.org/x', 'vbscript:msgbox']) {
      expect(parseInlineMarkdown(`[x](${href})`)).toEqual([
        { type: 'text', value: `[x](${href})` },
      ]);
    }
  });

  it('does not link inside a code span', () => {
    expect(parseInlineMarkdown('`[x](https://example.org)`')).toEqual([
      { type: 'code', value: '[x](https://example.org)' },
    ]);
  });

  it('leaves a link whose URL was broken by YAML folding as text', () => {
    // A `[label](url)` construct that wraps mid-URL gets a space folded into
    // it; better to show the raw text than to link a mangled target.
    expect(parseInlineMarkdown('[ataqv](https://github.com/ParkerLab/ ataqv)')).toEqual([
      { type: 'text', value: '[ataqv](https://github.com/ParkerLab/ ataqv)' },
    ]);
  });

  it('keeps bold inside link labels literal rather than nesting', () => {
    const tokens = parseInlineMarkdown('[**bold label**](https://example.org)');
    expect(tokens).toEqual([
      { type: 'link', value: '**bold label**', href: 'https://example.org', external: true },
    ]);
  });
});
