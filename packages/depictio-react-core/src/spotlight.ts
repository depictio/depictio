/**
 * Dashboard search: the index and the ranking behind the viewer's Cmd/Ctrl+K
 * palette.
 *
 * A dashboard family can run to a dozen tabs of thirty components each, and
 * the only way to find "the plot with the sunburst" used to be opening tabs
 * until it showed up. The palette answers from what the dashboard already says
 * about itself: every tab's name and description, and for every component its
 * title, subtitle and description, what kind of thing it is, the columns it
 * binds, the section it sits in and, for a text tile, its prose.
 *
 * Plain logic on purpose — no React, no DOM — so the ranking is unit-tested
 * and the palette only has to draw what comes back. Matching is "fuzzy-lite":
 * a word typed is found where a field starts with it, then where one of its
 * words does, then anywhere inside it, and where it is found counts as much as
 * how: a hit in the title outranks the same hit in a text body. No edit-distance
 * matching, and no search library: a typo finds nothing, which beats a list of
 * near-misses ranked by a score nobody can read.
 */
import type { StoredMetadata } from './api';
import { componentTypeVisual } from './componentTypeMeta';
import { interactiveTitle } from './components/interactive/titles';

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------

const RULE_LINE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE_SEP_LINE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
const FENCE_LINE = /^\s*(:{3,}|`{3,}|~{3,})/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;

/** One line of a body, without its block syntax. */
function stripBlockSyntax(line: string): string {
  if (FENCE_LINE.test(line) || RULE_LINE.test(line) || TABLE_SEP_LINE.test(line)) return '';
  let out = line
    .replace(/^\s*#{1,6}\s+/, '')
    .replace(/\s+#+\s*$/, '')
    .replace(/^\s*>\s?/, '')
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/, '');
  // A table row reads as its cells, one after the other.
  if (TABLE_ROW.test(line)) {
    out = out
      .trim()
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((cell) => cell.trim())
      .filter(Boolean)
      .join(' · ');
  }
  return out;
}

/**
 * The words a text tile shows, without the markdown it is written in.
 *
 * Covers the syntax `blockMarkdown.ts` and `inlineMarkdown.ts` render —
 * headings, lists, pipe tables, rules, `:::` fences, links (tab links
 * included), inline icons and colour swatches, emphasis and code — plus stray
 * HTML. A link keeps its label and a swatch its legend text; an icon has no
 * words and goes. The result is one line, so it can be searched and cut into a
 * snippet without a block boundary showing up as a gap.
 */
export function stripMarkdown(md: string | null | undefined): string {
  if (!md) return '';
  let s = md.replace(/\r\n?/g, '\n');
  s = s.split('\n').map(stripBlockSyntax).join('\n');
  s = s
    .replace(/<\/?[A-Za-z][^>\n]*>/g, ' ')
    // Images: `![](icon:mdi:dna)` has no alt text and vanishes; a swatch's alt
    // is the category it is the key of.
    .replace(/!\[([^\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)/g, '$1')
    // Links, `tab:` targets with a parenthesised name included.
    .replace(/\[([^\]\n]+)\]\((?:[^()\n]|\([^()\n]*\))*\)/g, '$1')
    .replace(/`([^`\n]*)`/g, '$1')
    .replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, '$2')
    .replace(/(^|[^\w*\\])\*(?=\S)([^*\n]*?\S)\*(?![\w*])/g, '$1$2')
    .replace(/(^|[^\w\\])_(?=\S)([^_\n]*?\S)_(?!\w)/g, '$1$2')
    .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '$1')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\\([\\`*_{}[\]()#+\-.!|>~:])/g, '$1');
  return s.replace(/\s+/g, ' ').trim();
}

/** The first line of a body with words on it, as a title for a text tile that
 *  has none: usually its heading. Cut at a word near `max` characters. */
function leadLine(md: string, max = 60): string {
  for (const raw of md.replace(/\r\n?/g, '\n').split('\n')) {
    const line = stripMarkdown(raw);
    if (!line) continue;
    if (line.length <= max) return line;
    const cut = line.slice(0, max);
    const space = cut.lastIndexOf(' ');
    return `${(space > max / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
  }
  return '';
}

// ---------------------------------------------------------------------------
// What a component is, in words
// ---------------------------------------------------------------------------

/** Kinds whose name does not survive `humanize`: acronyms, and the odd kind
 *  id that reads wrong spelled out. Everything else is its id in sentence
 *  case, which is how the builder lists it too. */
const KIND_LABELS: Record<string, string> = {
  scatter_3d: '3D scatter',
  line_3d: '3D line',
  ecdf: 'ECDF',
  imshow: 'Image',
  qq: 'QQ plot',
  ma: 'MA plot',
  pca: 'PCA',
  umap: 'UMAP',
  da_barplot: 'DA barplot',
  upset_plot: 'UpSet plot',
  roc_pr_curve: 'ROC / PR curve',
  pr_benchmark: 'PR benchmark',
  gsea_running_score: 'GSEA running score',
  scatter_xy: 'Scatter',
  MultiSelect: 'Multi-select',
};

/** `stacked_taxonomy` → "Stacked taxonomy", `RangeSlider` → "Range slider". */
export function humanizeKind(raw: string): string {
  if (KIND_LABELS[raw]) return KIND_LABELS[raw];
  const words = raw
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

/** Component types whose result reads better under another word than their
 *  type grid label: a reader looks for a "filter", not an "interactive". */
const TYPE_RESULT_LABELS: Record<string, string> = {
  interactive: 'Filter',
};

/**
 * What a component is, as one or two words a reader would type: the chart kind
 * for figures and advanced visualisations ("Sunburst", "Volcano"), the type for
 * everything else ("Card", "Table", "Filter").
 */
export function componentKindLabel(m: StoredMetadata): string {
  const type = m.component_type || '';
  if (type === 'figure' && str(m.visu_type)) return humanizeKind(str(m.visu_type));
  if (type === 'advanced_viz' && str(m.viz_kind)) return humanizeKind(str(m.viz_kind));
  return TYPE_RESULT_LABELS[type] ?? componentTypeVisual(type).label;
}

/** Figure arguments that name a column. */
const FIGURE_COLUMN_KEYS = [
  'x',
  'y',
  'z',
  'color',
  'size',
  'symbol',
  'facet_col',
  'facet_row',
  'names',
  'values',
  'path',
  'parents',
  'ids',
  'hover_name',
  'hover_data',
  'text',
  'line_group',
  'dimensions',
  'lat',
  'lon',
  'locations',
  'animation_frame',
];

/**
 * The data columns a component binds, in the order it names them: a card's or
 * a filter's column, a figure's axes and colour, a visualisation's role
 * columns, a map's coordinates, a table's column allowlist.
 */
export function boundColumns(m: StoredMetadata): string[] {
  const out: string[] = [];
  const add = (v: unknown): void => {
    if (typeof v === 'string') {
      if (v.trim()) out.push(v.trim());
    } else if (Array.isArray(v)) {
      for (const item of v) add(item);
    }
  };
  add(m.column_name);
  for (const [key, value] of Object.entries(m)) {
    if (key !== 'column_name' && (key === 'columns' || /_columns?$/.test(key))) add(value);
  }
  const kwargs = m.dict_kwargs;
  if (kwargs && typeof kwargs === 'object' && !Array.isArray(kwargs)) {
    for (const key of FIGURE_COLUMN_KEYS) add((kwargs as Record<string, unknown>)[key]);
  }
  const config = m.config;
  if (config && typeof config === 'object' && !Array.isArray(config)) {
    for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
      if (/_cols?$/.test(key)) add(value);
    }
  }
  return [...new Set(out)];
}

/** A card's own title when it has none: mirrors `inferCardTitle` in
 *  ComponentRenderer, which draws it. */
function cardTitle(m: StoredMetadata): string {
  const aggregation = str(m.aggregation);
  const column = str(m.column_name);
  if (aggregation && column) {
    return `${aggregation.charAt(0).toUpperCase()}${aggregation.slice(1)} of ${column}`;
  }
  return column || 'Metric';
}

/**
 * The name a component is listed under: its title, else what the tile itself
 * shows in its place (a filter's "Select on island", a card's "Mean of
 * depth", a text tile's heading), else what it is and what it plots.
 */
export function componentTitle(m: StoredMetadata): string {
  const own = str(m.title);
  if (own) return own;
  switch (m.component_type) {
    case 'interactive': {
      const title = interactiveTitle(m);
      if (title) return title;
      break;
    }
    case 'card':
      return cardTitle(m);
    case 'text': {
      const lead = leadLine(str(m.body));
      if (lead) return lead;
      break;
    }
    case 'multiqc': {
      const plot = str(m.selected_plot) || str(m.selected_module);
      if (plot) return plot;
      break;
    }
    case 'highlight': {
      const source = str(m.source_component);
      if (source) return source;
      break;
    }
  }
  const kind = componentKindLabel(m);
  const columns = boundColumns(m).slice(0, 2);
  return columns.length ? `${kind} of ${columns.join(' and ')}` : kind;
}

// ---------------------------------------------------------------------------
// The index
// ---------------------------------------------------------------------------

/** One tab of the family, as the index reads it. */
export interface SpotlightTab {
  id: string;
  /** The displayed name: the sidebar pill's label. */
  label: string;
  /** The tab's one-line description (its `subtitle`). */
  description?: string | null;
  /** The sidebar group the tab is listed under. */
  group?: string | null;
  /** The tab's components. Absent while they are still loading: the tab is
   *  searchable by name already, its components once they arrive. */
  components?: StoredMetadata[];
}

/** Where in an entry a word was found. Several fields may share a name — one
 *  per bound column, one per kind label — so each matches on its own. */
export type SpotlightFieldName =
  | 'title'
  | 'subtitle'
  | 'description'
  | 'kind'
  | 'column'
  | 'section'
  | 'body';

export interface SpotlightField {
  name: SpotlightFieldName;
  text: string;
  /** `text` folded for matching (lower case, accents dropped). Exactly as
   *  long as `text`, so a match position in one is a position in the other. */
  folded: string;
}

export interface SpotlightEntry {
  kind: 'tab' | 'component';
  /** Unique across the family: `tab:<id>`, `component:<tab id>:<index>`. */
  key: string;
  tabId: string;
  tabLabel: string;
  /** The component's index; absent on a tab entry. */
  index?: string;
  /** The component's `component_type`; absent on a tab entry. */
  componentType?: string;
  /** The name the result row shows. */
  title: string;
  /** What it is, in a word or two: "Sunburst", "Card", "Filter", "Tab". */
  kindLabel: string;
  /** The section a component sits in, or the group a tab is listed under. */
  section: string | null;
  fields: SpotlightField[];
}

/** Lower case with accents dropped, one code unit for one code unit, so that
 *  a position in the folded string is the same position in the original. */
export function foldText(s: string): string {
  let out = '';
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    const folded = c.normalize('NFD').charAt(0).toLowerCase();
    out += folded.length === 1 ? folded : c;
  }
  return out;
}

function field(name: SpotlightFieldName, text: string): SpotlightField | null {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean ? { name, text: clean, folded: foldText(clean) } : null;
}

function compact<T>(items: (T | null)[]): T[] {
  return items.filter((x): x is T => x !== null);
}

function tabEntry(tab: SpotlightTab): SpotlightEntry {
  const group = str(tab.group) || null;
  return {
    kind: 'tab',
    key: `tab:${tab.id}`,
    tabId: tab.id,
    tabLabel: tab.label,
    title: tab.label,
    kindLabel: 'Tab',
    section: group,
    fields: compact([
      field('title', tab.label),
      field('description', str(tab.description)),
      group ? field('section', group) : null,
    ]),
  };
}

function componentEntry(tab: SpotlightTab, m: StoredMetadata): SpotlightEntry {
  const type = m.component_type || '';
  const title = componentTitle(m);
  const kindLabel = componentKindLabel(m);
  const section = str(m.section) || null;
  // Every word a reader might call it by: the result label, the type grid's
  // label ("Interactive", "Advanced viz"), the control or chart it is, and a
  // MultiQC tile's module and plot.
  const kinds = new Set(
    [
      kindLabel,
      componentTypeVisual(type).label,
      str(m.interactive_component_type) && humanizeKind(str(m.interactive_component_type)),
      str(m.visu_type) && humanizeKind(str(m.visu_type)),
      str(m.viz_kind) && humanizeKind(str(m.viz_kind)),
      str(m.selected_module),
      str(m.selected_plot),
    ].filter(Boolean),
  );
  return {
    kind: 'component',
    key: `component:${tab.id}:${m.index}`,
    tabId: tab.id,
    tabLabel: tab.label,
    index: m.index,
    componentType: type,
    title,
    kindLabel,
    section,
    fields: compact([
      field('title', title),
      field('subtitle', str(m.subtitle)),
      field('subtitle', str(m.caption)),
      field('description', str(m.description)),
      ...[...kinds].map((k) => field('kind', k)),
      ...boundColumns(m).map((c) => field('column', c)),
      section ? field('section', section) : null,
      type === 'text' ? field('body', stripMarkdown(str(m.body))) : null,
    ]),
  };
}

/** Every tab of the family and every component on the tabs loaded so far. */
export function buildSpotlightIndex(tabs: SpotlightTab[]): SpotlightEntry[] {
  const entries: SpotlightEntry[] = [];
  for (const tab of tabs) {
    entries.push(tabEntry(tab));
    for (const m of tab.components ?? []) {
      if (m && typeof m.index === 'string' && m.index) entries.push(componentEntry(tab, m));
    }
  }
  return entries;
}

// ---------------------------------------------------------------------------
// Ranking
// ---------------------------------------------------------------------------

/** How much a hit in each field is worth, against a hit in the title. */
const FIELD_WEIGHTS: Record<SpotlightFieldName, number> = {
  title: 1,
  subtitle: 0.65,
  kind: 0.6,
  column: 0.55,
  description: 0.5,
  section: 0.5,
  body: 0.4,
};

/** How good a match is, by where the word was found. */
const QUALITY = {
  /** The whole field is the word: "Taxonomy" for `taxonomy`. */
  exact: 1,
  /** The field starts with it: "Taxonomy bar" for `tax`. */
  prefix: 0.9,
  /** One of its words does: "Read depth" for `dep`. */
  wordStart: 0.75,
  /** Anywhere inside a word: "Metadata" for `data`. */
  inside: 0.4,
};

/** Below this length a word inside another word is noise: `e` is in nearly
 *  every title, `ta` in a fair share. Short words count from a word start. */
const MIN_INSIDE_LENGTH = 3;

/** A multi-word query found as written in the title. */
const PHRASE_BONUS = 0.15;

const WORD_CHAR = /[\p{L}\p{N}]/u;

interface TokenMatch {
  quality: number;
  pos: number;
}

/** Where `token` matches best in `folded`, or null if it does not. */
function matchToken(folded: string, token: string): TokenMatch | null {
  const first = folded.indexOf(token);
  if (first < 0) return null;
  if (first === 0) {
    return { quality: folded.length === token.length ? QUALITY.exact : QUALITY.prefix, pos: 0 };
  }
  for (let p = first; p >= 0; p = folded.indexOf(token, p + 1)) {
    if (!WORD_CHAR.test(folded[p - 1])) return { quality: QUALITY.wordStart, pos: p };
  }
  return token.length >= MIN_INSIDE_LENGTH ? { quality: QUALITY.inside, pos: first } : null;
}

export type TextRange = [start: number, end: number];

export interface SpotlightSnippet {
  field: SpotlightFieldName;
  text: string;
  /** Matched spans of `text`; empty when the snippet is context rather than
   *  the match (a title hit, shown with the description under it). */
  ranges: TextRange[];
}

export interface SpotlightHit {
  entry: SpotlightEntry;
  score: number;
  /** Matched spans of `entry.title`, to emphasise. */
  titleRanges: TextRange[];
  /** The match outside the title, cut to a line, or the description when the
   *  title held every word; null when there is neither. */
  snippet: SpotlightSnippet | null;
}

/** Query words, folded, each once. */
export function queryTokens(query: string): string[] {
  return [...new Set(foldText(query).split(/\s+/).filter(Boolean))];
}

function mergeRanges(ranges: TextRange[]): TextRange[] {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out: TextRange[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else out.push([r[0], r[1]]);
  }
  return out;
}

/** The spans of `folded` the query's words match, each at its best place. */
function rangesIn(folded: string, tokens: string[]): TextRange[] {
  const ranges: TextRange[] = [];
  for (const token of tokens) {
    const m = matchToken(folded, token);
    if (m) ranges.push([m.pos, m.pos + token.length]);
  }
  return mergeRanges(ranges);
}

/** Room for a snippet in one dimmed line. */
const SNIPPET_LENGTH = 90;
/** How much of the text before the match the snippet keeps. */
const SNIPPET_LEAD = 28;

/** `text` cut to a line around its first match, ranges moved with it. */
export function snippetAround(
  text: string,
  ranges: TextRange[],
  length = SNIPPET_LENGTH,
): { text: string; ranges: TextRange[] } {
  if (text.length <= length) return { text, ranges };
  const anchor = ranges[0]?.[0] ?? 0;
  let start = Math.max(0, Math.min(anchor - SNIPPET_LEAD, text.length - length));
  // Start on a word rather than inside one, when there is a space close by.
  if (start > 0) {
    const space = text.indexOf(' ', start);
    if (space >= 0 && space < anchor && space - start < 12) start = space + 1;
  }
  let end = Math.min(text.length, start + length);
  // End on a word too, but never before the match the snippet is there for.
  if (end < text.length) {
    const space = text.lastIndexOf(' ', end);
    const firstMatchEnd = ranges[0]?.[1] ?? 0;
    if (space > start + length / 2 && space >= firstMatchEnd) end = space;
  }
  const lead = start > 0 ? '…' : '';
  const tail = end < text.length ? '…' : '';
  const shift = lead.length - start;
  return {
    text: `${lead}${text.slice(start, end)}${tail}`,
    ranges: ranges
      .filter(([a, b]) => a >= start && b <= end)
      .map(([a, b]) => [a + shift, b + shift] as TextRange),
  };
}

/** Fields that never make a snippet: the result row shows them already. */
const NO_SNIPPET: ReadonlySet<SpotlightFieldName> = new Set(['title', 'kind', 'section']);

function contextSnippet(entry: SpotlightEntry): SpotlightSnippet | null {
  const context =
    entry.fields.find((f) => f.name === 'subtitle') ??
    entry.fields.find((f) => f.name === 'description') ??
    entry.fields.find((f) => f.name === 'body');
  if (!context) return null;
  const cut = snippetAround(context.text, []);
  return { field: context.name, text: cut.text, ranges: [] };
}

function scoreEntry(entry: SpotlightEntry, tokens: string[], phrase: string): SpotlightHit | null {
  let total = 0;
  // The field that carries each word best, kept to pick the snippet.
  let snippetField: SpotlightField | null = null;
  let snippetWeight = 0;
  for (const token of tokens) {
    let best = 0;
    let bestField: SpotlightField | null = null;
    for (const f of entry.fields) {
      const m = matchToken(f.folded, token);
      if (!m) continue;
      const value = FIELD_WEIGHTS[f.name] * m.quality;
      if (value > best) {
        best = value;
        bestField = f;
      }
    }
    if (!bestField) return null;
    total += best;
    if (!NO_SNIPPET.has(bestField.name) && best > snippetWeight) {
      snippetWeight = best;
      snippetField = bestField;
    }
  }
  const titleFolded = foldText(entry.title);
  let score = total / tokens.length;
  if (tokens.length > 1 && titleFolded.includes(phrase)) score += PHRASE_BONUS;

  let snippet: SpotlightSnippet | null;
  if (snippetField) {
    const cut = snippetAround(snippetField.text, rangesIn(snippetField.folded, tokens));
    snippet = { field: snippetField.name, ...cut };
  } else {
    snippet = contextSnippet(entry);
  }
  return { entry, score, titleRanges: rangesIn(titleFolded, tokens), snippet };
}

function compareHits(a: SpotlightHit, b: SpotlightHit): number {
  return (
    b.score - a.score ||
    (a.entry.kind === b.entry.kind ? 0 : a.entry.kind === 'tab' ? -1 : 1) ||
    a.entry.title.length - b.entry.title.length ||
    a.entry.title.localeCompare(b.entry.title)
  );
}

/**
 * The entries matching every word of `query`, best first.
 *
 * An empty query lists the tabs, in family order, so the palette is a tab
 * switcher before it is a search.
 */
export function searchSpotlight(entries: SpotlightEntry[], query: string): SpotlightHit[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) {
    return entries
      .filter((e) => e.kind === 'tab')
      .map((entry) => ({ entry, score: 0, titleRanges: [], snippet: contextSnippet(entry) }));
  }
  const phrase = tokens.join(' ');
  const hits: SpotlightHit[] = [];
  for (const entry of entries) {
    const hit = scoreEntry(entry, tokens, phrase);
    if (hit) hits.push(hit);
  }
  return hits.sort(compareHits);
}

// ---------------------------------------------------------------------------
// Grouping
// ---------------------------------------------------------------------------

export interface SpotlightGroup {
  tabId: string;
  tabLabel: string;
  isCurrent: boolean;
  /** The tab's own entry first when it matched, then its components. */
  hits: SpotlightHit[];
  /** Matches left out past the per-tab cap. */
  more: number;
}

/** Rows per tab before the rest are counted rather than listed. */
export const SPOTLIGHT_PER_TAB = 8;

/**
 * Hits grouped by tab: the tab being read first, the others in family order.
 * Inside a group the tab itself leads, then its components best first.
 */
export function groupSpotlightHits(
  hits: SpotlightHit[],
  tabs: { id: string; label: string }[],
  currentTabId: string | null,
  perTab = SPOTLIGHT_PER_TAB,
): SpotlightGroup[] {
  const order = new Map(tabs.map((t, i) => [t.id, i]));
  const byTab = new Map<string, SpotlightHit[]>();
  for (const hit of hits) {
    const list = byTab.get(hit.entry.tabId);
    if (list) list.push(hit);
    else byTab.set(hit.entry.tabId, [hit]);
  }
  const rank = (id: string) =>
    id === currentTabId ? -1 : (order.get(id) ?? Number.MAX_SAFE_INTEGER);
  return [...byTab.entries()]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([tabId, list]) => {
      const ordered = [
        ...list.filter((h) => h.entry.kind === 'tab'),
        ...list.filter((h) => h.entry.kind !== 'tab'),
      ];
      return {
        tabId,
        tabLabel: list[0].entry.tabLabel,
        isCurrent: tabId === currentTabId,
        hits: ordered.slice(0, perTab),
        more: Math.max(0, ordered.length - perTab),
      };
    });
}
