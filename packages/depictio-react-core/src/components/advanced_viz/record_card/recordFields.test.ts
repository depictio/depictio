import { describe, expect, it } from 'vitest';

import { formatFieldValue, NULL_DISPLAY, recordLinks, renderLinkTemplate } from './recordFields';

describe('formatFieldValue', () => {
  it('shows a dash for nulls and blanks', () => {
    expect(formatFieldValue(null)).toBe(NULL_DISPLAY);
    expect(formatFieldValue(undefined)).toBe(NULL_DISPLAY);
    expect(formatFieldValue('   ')).toBe(NULL_DISPLAY);
    expect(formatFieldValue(Number.NaN)).toBe(NULL_DISPLAY);
  });

  it('groups integers and keeps a sane precision on fractions', () => {
    expect(formatFieldValue(1234567)).toBe('1,234,567');
    expect(formatFieldValue(0.123456)).toBe('0.1235');
    expect(formatFieldValue(12.3456)).toBe('12.35');
    expect(formatFieldValue(1234.5678)).toBe('1,234.6');
  });

  it('switches to exponential outside the readable band', () => {
    expect(formatFieldValue(0.0000031)).toBe('3.10e-6');
    expect(formatFieldValue(1.4e9)).toBe('1,400,000,000');
    expect(formatFieldValue(1.44e9 + 0.5)).toBe('1.44e+9');
  });

  it('leaves strings alone, including ones that look numeric', () => {
    expect(formatFieldValue('00123')).toBe('00123');
    expect(formatFieldValue('1.20')).toBe('1.20');
  });

  it('reads booleans as words', () => {
    expect(formatFieldValue(true)).toBe('yes');
    expect(formatFieldValue(false)).toBe('no');
  });
});

describe('renderLinkTemplate', () => {
  it('substitutes and percent-encodes the value', () => {
    expect(renderLinkTemplate('https://www.ebi.ac.uk/ena/browser/view/{value}', 'SRR1/2')).toBe(
      'https://www.ebi.ac.uk/ena/browser/view/SRR1%2F2',
    );
  });

  it('substitutes every occurrence', () => {
    expect(renderLinkTemplate('https://x/{value}/report/{value}.html', 'S1')).toBe(
      'https://x/S1/report/S1.html',
    );
  });

  it('treats a template with no placeholder as a constant link', () => {
    expect(renderLinkTemplate('https://nf-co.re/rnaseq', 'S1')).toBe('https://nf-co.re/rnaseq');
  });

  it('returns null when there is no value to link to', () => {
    expect(renderLinkTemplate('https://x/{value}', null)).toBeNull();
    expect(renderLinkTemplate('https://x/{value}', '')).toBeNull();
    expect(renderLinkTemplate('', 'S1')).toBeNull();
  });
});

describe('recordLinks', () => {
  it('keeps the declaration order and skips empty values', () => {
    const links = recordLinks(
      { accession: 'SRR1', report: null, missing_from_row: undefined },
      {
        accession: 'https://ena/{value}',
        report: 'https://reports/{value}',
        absent: 'https://x/{value}',
      },
    );
    expect(links).toEqual([
      { column: 'accession', href: 'https://ena/SRR1', value: 'SRR1' },
    ]);
  });

  it('returns nothing without templates', () => {
    expect(recordLinks({ a: 1 }, null)).toEqual([]);
  });
});
