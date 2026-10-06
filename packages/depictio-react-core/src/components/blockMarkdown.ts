/**
 * Block-level markdown for the `text` component's body.
 *
 * `inlineMarkdown.ts` handles what goes inside a line; this splits a body into
 * the blocks a landing page or a methods note needs: paragraphs, `#` headings,
 * bullet and numbered lists, pipe tables and `---` rules. Still no HTML and no
 * dependency: the grammar is the small subset dashboard prose uses, and every
 * block's text is handed back to the inline tokenizer, so links keep their
 * scheme allowlist.
 *
 * A body with none of this syntax parses to one paragraph that keeps its line
 * breaks, which is exactly how bodies rendered before blocks existed.
 */

export type Block =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; header: string[]; align: ('left' | 'center' | 'right')[]; rows: string[][] }
  | { type: 'rule' };

const HEADING = /^(#{1,3})\s+(.+?)\s*#*\s*$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

function splitRow(line: string): string[] {
  const inner = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return inner.split('|').map((cell) => cell.trim());
}

function alignOf(cell: string): 'left' | 'center' | 'right' {
  const c = cell.trim();
  if (c.startsWith(':') && c.endsWith(':')) return 'center';
  if (c.endsWith(':')) return 'right';
  return 'left';
}

export function parseBlocks(input: string): Block[] {
  const lines = input.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let para: string[] = [];

  const flush = () => {
    if (para.length) blocks.push({ type: 'paragraph', text: para.join('\n') });
    para = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) {
      flush();
      continue;
    }
    // A rule before lists: `---` would otherwise never be reached, and `***`
    // must not open a bullet.
    if (RULE.test(line)) {
      flush();
      blocks.push({ type: 'rule' });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({
        type: 'heading',
        level: heading[1].length as 1 | 2 | 3,
        text: heading[2],
      });
      continue;
    }
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flush();
      const header = splitRow(line);
      const align = splitRow(lines[i + 1]).map(alignOf);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      i--;
      blocks.push({ type: 'table', header, align, rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flush();
      const ordered = Boolean(numbered);
      const pattern = ordered ? NUMBERED : BULLET;
      const items: string[] = [];
      while (i < lines.length) {
        const m = pattern.exec(lines[i]);
        if (m) {
          items.push(m[1]);
        } else if (items.length && /^\s{2,}\S/.test(lines[i])) {
          // An indented line continues the item above it.
          items[items.length - 1] += ` ${lines[i].trim()}`;
        } else {
          break;
        }
        i++;
      }
      i--;
      blocks.push({ type: 'list', ordered, items });
      continue;
    }
    para.push(line);
  }
  flush();
  return blocks;
}

/** One fact of a fact list: `![](icon:mdi:dna) **Label** value`. */
export interface Fact {
  icon: string | null;
  label: string;
  value: string;
}

const FACT = /^(?:!\[[^\]\n]*\]\(icon:([a-z0-9-]+:[a-z0-9-]+)\)\s*)?\*\*([^*\n]+?)\*\*:?\s+(\S.*)$/;

/**
 * Reads a list item as a fact (an optional icon, a bold label, a value), or
 * null. A list renders as a fact grid only when every item reads, so a list
 * that merely opens one item in bold stays a list.
 */
export function parseFact(item: string): Fact | null {
  const m = FACT.exec(item.trim());
  if (!m) return null;
  return { icon: m[1] ?? null, label: m[2].trim(), value: m[3].trim() };
}

const LINKS_ONLY = /^(?:\s*\[[^\]\n]+\]\([^)\n]+(?:\([^)\n]*\))?[^)\n]*\)\s*[·|,]?)+\s*$/;

/** True for a paragraph made of links and nothing else: a card's footer. */
export function isLinksOnly(text: string): boolean {
  return LINKS_ONLY.test(text);
}

/** One row of a result list: `**41%** Claim — context [Tab](tab:Name)`. */
export interface StatRow {
  stat: string;
  claim: string;
  context: string | null;
  /** The trailing link, as written (`[label](target)`), or null. */
  link: string | null;
}

const STAT_HEAD = /^\*\*([^*\n]{1,16})\*\*\s+(\S.*)$/;
const TRAILING_LINK = /\s*(\[[^\]\n]+\]\((?:[^()\n]|\([^()\n]*\))+\))\s*$/;
const CONTEXT_SPLIT = /\s+[—–]\s+/;

/**
 * Reads a list item as a result row, or null: a bold figure (it must hold a
 * digit), the claim, then a context after an em or en dash and/or a closing
 * link. The figure alone is not enough: `**16S** amplicons` is a fact, not a
 * result, so a row also needs its context or its link.
 */
export function parseStatRow(item: string): StatRow | null {
  const m = STAT_HEAD.exec(item.trim());
  if (!m || !/\d/.test(m[1])) return null;
  let rest = m[2];
  const linkMatch = TRAILING_LINK.exec(rest);
  const link = linkMatch ? linkMatch[1] : null;
  if (linkMatch) rest = rest.slice(0, linkMatch.index);
  const [claim, ...ctx] = rest.split(CONTEXT_SPLIT);
  const context = ctx.length ? ctx.join(' — ').trim() : null;
  if (!claim.trim() || (!link && !context)) return null;
  return { stat: m[1].trim(), claim: claim.trim(), context, link };
}
