/**
 * HMM logo letter heights: a port of `depictio/recipes/lib/hmm.py::letter_heights`,
 * itself a port of HMMER's `src/hmmlogo.c` (`hmmlogo_RelativeEntropy_all`,
 * `hmmlogo_RelativeEntropy_above_bg`). Pure, no DOM.
 *
 * With `p_a` the match emission of letter `a`, `b_a` its background and
 * `lo_a = log2(p_a / b_a)` (letters with `p_a = 0` skipped):
 *
 *     RE_k = sum_a p_a * lo_a                     relative entropy, bits
 *
 * - `relent_all` (hmmlogo's default): `height_a = RE_k * p_a`;
 * - `relent_abovebg`: `height_a = RE_k * p_a / A_k` when `lo_a > 0`, else 0,
 *   with `A_k = sum_{lo_a > 0} p_a`. The column height stays the FULL `RE_k`
 *   (letters below background count negatively in it); it is only
 *   redistributed over the letters above background;
 * - `probability`: `height_a = p_a` (the column height is the mass, 1).
 *
 * The stack height (`info`) is `RE_k` for both entropy modes and the summed
 * probability for `probability`, exactly as the Python returns it.
 *
 * Parity is checked both ways: `heights.test.ts` asserts the numbers of
 * `__fixtures__/heights.json`, which
 * `depictio/tests/unit/recipes/test_hmm_logo_parity.py` recomputes with the
 * Python; that test also parses `BACKGROUND_AMINO` out of this file, so keep
 * the table one `letter: value,` per line.
 */

export type HeightMode = 'relent_abovebg' | 'relent_all' | 'probability';

export const HEIGHT_MODES: readonly HeightMode[] = ['relent_abovebg', 'relent_all', 'probability'];

/** Amino acids (HMMER's 20-letter alphabet, in its order) or DNA / RNA. */
export type LogoAlphabet = 'amino' | 'nucleic';

/** HMMER's amino alphabet, in the order it writes the `HMM` header. */
export const AMINO_ORDER = 'ACDEFGHIKLMNPQRSTVWY';

/**
 * Swiss-Prot 50.8 residue frequencies, the null model of every HMMER3 amino
 * profile (`p7_AminoFrequencies` in hmmer.c = `esl_composition_SW50`), copied
 * from `BACKGROUND_AMINO` in `depictio/recipes/lib/hmm.py`.
 */
export const BACKGROUND_AMINO: Readonly<Record<string, number>> = {
  A: 0.0787945,
  C: 0.01516,
  D: 0.0535222,
  E: 0.0668298,
  F: 0.0397062,
  G: 0.0695071,
  H: 0.0229198,
  I: 0.0590092,
  K: 0.0594422,
  L: 0.0963728,
  M: 0.0237718,
  N: 0.0414386,
  P: 0.0482904,
  Q: 0.0395639,
  R: 0.0540978,
  S: 0.0683364,
  T: 0.0540687,
  V: 0.0673417,
  W: 0.0114135,
  Y: 0.0304133,
};

/** Letters of a DNA or RNA model; HMMER's background there is uniform, 1/K. */
const NUCLEIC_LETTERS = new Set(['A', 'C', 'G', 'T', 'U']);
const NUCLEIC_K = 4;

/**
 * The alphabet a set of letters belongs to: nucleic when every letter is one
 * of A, C, G, T, U, amino otherwise. The profile table carries no `ALPH`
 * column, and an amino model always has rows for its 20 letters (so it holds
 * more than A, C, G and T).
 */
export function detectAlphabet(letters: Iterable<string>): LogoAlphabet {
  let any = false;
  for (const raw of letters) {
    const l = raw.toUpperCase();
    if (!l) continue;
    any = true;
    if (!NUCLEIC_LETTERS.has(l)) return 'amino';
  }
  return any ? 'nucleic' : 'amino';
}

/**
 * Background frequency of each letter, in the given order (`background_frequencies`
 * in hmm.py): Swiss-Prot 50.8 for amino acids, 1/4 for DNA and RNA. A letter
 * outside the 20-letter amino alphabet gets 0: it takes no part in the
 * relative entropy and draws no height in the entropy modes (the Python
 * refuses such a model outright).
 */
export function backgroundFor(letters: readonly string[], alphabet: LogoAlphabet): number[] {
  if (alphabet === 'nucleic') return letters.map(() => 1 / NUCLEIC_K);
  return letters.map((l) => BACKGROUND_AMINO[l.toUpperCase()] ?? 0);
}

export interface ColumnHeights {
  /** Height of each letter, in the input order (bits, or probability). */
  heights: number[];
  /** Stack height: RE_k in bits for the entropy modes, the mass for `probability`. */
  info: number;
}

const clean = (v: number): number => (Number.isFinite(v) && v > 0 ? v : 0);

/** Letter heights of one match state (`letter_heights` for one row of emissions). */
export function columnHeights(
  emissions: ArrayLike<number>,
  background: ArrayLike<number>,
  mode: HeightMode,
): ColumnHeights {
  const k = emissions.length;
  const heights = new Array<number>(k).fill(0);
  if (mode === 'probability') {
    let mass = 0;
    for (let a = 0; a < k; a++) {
      heights[a] = clean(emissions[a]);
      mass += heights[a];
    }
    return { heights, info: mass };
  }
  const logodds = new Array<number>(k).fill(0);
  let relEnt = 0;
  let above = 0;
  for (let a = 0; a < k; a++) {
    const p = clean(emissions[a]);
    const b = clean(background[a]);
    if (p <= 0 || b <= 0) continue;
    logodds[a] = Math.log2(p / b);
    relEnt += p * logodds[a];
    if (logodds[a] > 0) above += p;
  }
  for (let a = 0; a < k; a++) {
    const p = clean(emissions[a]);
    if (clean(background[a]) <= 0) continue;
    if (mode === 'relent_all') {
      heights[a] = relEnt * p;
    } else if (p > 0 && logodds[a] > 0 && above > 0) {
      heights[a] = (relEnt * p) / above;
    }
  }
  return { heights, info: relEnt };
}

export interface LogoHeights {
  /** `heights[i * K + a]`: letter `a` of state index `i`. */
  heights: Float64Array;
  /** Stack height per state index. */
  info: Float64Array;
  /** Largest stack height over the model (0 for an empty one). */
  maxInfo: number;
  /** Per state, the letter indices from the smallest height to the largest:
   *  the drawing order, so the tallest letter ends on top. */
  order: Uint8Array;
}

/** Heights of every state of a profile, plus the stacking order. */
export function logoHeights(
  emissions: Float64Array,
  letterCount: number,
  background: readonly number[],
  mode: HeightMode,
): LogoHeights {
  const k = letterCount;
  const m = k > 0 ? Math.floor(emissions.length / k) : 0;
  const heights = new Float64Array(m * k);
  const info = new Float64Array(m);
  const order = new Uint8Array(m * k);
  let maxInfo = 0;
  const idx = Array.from({ length: k }, (_, a) => a);
  for (let i = 0; i < m; i++) {
    const col = columnHeights(emissions.subarray(i * k, (i + 1) * k), background, mode);
    for (let a = 0; a < k; a++) heights[i * k + a] = col.heights[a];
    info[i] = col.info;
    if (col.info > maxInfo) maxInfo = col.info;
    // Stable: equal heights keep the alphabet order (reversed on screen).
    const sorted = idx.slice().sort((x, y) => col.heights[x] - col.heights[y] || y - x);
    for (let a = 0; a < k; a++) order[i * k + a] = sorted[a];
  }
  return { heights, info, maxInfo, order };
}
