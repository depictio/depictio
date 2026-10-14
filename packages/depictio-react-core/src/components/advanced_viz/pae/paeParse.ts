/**
 * Predicted aligned error (PAE) matrices from the formats structure predictors
 * publish, as one square `Float32Array`.
 *
 * Mirrors `depictio/recipes/lib/pae.py::read_pae` (same formats, same errors),
 * so a file the ingest recipe accepts is a file the tile draws:
 *
 * - nf-core/proteinfold `paes/<name>_pae.tsv`: whitespace, tab, comma or
 *   semicolon separated rows, an optional header row of names skipped;
 * - AlphaFold DB v3/v4: `[{"predicted_aligned_error": [[...]], "max_predicted_aligned_error": 31.75}]`;
 * - ColabFold: a bare `{"predicted_aligned_error": [[...]]}` or `{"pae": [[...]]}`;
 * - AlphaFold DB v1: `[{"residue1": [...], "residue2": [...], "distance": [...]}]`,
 *   the matrix flattened into 1-based residue pairs.
 *
 * Row `i` is the aligned residue, column `j` the scored residue: `values[i * n + j]`
 * is the expected position error (Å) of residue j when the predicted and true
 * structures are aligned on residue i. Gzip is handled before this module, by the
 * object loader (`molecule/objectText.ts` gunzips by magic number), so the
 * parser only ever sees text. Pure, unit-tested in `paeParse.test.ts`.
 */

export interface PaeMatrix {
  /** Row-major `n * n` errors in Å; row = aligned residue, column = scored residue. */
  values: Float32Array;
  n: number;
  /** Largest finite value of the matrix (0 when none is finite). */
  max: number;
  /** The maximum the file declares (`max_predicted_aligned_error`, or
   *  ColabFold's `max_pae`), when it declares one. */
  declaredMax: number | null;
}

/** A file that holds no readable square matrix; the message says why. */
export class PaeParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PaeParseError';
  }
}

/** Keys under which a JSON object may hold the matrix (`_MATRIX_KEYS`). */
const MATRIX_KEYS = ['predicted_aligned_error', 'pae'] as const;
/** Keys under which a JSON object may declare the scale's maximum. */
const DECLARED_MAX_KEYS = ['max_predicted_aligned_error', 'max_pae'] as const;
const SPLIT_RE = /[,;\s]+/;

/** Parse a PAE file's text (any of the formats above). Throws `PaeParseError`. */
export function parsePae(input: string): PaeMatrix {
  const text = input.replace(/^﻿/, '').trim();
  if (!text) throw new PaeParseError('empty PAE input');
  if (text[0] === '[' || text[0] === '{') return fromJson(text);
  return finish(fromDelimited(text), null);
}

// ---- delimited text --------------------------------------------------------

/** Python `float()` on one token: a decimal or scientific number, or
 *  nan / inf / infinity in any case. Null for anything else (a name). */
export function pyFloat(token: string): number | null {
  const v = Number(token);
  if (!Number.isNaN(v)) {
    // `Number` also reads 0x / 0o / 0b literals, which `float()` refuses.
    const body = token[0] === '+' || token[0] === '-' ? token.slice(1) : token;
    if (body.length > 1 && body[0] === '0' && /[xob]/i.test(body[1])) return null;
    return v;
  }
  if (/^[+-]?nan$/i.test(token)) return Number.NaN;
  const inf = token.match(/^([+-]?)inf(inity)?$/i);
  if (inf) return inf[1] === '-' ? -Infinity : Infinity;
  return null;
}

function fromDelimited(text: string): number[][] {
  const rows: number[][] = [];
  const lines = text.split(/\r\n|\r|\n/);
  for (let ln = 0; ln < lines.length; ln++) {
    const tokens = lines[ln].trim().split(SPLIT_RE).filter(Boolean);
    if (tokens.length === 0) continue;
    const row: number[] = new Array(tokens.length);
    let bad = false;
    for (let k = 0; k < tokens.length; k++) {
      const v = pyFloat(tokens[k]);
      if (v === null) {
        bad = true;
        break;
      }
      row[k] = v;
    }
    if (!bad) {
      rows.push(row);
      continue;
    }
    // A header row of names (no number at all) before the first row.
    if (rows.length === 0 && !tokens.some((t) => pyFloat(t) !== null)) continue;
    throw new PaeParseError(`line ${ln + 1}: non-numeric value in PAE row`);
  }
  return rows;
}

// ---- JSON ------------------------------------------------------------------

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function fromJson(text: string): PaeMatrix {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch (err) {
    throw new PaeParseError(`PAE JSON is not valid: ${err instanceof Error ? err.message : String(err)}`);
  }
  // AlphaFold DB wraps the object in a one-item list.
  if (Array.isArray(payload) && payload.length > 0 && isObject(payload[0])) payload = payload[0];
  if (isObject(payload)) {
    const declared = declaredMaxOf(payload);
    for (const key of MATRIX_KEYS) {
      if (key in payload) return finish(numericMatrix(payload[key]), declared);
    }
    if ('residue1' in payload && 'residue2' in payload && 'distance' in payload) {
      return finish(fromPairs(payload.residue1, payload.residue2, payload.distance), declared);
    }
    throw new PaeParseError(
      `PAE JSON has none of ${MATRIX_KEYS.join(', ')} nor residue1/residue2/distance`,
    );
  }
  return finish(numericMatrix(payload), null);
}

function declaredMaxOf(payload: Record<string, unknown>): number | null {
  for (const key of DECLARED_MAX_KEYS) {
    const v = payload[key];
    if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v;
  }
  return null;
}

/** A JSON number (not a bool, not a numeric string), as `_number` accepts. */
function jsonNumber(v: unknown): number {
  if (typeof v !== 'number') throw new PaeParseError('PAE matrix holds a non-numeric value');
  return v;
}

function numericMatrix(value: unknown): number[][] {
  if (!Array.isArray(value) || !value.every((row) => Array.isArray(row))) {
    throw new PaeParseError('PAE matrix must be a list of rows');
  }
  return (value as unknown[][]).map((row) => row.map(jsonNumber));
}

/** Python `int()` on a pair index: numbers truncate, integer strings parse. */
function pyInt(v: unknown): number {
  if (typeof v === 'number' && Number.isFinite(v)) return Math.trunc(v);
  if (typeof v === 'string' && /^\s*[+-]?\d+\s*$/.test(v)) return Number(v);
  throw new PaeParseError('PAE pair lists hold a non-numeric value');
}

/** AlphaFold DB v1: flattened (residue1, residue2, error) triples, residues 1-based. */
function fromPairs(residue1: unknown, residue2: unknown, distance: unknown): number[][] {
  if (!Array.isArray(residue1) || !Array.isArray(residue2) || !Array.isArray(distance)) {
    throw new PaeParseError('residue1, residue2 and distance must be lists');
  }
  if (!(residue1.length === residue2.length && residue2.length === distance.length)) {
    throw new PaeParseError('residue1, residue2 and distance differ in length');
  }
  if (residue1.length === 0) throw new PaeParseError('empty PAE pair list');
  const r1 = residue1.map(pyInt);
  const r2 = residue2.map(pyInt);
  let values: number[];
  try {
    values = distance.map(jsonNumber);
  } catch {
    throw new PaeParseError('PAE pair lists hold a non-numeric value');
  }
  let size = 0;
  for (let k = 0; k < r1.length; k++) {
    if (r1[k] < 1 || r2[k] < 1) throw new PaeParseError('residue indices are 1-based');
    size = Math.max(size, r1[k], r2[k]);
  }
  const matrix: (number | null)[][] = Array.from({ length: size }, () =>
    new Array<number | null>(size).fill(null),
  );
  for (let k = 0; k < r1.length; k++) matrix[r1[k] - 1][r2[k] - 1] = values[k];
  if (matrix.some((row) => row.some((v) => v === null))) {
    throw new PaeParseError(`PAE pairs do not cover the full ${size} x ${size} matrix`);
  }
  return matrix as number[][];
}

// ---- validation --------------------------------------------------------------

function finish(rows: number[][], declaredMax: number | null): PaeMatrix {
  const n = rows.length;
  if (n === 0) throw new PaeParseError('no PAE rows found');
  const widths = new Set(rows.map((r) => r.length));
  if (widths.size !== 1 || !widths.has(n)) {
    const sorted = Array.from(widths).sort((a, b) => a - b);
    throw new PaeParseError(
      `PAE matrix must be square: ${n} rows, row lengths [${sorted.join(', ')}]`,
    );
  }
  const values = new Float32Array(n * n);
  let max = 0;
  let seen = false;
  for (let i = 0; i < n; i++) {
    const row = rows[i];
    const base = i * n;
    for (let j = 0; j < n; j++) {
      const v = row[j];
      values[base + j] = v;
      if (Number.isFinite(v) && (!seen || v > max)) {
        max = v;
        seen = true;
      }
    }
  }
  return { values, n, max: seen ? max : 0, declaredMax };
}

/** The error at aligned residue `i` (row) and scored residue `j` (column). */
export function paeAt(matrix: PaeMatrix, i: number, j: number): number {
  return matrix.values[i * matrix.n + j];
}
