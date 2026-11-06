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

/** Where `pattern` first lands in `text`, as `[start, end)`, to mark the
 *  caught part in a list of matches. Read with the browser's regex dialect,
 *  which can differ from the server's on exotic syntax: `null` (nothing
 *  marked) then, never a wrong filter. Empty matches mark nothing. */
export function firstMatchSpan(
  text: string,
  pattern: string,
  matchMode: string | null | undefined = 'regex',
  caseSensitive = false,
): [number, number] | null {
  const source =
    matchMode === 'contains'
      ? pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      : pattern.replace(INLINE_FLAGS, '');
  try {
    const hit = new RegExp(source, caseSensitive ? '' : 'i').exec(text);
    return hit && hit[0].length > 0 ? [hit.index, hit.index + hit[0].length] : null;
  } catch {
    return null;
  }
}
