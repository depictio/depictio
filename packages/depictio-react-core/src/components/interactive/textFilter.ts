import type { InteractiveFilter, StoredMetadata } from '../../api';

/**
 * Pure logic of the TextInput filter: a box that keeps the rows of a string
 * column matching a regular expression (a plain substring is one too).
 *
 * Kept free of React so the renderer, the filter bar's compact form, the
 * declared-default seeding and the active-filter chips all agree on what a
 * value means, and so it is testable without a DOM.
 */

/** Wait after the last keystroke before the filter is sent. */
export const TEXT_FILTER_DEBOUNCE_MS = 300;

/** What the box says under a pattern the browser cannot compile. */
export const INVALID_REGEX_MESSAGE = 'Invalid regular expression';

/** What the box says under a pattern too long to filter with (the server's cap). */
export const PATTERN_TOO_LONG_MESSAGE = 'Pattern too long';

/** Longest pattern the server filters with; keep in step with
 *  `MAX_TEXT_PATTERN_LENGTH` in deltatables_utils.py. */
export const MAX_PATTERN_LENGTH = 512;

/** `regex` reads the text as a regular expression, `contains` as literal text. */
export type TextMatchMode = 'regex' | 'contains';

/** Leading inline flag groups (`(?i)`), which the server's engine takes and a
 *  JS RegExp rejects. Case is the component's own option, so they are only
 *  skipped when checking, never sent differently. */
const INLINE_FLAGS = /^(\(\?[a-z]+\))+/;

/** The pattern a user typed, trimmed; `null` when nothing is left (no filter). */
export function normalizeTextFilterValue(raw: string | null | undefined): string | null {
  const text = (raw ?? '').trim();
  return text === '' ? null : text;
}

/** A message when `value` cannot filter (too long, or a regex that does not compile), else
 *  `null`. Literal text under the length cap always compiles; an empty value is no filter, not an error. */
export function regexError(
  value: string | null | undefined,
  matchMode: string | null | undefined = 'regex',
): string | null {
  const text = normalizeTextFilterValue(value);
  if (text === null) return null;
  if (text.length > MAX_PATTERN_LENGTH) return PATTERN_TOO_LONG_MESSAGE;
  if (matchMode === 'contains') return null;
  try {
    new RegExp(text.replace(INLINE_FLAGS, ''));
    return null;
  } catch {
    return INVALID_REGEX_MESSAGE;
  }
}

/** The options a stored component carries, in the shape a filter's metadata
 *  holds them: each present only when it differs from the default (a
 *  case-insensitive regex), so a plain box keeps a short share link. */
export function textFilterOptions(
  m: Pick<StoredMetadata, 'case_sensitive' | 'match_mode'>,
): { case_sensitive?: boolean; match_mode?: TextMatchMode } {
  return {
    ...(m.case_sensitive === true ? { case_sensitive: true } : {}),
    ...(m.match_mode === 'contains' ? { match_mode: 'contains' as const } : {}),
  };
}

/** The filter a TextInput sends for `raw`: `value: null` clears it. `undefined`
 *  when `raw` is a regex that does not compile, which is never sent. */
export function textFilterEvent(
  m: Pick<
    StoredMetadata,
    'index' | 'column_name' | 'dc_id' | 'filter_expr' | 'case_sensitive' | 'match_mode'
  >,
  raw: string | null | undefined,
): InteractiveFilter | undefined {
  const value = normalizeTextFilterValue(raw);
  if (regexError(value, m.match_mode)) return undefined;
  return {
    index: m.index,
    value,
    column_name: m.column_name,
    interactive_component_type: 'TextInput',
    filter_expr: m.filter_expr,
    metadata: {
      dc_id: m.dc_id,
      column_name: m.column_name,
      interactive_component_type: 'TextInput',
      ...textFilterOptions(m),
    },
  };
}

/** How a TextInput's value reads on an active-filter chip: the pattern as
 *  typed, or in quotes when it is matched as literal text. */
export function formatTextFilterValue(filter: Pick<InteractiveFilter, 'value' | 'metadata'>): string {
  const text = typeof filter.value === 'string' ? filter.value.trim() : '';
  if (text === '') return '';
  return filter.metadata?.match_mode === 'contains' ? `"${text}"` : text;
}

/** Mantine colours the alternatives of a pattern are marked with, in order. */
export const MARK_COLORS = ['yellow', 'cyan', 'grape', 'lime', 'orange', 'pink'] as const;

/**
 * The top-level alternatives of a regular expression (`^CCA|GG$` is two):
 * the parts a person would call separate patterns, each marked in its own
 * colour. A `|` inside a group, a class or after a backslash is not a split.
 * Literal text is one alternative whatever it contains.
 */
export function splitAlternatives(
  pattern: string,
  matchMode: string | null | undefined = 'regex',
): string[] {
  if (matchMode === 'contains') return pattern === '' ? [] : [pattern];
  const parts: string[] = [];
  let depth = 0;
  let inClass = false;
  let current = '';
  for (let i = 0; i < pattern.length; i += 1) {
    const ch = pattern[i];
    if (ch === '\\' && i + 1 < pattern.length) {
      current += ch + pattern[i + 1];
      i += 1;
      continue;
    }
    if (inClass) {
      if (ch === ']') inClass = false;
    } else if (ch === '[') {
      inClass = true;
    } else if (ch === '(') {
      depth += 1;
    } else if (ch === ')') {
      depth = Math.max(0, depth - 1);
    } else if (ch === '|' && depth === 0) {
      parts.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  parts.push(current);
  return parts.filter((part) => part !== '');
}

function alternativeRegExp(
  alternative: string,
  matchMode: string | null | undefined,
  caseSensitive: boolean,
  flags: string,
): RegExp | null {
  const source =
    matchMode === 'contains'
      ? alternative.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      : alternative.replace(INLINE_FLAGS, '');
  try {
    return new RegExp(source, flags + (caseSensitive ? '' : 'i'));
  } catch {
    return null;
  }
}

/** One stretch of a value: the alternative that caught it, or `null` for plain text. */
export interface MarkedPiece {
  text: string;
  alt: number | null;
}

/**
 * `text` cut into plain and caught pieces, every match of every alternative
 * marked with the index of its alternative. Where two matches overlap the
 * earlier one wins. Read with the browser's regex dialect, which can differ
 * from the server's on exotic syntax: an alternative it rejects marks nothing,
 * it never changes the filter. Empty matches mark nothing.
 */
export function markMatches(
  text: string,
  alternatives: string[],
  matchMode: string | null | undefined = 'regex',
  caseSensitive = false,
): MarkedPiece[] {
  const spans: { start: number; end: number; alt: number }[] = [];
  alternatives.forEach((alternative, alt) => {
    const re = alternativeRegExp(alternative, matchMode, caseSensitive, 'g');
    if (!re) return;
    for (let hit = re.exec(text); hit; hit = re.exec(text)) {
      if (hit[0].length === 0) {
        re.lastIndex += 1;
        continue;
      }
      spans.push({ start: hit.index, end: hit.index + hit[0].length, alt });
    }
  });
  spans.sort((a, b) => a.start - b.start || a.alt - b.alt);
  const pieces: MarkedPiece[] = [];
  let at = 0;
  for (const span of spans) {
    if (span.start < at) continue;
    if (span.start > at) pieces.push({ text: text.slice(at, span.start), alt: null });
    pieces.push({ text: text.slice(span.start, span.end), alt: span.alt });
    at = span.end;
  }
  if (at < text.length) pieces.push({ text: text.slice(at), alt: null });
  return pieces.length > 0 ? pieces : [{ text, alt: null }];
}

/** How many of `values` each alternative catches, in the order of `alternatives`. */
export function countAlternativeHits(
  values: string[],
  alternatives: string[],
  matchMode: string | null | undefined = 'regex',
  caseSensitive = false,
): number[] {
  return alternatives.map((alternative) => {
    const re = alternativeRegExp(alternative, matchMode, caseSensitive, '');
    return re ? values.filter((v) => re.test(v)).length : 0;
  });
}
