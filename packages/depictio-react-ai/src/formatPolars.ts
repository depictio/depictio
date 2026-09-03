/**
 * Pretty-print a one-line Polars expression for display.
 *
 * The executor grammar forces the LLM to write a single expression, which
 * arrives as one long line. For reading, split the frame-level method
 * chain onto its own lines and, when a call is still too wide, break its
 * top-level arguments — the classic
 *
 *   df.filter((pl.col('a') == 'x') & (pl.col('b') == 'y'))
 *     .select(
 *       pl.col('c').quantile(0.9).alias('q90'),
 *       pl.col('c').count().alias('n'),
 *     )
 *
 * String- and depth-aware (quotes, parens, brackets) but deliberately not
 * a parser: on anything surprising it degrades to returning the input.
 * Display-only — the executed code is never rewritten.
 */

const MAX_LINE = 72;

type Scan = { depth: number; quote: string | null };

function step(scan: Scan, src: string, i: number): void {
  const ch = src[i];
  if (scan.quote) {
    if (ch === scan.quote && src[i - 1] !== '\\') scan.quote = null;
    return;
  }
  if (ch === "'" || ch === '"') scan.quote = ch;
  else if (ch === '(' || ch === '[') scan.depth++;
  else if (ch === ')' || ch === ']') scan.depth--;
}

/** Split the outermost method chain: `df.filter(..).select(..)` →
 *  ['df', '.filter(..)', '.select(..)']. */
function splitChain(src: string): string[] {
  const parts: string[] = [];
  const scan: Scan = { depth: 0, quote: null };
  let start = 0;
  for (let i = 0; i < src.length; i++) {
    if (
      src[i] === '.' &&
      scan.depth === 0 &&
      !scan.quote &&
      i > start &&
      /^[A-Za-z_]\w*\s*\(/.test(src.slice(i + 1))
    ) {
      parts.push(src.slice(start, i));
      start = i;
    }
    step(scan, src, i);
  }
  parts.push(src.slice(start));
  return parts;
}

/** Break `name(a, b, c)` onto one argument per line when it runs wide. */
function breakArgs(segment: string, indent: string): string[] {
  const line = indent + segment;
  if (line.length <= MAX_LINE) return [line];
  const open = segment.indexOf('(');
  if (open === -1 || !segment.endsWith(')')) return [line];
  const inner = segment.slice(open + 1, -1);
  const args: string[] = [];
  const scan: Scan = { depth: 0, quote: null };
  let start = 0;
  for (let i = 0; i < inner.length; i++) {
    if (inner[i] === ',' && scan.depth === 0 && !scan.quote) {
      args.push(inner.slice(start, i));
      start = i + 1;
    }
    step(scan, inner, i);
  }
  args.push(inner.slice(start));
  if (args.length <= 1) return [line];
  return [
    indent + segment.slice(0, open + 1),
    ...args.map((a) => `${indent}  ${a.trim()},`),
    `${indent})`,
  ];
}

export function formatPolarsCode(code: string): string {
  const src = code.trim();
  // Already short, or already hand-formatted — leave it alone.
  if (src.includes('\n') || src.length <= MAX_LINE) return src;
  try {
    const parts = splitChain(src);
    // Keep a short receiver (`df`, `dc['tag']`) glued to its first call
    // instead of stranding it on a line of its own.
    if (parts.length > 1 && parts[0].length <= 12) {
      parts.splice(0, 2, parts[0] + parts[1]);
    }
    const lines: string[] = [];
    parts.forEach((p, i) => {
      lines.push(...breakArgs(p, i === 0 ? '' : '  '));
    });
    return lines.join('\n');
  } catch {
    return src;
  }
}
