/**
 * Pure text helpers behind a tile's description display (`ComponentInfo.tsx`):
 * the one-line subtitle under the title, and the paragraphs of the popover.
 *
 * `description` is the single source: the same string feeds both. It may be
 * markdown (the `text` component's grammar, see `blockMarkdown.ts`) or a folded
 * YAML scalar (`>-`) that arrives as one run-on line of three to six sentences.
 * No DOM and no React, so the rules are unit-tested under the node-only vitest.
 */

import { resolveFigureStyle } from '../figureStyle';

/** Characters the subtitle may take at most, whatever the sentence length. */
export const SUBTITLE_MAX_CHARS = 140;

/** Words that end in a period without ending the sentence. Lower case, no dot. */
const ABBREVIATIONS = new Set([
  'e.g',
  'i.e',
  'vs',
  'cf',
  'etc',
  'approx',
  'fig',
  'figs',
  'eq',
  'ca',
  'al',
  'no',
  'resp',
  'incl',
  'st',
  'dr',
  'sp',
  'spp',
  'ref',
  'refs',
]);

/** Markdown syntax a block parser would turn into structure (not prose). */
const STRUCTURAL_LINE = /^\s*(?:#{1,3}\s|[-*+]\s|\d+[.)]\s|\||:{3,}|-{3,}\s*$|\*{3,}\s*$|_{3,}\s*$)/;

/** The labels a paragraph may open with, the way it is shown, and what it makes
 *  of the paragraph. A fixed list on purpose: "Ratio: ..." or "Warning signs: ..."
 *  is prose, and only the conventions the templates use are structure. */
export type SectionKind = 'lead' | 'body' | 'labelled' | 'callout' | 'source';
export type CalloutTone = 'note' | 'warning' | 'caution';

const LABELS: Record<
  string,
  { kind: Exclude<SectionKind, 'lead' | 'body'>; label: string; tone?: CalloutTone; icon: string }
> = {
  // One light line icon a label, from the tabler set the viewer bundles.
  'how to read': { kind: 'labelled', label: 'How to read', icon: 'tabler:eye' },
  'lines and annotations': {
    kind: 'labelled',
    label: 'Lines and annotations',
    icon: 'tabler:chart-line',
  },
  annotations: { kind: 'labelled', label: 'Annotations', icon: 'tabler:tag' },
  'reference lines': { kind: 'labelled', label: 'Reference lines', icon: 'tabler:ruler-2' },
  source: { kind: 'source', label: 'Source', icon: 'tabler:book-2' },
  sources: { kind: 'source', label: 'Sources', icon: 'tabler:book-2' },
  note: { kind: 'callout', label: 'Note', tone: 'note', icon: 'tabler:notes' },
  warning: { kind: 'callout', label: 'Warning', tone: 'warning', icon: 'tabler:alert-triangle' },
  caution: { kind: 'callout', label: 'Caution', tone: 'caution', icon: 'tabler:alert-triangle' },
};

/** A paragraph's opening label: capitalised, then a colon and a space (or the
 *  end of the line). "Note that the median..." has no colon and is prose; so is
 *  a label met mid-paragraph ("e.g. Source: x"), as this only reads the start. */
const LABEL = /^(how to read|lines and annotations|annotations|reference lines|sources?|note|warning|caution)[ \t]*:(?:[ \t]+|(?=\n|$))/i;

/** `LABEL` at the start of a paragraph, the first letter capitalised ("note: x"
 *  is prose). Under the `i` flag the pattern alone would take any case. */
function matchLabel(paragraph: string): RegExpExecArray | null {
  return /^\p{Lu}/u.test(paragraph) ? LABEL.exec(paragraph) : null;
}

/** Markup stripped from a line to read it as plain text. */
export function plainText(markdown: string): string {
  return markdown
    .replace(/!\[([^\]\n]*)\]\([^)\s]*\)/g, '$1') // image / icon / swatch: its alt text
    .replace(/\[([^\]\n]+)\]\([^)\s]+\)/g, '$1') // link: its label
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/\*([^*\n]+)\*/g, '$1')
    .replace(/^\s{0,3}#{1,3}\s+/gm, '')
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Index just past the first sentence of `text`, or -1 when it has one sentence
 * only. A sentence ends at `.`, `!` or `?` followed by whitespace and then
 * something that is not lower case. So "e.g. a ratio" (abbreviation, then
 * lower case), "0.05" (no space), "J. Smith" (an initial) and "vs. control"
 * stay in one piece, and so do periods inside `code` and [link labels].
 */
function sentenceEnd(text: string, from = 0): number {
  let inCode = false;
  let bracket = 0;
  for (let i = from; i < text.length; i++) {
    const ch = text[i];
    if (ch === '`') inCode = !inCode;
    else if (!inCode && ch === '[') bracket++;
    else if (!inCode && ch === ']') bracket = Math.max(0, bracket - 1);
    if (inCode || bracket > 0) continue;
    if (ch !== '.' && ch !== '!' && ch !== '?') continue;
    // Swallow closing quotes and brackets that belong to this sentence.
    let end = i + 1;
    while (end < text.length && /["'”’)\]*_]/.test(text[end])) end++;
    if (end >= text.length) return -1; // the text's own last stop
    if (!/\s/.test(text[end])) continue; // "0.05", "a.b"
    let next = end;
    while (next < text.length && /\s/.test(text[next])) next++;
    if (next >= text.length) return -1;
    if (/\p{Ll}/u.test(text[next])) continue; // "e.g. a", "vs. control"
    if (ch === '.') {
      const word = /([A-Za-z][A-Za-z.]*)$/.exec(text.slice(from, i))?.[1] ?? '';
      if (ABBREVIATIONS.has(word.toLowerCase())) continue;
      // An initial: "J. Smith".
      if (/^[A-Z]$/.test(word)) continue;
    }
    return end;
  }
  return -1;
}

/** The sentences of a single run of text, markup kept, in order. */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  let rest = text.trim();
  while (rest) {
    const end = sentenceEnd(rest);
    if (end < 0) {
      out.push(rest);
      break;
    }
    out.push(rest.slice(0, end).trim());
    rest = rest.slice(end).trim();
  }
  return out;
}

/**
 * The paragraphs of a description. A blank line breaks one; so does a single
 * newline, because in a YAML folded (`>-`) or plain scalar a blank line between
 * paragraphs arrives as one "\n" and nothing else can be a line break.
 *
 * Markdown structure keeps its lines together: a run of list items, table rows
 * or a heading, with the indented lines that continue an item, and a fenced
 * `:::` div through its closing fence. A label alone on its line
 * (`How to read:`) goes with what follows it, a run or one line of text. A
 * plain line after a run is a new paragraph.
 */
export function paragraphsOf(text: string): string[] {
  const out: string[] = [];
  const isBareLabel = (line: string) => {
    const m = matchLabel(line.trim());
    return m !== null && m[0].length >= line.trim().length;
  };
  const isDivOpen = (line: string) => /^\s*:{3,}\s*\S/.test(line);
  const isDivClose = (line: string) => /^\s*:{3,}\s*$/.test(line);
  for (const block of text.replace(/\r\n?/g, '\n').trim().split(/\n\s*\n/)) {
    const lines = block.split('\n').filter((l) => l.trim());
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const next = lines[i + 1];
      // Where a structural run starting at `from` ends (exclusive).
      const runEnd = (from: number) => {
        let j = from;
        if (isDivOpen(lines[j])) {
          j++;
          while (j < lines.length && !isDivClose(lines[j])) j++;
          return Math.min(j + 1, lines.length);
        }
        while (
          j < lines.length &&
          (STRUCTURAL_LINE.test(lines[j]) || (j > from && /^\s/.test(lines[j])))
        ) {
          j++;
        }
        return j;
      };
      if (STRUCTURAL_LINE.test(line)) {
        const end = runEnd(i);
        out.push(lines.slice(i, end).join('\n').trim());
        i = end - 1;
      } else if (isBareLabel(line) && next !== undefined) {
        if (STRUCTURAL_LINE.test(next)) {
          const end = runEnd(i + 1);
          out.push([line.trim(), ...lines.slice(i + 1, end)].join('\n'));
          i = end - 1;
        } else if (!matchLabel(next.trim())) {
          out.push(`${line.trim()}\n${next.trim()}`);
          i++;
        } else out.push(line.trim());
      } else out.push(line.trim());
    }
  }
  return out;
}

/** The first paragraph the subtitle can speak for: the first one that is not a
 *  labelled block (`Source:`, `Note:`...), else the first, label stripped. Up to
 *  the first blank line, or the first line when the paragraph opens on a
 *  structural one (a heading, a list item). */
function leadParagraph(text: string): string {
  const paragraphs = paragraphsOf(text);
  const unlabelled = paragraphs.find((p) => !matchLabel(p.trim()));
  const picked = (unlabelled ?? paragraphs[0] ?? '').trim();
  const body = unlabelled === undefined ? picked.slice(matchLabel(picked)?.[0].length ?? 0).trim() : picked;
  const lines = body.split('\n');
  return STRUCTURAL_LINE.test(lines[0] ?? '') ? (lines[0] ?? '') : body;
}

/**
 * The subtitle of a description: its first sentence as plain text, on one line.
 *
 * - Only the first paragraph is read, so a title-like first line with no full
 *   stop never swallows the paragraph under it.
 * - Text with no stop is its own first sentence.
 * - A first sentence longer than `maxChars` is cut at the last word that fits
 *   and ends with an ellipsis, so one very long sentence cannot fill the line.
 */
export function firstSentence(description: string, maxChars = SUBTITLE_MAX_CHARS): string {
  const lead = leadParagraph(description);
  if (!lead) return '';
  const end = sentenceEnd(lead);
  const sentence = plainText(end < 0 ? lead : lead.slice(0, end));
  if (sentence.length <= maxChars) return sentence;
  const room = sentence.slice(0, maxChars - 1);
  const atWord = room.replace(/\s+\S*$/, '');
  // A single unbroken token longer than the cap is cut where it stands.
  const cut = atWord.length >= maxChars / 2 ? atWord : room;
  return `${cut.replace(/[\s,;:.\-–—]+$/, '')}…`;
}

/**
 * What the subtitle drops. False when the description is a single sentence that
 * the subtitle shows whole (markup aside), so the popover would only repeat it.
 */
export function hasMoreThanSubtitle(description: string, maxChars = SUBTITLE_MAX_CHARS): boolean {
  const all = plainText(description);
  return all !== '' && firstSentence(description, maxChars) !== all;
}

/**
 * The popover's source text, broken into short paragraphs when the author did
 * not break it themselves. A folded YAML scalar (`>-`) is one line of several
 * sentences; read as one paragraph it is a wall. That single line becomes the
 * lead sentence (the subtitle's own) on its own, then the rest two sentences to
 * a paragraph. Text with a newline of its own, or any list, heading or table
 * syntax, is the author's structure and is returned untouched.
 */
export function readableParagraphs(description: string): string {
  const text = description.replace(/\r\n?/g, '\n').trim();
  if (!text || text.includes('\n') || STRUCTURAL_LINE.test(text) || matchLabel(text)) return text;
  const sentences = splitSentences(text);
  if (sentences.length < 3) return text;
  const paragraphs = [sentences[0]];
  for (let i = 1; i < sentences.length; i += 2) {
    paragraphs.push(sentences.slice(i, i + 2).join(' '));
  }
  return paragraphs.join('\n\n');
}

export interface Section {
  kind: SectionKind;
  /** The label shown over a labelled, callout or source section. */
  label?: string;
  /** The line icon drawn before the label. */
  icon?: string;
  tone?: CalloutTone;
  /** Markdown of the section, its label taken off. */
  text: string;
}

/**
 * Upper-cases the first letter of the text after a label ("the dotted line"
 * becomes "The dotted line"), as it is a sentence of its own once the label is
 * a heading. Only a plain lower-case word is touched: `pH`, `mRNA`, `log2`,
 * `p-value`, `e.g.` and a leading code span or link keep their spelling. The
 * source string is never changed; this is what the popover draws.
 */
export function capitalizeLead(text: string): string {
  return /^(?:a|[a-z][a-z'’]+|[a-z]{2,}(?:-[a-z]{2,})+)(?=\s|$)/.test(text) ? text[0].toUpperCase() + text.slice(1) : text;
}

/**
 * The description as the sections the popover draws.
 *
 * `description` stays one string. Paragraphs are separated by blank lines
 * (YAML `|`, or a folded scalar with an empty line between them). The first
 * paragraph is the LEAD; a paragraph opening on a known label (`How to read:`,
 * `Lines and annotations:`, `Note:`, `Source:`...) is a labelled block, a
 * callout or the source footer; any other is body text. A single run-on line
 * with no label is split by sentences first (see `readableParagraphs`), so its
 * first sentence leads. Paragraphs with markdown structure of their own (a
 * list, a heading, a table) keep it: their text is returned as written and is
 * never taken for the lead.
 */
export function parseSections(description: string): Section[] {
  const paragraphs = paragraphsOf(readableParagraphs(description));
  const out: Section[] = [];
  paragraphs.forEach((paragraph) => {
    const match = matchLabel(paragraph);
    if (match) {
      const spec = LABELS[match[1].toLowerCase()];
      out.push({
        kind: spec.kind,
        label: spec.label,
        icon: spec.icon,
        tone: spec.tone,
        text:
          spec.kind === 'source'
            ? paragraph.slice(match[0].length).trim()
            : capitalizeLead(paragraph.slice(match[0].length).trim()),
      });
      return;
    }
    const lead =
      out.length === 0 && !STRUCTURAL_LINE.test(paragraph.split('\n')[0] ?? '');
    out.push({ kind: lead ? 'lead' : 'body', text: paragraph });
  });
  return out;
}

/** Entries of a source block: split at semicolons outside parentheses and at
 *  line breaks (a leading bullet dropped), so "Smith 2020; Lee 2021" is two
 *  citations and "(Nature; 2020)" is one. */
export function splitSources(text: string): string[] {
  const entries: string[] = [];
  for (const line of text.split('\n')) {
    let depth = 0;
    let current = '';
    for (const ch of line.replace(/^\s*[-*+]\s+/, '')) {
      if (ch === '(') depth++;
      else if (ch === ')') depth = Math.max(0, depth - 1);
      if (ch === ';' && depth === 0) {
        entries.push(current);
        current = '';
      } else current += ch;
    }
    entries.push(current);
  }
  return entries.map((e) => e.trim()).filter(Boolean);
}

/** A markdown link (kept), a bare http(s) URL, or a `doi:` token. */
const SOURCE_TOKEN = /\[[^\]\n]+\]\([^)\s]+\)|https?:\/\/[^\s<>]+|doi:[ \t]*10\.\d{4,9}\/[^\s;,<>]+/gi;

/** `)` ending a token that opened no `(`, and sentence punctuation, are the
 *  citation's own, not the link's. */
function trimLinkEnd(token: string): string {
  let out = token;
  for (;;) {
    const last = out[out.length - 1];
    if (last && '.,;:!?'.includes(last)) out = out.slice(0, -1);
    else if (
      last === ')' &&
      (out.match(/\)/g) ?? []).length > (out.match(/\(/g) ?? []).length
    ) {
      out = out.slice(0, -1);
    } else return out;
  }
}

const encodeParens = (href: string) => href.replace(/\(/g, '%28').replace(/\)/g, '%29');

/**
 * One source entry as markdown: every bare http(s) URL and `doi:10.x/y` token
 * becomes a link (a DOI to https://doi.org/10.x/y); the rest of the citation,
 * and links the author already wrote, stay as they are.
 */
export function linkifySource(entry: string): string {
  return entry.replace(SOURCE_TOKEN, (token) => {
    if (token.startsWith('[')) return token;
    const trimmed = trimLinkEnd(token);
    const tail = token.slice(trimmed.length);
    if (/^doi:/i.test(trimmed)) {
      const doi = trimmed.replace(/^doi:\s*/i, '');
      return `[doi:${doi}](${encodeParens(`https://doi.org/${doi}`)})${tail}`;
    }
    return `[${trimmed}](${encodeParens(trimmed)})${tail}`;
  });
}

/**
 * Whether the tile's own header row carries the description (a subtitle and an
 * info icon next to the title). The chrome's toolbar icon is then left out, so
 * a tile has one place that opens its description and not two.
 *
 * True where the renderer draws a title row: a figure in the default style, a
 * table, an advanced viz outside the `minimal` style (whose header shows the
 * short `subtitle` field instead). Cards, maps, images and the rest keep the
 * toolbar icon. Renderers and the chrome both ask this, so they cannot drift.
 */
export function titleCarriesDescription(
  componentType: string,
  metadata: { title?: unknown; figure_style?: unknown; description?: unknown },
): boolean {
  const description = typeof metadata.description === 'string' ? metadata.description.trim() : '';
  if (!description) return false;
  const minimal = resolveFigureStyle(metadata.figure_style) === 'minimal';
  switch (componentType) {
    case 'advanced_viz':
      // The dispatch titles every advanced viz, falling back to its kind.
      return !minimal;
    case 'figure':
      return !minimal && Boolean(metadata.title);
    case 'table':
      return Boolean(metadata.title);
    default:
      return false;
  }
}

/**
 * A value in prose: a number, with the sign or comparison before it and the
 * unit after it. It is what a reader scans a reference line's description for
 * ("1 Mb", "95 %", "<= 0.5", "10X", "500 nM"). Digits that are part of a name
 * (`log10`, `Q40`, `v2`, `tabler:x1`) or of an identifier with dots are not.
 */
const VALUE =
  /(?<![\w.:/-])(?:[<>≤≥~±+-]=?\s?)?\d+(?:[.,]\d+)*(?:\s?(?:%|X\b|x\b|[kKMG]b\b|bp\b|nM\b|µM\b|reads?\b|bins?\b|-fold\b))?(?![\w])/gu;

export interface ValueSegment {
  text: string;
  value: boolean;
}

/** The text cut into plain runs and values, in order, nothing lost. */
export function splitValues(text: string): ValueSegment[] {
  const out: ValueSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(VALUE)) {
    const at = match.index ?? 0;
    if (at > last) out.push({ text: text.slice(last, at), value: false });
    out.push({ text: match[0], value: true });
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), value: false });
  return out;
}

/** The labelled sections whose values are set apart: the ones that describe
 *  what is drawn on the figure. */
export const VALUE_SECTIONS: ReadonlySet<string> = new Set([
  'Lines and annotations',
  'Annotations',
  'Reference lines',
]);
