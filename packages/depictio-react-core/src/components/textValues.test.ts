import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../api';
import { parseBlocks, parseFact, parseStatRow } from './blockMarkdown';
import { parseInlineMarkdown } from './inlineMarkdown';
import {
  formatTextValue,
  hasLiveValues,
  hasPlaceholder,
  MISSING_VALUE,
  splitPlaceholders,
  withStandIns,
} from './textValues';

const text = (m: Partial<StoredMetadata>) =>
  ({ index: 't', component_type: 'text', ...m }) as StoredMetadata;

describe('splitPlaceholders', () => {
  it('cuts prose around values and parameters', () => {
    expect(splitPlaceholders('{{share}} of reads, {{param:dada_ref_taxonomy}}.')).toEqual([
      { type: 'value', key: 'share', param: false },
      { type: 'text', value: ' of reads, ' },
      { type: 'value', key: 'param:dada_ref_taxonomy', param: true },
      { type: 'text', value: '.' },
    ]);
  });

  it('leaves what is not a placeholder as prose', () => {
    // Upper case, too long, spaced, or a single brace: not a value name.
    for (const t of ['{{Share}}', '{{abcdefghijklm}}', '{{ share }}', '{share}', '{{}}']) {
      expect(splitPlaceholders(t)).toEqual([{ type: 'text', value: t }]);
      expect(hasPlaceholder(t)).toBe(false);
    }
  });

  it('is stable across calls (no regex state carried over)', () => {
    expect(hasPlaceholder('{{a}}')).toBe(true);
    expect(hasPlaceholder('{{a}}')).toBe(true);
  });
});

describe('placeholders survive the markdown parsers', () => {
  it('stays in text, bold, italic and link labels; code keeps it literal', () => {
    const tokens = parseInlineMarkdown(
      'A {{top}}, **{{share}}**, *{{n}}*, [{{tab_n}}](tab:QC) and `{{raw}}`',
    );
    expect(tokens).toEqual([
      { type: 'text', value: 'A {{top}}, ' },
      { type: 'bold', value: '{{share}}' },
      { type: 'text', value: ', ' },
      { type: 'italic', value: '{{n}}' },
      { type: 'text', value: ', ' },
      { type: 'link', value: '{{tab_n}}', href: 'tab:QC', external: false },
      { type: 'text', value: ' and ' },
      { type: 'code', value: '{{raw}}' },
    ]);
  });

  it('keeps a body of placeholders in its blocks', () => {
    expect(parseBlocks('# {{share}}\n- {{top}} leads\n\nRun with {{param:x.y}}')).toEqual([
      { type: 'heading', level: 1, text: '{{share}}' },
      { type: 'list', ordered: false, items: ['{{top}} leads'] },
      { type: 'paragraph', text: 'Run with {{param:x.y}}' },
    ]);
  });

  it('reads a bold placeholder as a result row figure', () => {
    expect(parseStatRow('**{{top_share}}** of reads are {{top}} [Community](tab:Community)')).toEqual({
      stat: '{{top_share}}',
      claim: 'of reads are {{top}}',
      context: null,
      link: '[Community](tab:Community)',
    });
    // A parameter's long key still counts: the figure is what it shows.
    expect(parseStatRow('**{{param:dada_ref_taxonomy}}** reference – the database')?.stat).toBe(
      '{{param:dada_ref_taxonomy}}',
    );
    // A bold label of words is still no figure.
    expect(parseStatRow('**Marker** 16S – V4 region')).toBeNull();
    expect(parseFact('**Shannon** {{shannon}}')).toEqual({
      icon: null,
      label: 'Shannon',
      value: '{{shannon}}',
    });
  });

  it('stands a placeholder in for a figure', () => {
    expect(withStandIns('×{{fold}}')).toBe('×0');
    expect(withStandIns('no value')).toBe('no value');
  });
});

describe('hasLiveValues', () => {
  it('holds for a text tile with values or a run parameter', () => {
    expect(hasLiveValues(text({ values: { n: { dc: 'd', column: 'c', aggregation: 'count' } } }))).toBe(
      true,
    );
    expect(hasLiveValues(text({ body: 'Run with {{param:primer}}' }))).toBe(true);
    expect(hasLiveValues(text({ title: '{{param:outdir}}' }))).toBe(true);
  });

  it('does not hold for plain text, empty values or other components', () => {
    expect(hasLiveValues(text({ body: 'Plain prose' }))).toBe(false);
    expect(hasLiveValues(text({ values: {}, body: '{{n}}' }))).toBe(false);
    expect(hasLiveValues(text({ values: null }))).toBe(false);
    expect(
      hasLiveValues({ index: 'c', component_type: 'card', values: { n: {} } } as unknown as StoredMetadata),
    ).toBe(false);
  });
});

describe('formatTextValue', () => {
  it('shows a share as a percentage, one decimal under 10%', () => {
    expect(formatTextValue(0.4123, 'percent')).toBe('41%');
    expect(formatTextValue(0.047, 'percent')).toBe('4.7%');
    expect(formatTextValue(0.05, 'percent')).toBe('5%');
    expect(formatTextValue(1, 'percent')).toBe('100%');
  });

  it('rounds integers with thousands separators', () => {
    expect(formatTextValue(12345.6, 'integer')).toBe('12,346');
    expect(formatTextValue(-0.4, 'integer')).toBe('0');
  });

  it('abbreviates with SI suffixes', () => {
    expect(formatTextValue(1234, 'si')).toBe('1.2k');
    expect(formatTextValue(3_400_000, 'si')).toBe('3.4M');
    expect(formatTextValue(5_600_000_000, 'si')).toBe('5.6G');
    expect(formatTextValue(1000, 'si')).toBe('1k');
    expect(formatTextValue(999_960, 'si')).toBe('1M');
    expect(formatTextValue(812, 'si')).toBe('812');
  });

  it('keeps an author\'s decimals as written', () => {
    expect(formatTextValue(3.14159, 'decimals:2')).toBe('3.14');
    expect(formatTextValue(7.1, 'decimals:2')).toBe('7.10');
  });

  it('prints a number like a card without a format, a string as is', () => {
    expect(formatTextValue(12.34567)).toBe('12.35');
    expect(formatTextValue(879737777)).toBe('879,737,777');
    expect(formatTextValue('Proteobacteria')).toBe('Proteobacteria');
    expect(formatTextValue('SILVA 138', 'percent')).toBe('SILVA 138');
    // An unknown format falls back to the card's printing.
    expect(formatTextValue(0.5, 'decimals:9')).toBe('0.5');
  });

  it('shows a dash for a value that is not there', () => {
    expect(formatTextValue(null)).toBe(MISSING_VALUE);
    expect(formatTextValue(undefined, 'percent')).toBe(MISSING_VALUE);
    expect(formatTextValue(Number.NaN, 'integer')).toBe(MISSING_VALUE);
    expect(MISSING_VALUE).toBe('–');
  });
});
