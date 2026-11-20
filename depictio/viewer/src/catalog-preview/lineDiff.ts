/**
 * Line-by-line diff (LCS) for the catalog's module history. Pure TypeScript,
 * no dependency: render YAMLs are a few dozen lines.
 */

export type DiffKind = 'same' | 'add' | 'del';
export interface DiffOp {
  t: DiffKind;
  text: string;
}

const toLines = (s: string | null | undefined): string[] => {
  if (!s) return [];
  return s.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n');
};

/** Diff `a` (old) into `b` (new). */
export function diffLines(a: string | null | undefined, b: string | null | undefined): DiffOp[] {
  const A = toLines(a);
  const B = toLines(b);
  let lo = 0;
  while (lo < A.length && lo < B.length && A[lo] === B[lo]) lo++;
  let ea = A.length;
  let eb = B.length;
  while (ea > lo && eb > lo && A[ea - 1] === B[eb - 1]) {
    ea--;
    eb--;
  }
  const out: DiffOp[] = A.slice(0, lo).map((text) => ({ t: 'same', text }));
  const n = ea - lo;
  const m = eb - lo;
  if (n * m > 4_000_000) {
    // Too large for the table: report the middle as one removal and one addition.
    for (let i = lo; i < ea; i++) out.push({ t: 'del', text: A[i] });
    for (let j = lo; j < eb; j++) out.push({ t: 'add', text: B[j] });
  } else {
    // lcs[i][j] = LCS length of A[lo+i..ea) and B[lo+j..eb)
    const w = m + 1;
    const lcs = new Uint32Array((n + 1) * w);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        lcs[i * w + j] =
          A[lo + i] === B[lo + j]
            ? lcs[(i + 1) * w + j + 1] + 1
            : Math.max(lcs[(i + 1) * w + j], lcs[i * w + j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (A[lo + i] === B[lo + j]) {
        out.push({ t: 'same', text: A[lo + i] });
        i++;
        j++;
      } else if (lcs[(i + 1) * w + j] >= lcs[i * w + j + 1]) {
        out.push({ t: 'del', text: A[lo + i++] });
      } else {
        out.push({ t: 'add', text: B[lo + j++] });
      }
    }
    while (i < n) out.push({ t: 'del', text: A[lo + i++] });
    while (j < m) out.push({ t: 'add', text: B[lo + j++] });
  }
  for (let k = ea; k < A.length; k++) out.push({ t: 'same', text: A[k] });
  return out;
}

export interface RenderLike {
  index: string;
  _yaml?: string | null;
}
export interface RenderDiff {
  index: string;
  status: 'same' | 'changed' | 'added' | 'removed';
  ops: DiffOp[];
}

/** Pair renders by `index`: `from` is the old side, `to` the new one. Renders of
 *  `to` come first (in order), then those only in `from` (removed). */
export function diffRenders(from: RenderLike[], to: RenderLike[]): RenderDiff[] {
  const old = new Map(from.map((r) => [r.index, r]));
  const seen = new Set<string>();
  const out: RenderDiff[] = [];
  for (const r of to) {
    seen.add(r.index);
    const o = old.get(r.index);
    if (!o) {
      out.push({ index: r.index, status: 'added', ops: diffLines('', r._yaml) });
      continue;
    }
    const ops = diffLines(o._yaml, r._yaml);
    out.push({
      index: r.index,
      status: ops.every((x) => x.t === 'same') ? 'same' : 'changed',
      ops,
    });
  }
  for (const r of from) {
    if (!seen.has(r.index)) {
      out.push({ index: r.index, status: 'removed', ops: diffLines(r._yaml, '') });
    }
  }
  return out;
}

export type FoldedOp = DiffOp | { t: 'fold'; count: number };

/** Collapse runs of unchanged lines longer than `2 * ctx + 1`, keeping `ctx` lines
 *  of context around every change. */
export function foldUnchanged(ops: DiffOp[], ctx = 3): FoldedOp[] {
  const keep = new Array<boolean>(ops.length).fill(false);
  ops.forEach((op, i) => {
    if (op.t === 'same') return;
    for (let k = Math.max(0, i - ctx); k <= Math.min(ops.length - 1, i + ctx); k++) keep[k] = true;
  });
  if (!ops.some((o) => o.t !== 'same')) return ops;
  const out: FoldedOp[] = [];
  let hidden = 0;
  ops.forEach((op, i) => {
    if (keep[i]) {
      if (hidden) out.push({ t: 'fold', count: hidden });
      hidden = 0;
      out.push(op);
    } else hidden++;
  });
  if (hidden) out.push({ t: 'fold', count: hidden });
  return out;
}
