import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { formatFilterValue, isFilterActive } from '../../activeFilters';
import {
  INVALID_REGEX_MESSAGE,
  MAX_PATTERN_LENGTH,
  PATTERN_TOO_LONG_MESSAGE,
  countAlternativeHits,
  markMatches,
  splitAlternatives,
  formatTextFilterValue,
  normalizeTextFilterValue,
  regexError,
  textFilterEvent,
  textFilterOptions,
} from './textFilter';

const control = (extra: Partial<StoredMetadata> = {}): StoredMetadata => ({
  index: 'guide-text',
  component_type: 'interactive',
  interactive_component_type: 'TextInput',
  column_name: 'guide',
  dc_id: 'dc1',
  ...extra,
});

describe('regexError', () => {
  it.each(['GGG$', '^ACG', 'A{5,}', '[ACG]+T', 'GGG', '(?i)acg'])('accepts %s', (pattern) => {
    expect(regexError(pattern)).toBeNull();
  });

  it.each(['(', '[A-', '*A', 'a**', 'GGG\\'])('rejects %s', (pattern) => {
    expect(regexError(pattern)).toBe(INVALID_REGEX_MESSAGE);
  });

  it('never rejects an empty value: that is no filter', () => {
    expect(regexError('')).toBeNull();
    expect(regexError('   ')).toBeNull();
    expect(regexError(null)).toBeNull();
  });

  it('never rejects literal text', () => {
    expect(regexError('(', 'contains')).toBeNull();
  });
});

describe('normalizeTextFilterValue', () => {
  it('trims, and turns a blank box into no value', () => {
    expect(normalizeTextFilterValue('  GGG$ ')).toBe('GGG$');
    expect(normalizeTextFilterValue('   ')).toBeNull();
    expect(normalizeTextFilterValue(undefined)).toBeNull();
  });
});

describe('textFilterEvent', () => {
  it('sends the pattern with the collection and column it filters', () => {
    expect(textFilterEvent(control(), ' ^ACG ')).toEqual({
      index: 'guide-text',
      value: '^ACG',
      column_name: 'guide',
      interactive_component_type: 'TextInput',
      filter_expr: undefined,
      metadata: { dc_id: 'dc1', column_name: 'guide', interactive_component_type: 'TextInput' },
    });
  });

  it('clears the filter with null on an empty box', () => {
    expect(textFilterEvent(control(), '')?.value).toBeNull();
  });

  it('sends nothing for a regex that does not compile', () => {
    expect(textFilterEvent(control(), '[A-')).toBeUndefined();
  });

  it('sends a literal pattern whatever its characters', () => {
    expect(textFilterEvent(control({ match_mode: 'contains' }), '(')?.value).toBe('(');
  });

  it('carries the options that differ from the default', () => {
    const meta = textFilterEvent(
      control({ case_sensitive: true, match_mode: 'contains' }),
      'A+',
    )?.metadata;
    expect(meta).toMatchObject({ case_sensitive: true, match_mode: 'contains' });
  });
});

describe('textFilterOptions', () => {
  it('leaves the defaults out, so a plain box keeps a compact share link', () => {
    expect(textFilterOptions({})).toEqual({});
    expect(textFilterOptions({ case_sensitive: false, match_mode: 'regex' })).toEqual({});
    expect(textFilterOptions({ case_sensitive: true })).toEqual({ case_sensitive: true });
  });
});

describe('active filter chips', () => {
  const filter = (value: unknown, metadata?: InteractiveFilter['metadata']): InteractiveFilter => ({
    index: 'guide-text',
    value,
    interactive_component_type: 'TextInput',
    metadata,
  });

  it('shows the pattern as typed', () => {
    expect(formatFilterValue(filter('GGG$'))).toBe('GGG$');
    expect(formatTextFilterValue(filter('^ACG'))).toBe('^ACG');
  });

  it('quotes a literal match', () => {
    expect(formatFilterValue(filter('A+', { match_mode: 'contains' }))).toBe('"A+"');
  });

  it('truncates a long pattern to chip size', () => {
    expect(formatFilterValue(filter('A'.repeat(60))).length).toBeLessThanOrEqual(28);
  });

  it('counts only a non-blank pattern as active', () => {
    expect(isFilterActive(filter('GGG$'))).toBe(true);
    expect(isFilterActive(filter(''))).toBe(false);
    expect(isFilterActive(filter('  '))).toBe(false);
    expect(isFilterActive(filter(null))).toBe(false);
  });
});

describe('splitAlternatives', () => {
  it('splits on top-level bars only', () => {
    expect(splitAlternatives('^CCA|GG$')).toEqual(['^CCA', 'GG$']);
    expect(splitAlternatives('(A|C)GG|T[|]T|a\\|b')).toEqual(['(A|C)GG', 'T[|]T', 'a\\|b']);
  });

  it('drops empty alternatives and keeps literal text whole', () => {
    expect(splitAlternatives('A||B|')).toEqual(['A', 'B']);
    expect(splitAlternatives('A|B', 'contains')).toEqual(['A|B']);
    expect(splitAlternatives('')).toEqual([]);
  });
});

describe('markMatches', () => {
  const plain = (pieces: { text: string; alt: number | null }[]) =>
    pieces.map((p) => (p.alt === null ? p.text : `[${p.alt}:${p.text}]`)).join('');

  it('marks every match of every alternative, ignoring case by default', () => {
    expect(plain(markMatches('ccaTTgg', ['^CCA', 'GG$']))).toBe('[0:cca]TT[1:gg]');
    expect(plain(markMatches('AAxAA', ['A+']))).toBe('[0:AA]x[0:AA]');
  });

  it('lets the earlier match win an overlap', () => {
    expect(plain(markMatches('ACGT', ['AC', 'CG']))).toBe('[0:AC]GT');
  });

  it('respects case when asked', () => {
    expect(plain(markMatches('ccaGG', ['^CCA'], 'regex', true))).toBe('ccaGG');
  });

  it('reads literal text as is', () => {
    expect(plain(markMatches('a+b', ['+'], 'contains'))).toBe('a[0:+]b');
  });

  it('marks nothing for an empty match or an alternative the browser rejects', () => {
    expect(plain(markMatches('ACG', ['X*']))).toBe('ACG');
    expect(plain(markMatches('ACG', ['(']))).toBe('ACG');
  });
});

describe('countAlternativeHits', () => {
  it('counts the values each alternative catches', () => {
    expect(countAlternativeHits(['CCAGG', 'CCATT', 'AAGG'], ['^CCA', 'GG$'])).toEqual([2, 2]);
  });
});

describe('pattern length cap', () => {
  it('rejects a pattern the server would not filter with, in either mode', () => {
    const long = 'A'.repeat(MAX_PATTERN_LENGTH + 1);
    expect(regexError(long)).toBe(PATTERN_TOO_LONG_MESSAGE);
    expect(regexError(long, 'contains')).toBe(PATTERN_TOO_LONG_MESSAGE);
    expect(regexError('A'.repeat(MAX_PATTERN_LENGTH))).toBeNull();
  });
});
