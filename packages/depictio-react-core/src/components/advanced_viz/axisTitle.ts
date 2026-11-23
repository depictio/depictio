/**
 * An axis title that fell back to its column name reads as code:
 * `lane_label`, `neg_log10_padj`, `genome_pct`. When a renderer had no title
 * to use, it printed the column, so the readable version is made here, once,
 * for every advanced figure (applyLayoutTheme runs on all of them).
 *
 * Only a bare lowercase snake_case identifier is rewritten. A title with a
 * space or a capital was written by a person, and a sample id such as
 * `SRR7961102_GSM3415666` (a coverage track's per-sample axis) is data.
 */
const IDENTIFIER = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/;

/** Tokens a word-by-word rewrite would garble. */
const TOKENS: Record<string, string> = {
  pct: '%',
  pd: 'PD',
  id: 'ID',
  aa: 'AA',
  bp: 'bp',
  padj: 'padj',
  pval: 'p-value',
  log2fc: 'log2 FC',
};

/** Suffixes that only say "this is a label or value column". */
const NOISE = new Set(['label', 'col', 'value']);

export function readableAxisTitle(text: string): string {
  if (!IDENTIFIER.test(text)) return text;
  let words = text.split('_');
  let prefix = '';
  if (words[0] === 'neg' && words[1]?.startsWith('log')) {
    prefix = `−${words[1]} `;
    words = words.slice(2);
  } else if (words[0].startsWith('log') && /^log\d+$/.test(words[0])) {
    prefix = `${words[0]} `;
    words = words.slice(1);
  }
  if (words.length > 1 && NOISE.has(words[words.length - 1])) words = words.slice(0, -1);
  const body = words
    .map((w) => TOKENS[w] ?? w)
    .join(' ')
    .replace(/ %$/, ' (%)')
    .replace(/ bp$/, ' (bp)');
  const out = `${prefix}${body}`.trim();
  return prefix ? out : out.charAt(0).toUpperCase() + out.slice(1);
}

/** Rewrite an axis object's title in place of a copy, keeping its font. */
export function withReadableTitle(axis: unknown): unknown {
  if (!axis || typeof axis !== 'object') return axis;
  const a = axis as Record<string, unknown>;
  const title = a.title;
  if (typeof title === 'string') {
    const next = readableAxisTitle(title);
    return next === title ? axis : { ...a, title: next };
  }
  if (title && typeof title === 'object') {
    const t = title as Record<string, unknown>;
    if (typeof t.text !== 'string') return axis;
    const next = readableAxisTitle(t.text);
    return next === t.text ? axis : { ...a, title: { ...t, text: next } };
  }
  return axis;
}
